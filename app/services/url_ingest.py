"""
Audio from a pasted link (app/services/url_ingest.py)
-----------------------------------------------------
- **YouTube** (yt-dlp, optional URL_INGEST_PROXY): metadata first (length, title), then only the
  audio stream. When the audio cannot be downloaded, the video's captions are the fallback: a
  transcript without speakers.
- **Direct links** to an audio file: http/https only, every address the host resolves to must be
  public, the connection goes to the address that was checked (no second DNS lookup), each
  redirect is checked the same way, and size and time are capped. The proxy is never used here.

The route (app/api/routes_upload.py) adds the file to the caller's upload session as one more
track; the rest of the flow does not change.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import secrets
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings
from app.errors import UserFacingError

logger = logging.getLogger("app.services.url_ingest")

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
}
_ALLOWED_PORTS = {80, 443, 8080, 8443}
_MAX_REDIRECTS = 5
_CONTENT_TYPES = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/wave": ".wav", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".m4a", "audio/flac": ".flac",
    "audio/x-flac": ".flac", "audio/webm": ".webm", "video/webm": ".webm", "video/mp4": ".mp4",
}


class UrlIngestError(UserFacingError):
    """A link that cannot be used; the message is for the user."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Fetched:
    path: Path
    filename: str


@dataclass
class Caption:
    start: float
    end: float
    text: str


def parse_link(raw: str) -> httpx.URL:
    text = (raw or "").strip()
    if not text or len(text) > 2048:
        raise UrlIngestError("Pega un enlace válido. / Paste a valid link.")
    try:
        url = httpx.URL(text)
    except Exception as exc:
        raise UrlIngestError("Pega un enlace válido. / Paste a valid link.") from exc
    if url.scheme not in ("http", "https") or not url.host:
        raise UrlIngestError("Solo se aceptan enlaces http o https. / Only http and https links are accepted.")
    if url.userinfo:
        raise UrlIngestError("El enlace no puede llevar usuario ni contraseña. / Links with credentials are not accepted.")
    return url


def is_youtube(url: httpx.URL) -> bool:
    return url.host.lower() in YOUTUBE_HOSTS


def safe_filename(title: str, ext: str) -> str:
    name = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", " ", title or "")
    name = re.sub(r"\s+", " ", name).strip(" .")[:80] or "audio"
    return f"{name}{ext}"


# -----------------------------------------------------------------------------
# Direct links (SSRF-safe)
# -----------------------------------------------------------------------------


def _resolve(host: str, port: int) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlIngestError("No encontramos ese sitio. Revisa el enlace. / We could not find that site.") from exc
    return sorted({info[4][0] for info in infos})


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def _checked_address(url: httpx.URL) -> str:
    port = url.port or (443 if url.scheme == "https" else 80)
    if port not in _ALLOWED_PORTS:
        raise UrlIngestError("Ese puerto no está permitido. / That port is not allowed.")
    try:
        literal = ipaddress.ip_address(url.host)
        addresses = [str(literal)]
    except ValueError:
        addresses = _resolve(url.host, port)
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise UrlIngestError(
            "Ese enlace apunta a una red privada y no se puede usar. / That link points to a private network.", 400
        )
    return addresses[0]


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False, trust_env=False)


def _extension(url: httpx.URL, content_type: str) -> Optional[str]:
    ext = Path(url.path).suffix.lower()
    if ext in settings.ALLOWED_EXTENSIONS:
        return ext
    return _CONTENT_TYPES.get(content_type.split(";", 1)[0].strip().lower())


