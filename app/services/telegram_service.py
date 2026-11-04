"""
Telegram audio inbox (app/services/telegram_service.py)
-------------------------------------------------------
- One Telegram chat per Apex Pro account ("1 bot por suscripción") and one account per chat.
- Linking: the signed-in user creates a one-time code in the web app and sends
  `/start <code>` (or opens the t.me deep link). Nothing is accepted from unlinked chats.
- Voice notes, audio files and audio documents are transcribed with the account's
  plan/quota; the transcript comes back as a message plus a .txt file.
- The webhook is authenticated with Telegram's X-Telegram-Bot-Api-Secret-Token header.
"""

from __future__ import annotations

import copy
import datetime as dt
import hmac
import logging
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.config import settings
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.services.telegram_service")

TELEGRAM_API = "https://api.telegram.org"
MAX_TELEGRAM_FILE_BYTES = 20 * 1024 * 1024  # Bot API download limit
LINK_CODE_TTL_MINUTES = 10
PAID_PLANS = ("trial", "pro")


def is_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def webhook_secret() -> str:
    """Secret Telegram echoes back on every webhook call (derived, never stored in clear)."""
    if settings.TELEGRAM_WEBHOOK_SECRET:
        return settings.TELEGRAM_WEBHOOK_SECRET
    return supabase_service._digest(f"telegram-webhook:{settings.TELEGRAM_BOT_TOKEN}")[:48]


def verify_webhook(header_value: Optional[str]) -> bool:
    return is_configured() and bool(header_value) and hmac.compare_digest(header_value, webhook_secret())


def _api(method: str, **payload: Any) -> Dict[str, Any]:
    url = f"{TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Telegram %s failed: %s", method, exc)
        return {"ok": False}
    if not data.get("ok"):
        logger.warning("Telegram %s rejected: %s", method, data.get("description"))
    return data


def send_message(chat_id: int, text: str) -> None:
    _api("sendMessage", chat_id=chat_id, text=text[:4096], disable_web_page_preview=True)


def send_document(chat_id: int, filename: str, content: bytes, caption: str = "") -> None:
    url = f"{TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with httpx.Client(timeout=60.0) as client:
            client.post(
                url,
                data={"chat_id": str(chat_id), "caption": caption[:1024]},
                files={"document": (filename, content, "text/plain; charset=utf-8")},
            )
    except httpx.HTTPError as exc:
        logger.warning("Telegram sendDocument failed: %s", exc)


def set_webhook(base_url: str) -> Dict[str, Any]:
    return _api(
        "setWebhook",
        url=f"{base_url.rstrip('/')}/api/telegram/webhook",
        secret_token=webhook_secret(),
        allowed_updates=["message"],
        drop_pending_updates=True,
    )


def bot_username() -> str:
    if settings.TELEGRAM_BOT_USERNAME:
        return settings.TELEGRAM_BOT_USERNAME.lstrip("@")
    data = _api("getMe")
    return str((data.get("result") or {}).get("username") or "")


# ---------------------------------------------------------------------------
# Account linking (stored in the users DB)
# ---------------------------------------------------------------------------

def create_link_code(user_id: str) -> Dict[str, Any]:
    """One-time code (10 min) the user sends to the bot. Paid plans only."""
    user = supabase_service.get_user_by_id(user_id) or {}
    if str(user.get("plan", "free")).lower() not in PAID_PLANS:
        raise PermissionError("El bot de Telegram está incluido en Apex Pro (prueba gratis o pago).")
    if user.get("telegram_chat_id"):
        raise PermissionError("Ya tienes un chat de Telegram vinculado. Desvincúlalo para usar otro.")
    code = secrets.token_hex(4).upper()
    with supabase_service._lock:
        db = supabase_service._load_db()
        links = db.setdefault("telegram_codes", {})
        now = dt.datetime.now(dt.timezone.utc)
        for key in [k for k, v in links.items() if v.get("user_id") == user_id or v.get("expires_at", "") <= now.isoformat()]:
            links.pop(key, None)
        links[supabase_service._digest(f"tg:{code}")] = {
            "user_id": user_id,
            "expires_at": (now + dt.timedelta(minutes=LINK_CODE_TTL_MINUTES)).isoformat(),
        }
        supabase_service._save_db(db)
    username = bot_username()
    return {
        "code": code,
        "expires_in_minutes": LINK_CODE_TTL_MINUTES,
        "bot_username": username,
        "deep_link": f"https://t.me/{username}?start={code}" if username else None,
    }


