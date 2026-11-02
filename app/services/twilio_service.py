"""
Llamadas grabadas con número enmascarado (app/services/twilio_service.py)
-------------------------------------------------------------------------
1. El usuario verifica su celular con un código SMS (Twilio Verify). Solo a ese número
   llama Apex Vox, así nadie puede usar la cuenta para hacer sonar teléfonos ajenos.
2. «Llamar»: Twilio llama primero al celular verificado. Al contestar, el usuario pulsa 1
   (así un buzón de voz nunca queda conectado al contacto) y Twilio marca al destino
   mostrando TWILIO_CALLER_ID: el contacto nunca ve el número real del usuario.
3. Ambas partes oyen un aviso de grabación. Se graba en doble canal (canal 1 = usuario,
   canal 2 = contacto), lo que da oradores exactos sin adivinar voces.
4. Durante la llamada el usuario puede tomar apuntes; se ubican en la línea de tiempo.
5. Al terminar, la grabación pasa por la tubería de Apex Box (bloques de 3 min), se
   generan resumen y acta, y el usuario recibe el enlace por correo.

Los webhooks de Twilio se validan con la firma X-Twilio-Signature (HMAC-SHA1).
"""

from __future__ import annotations

import base64
import datetime as dt
import email.utils
import hashlib
import hmac
import logging
import re
import shutil
import subprocess
import threading
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape, quoteattr

import httpx

from app.config import settings
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.services.twilio_service")

API_BASE = "https://api.twilio.com/2010-04-01"
VERIFY_BASE = "https://verify.twilio.com/v2"
E164_RE = re.compile(r"\+[1-9]\d{7,14}")
CODE_RE = re.compile(r"\d{4,10}")
BLOCK_SEC = 180
FRAME_SEC = 0.1
NOTE_TAGS = ("nota", "acuerdo", "tarea", "alerta", "idea", "pregunta")
MAX_NOTES_PER_CALL = 200

# Estados de una llamada
ACTIVE_STATUSES = ("initiating", "calling_you", "connecting", "in_call")
NOTE_STATUSES = ACTIVE_STATUSES + ("awaiting_recording",)
FINAL_STATUSES = ("done", "failed", "ended", "no_answer", "busy", "cancelled", "contact_no_answer", "contact_busy")


class TwilioError(Exception):
    pass


# ---------------------------------------------------------------------------
# Configuración y API REST
# ---------------------------------------------------------------------------

def webhook_base() -> str:
    """Origen público de los webhooks: SOLO de PUBLIC_BASE_URL, nunca de la cabecera Host de la petición.

    Si viniera de la petición, un usuario podría enviar `Host: atacante.com` y Twilio pediría ahí
    las instrucciones de la llamada (TwiML): el atacante marcaría cualquier número a costa del servicio.
    """
    return (settings.PUBLIC_BASE_URL or "").rstrip("/")


def is_configured() -> bool:
    return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN
                and settings.TWILIO_VERIFY_SERVICE_SID and E164_RE.fullmatch(settings.TWILIO_CALLER_ID or "")
                and webhook_base().startswith("https://"))


def _auth() -> Tuple[str, str]:
    if settings.TWILIO_API_KEY_SID and settings.TWILIO_API_KEY_SECRET:
        return settings.TWILIO_API_KEY_SID, settings.TWILIO_API_KEY_SECRET
    return settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN


def _request(method: str, url: str, data: Optional[Sequence[Tuple[str, str]]] = None) -> Dict[str, Any]:
    if not is_configured():
        raise TwilioError("Las llamadas no están configuradas en este servidor.")
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.request(method, url, data=list(data or []), auth=_auth())
    except httpx.HTTPError as exc:
        raise TwilioError(f"No se pudo contactar al servicio de llamadas: {exc}") from exc
    if resp.status_code >= 400:
        logger.warning("Twilio %s %s -> %s %s", method, url.split("?")[0], resp.status_code, resp.text[:300])
        try:
            detail = resp.json().get("message") or ""
        except ValueError:
            detail = ""
        raise TwilioError(f"El servicio de llamadas respondió {resp.status_code}. {detail}".strip())
    return resp.json() if resp.content else {}


def _account_url(path: str) -> str:
    return f"{API_BASE}/Accounts/{settings.TWILIO_ACCOUNT_SID}{path}"