def download_direct(raw_url: str, dest_dir: Path, max_bytes: int, timeout_seconds: float) -> Fetched:
    """Download an audio file from a public address, following at most 5 checked redirects."""
    url = parse_link(raw_url)
    deadline = time.monotonic() + timeout_seconds
    with _http_client() as client:
        for _ in range(_MAX_REDIRECTS + 1):
            address = _checked_address(url)
            target = url.copy_with(host=address)
            extensions = {"sni_hostname": url.host} if url.scheme == "https" else {}
            headers = {"Host": url.netloc.decode("ascii"), "User-Agent": "ApexVox/1.0", "Accept": "audio/*, video/*;q=0.8"}
            try:
                with client.stream("GET", target, headers=headers, extensions=extensions) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise UrlIngestError("El enlace redirige a ninguna parte. / The link redirects nowhere.")
                        url = parse_link(str(url.join(location)))
                        continue
                    if resp.status_code >= 400:
                        raise UrlIngestError(
                            f"El enlace respondió con un error (HTTP {resp.status_code}). / The link answered HTTP {resp.status_code}."
                        )
                    ext = _extension(url, resp.headers.get("content-type", ""))
                    if not ext:
                        raise UrlIngestError(
                            "Ese enlace no lleva a un archivo de audio. / That link does not lead to an audio file.", 415
                        )
                    declared = int(resp.headers.get("content-length") or 0)
                    if declared > max_bytes:
                        raise UrlIngestError(_too_large(max_bytes), 413)
                    name = safe_filename(Path(url.path).stem or url.host, ext)
                    dest = dest_dir / name
                    total = 0
                    with dest.open("wb") as fh:
                        for chunk in resp.iter_bytes(64 * 1024):
                            total += len(chunk)
                            if total > max_bytes:
                                raise UrlIngestError(_too_large(max_bytes), 413)
                            if time.monotonic() > deadline:
                                raise UrlIngestError(_too_slow(), 408)
                            fh.write(chunk)
                    return Fetched(path=dest, filename=name)
            except httpx.TimeoutException as exc:
                raise UrlIngestError(_too_slow(), 408) from exc
            except httpx.HTTPError as exc:
                logger.info("Direct link download failed: %s", type(exc).__name__)
                raise UrlIngestError("No pudimos descargar ese enlace. / We could not download that link.", 502) from exc
    raise UrlIngestError("El enlace redirige demasiadas veces. / The link redirects too many times.")


def _too_large(max_bytes: int) -> str:
    mb = max_bytes // (1024 * 1024)
    return f"El audio supera el máximo de {mb} MB. / The audio is larger than {mb} MB."


def _too_slow() -> str:
    return "El enlace tardó demasiado en descargarse. / The link took too long to download."


# -----------------------------------------------------------------------------
# YouTube (yt-dlp)
# -----------------------------------------------------------------------------


def proxy_for_request() -> str:
    """
    URL_INGEST_PROXY for one pasted link. A `{session}` in it becomes a new random id, so a
    provider's sticky session keeps one exit IP for the whole link: YouTube ties the audio URLs
    to the IP that read the video, and a rotating IP would get them refused.
    """
    proxy = settings.URL_INGEST_PROXY
    return proxy.replace("{session}", secrets.token_hex(6)) if "{session}" in proxy else proxy


def _ydl(extra: Optional[Dict[str, Any]] = None, proxy: Optional[str] = None):
    from yt_dlp import YoutubeDL

    params: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "cachedir": False,
        "allowed_extractors": ["youtube"],
        "socket_timeout": 20,
    }
    proxy = proxy if proxy is not None else proxy_for_request()
    if proxy:
        params["proxy"] = proxy
    params.update(extra or {})
    return YoutubeDL(params)


def youtube_info(url: str, proxy: Optional[str] = None) -> Dict[str, Any]:
    """Title, length and available captions, without downloading anything."""
    from yt_dlp.utils import DownloadError

    try:
        with _ydl(proxy=proxy) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        logger.info("YouTube metadata failed: %s", type(exc).__name__)
        raise UrlIngestError(
            "No pudimos leer ese video de YouTube (puede ser privado o no estar disponible). / "
            "We could not read that YouTube video (it may be private or unavailable).", 502,
        ) from exc
    if not isinstance(info, dict) or info.get("_type") == "playlist":
        raise UrlIngestError("Pega el enlace de un solo video, no de una lista. / Paste a single video, not a playlist.")
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise UrlIngestError("Las transmisiones en vivo no se pueden transcribir. / Live streams cannot be transcribed.")
    return info