def link_chat(code: str, chat_id: int, tg_username: str = "") -> Optional[Dict[str, Any]]:
    """Consume a link code; enforces one chat per account and one account per chat."""
    with supabase_service._lock:
        db = supabase_service._load_db()
        entry = db.setdefault("telegram_codes", {}).pop(supabase_service._digest(f"tg:{code.strip().upper()}"), None)
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        if not entry or entry.get("expires_at", "") <= now_iso:
            supabase_service._save_db(db)
            return None
        if any(u.get("telegram_chat_id") == chat_id for u in db["users"].values()):
            supabase_service._save_db(db)
            raise PermissionError("Este chat ya está vinculado a otra cuenta de Apex Vox.")
        user = db["users"].get(entry["user_id"])
        if not user:
            return None
        if user.get("telegram_chat_id"):
            raise PermissionError("Esta cuenta ya tiene un chat de Telegram vinculado.")
        user["telegram_chat_id"] = chat_id
        user["telegram_username"] = tg_username or ""
        user["telegram_linked_at"] = now_iso
        supabase_service._save_db(db)
        return dict(user)


def unlink(user_id: str) -> None:
    with supabase_service._lock:
        db = supabase_service._load_db()
        user = db["users"].get(user_id)
        if user:
            for key in ("telegram_chat_id", "telegram_username", "telegram_linked_at"):
                user.pop(key, None)
            supabase_service._save_db(db)


def user_for_chat(chat_id: int) -> Optional[Dict[str, Any]]:
    users = supabase_service._read_snapshot()["users"]
    known = next((u for u in users.values() if u.get("telegram_chat_id") == chat_id), None)
    if not known:
        return None
    if not supabase_service._plan_expired(known):
        return copy.deepcopy(known)
    with supabase_service._lock:
        db = supabase_service._load_db()
        user = next((u for u in db["users"].values() if u.get("telegram_chat_id") == chat_id), None)
        if user and supabase_service._refresh_plan_expiry(user):
            supabase_service._save_db(db)
        return dict(user) if user else None


def link_status(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "configured": is_configured(),
        "linked": bool(user.get("telegram_chat_id")),
        "telegram_username": user.get("telegram_username") or None,
        "linked_at": user.get("telegram_linked_at"),
        "eligible": str(user.get("plan", "free")).lower() in PAID_PLANS,
    }


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------

HELP_ES = (
    "Apex Vox · bot de audio\n\n"
    "1. En apex-vox.ialabs.app abre tu cuenta (icono de usuario) → Telegram → Generar código.\n"
    "2. Envíame: /start TU_CÓDIGO\n"
    "3. Mándame notas de voz o audios (hasta 20 MB) y te devuelvo la transcripción.\n\n"
    "Comandos: /estado · /desvincular · /ayuda"
)


