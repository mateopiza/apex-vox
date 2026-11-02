"""
Bot de reuniones con Recall.ai (app/services/recall_service.py)
---------------------------------------------------------------
- El bot entra a Zoom, Google Meet, Microsoft Teams o Webex (ahora o a una hora programada),
  graba el audio y, al terminar (webhook bot.done), Apex Vox descarga el audio, lo transcribe
  en bloques de 3 minutos (igual que Apex Box) y envía al usuario el enlace con notas,
  resumen y acta.
- Verificación de webhooks Svix (Recall.ai y Resend usan el mismo esquema).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import logging
import re
import shutil
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.services.recall_service")

MEETING_URL_RE = re.compile(
    r"https://(?:[\w-]+\.)?(?:meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}"
    r"|zoom\.us/(?:j|my|w)/[\w?=.&%-]+"
    r"|teams\.microsoft\.com/l/meetup-join/[^\s\"'<>]+"
    r"|teams\.live\.com/meet/[^\s\"'<>]+"
    r"|[\w-]+\.webex\.com/[^\s\"'<>]+)",
    re.I,
)
BLOCK_SEC = 180


class RecallError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.RECALL_API_KEY)


_REGION_RE = re.compile(r"[a-z]{2}-[a-z]+-\d")
_PATH_RE = re.compile(r"/(?:[\w-]+/)*")


def _base() -> str:
    region = settings.RECALL_REGION or "us-west-2"
    if not _REGION_RE.fullmatch(region):
        raise RecallError("RECALL_REGION no es válida.")
    return f"https://{region}.recall.ai/api/v1"


def _request(method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
    if not is_configured():
        raise RecallError("El bot de reuniones no está configurado.")
    if not _PATH_RE.fullmatch(path):  # ids de bot y rutas solo con letras, números, _ y -
        raise RecallError("Ruta no válida.")
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.request(method, f"{_base()}{path}", json=json_body,
                                  headers={"Authorization": f"Token {settings.RECALL_API_KEY}"})
    except httpx.HTTPError as exc:
        raise RecallError(f"No se pudo contactar al servicio del bot: {exc}") from exc
    if resp.status_code >= 400:
        logger.warning("Recall %s /%s -> HTTP %s", method, path.split("/")[1], resp.status_code)
        raise RecallError(f"El servicio del bot respondió {resp.status_code}.")
    return resp.json() if resp.content else None


def extract_meeting_url(*texts: Optional[str]) -> Optional[str]:
    for text in texts:
        if not text:
            continue
        m = MEETING_URL_RE.search(text.replace("\\n", " ").replace("\\,", ","))
        if m:
            return m.group(0).rstrip(".,;)>")
    return None


def platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()

    def on(domain: str) -> bool:
        return host == domain or host.endswith("." + domain)

    if on("meet.google.com"):
        return "google_meet"
    if on("zoom.us"):
        return "zoom"
    if on("teams.microsoft.com") or on("teams.live.com"):
        return "microsoft_teams"
    if on("webex.com"):
        return "webex"
    return "other"


# ---------------------------------------------------------------------------
# Bots
# ---------------------------------------------------------------------------

def _bots(db: Dict[str, Any]) -> Dict[str, Any]:
    return db.setdefault("meeting_bots", {})


def create_bot(user_id: str, meeting_url: str, title: str = "", join_at: Optional[dt.datetime] = None,
               source: str = "manual", event_uid: str = "") -> Dict[str, Any]:
    if not MEETING_URL_RE.fullmatch(meeting_url.strip()) and not extract_meeting_url(meeting_url):
        raise RecallError("Enlace no válido: usa un enlace de Zoom, Google Meet, Teams o Webex.")
    meeting_url = extract_meeting_url(meeting_url) or meeting_url.strip()
    body: Dict[str, Any] = {
        "meeting_url": meeting_url,
        "bot_name": settings.BOT_NAME[:100],
        "recording_config": {"audio_mixed_mp3": {}},
        "metadata": {"user_id": user_id, "title": (title or "Reunión")[:120], "source": source},
    }
    now = dt.datetime.now(dt.timezone.utc)
    if join_at and join_at > now + dt.timedelta(minutes=10):
        body["join_at"] = join_at.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    bot = _request("POST", "/bot/", body)
    record = {
        "bot_id": bot["id"],
        "user_id": user_id,
        "title": (title or "Reunión")[:120],
        "meeting_url": meeting_url,
        "platform": platform_of(meeting_url),
        "join_at": body.get("join_at"),
        "status": "scheduled" if body.get("join_at") else "joining",
        "source": source,
        "event_uid": event_uid,
        "job_id": None,
        "created_at": now.isoformat(),
    }
    with supabase_service._lock:
        db = supabase_service._load_db()
        _bots(db)[bot["id"]] = record
        supabase_service._save_db(db)
    return record


def cancel_bot(bot_id: str) -> None:
    try:
        _request("DELETE", f"/bot/{bot_id}/")  # solo bots programados que aún no entran
    except RecallError:
        try:
            _request("POST", f"/bot/{bot_id}/leave_call/")
        except RecallError:
            logger.info("Bot %s already left or finished", bot_id)  # se marca cancelado igual
    _update(bot_id, status="cancelled")


def list_bots(user_id: str) -> List[Dict[str, Any]]:
    with supabase_service._lock:
        db = supabase_service._load_db()
        items = [dict(b) for b in _bots(db).values() if b.get("user_id") == user_id]
    return sorted(items, key=lambda b: b.get("join_at") or b.get("created_at", ""), reverse=True)


def _update(bot_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    with supabase_service._lock:
        db = supabase_service._load_db()
        rec = _bots(db).get(bot_id)
        if not rec:
            return None
        rec.update(fields)
        supabase_service._save_db(db)
        return dict(rec)


# ---------------------------------------------------------------------------
# Webhooks (Svix)
# ---------------------------------------------------------------------------

def verify_svix(secret: str, headers: Dict[str, str], body: bytes, tolerance: int = 300) -> bool:
    """Firma Svix: base64(HMAC-SHA256(secreto, f'{id}.{timestamp}.{cuerpo}'))."""
    if not secret:
        return False
    h = {k.lower(): v for k, v in headers.items()}
    msg_id = h.get("svix-id") or h.get("webhook-id")
    ts = h.get("svix-timestamp") or h.get("webhook-timestamp")
    sigs = h.get("svix-signature") or h.get("webhook-signature") or ""
    if not msg_id or not ts or not sigs:
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
        key = base64.b64decode(secret.split("_", 1)[1] if secret.startswith("whsec_") else secret)
    except (ValueError, TypeError):
        return False
    expected = base64.b64encode(
        hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return any(hmac.compare_digest(expected, s.split(",", 1)[1]) for s in sigs.split() if "," in s)


def handle_status_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    event = str(payload.get("event") or "")
    bot = ((payload.get("data") or {}).get("bot") or {})
    bot_id = bot.get("id")
    if not bot_id:
        return {"status": "ignored"}
    status_map = {
        "bot.joining_call": "joining", "bot.in_waiting_room": "waiting_room",
        "bot.in_call_recording": "recording", "bot.call_ended": "processing",
        "bot.fatal": "failed", "bot.recording_permission_denied": "failed",
    }
    if event in status_map:
        _update(bot_id, status=status_map[event])
    if event == "bot.done":
        rec = _update(bot_id, status="processing")
        if rec and not rec.get("job_id"):
            threading.Thread(target=process_finished_bot, args=(bot_id,), daemon=True).start()
    return {"status": "ok", "event": event}


# ---------------------------------------------------------------------------
# Procesar la grabación
# ---------------------------------------------------------------------------

def _audio_url(bot: Dict[str, Any]) -> Optional[str]:
    for rec in bot.get("recordings") or []:
        shortcuts = rec.get("media_shortcuts") or {}
        for key in ("audio_mixed", "audio_mixed_mp3", "video_mixed"):
            url = ((shortcuts.get(key) or {}).get("data") or {}).get("download_url")
            if url:
                return url
    return None


def process_finished_bot(bot_id: str) -> Optional[str]:
    """Descarga el audio del bot, lo transcribe en bloques de 3 min y crea el resumen."""
    from app.models.schemas import BoxCreateSessionRequest, BoxFinalizeRequest
    from app.services import email_service
    from app.services.apex_box import apex_box_manager
    from app.services.audio_engine import extract_chunk, probe_audio

    with supabase_service._lock:
        rec = dict(_bots(supabase_service._load_db()).get(bot_id) or {})
    if not rec:
        return None
    work = settings.TEMP_DIR / f"recall_{bot_id}"
    try:
        url = _audio_url(_request("GET", f"/bot/{bot_id}/"))
        if not url:
            raise RecallError("La grabación todavía no está disponible.")
        work.mkdir(parents=True, exist_ok=True)
        src = work / "meeting_audio"
        with httpx.Client(timeout=300.0, follow_redirects=True) as client, client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(src, "wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        total = float(probe_audio(src).duration_sec or 0.0)
        if total <= 1:
            raise RecallError("La grabación no tiene audio.")

        user = supabase_service._load_db()["users"].get(rec["user_id"]) or {}
        paid = str(user.get("plan", "free")).lower() in ("pro", "trial")
        session = apex_box_manager.create_session(BoxCreateSessionRequest(
            title=rec.get("title") or "Reunión", mode="virtual", platform=rec.get("platform") or "google_meet",
            meeting_url=rec.get("meeting_url"), user_id=rec["user_id"], plan="pro" if paid else "free",
            device_type="meeting_bot",
        ))
        start, index = 0.0, 0
        while start < total - 0.5:
            end = min(total, start + BLOCK_SEC)
            part = work / f"block_{index:04d}.mp3"
            extract_chunk(src, part, start, end)
            apex_box_manager.ingest_block(
                box_session_id=session.box_session_id, filename=part.name, content=part.read_bytes(),
                block_index=index, duration_hint_sec=end - start, transcribe_immediately=True,
            )
            start, index = end, index + 1
        fin = apex_box_manager.finalize_session(
            session.box_session_id, BoxFinalizeRequest(generate_minutes=True),
            record_extra={"source": "meeting_bot", "meeting_url": rec.get("meeting_url"), "bot_id": bot_id,
                          "event_uid": rec.get("event_uid") or None},
        )
        _update(bot_id, status="done", job_id=fin.job_id)
        link = f"{settings.PUBLIC_BASE_URL or 'https://apex-vox.ialabs.app'}/?job={fin.job_id}"
        if user.get("email"):
            email_service.send_email(user["email"], email_service.render_meeting_ready(
                user.get("full_name", ""), rec.get("title") or "Reunión", fin.total_duration_formatted, link,
                user.get("preferred_language", "es")), tags=[{"name": "category", "value": "meeting_ready"}])
        return fin.job_id
    except Exception as exc:  # noqa: BLE001 — se registra y se marca el bot como fallido
        logger.exception("No se pudo procesar el bot %s", bot_id)
        _update(bot_id, status="failed", error=str(exc)[:200])
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def new_uid() -> str:
    return uuid.uuid4().hex
