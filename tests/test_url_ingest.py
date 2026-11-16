"""Audio from a pasted link: YouTube through yt-dlp (with a captions fallback) and direct links with
SSRF protection. yt-dlp and the network are replaced by doubles: nothing leaves the test."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Dict, List

import httpx
import pytest
from fastapi.testclient import TestClient
from yt_dlp.utils import DownloadError

from app.api import deps
from app.config import settings
from app.main import app
from app.services import url_ingest
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service
from tests.fixtures.audio_generator import create_synthetic_wav

VTT = """WEBVTT
Kind: captions
Language: es

00:00:01.000 --> 00:00:03.000
Hola <c>a todos</c>

00:00:03.000 --> 00:00:05.000
Hola a todos

00:00:05.000 --> 00:00:08.500
hoy revisamos el presupuesto
"""


@pytest.fixture(scope="module")
def wav_bytes(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("audio") / "tone.wav"
    create_synthetic_wav(path, [(2.0, 440.0)])
    return path.read_bytes()


@pytest.fixture(autouse=True)
def _fresh_limits():
    deps._throttle_hits.clear()
    yield
    deps._throttle_hits.clear()


def _client(**fields) -> TestClient:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    if fields:
        db = supabase_service._load_db()
        db["users"][profile.user_id].update(fields)
        supabase_service._save_db(db)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {profile.access_token}"})
    return client


# yt-dlp double ---------------------------------------------------------------------------------------


class FakeYDL:
    info: Dict = {}
    fail_info = False
    fail_audio = False
    audio: bytes = b""
    calls: List[str] = []
    params_seen: List[Dict] = []

    def __init__(self, params: Dict) -> None:
        self.params = params
        FakeYDL.params_seen.append(params)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def extract_info(self, url: str, download: bool = False) -> Dict:
        FakeYDL.calls.append("info")
        if FakeYDL.fail_info:
            raise DownloadError("private video")
        return dict(FakeYDL.info)

    def process_ie_result(self, info: Dict, download: bool = True) -> Dict:
        FakeYDL.calls.append("download")
        if FakeYDL.fail_audio:
            raise DownloadError("Sign in to confirm you're not a bot")
        path = Path(self.params["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", "webm"))
        path.write_bytes(FakeYDL.audio)
        return {**info, "requested_downloads": [{"filepath": str(path)}]}

    def urlopen(self, url: str):
        FakeYDL.calls.append("captions")

        class _Resp:
            def read(self_inner) -> bytes:
                return VTT.encode("utf-8")

        return _Resp()


@pytest.fixture
def ydl(monkeypatch: pytest.MonkeyPatch, wav_bytes: bytes):
    FakeYDL.info = {
        "id": "abc123", "title": "Comité / semanal", "duration": 120, "language": "es",
        "automatic_captions": {"es": [{"ext": "json3", "url": "https://x/j"}, {"ext": "vtt", "url": "https://x/v"}]},
    }
    FakeYDL.fail_info = FakeYDL.fail_audio = False
    FakeYDL.audio = wav_bytes
    FakeYDL.calls, FakeYDL.params_seen = [], []
    monkeypatch.setattr(
        url_ingest, "_ydl",
        lambda extra=None, proxy=None: FakeYDL({**url_ingest_params(proxy), **(extra or {})}),
    )
    return FakeYDL


def url_ingest_params(proxy=None) -> Dict:
    params = {"allowed_extractors": ["youtube"], "noplaylist": True}
    if proxy:
        params["proxy"] = proxy
    return params


YT = "https://www.youtube.com/watch?v=abc123"


def test_youtube_audio_becomes_one_more_track(ydl, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    first = client.post("/api/upload/url", json={"url": YT})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["kind"] == "audio" and body["title"] == "Comité / semanal" and len(body["files"]) == 1
    assert body["files"][0]["filename"] == "Comité semanal.webm"
    assert ydl.calls == ["info", "download"]

    again = client.post("/api/upload/url", json={"url": YT, "session_id": body["session_id"]})
    assert again.json()["session_id"] == body["session_id"] and len(again.json()["files"]) == 2


def test_proxy_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "URL_INGEST_PROXY", "http://user:pass@proxy.example:3128")
    seen = {}

    class Capture:
        def __init__(self, params):
            seen.update(params)

    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Capture)
    url_ingest._ydl()
    assert seen["proxy"] == "http://user:pass@proxy.example:3128"
    assert seen["allowed_extractors"] == ["youtube"] and seen["noplaylist"] is True


def test_length_is_checked_before_downloading(ydl, monkeypatch: pytest.MonkeyPatch) -> None:
    ydl.info["duration"] = settings.GUEST_MAX_AUDIO_SECONDS + 60
    res = TestClient(app).post("/api/upload/url", json={"url": YT})
    assert res.status_code == 413 and "minutos" in res.json()["detail"]
    assert ydl.calls == ["info"]  # no se descargó nada

    ydl.calls.clear()
    ydl.info["duration"] = settings.URL_INGEST_MAX_MINUTES * 60 + 1
    assert _client(plan="pro", pro_until="2099-01-01T00:00:00+00:00").post("/api/upload/url", json={"url": YT}).status_code == 413
    assert ydl.calls == ["info"]


def test_free_quota_is_checked_before_downloading(ydl) -> None:
    ydl.info["duration"] = settings.FREE_DAILY_SECONDS + 60
    res = _client().post("/api/upload/url", json={"url": YT})
    assert res.status_code == 402 and "2 horas" in res.json()["detail"]
    assert ydl.calls == ["info"]


def test_unreadable_video_or_live_stream(ydl) -> None:
    ydl.fail_info = True
    assert _client().post("/api/upload/url", json={"url": YT}).status_code == 502
    ydl.fail_info = False
    ydl.info["is_live"] = True
    res = _client().post("/api/upload/url", json={"url": YT})
    assert res.status_code == 400 and "en vivo" in res.json()["detail"]


def test_captions_fallback_gives_a_transcript_without_speakers(ydl) -> None:
    ydl.fail_audio = True
    client = _client()
    res = client.post("/api/upload/url", json={"url": YT, "language": "es"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == "captions" and body["job_id"] and body["files"] == []
    assert ydl.calls == ["info", "download", "captions"]

    result = client.get(f"/api/jobs/{body['job_id']}/result").json()
    assert result["detected_speakers_count"] == 1 and {s["speaker"] for s in result["segments"]} == {"Video"}
    assert [s["text"] for s in result["segments"]] == ["Hola a todos", "hoy revisamos el presupuesto"]
    assert result["summa_report"]["is_locked"] is True  # plan Gratis: vista previa, sin LLM
    history = client.get("/api/portal/summary").json()
    assert any(item.get("job_id") == body["job_id"] for item in history.get("transcriptions", history.get("history", [])))
    assert TestClient(app).get(f"/api/jobs/{body['job_id']}/result").status_code == 404  # solo su dueño


def test_guest_captions_result_lives_like_a_guest_result(ydl) -> None:
    ydl.fail_audio = True
    guest = TestClient(app)
    body = guest.post("/api/upload/url", json={"url": YT}).json()
    result = guest.get(f"/api/jobs/{body['job_id']}/result").json()
    assert result["plan"] == "guest" and result["summa_report"] is None


def test_no_audio_and_no_captions_is_a_clear_error(ydl) -> None:
    ydl.fail_audio = True
    ydl.info.pop("automatic_captions")
    res = _client().post("/api/upload/url", json={"url": YT})
    assert res.status_code == 502 and "subtítulos" in res.json()["detail"]


def test_one_sticky_proxy_session_per_link(ydl, monkeypatch: pytest.MonkeyPatch) -> None:
    """YouTube ties the audio URLs to the IP that read the video: the whole link uses one session."""
    monkeypatch.setattr(settings, "URL_INGEST_PROXY", "http://user-u-session-{session}-sessionduration-10:p@gate.decodo.com:7000")
    ydl.fail_audio = True  # metadatos, audio y subtítulos: tres llamadas
    client = _client()
    assert client.post("/api/upload/url", json={"url": YT}).status_code == 200
    first = {p["proxy"] for p in ydl.params_seen}
    assert len(first) == 1 and "{session}" not in next(iter(first))
    ydl.params_seen.clear()
    client.post("/api/upload/url", json={"url": YT})
    assert {p["proxy"] for p in ydl.params_seen}.isdisjoint(first)  # otro enlace, otra sesión


def test_proxy_without_placeholder_is_used_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "URL_INGEST_PROXY", "http://u:p@proxy.example:3128")
    assert url_ingest.proxy_for_request() == "http://u:p@proxy.example:3128"
    monkeypatch.setattr(settings, "URL_INGEST_PROXY", "")
    assert url_ingest.proxy_for_request() == ""


# Direct links ----------------------------------------------------------------------------------------


class FakeWeb:
    def __init__(self, routes: Dict[str, httpx.Response]) -> None:
        self.routes = routes
        self.requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.headers['host']}{request.url.raw_path.decode()}"
        return self.routes.get(key, httpx.Response(404))


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch):
    dns = {"audio.example": ["93.184.216.34"], "cdn.example": ["93.184.216.35"], "evil.example": ["10.0.0.5"],
           "mixed.example": ["93.184.216.36", "192.168.1.10"], "meta.example": ["169.254.169.254"]}

    def install(routes: Dict[str, httpx.Response]) -> FakeWeb:
        fake = FakeWeb(routes)
        monkeypatch.setattr(url_ingest, "_resolve", lambda host, port: dns.get(host, []))
        monkeypatch.setattr(
            url_ingest, "_http_client",
            lambda: httpx.Client(transport=httpx.MockTransport(fake), follow_redirects=False),
        )
        return fake

    return install


def test_direct_link_downloads_from_the_checked_address(web, wav_bytes: bytes) -> None:
    fake = web({"audio.example/files/reunion.wav": httpx.Response(200, content=wav_bytes, headers={"content-type": "audio/wav"})})
    res = _client().post("/api/upload/url", json={"url": "https://audio.example/files/reunion.wav"})
    assert res.status_code == 200, res.text
    assert res.json()["files"][0]["filename"] == "reunion.wav"
    request = fake.requests[0]
    assert request.url.host == "93.184.216.34" and request.headers["host"] == "audio.example"
    assert request.extensions["sni_hostname"] == "audio.example"


def test_extension_can_come_from_the_content_type(web, wav_bytes: bytes) -> None:
    web({"audio.example/download?id=7": httpx.Response(200, content=wav_bytes, headers={"content-type": "audio/x-wav"})})
    res = _client().post("/api/upload/url", json={"url": "http://audio.example/download?id=7"})
    assert res.status_code == 200 and res.json()["files"][0]["filename"].endswith(".wav")


@pytest.mark.parametrize("link", [
    "ftp://audio.example/a.mp3",
    "file:///etc/passwd",
    "https://user:pw@audio.example/a.mp3",
    "https://audio.example:22/a.mp3",
    "http://127.0.0.1/a.mp3",
    "http://[::1]/a.mp3",
    "http://[::ffff:10.0.0.1]/a.mp3",
    "https://evil.example/a.mp3",
    "https://mixed.example/a.mp3",
    "https://meta.example/latest/meta-data",
    "not a link",
])
def test_unsafe_links_are_refused_before_connecting(web, link: str) -> None:
    fake = web({})
    res = _client().post("/api/upload/url", json={"url": link})
    assert res.status_code == 400, (link, res.text)
    assert fake.requests == []


def test_redirect_to_a_private_address_is_refused(web) -> None:
    fake = web({
        "audio.example/a.mp3": httpx.Response(302, headers={"location": "https://cdn.example/b.mp3"}),
        "cdn.example/b.mp3": httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}),
    })
    res = _client().post("/api/upload/url", json={"url": "https://audio.example/a.mp3"})
    assert res.status_code == 400 and "red privada" in res.json()["detail"]
    assert len(fake.requests) == 2


def test_too_many_redirects(web) -> None:
    web({"audio.example/loop.mp3": httpx.Response(302, headers={"location": "/loop.mp3"})})
    res = _client().post("/api/upload/url", json={"url": "https://audio.example/loop.mp3"})
    assert res.status_code == 400 and "demasiadas" in res.json()["detail"]


def test_size_is_capped_by_header_and_while_streaming(web, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    big = b"\0" * (2 * 1024 * 1024)
    web({
        "audio.example/declared.mp3": httpx.Response(200, headers={"content-length": str(len(big)), "content-type": "audio/mpeg"}, content=big),
        "audio.example/streamed.mp3": httpx.Response(200, headers={"content-type": "audio/mpeg"}, stream=httpx.ByteStream(big)),
    })
    client = _client()
    for name in ("declared", "streamed"):
        res = client.post("/api/upload/url", json={"url": f"https://audio.example/{name}.mp3"})
        assert res.status_code == 413 and "MB" in res.json()["detail"]
    assert not list(settings.TEMP_DIR.glob("url_*"))  # sin restos en temp


def test_download_time_is_capped(web, monkeypatch: pytest.MonkeyPatch, wav_bytes: bytes) -> None:
    monkeypatch.setattr(settings, "URL_INGEST_TIMEOUT_SECONDS", -1)
    web({"audio.example/slow.wav": httpx.Response(200, content=wav_bytes, headers={"content-type": "audio/wav"})})
    res = _client().post("/api/upload/url", json={"url": "https://audio.example/slow.wav"})
    assert res.status_code == 408


def test_a_page_is_not_audio(web) -> None:
    web({"audio.example/page": httpx.Response(200, html="<html></html>")})
    res = _client().post("/api/upload/url", json={"url": "https://audio.example/page"})
    assert res.status_code == 415


def test_guest_limits_apply_to_direct_links(web, wav_bytes: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GUEST_MAX_AUDIO_MINUTES", 1 / 60)  # 1 segundo; el audio dura 2
    web({"audio.example/long.wav": httpx.Response(200, content=wav_bytes, headers={"content-type": "audio/wav"})})
    guest = supabase_service.guest_key("testclient")
    session = job_manager.create_or_get_session(None, guest)
    res = TestClient(app).post("/api/upload/url", json={"url": "https://audio.example/long.wav", "session_id": session.session_id})
    assert res.status_code == 413
    assert session.tracks == {}  # la pista se retiró


def test_requests_per_hour_are_limited(web) -> None:
    web({})
    client = _client()
    codes = [client.post("/api/upload/url", json={"url": "ftp://x"}).status_code for _ in range(21)]
    assert codes[:20] == [400] * 20 and codes[20] == 429


# Captions parsing ------------------------------------------------------------------------------------


def test_parse_vtt_cleans_tags_and_rolling_lines() -> None:
    cues = url_ingest.parse_vtt(VTT)
    assert [(c.start, c.end, c.text) for c in cues] == [
        (1.0, 5.0, "Hola a todos"), (5.0, 8.5, "hoy revisamos el presupuesto"),
    ]
    rolling = "WEBVTT\n\n00:01.000 --> 00:02.000\nuno dos\n\n00:02.000 --> 00:03.000\nuno dos tres cuatro\n"
    assert [c.text for c in url_ingest.parse_vtt(rolling)] == ["uno dos", "tres cuatro"]


def test_temp_folder_is_removed_after_success(ydl) -> None:
    _client().post("/api/upload/url", json={"url": YT})
    assert not list(settings.TEMP_DIR.glob("url_*"))
    shutil.rmtree(settings.TEMP_DIR / "nothing", ignore_errors=True)