def handle_update(update: Dict[str, Any]) -> None:
    """Entry point called (in a background thread) for each webhook update."""
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or chat.get("type") != "private":
        return
    text = (message.get("text") or "").strip()
    sender = message.get("from") or {}

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code:
            send_message(chat_id, HELP_ES)
            return
        if not re.fullmatch(r"[A-Fa-f0-9]{8}", code):
            send_message(chat_id, "Código inválido. Genera uno nuevo desde tu cuenta en apex-vox.ialabs.app.")
            return
        try:
            user = link_chat(code, chat_id, sender.get("username", ""))
        except PermissionError as exc:
            send_message(chat_id, str(exc))
            return
        if not user:
            send_message(chat_id, "El código expiró o ya se usó. Genera uno nuevo desde tu cuenta.")
            return
        send_message(chat_id, f"Listo, {user.get('full_name') or user.get('email')}. Envíame una nota de voz o un audio para transcribirlo.")
        return

    user = user_for_chat(chat_id)
    if text in ("/ayuda", "/help"):
        send_message(chat_id, HELP_ES)
        return
    if not user:
        send_message(chat_id, "Este chat no está vinculado a ninguna cuenta.\n\n" + HELP_ES)
        return
    if text == "/estado":
        quota = supabase_service.get_user_quota(user["user_id"])
        send_message(chat_id, f"Cuenta: {user.get('email')}\nPlan: {quota.plan_display_name}")
        return
    if text == "/desvincular":
        unlink(user["user_id"])
        send_message(chat_id, "Chat desvinculado. Puedes vincular otro desde tu cuenta.")
        return

    media = message.get("voice") or message.get("audio") or message.get("video_note")
    document = message.get("document") or {}
    if not media and str(document.get("mime_type", "")).startswith("audio/"):
        media = document
    if not media:
        if text:
            send_message(chat_id, "Envíame una nota de voz o un archivo de audio. /ayuda")
        return

    if str(user.get("plan", "free")).lower() not in PAID_PLANS:
        send_message(chat_id, "Tu Apex Pro no está activo. Renuévalo en apex-vox.ialabs.app para seguir usando el bot.")
        return
    if int(media.get("file_size") or 0) > MAX_TELEGRAM_FILE_BYTES:
        send_message(chat_id, "Telegram solo permite a los bots descargar archivos de hasta 20 MB. Sube los audios grandes en la web.")
        return
    transcribe_media(user, chat_id, media, message.get("message_id"))


def _download(file_id: str) -> Optional[tuple[str, bytes]]:
    info = _api("getFile", file_id=file_id).get("result") or {}
    path = info.get("file_path")
    if not path:
        return None
    url = f"{TELEGRAM_API}/file/bot{settings.TELEGRAM_BOT_TOKEN}/{path}"
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.get(url)
        resp.raise_for_status()
        return Path(path).name, resp.content
    except httpx.HTTPError as exc:
        logger.warning("Telegram download failed: %s", exc)
        return None


def transcribe_media(user: Dict[str, Any], chat_id: int, media: Dict[str, Any], message_id: Optional[int]) -> None:
    from app.models.schemas import TranscribeRequest
    from app.services.job_manager import job_manager

    send_message(chat_id, "Recibido. Transcribiendo con Apex Vox…")
    downloaded = _download(media.get("file_id", ""))
    if not downloaded:
        send_message(chat_id, "No pude descargar el audio desde Telegram. Intenta de nuevo.")
        return
    name, content = downloaded
    suffix = Path(name).suffix.lower()
    if suffix not in settings.ALLOWED_EXTENSIONS:
        name = f"{Path(name).stem or 'telegram'}.ogg" if suffix in ("", ".oga") else name
    filename = media.get("file_name") or name
    owner = user["user_id"]
    try:
        session = job_manager.create_or_get_session(None, owner)
        job_manager.add_file_to_session(session.session_id, filename, content, owner=owner)
        req = TranscribeRequest(
            session_id=session.session_id,
            diarization_engine=settings.DEFAULT_DIARIZATION_ENGINE or "Mc-Lewis",
            model=settings.DEFAULT_DIARIZATION_ENGINE or "Mc-Lewis",
            language=None,
            user_id=owner,
        )
        status = job_manager.create_job(req)
        result = job_manager.execute_job(status.job_id, req)
    except PermissionError as exc:
        send_message(chat_id, str(exc))
        return
    except Exception as exc:  # pipeline errors are reported, never raised to Telegram
        logger.exception("Telegram transcription failed")
        send_message(chat_id, f"No se pudo transcribir el audio: {exc}")
        return

    text = result.full_text or "(sin voz detectada)"
    preview = text if len(text) <= 3500 else text[:3500] + "…"
    send_message(chat_id, preview)
    send_document(
        chat_id,
        f"apex-vox-{status.job_id}.txt",
        text.encode("utf-8"),
        caption=f"{result.total_duration_formatted} · {result.detected_speakers_count} orador(es) · {result.engine_brand}",
    )


def handle_update_async(update: Dict[str, Any]) -> None:
    threading.Thread(target=handle_update, args=(update,), daemon=True).start()