def youtube_audio(info: Dict[str, Any], dest_dir: Path, max_bytes: int, proxy: Optional[str] = None) -> Fetched:
    """Download only the audio stream. Raises UrlIngestError when YouTube refuses it."""
    from yt_dlp.utils import DownloadError

    params = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "max_filesize": max_bytes,
    }
    try:
        with _ydl(params, proxy=proxy) as ydl:
            done = ydl.process_ie_result(dict(info), download=True)
    except DownloadError as exc:
        logger.info("YouTube audio download failed: %s", type(exc).__name__)
        raise UrlIngestError("YouTube no permitió descargar el audio. / YouTube did not allow the audio download.", 502) from exc
    downloads = (done or {}).get("requested_downloads") or []
    path = Path(downloads[0]["filepath"]) if downloads and downloads[0].get("filepath") else None
    if not path or not path.exists():
        raise UrlIngestError(_too_large(max_bytes), 413)  # yt-dlp omite en silencio lo que supera max_filesize
    ext = path.suffix.lower() if path.suffix.lower() in settings.ALLOWED_EXTENSIONS else ".webm"
    return Fetched(path=path, filename=safe_filename(str(info.get("title") or ""), ext))


def _pick_caption_track(info: Dict[str, Any], lang: str) -> Optional[Dict[str, Any]]:
    for source in ("subtitles", "automatic_captions"):
        tracks: Dict[str, List[Dict[str, Any]]] = info.get(source) or {}
        if not tracks:
            continue
        original = str(info.get("language") or "")
        prefs = [lang, original, "es", "en"]
        keys = [k for p in prefs if p for k in tracks if k == p or k.startswith(f"{p}-")]
        keys += [k for k in tracks if k.endswith("-orig")]  # pista original de los automáticos
        for key in keys or list(tracks)[:1]:
            vtt = next((f for f in tracks.get(key) or [] if f.get("ext") == "vtt" and f.get("url")), None)
            if vtt:
                return vtt
    return None


_CUE_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})|(\d{2}):(\d{2})[.,](\d{3})")


def _seconds(stamp: str) -> float:
    m = _CUE_TIME.fullmatch(stamp.strip().split(" ")[0])
    if not m:
        raise ValueError(stamp)
    if m.group(1) is not None:
        h, mi, s, ms = (int(m.group(i)) for i in range(1, 5))
    else:
        h, (mi, s, ms) = 0, (int(m.group(i)) for i in range(5, 8))
    return h * 3600 + mi * 60 + s + ms / 1000


def parse_vtt(text: str) -> List[Caption]:
    """WebVTT cues as text, without tags and without the repeated lines of rolling captions."""
    cues: List[Caption] = []
    for block in re.split(r"\r?\n\r?\n", text):
        lines = [line for line in block.splitlines() if line.strip()]
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start_raw, end_raw = lines[timing].split("-->", 1)
        try:
            start, end = _seconds(start_raw), _seconds(end_raw)
        except ValueError:
            continue
        body = " ".join(re.sub(r"<[^>]+>", "", line).strip() for line in lines[timing + 1:])
        body = re.sub(r"\s+", " ", body).strip()
        if not body:
            continue
        if cues and (body == cues[-1].text or cues[-1].text.endswith(body)):
            cues[-1].end = max(cues[-1].end, end)
            continue
        if cues and body.startswith(cues[-1].text):
            body = body[len(cues[-1].text):].strip()
            if not body:
                continue
        cues.append(Caption(start=start, end=end, text=body))
    return cues


def youtube_captions(info: Dict[str, Any], lang: str, proxy: Optional[str] = None) -> List[Caption]:
    """The video's captions (uploaded first, then automatic). Empty when it has none."""
    track = _pick_caption_track(info, lang)
    if not track:
        return []
    try:
        with _ydl(proxy=proxy) as ydl:
            raw = ydl.urlopen(track["url"]).read()
    except Exception as exc:  # red, proxy o respuesta inválida: sin respaldo
        logger.info("YouTube captions download failed: %s", type(exc).__name__)
        return []
    return parse_vtt(raw.decode("utf-8", errors="replace"))


def captions_text(cues: List[Caption]) -> Tuple[str, float]:
    return " ".join(c.text for c in cues), max((c.end for c in cues), default=0.0)