def validate_signature(url: str, params: Dict[str, str], signature: Optional[str]) -> bool:
    """X-Twilio-Signature = base64(HMAC-SHA1(auth_token, url + clave1valor1 + clave2valor2…))."""
    if not signature or not settings.TWILIO_AUTH_TOKEN:
        return False
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    expected = base64.b64encode(
        hmac.new(settings.TWILIO_AUTH_TOKEN.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Números
# ---------------------------------------------------------------------------

def normalize_phone(raw: str) -> str:
    """'+57 300 123-4567' → '+573001234567'. Exige el indicativo del país."""
    s = re.sub(r"[\s().\-]", "", str(raw or ""))
    if s.startswith("00"):
        s = "+" + s[2:]
    if not E164_RE.fullmatch(s):
        raise TwilioError("Número no válido: escríbelo con el indicativo del país, p. ej. +57 300 123 4567.")
    return s


def is_allowed_destination(phone: str) -> bool:
    """Prefijo permitido y no bloqueado (los bloqueados ganan: p. ej. +1-876 Jamaica dentro de +1)."""
    if any(phone.startswith(p.strip()) for p in settings.CALL_BLOCKED_PREFIXES if p.strip().startswith("+")):
        return False
    return any(phone.startswith(p.strip()) for p in settings.CALL_ALLOWED_PREFIXES if p.strip().startswith("+"))


def mask_phone(phone: Optional[str]) -> str:
    """'+573001234567' → '+57 ••• ••4567' (para mostrar sin exponer el número completo)."""
    if not phone:
        return ""
    digits = phone.lstrip("+")
    cc = 1 if digits.startswith("1") else (2 if len(digits) > 10 else 1)
    return f"+{digits[:cc]} ••• ••{digits[-4:]}"


# ---------------------------------------------------------------------------
# Verificación del celular del usuario (Twilio Verify)
# ---------------------------------------------------------------------------

def phone_state(user: Dict[str, Any]) -> Dict[str, Any]:
    phone = user.get("phone_e164")
    return {
        "calling_enabled": is_configured(),
        "phone_verified": bool(phone and user.get("phone_verified_at")),
        "phone_masked": mask_phone(phone),
        "caller_id": settings.TWILIO_CALLER_ID if is_configured() else "",
        "allowed_prefixes": settings.CALL_ALLOWED_PREFIXES,
        "recording_notice": settings.CALL_RECORDING_NOTICE,
    }


def _update_user(user_id: str, **fields: Any) -> None:
    with supabase_service._lock:
        db = supabase_service._load_db()
        user = db["users"].get(user_id)
        if user is None:
            raise TwilioError("Cuenta no encontrada.")
        for k, v in fields.items():
            if v is None:
                user.pop(k, None)
            else:
                user[k] = v
        supabase_service._save_db(db)


def start_verification(user: Dict[str, Any], raw_phone: str) -> Dict[str, Any]:
    phone = normalize_phone(raw_phone)
    if not is_allowed_destination(phone):
        raise TwilioError("Por ahora solo se aceptan números de: " + ", ".join(settings.CALL_ALLOWED_PREFIXES))
    if phone == settings.TWILIO_CALLER_ID:
        raise TwilioError("Ese es el número de Apex Vox, no el tuyo.")
    lang = "en" if user.get("preferred_language") == "en" else "es"
    _request("POST", f"{VERIFY_BASE}/Services/{settings.TWILIO_VERIFY_SERVICE_SID}/Verifications",
             [("To", phone), ("Channel", "sms"), ("Locale", lang)])
    _update_user(user["user_id"], phone_pending=phone, phone_pending_at=_now_iso())
    return {"status": "pending", "phone_masked": mask_phone(phone)}


def check_verification(user: Dict[str, Any], raw_phone: str, code: str) -> Dict[str, Any]:
    phone = normalize_phone(raw_phone)
    code = str(code or "").strip()
    if not CODE_RE.fullmatch(code):
        raise TwilioError("El código tiene solo números.")
    if user.get("phone_pending") != phone:
        raise TwilioError("Primero pide el código para ese número.")
    try:
        res = _request("POST", f"{VERIFY_BASE}/Services/{settings.TWILIO_VERIFY_SERVICE_SID}/VerificationCheck",
                       [("To", phone), ("Code", code)])
    except TwilioError as exc:
        if "404" in str(exc):  # vencido o ya usado
            raise TwilioError("El código venció. Pide uno nuevo.") from exc
        raise
    if res.get("status") != "approved":
        raise TwilioError("Código incorrecto.")
    _update_user(user["user_id"], phone_e164=phone, phone_verified_at=_now_iso(),
                 phone_pending=None, phone_pending_at=None)
    return {"status": "verified", "phone_masked": mask_phone(phone)}


def remove_phone(user_id: str) -> None:
    _update_user(user_id, phone_e164=None, phone_verified_at=None, phone_pending=None, phone_pending_at=None)


# ---------------------------------------------------------------------------
# Registro de llamadas (estado en el archivo JSON, como los bots de reuniones)
# ---------------------------------------------------------------------------

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _calls(db: Dict[str, Any]) -> Dict[str, Any]:
    return db.setdefault("phone_calls", {})


def get_call(call_id: str) -> Optional[Dict[str, Any]]:
    with supabase_service._lock:
        rec = _calls(supabase_service._load_db()).get(call_id)
        return dict(rec) if rec else None


def _update(call_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    with supabase_service._lock:
        db = supabase_service._load_db()
        rec = _calls(db).get(call_id)
        if not rec:
            return None
        rec.update(fields)
        rec["updated_at"] = _now_iso()
        supabase_service._save_db(db)
        return dict(rec)


def public_call(rec: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("call_id", "title", "contact_name", "to", "status", "created_at", "answered_at", "ended_at",
            "duration_sec", "job_id", "error")
    out = {k: rec.get(k) for k in keys}
    out["to_masked"] = mask_phone(rec.get("to"))
    out["caller_id"] = rec.get("caller_id")
    out["notes"] = list(rec.get("notes") or [])
    return out


def list_calls(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with supabase_service._lock:
        items = [dict(c) for c in _calls(supabase_service._load_db()).values() if c.get("user_id") == user_id]
    items.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return [public_call(c) for c in items[:limit]]


def _is_stale(rec: Dict[str, Any]) -> bool:
    try:
        created = dt.datetime.fromisoformat(rec["created_at"])
    except (KeyError, ValueError):
        return True
    return _now() - created > dt.timedelta(minutes=settings.CALL_MAX_MINUTES + 15)


def create_call(user: Dict[str, Any], raw_to: str, title: str = "", contact_name: str = "") -> Dict[str, Any]:
    """Llama al celular verificado del usuario; al pulsar 1 se conecta con `raw_to`."""
    own = user.get("phone_e164")
    if not own or not user.get("phone_verified_at"):
        raise TwilioError("Primero verifica tu celular en «Llamadas».")
    to = normalize_phone(raw_to)
    if not is_allowed_destination(to):
        raise TwilioError("Ese destino no está permitido. Prefijos habilitados: " + ", ".join(settings.CALL_ALLOWED_PREFIXES))
    if to in (own, settings.TWILIO_CALLER_ID):
        raise TwilioError("No puedes llamarte a ti mismo ni al número de Apex Vox.")

    user_id = user["user_id"]
    since = _now() - dt.timedelta(days=1)
    with supabase_service._lock:
        mine = [c for c in _calls(supabase_service._load_db()).values() if c.get("user_id") == user_id]
    if any(c.get("status") in ACTIVE_STATUSES and not _is_stale(c) for c in mine):
        raise TwilioError("Ya tienes una llamada en curso.")
    if sum(1 for c in mine if c.get("created_at", "") >= since.isoformat()) >= settings.CALLS_PER_DAY:
        raise TwilioError("Llegaste al límite de llamadas de hoy.")

    call_id = f"call_{uuid.uuid4().hex[:16]}"
    contact_name = (contact_name or "").strip()[:80]
    record = {
        "call_id": call_id, "user_id": user_id, "to": to, "contact_name": contact_name,
        "title": (title or "").strip()[:120] or f"Llamada con {contact_name or mask_phone(to)}",
        "caller_id": settings.TWILIO_CALLER_ID, "status": "initiating", "notes": [],
        "language": "en" if user.get("preferred_language") == "en" else "es",
        "created_at": _now_iso(), "updated_at": _now_iso(),
        "call_sid": None, "recording_sid": None, "job_id": None,
    }
    with supabase_service._lock:
        db = supabase_service._load_db()
        _calls(db)[call_id] = record
        supabase_service._save_db(db)

    base = webhook_base()
    data: List[Tuple[str, str]] = [
        ("To", own), ("From", settings.TWILIO_CALLER_ID),
        ("Url", f"{base}/api/twilio/voice/{call_id}"), ("Method", "POST"),
        ("StatusCallback", f"{base}/api/twilio/status/{call_id}?leg=owner"), ("StatusCallbackMethod", "POST"),
        ("Timeout", "30"), ("TimeLimit", str(settings.CALL_MAX_MINUTES * 60 + 120)),
    ]
    data += [("StatusCallbackEvent", e) for e in ("initiated", "ringing", "answered", "completed")]
    try:
        res = _request("POST", _account_url("/Calls.json"), data)
    except TwilioError as exc:
        _update(call_id, status="failed", error=str(exc)[:200])
        raise
    return public_call(_update(call_id, call_sid=res.get("sid"), status="calling_you") or record)


def hangup(call_id: str) -> None:
    rec = get_call(call_id)
    if not rec:
        return
    if rec.get("call_sid") and rec.get("status") in ACTIVE_STATUSES:
        try:
            _request("POST", _account_url(f"/Calls/{rec['call_sid']}.json"), [("Status", "completed")])
        except TwilioError:
            logger.info("Call %s already finished when hanging up", call_id)  # Twilio ya la cerró
    if rec.get("status") in ACTIVE_STATUSES and rec.get("status") != "in_call":
        _update(call_id, status="cancelled")


def hangup_all(user_id: str) -> None:
    """Cuelga las llamadas activas de la cuenta (p. ej. antes de borrarla)."""
    with supabase_service._lock:
        ids = [c["call_id"] for c in _calls(supabase_service._load_db()).values()
               if c.get("user_id") == user_id and c.get("status") in ACTIVE_STATUSES]
    for call_id in ids:
        hangup(call_id)


def add_note(user_id: str, call_id: str, text: str, tag: str = "nota") -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise TwilioError("El apunte está vacío.")
    tag = (tag or "nota").strip().lower()
    if tag not in NOTE_TAGS:
        tag = "nota"
    with supabase_service._lock:
        db = supabase_service._load_db()
        rec = _calls(db).get(call_id)
        if not rec or rec.get("user_id") != user_id:
            raise KeyError(call_id)
        if rec.get("status") not in NOTE_STATUSES:
            raise TwilioError("La llamada ya se procesó: agrega el apunte en el resumen de la reunión.")
        notes = rec.setdefault("notes", [])
        if len(notes) >= MAX_NOTES_PER_CALL:
            raise TwilioError("Esta llamada ya tiene demasiados apuntes.")
        note = {"note_id": f"note_{uuid.uuid4().hex[:8]}", "text": text[:2000], "tag": tag, "at": _now_iso()}
        notes.append(note)
        supabase_service._save_db(db)
    return note


# ---------------------------------------------------------------------------
# TwiML
# ---------------------------------------------------------------------------

_SAY_LANG = {"es": "es-MX", "en": "en-US"}
_TEXTS = {
    "es": {
        "press": "Apex Vox. Pulsa 1 para conectar con {who}.",
        "no_input": "No recibimos respuesta. Hasta luego.",
        "notice_owner": "Conectando. La llamada se grabará para tomar notas.",
        "notice_contact": "Esta llamada será grabada para tomar notas.",
        "contact_failed": "El contacto no contestó.",
        "unavailable": "Esta llamada ya no está disponible.",
    },
    "en": {
        "press": "Apex Vox. Press 1 to connect with {who}.",
        "no_input": "We did not get a response. Goodbye.",
        "notice_owner": "Connecting. This call will be recorded for note taking.",
        "notice_contact": "This call will be recorded for note taking.",
        "contact_failed": "The contact did not answer.",
        "unavailable": "This call is no longer available.",
    },
}


def _lang(rec: Optional[Dict[str, Any]]) -> str:
    return "en" if (rec or {}).get("language") == "en" else "es"


def _say(text: str, lang: str) -> str:
    return f"<Say language={quoteattr(_SAY_LANG[lang])}>{escape(text)}</Say>"


def _twiml(*verbs: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(verbs) + "</Response>"


def _spoken_number(phone: str) -> str:
    return " ".join(phone.lstrip("+")[-4:])


def twiml_unavailable(rec: Optional[Dict[str, Any]] = None) -> str:
    return _twiml(_say(_TEXTS[_lang(rec)]["unavailable"], _lang(rec)), "<Hangup/>")


def twiml_owner_answered(rec: Dict[str, Any], base_url: str) -> str:
    """El usuario contestó: pide pulsar 1 (un buzón de voz nunca conecta con el contacto)."""
    lang, base = _lang(rec), base_url.rstrip("/")
    who = rec.get("contact_name") or (
        ("the number ending in " if lang == "en" else "el número terminado en ") + _spoken_number(rec["to"]))
    action = quoteattr(f"{base}/api/twilio/connect/{rec['call_id']}")
    return _twiml(
        f'<Gather numDigits="1" timeout="8" action={action} method="POST">'
        + _say(_TEXTS[lang]["press"].format(who=who), lang) + "</Gather>",
        _say(_TEXTS[lang]["no_input"], lang), "<Hangup/>",
    )


def twiml_connect(rec: Dict[str, Any], base_url: str) -> str:
    """Marca al contacto con el número de Apex Vox y graba en doble canal."""
    lang, base, cid = _lang(rec), base_url.rstrip("/"), rec["call_id"]
    number_attrs = [
        f"statusCallback={quoteattr(f'{base}/api/twilio/status/{cid}?leg=contact')}",
        'statusCallbackEvent="answered completed"', 'statusCallbackMethod="POST"',
    ]
    if settings.CALL_RECORDING_NOTICE:
        number_attrs.append(f"url={quoteattr(f'{base}/api/twilio/notice/{cid}')}")
    dial = (
        f"<Dial callerId={quoteattr(settings.TWILIO_CALLER_ID)} record=\"record-from-answer-dual\""
        f" recordingStatusCallback={quoteattr(f'{base}/api/twilio/recording/{cid}')}"
        ' recordingStatusCallbackMethod="POST" recordingStatusCallbackEvent="completed"'
        f" action={quoteattr(f'{base}/api/twilio/dial-done/{cid}')} method=\"POST\""
        f' timeout="40" timeLimit="{settings.CALL_MAX_MINUTES * 60}">'
        f"<Number {' '.join(number_attrs)}>{escape(rec['to'])}</Number></Dial>"
    )
    verbs = [_say(_TEXTS[lang]["notice_owner"], lang)] if settings.CALL_RECORDING_NOTICE else []
    return _twiml(*verbs, dial)


def twiml_contact_notice(rec: Dict[str, Any]) -> str:
    """Lo oye el contacto al contestar, antes de unirse a la llamada."""
    return _twiml(_say(_TEXTS[_lang(rec)]["notice_contact"], _lang(rec)))


def twiml_dial_done(rec: Dict[str, Any], dial_status: str) -> str:
    if dial_status in ("busy", "no-answer", "failed", "canceled"):
        return _twiml(_say(_TEXTS[_lang(rec)]["contact_failed"], _lang(rec)), "<Hangup/>")
    return _twiml("<Hangup/>")


# ---------------------------------------------------------------------------
# Webhooks de estado
# ---------------------------------------------------------------------------

def on_owner_pressed(call_id: str) -> None:
    _update(call_id, status="connecting")


def on_status(call_id: str, leg: str, params: Dict[str, str]) -> None:
    rec = get_call(call_id)
    if not rec or rec.get("status") in ("processing", "done"):
        return
    status = params.get("CallStatus", "")
    if leg == "contact":
        if status == "in-progress" and rec.get("status") != "in_call":
            _update(call_id, status="in_call", answered_at=_now_iso())
        return
    if status == "ringing" and rec.get("status") == "initiating":
        _update(call_id, status="calling_you")
    elif status == "completed":
        duration = int(params.get("CallDuration") or 0) or None
        nxt = "awaiting_recording" if rec.get("status") == "in_call" else (
            rec["status"] if rec.get("status") in FINAL_STATUSES else "ended")
        _update(call_id, status=nxt, ended_at=_now_iso(), owner_duration_sec=duration)
    elif status in ("busy", "no-answer", "failed", "canceled"):
        _update(call_id, status={"busy": "busy", "no-answer": "no_answer", "failed": "failed",
                                 "canceled": "cancelled"}[status], ended_at=_now_iso())


def on_dial_done(call_id: str, dial_status: str) -> None:
    rec = get_call(call_id)
    if not rec or rec.get("status") in ("processing", "done", "awaiting_recording"):
        return
    mapped = {"busy": "contact_busy", "no-answer": "contact_no_answer", "failed": "failed", "canceled": "cancelled"}
    if dial_status in mapped and rec.get("status") != "in_call":
        _update(call_id, status=mapped[dial_status], ended_at=_now_iso())


def on_recording(call_id: str, params: Dict[str, str]) -> bool:
    """Guarda los datos de la grabación y la procesa en segundo plano (una sola vez)."""
    if params.get("RecordingStatus") != "completed" or not params.get("RecordingSid"):
        return False
    with supabase_service._lock:
        db = supabase_service._load_db()
        rec = _calls(db).get(call_id)
        if not rec or rec.get("job_id") or rec.get("status") in ("processing", "done"):
            return False
        rec.update({
            "status": "processing", "recording_sid": params["RecordingSid"],
            "recording_url": params.get("RecordingUrl", ""),
            "recording_channels": int(params.get("RecordingChannels") or 1),
            "recording_start": params.get("RecordingStartTime", ""),
            "duration_sec": int(params.get("RecordingDuration") or 0),
            "updated_at": _now_iso(),
        })
        supabase_service._save_db(db)
    threading.Thread(target=process_recording, args=(call_id,), daemon=True).start()
    return True


# ---------------------------------------------------------------------------
# Procesar la grabación
# ---------------------------------------------------------------------------

def _download_recording(rec: Dict[str, Any], dst) -> int:
    """Descarga el MP3 (doble canal si existe). Devuelve el número de canales descargados."""
    url = rec.get("recording_url") or _account_url(f"/Recordings/{rec['recording_sid']}")
    attempts = [2, 1] if int(rec.get("recording_channels") or 1) == 2 else [1]
    last: Optional[Exception] = None
    for channels in attempts:
        try:
            with httpx.Client(timeout=300.0, follow_redirects=True) as client, client.stream(
                "GET", f"{url}.mp3", params={"RequestedChannels": channels}, auth=_auth()
            ) as resp:
                resp.raise_for_status()
                with open(dst, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
            return channels
        except httpx.HTTPError as exc:
            last = exc
    raise TwilioError(f"No se pudo descargar la grabación: {last}")


def channel_energy(path, frame_sec: float = FRAME_SEC):
    """Energía por ventana de cada canal: array (ventanas, 2). None si no es estéreo."""
    import numpy as np

    rate = 8000
    frame = int(rate * frame_sec)
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(rate), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    out: List[Any] = []
    step = frame * 2 * 2 * 200  # 200 ventanas por lectura
    rest = b""
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(step)
            if not buf:
                break
            buf = rest + buf
            usable = len(buf) - len(buf) % (frame * 4)
            rest = buf[usable:]
            if usable:
                pcm = np.frombuffer(buf[:usable], dtype=np.int16).astype(np.float32).reshape(-1, frame, 2)
                out.append(np.sqrt((pcm ** 2).mean(axis=1)))
    finally:
        proc.wait(timeout=60)
    if not out:
        return None
    energy = np.concatenate(out)
    left, right = energy[:, 0], energy[:, 1]
    if np.allclose(left, right, atol=1.0):  # mono duplicado: no sirve para separar oradores
        return None
    return energy


def label_by_channel(segments: Iterable[Any], energy, owner_label: str, contact_label: str) -> List[Any]:
    """Asigna cada segmento al canal con más voz (canal 1 = usuario, canal 2 = contacto)."""
    out = []
    n = len(energy)
    for seg in segments:
        i0 = max(0, min(n - 1, int(seg.start / FRAME_SEC)))
        i1 = max(i0 + 1, min(n, int(seg.end / FRAME_SEC) + 1))
        e = energy[i0:i1].sum(axis=0)
        if float(e.sum()) <= 0:
            out.append(seg)
            continue
        out.append(seg.model_copy(update={"speaker": owner_label if e[0] >= e[1] else contact_label}))
    return out


def _parse_rfc2822(value: str) -> Optional[dt.datetime]:
    try:
        parsed = email.utils.parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError):
        return None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _note_offset(note: Dict[str, Any], start: Optional[dt.datetime]) -> float:
    try:
        at = dt.datetime.fromisoformat(note["at"])
    except (KeyError, ValueError):
        return 0.0
    return max(0.0, (at - start).total_seconds()) if start else 0.0


def speaker_labels(user: Dict[str, Any], rec: Dict[str, Any]) -> Tuple[str, str]:
    first = str(user.get("full_name") or "").strip().split(" ")[0]
    owner = first or ("Me" if rec.get("language") == "en" else "Yo")
    contact = rec.get("contact_name") or rec.get("to") or "Contacto"
    if contact == owner:
        contact = f"{contact} (contacto)"
    return owner, contact


def process_recording(call_id: str) -> Optional[str]:
    """Descarga, transcribe en bloques, separa oradores por canal, integra apuntes y avisa al usuario."""
    from app.models.schemas import BoxCreateSessionRequest, BoxFinalizeRequest, BoxNoteRequest
    from app.services import email_service
    from app.services.apex_box import apex_box_manager
    from app.services.audio_engine import extract_chunk, probe_audio

    rec = get_call(call_id)
    if not rec:
        return None
    work = settings.TEMP_DIR / f"twilio_{call_id}"
    try:
        work.mkdir(parents=True, exist_ok=True)
        src = work / "call.mp3"
        channels = _download_recording(rec, src)
        total = float(probe_audio(src).duration_sec or 0.0)
        if total <= 1:
            raise TwilioError("La grabación no tiene audio.")

        with supabase_service._lock:
            user = dict(supabase_service._load_db()["users"].get(rec["user_id"]) or {})
        if not user:
            raise TwilioError("La cuenta ya no existe: no se guarda la llamada.")
        paid = str(user.get("plan", "free")).lower() in ("pro", "trial")
        owner_label, contact_label = speaker_labels(user, rec)
        session = apex_box_manager.create_session(BoxCreateSessionRequest(
            title=rec.get("title") or "Llamada", mode="virtual", platform="phone_call",
            user_id=rec["user_id"], plan="pro" if paid else "free", device_type="phone_call",
            num_speakers=2, language=rec.get("language") or "es",
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

        energy = channel_energy(src) if channels == 2 else None
        box = apex_box_manager.get_session(session.box_session_id)
        with apex_box_manager._lock:
            if energy is not None:
                box.segments = label_by_channel(box.segments, energy, owner_label, contact_label)
            box.num_speakers = 2

        rec_start = _parse_rfc2822(rec.get("recording_start", "")) or _iso(rec.get("answered_at"))
        for note in rec.get("notes") or []:
            apex_box_manager.add_note(session.box_session_id, BoxNoteRequest(
                text=note["text"], tag=note.get("tag") or "nota",
                timestamp_sec=min(total, _note_offset(note, rec_start)), author=owner_label,
            ))

        with supabase_service._lock:  # la cuenta pudo borrarse mientras se transcribía
            if rec["user_id"] not in supabase_service._load_db()["users"]:
                raise TwilioError("La cuenta ya no existe: no se guarda la llamada.")
        fin = apex_box_manager.finalize_session(
            session.box_session_id, BoxFinalizeRequest(generate_minutes=True),
            record_extra={
                "source": "phone_call", "call_id": call_id, "contact_name": rec.get("contact_name") or "",
                "contact_number": rec.get("to"), "caller_id": rec.get("caller_id"), "direction": "outbound",
                "speakers_by_channel": energy is not None,
            },
        )
        _update(call_id, status="done", job_id=fin.job_id)
        if settings.TWILIO_DELETE_RECORDINGS:
            try:
                _request("DELETE", _account_url(f"/Recordings/{rec['recording_sid']}.json"))
            except TwilioError:
                logger.warning("No se pudo borrar la grabación %s en Twilio", rec.get("recording_sid"))
        link = f"{settings.PUBLIC_BASE_URL or 'https://apex-vox.ialabs.app'}/?job={fin.job_id}"
        if user.get("email"):
            email_service.send_email(user["email"], email_service.render_meeting_ready(
                user.get("full_name", ""), rec.get("title") or "Llamada", fin.total_duration_formatted, link,
                user.get("preferred_language", "es")), tags=[{"name": "category", "value": "call_ready"}])
        return fin.job_id
    except Exception as exc:  # noqa: BLE001 — se registra y la llamada queda como fallida
        logger.exception("No se pudo procesar la llamada %s", call_id)
        _update(call_id, status="failed", error=str(exc)[:200])
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _iso(value: Optional[str]) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
