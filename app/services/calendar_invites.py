"""
Invitaciones por correo (app/services/calendar_invites.py)
----------------------------------------------------------
Invita a agenda@apexbox.ialabs.app a tus reuniones (o reenvíale la invitación). Apex Vox lee
el archivo de calendario (.ics), guarda el evento en tu cuenta y, si tienes Apex Pro y la
reunión tiene enlace de Zoom / Meet / Teams / Webex, programa el bot para que entre a grabar.
Solo se acepta si quien envía o quien organiza es el dueño de la cuenta (no basta con
aparecer como invitado), y se rechazan correos que fallan SPF y DKIM.
"""

from __future__ import annotations

import datetime as dt
import email
import email.policy
import email.utils
import logging
import re
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.services import recall_service
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.services.calendar_invites")
RESEND_API = "https://api.resend.com"


# ---------------------------------------------------------------------------
# iCalendar mínimo (RFC 5545)
# ---------------------------------------------------------------------------

def _unfold(text: str) -> List[str]:
    lines: List[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _parse_dt(value: str, params: Dict[str, str]) -> Optional[dt.datetime]:
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
            d = dt.datetime.strptime(value[:8], "%Y%m%d")
            return d.replace(tzinfo=dt.timezone.utc)
        if value.endswith("Z"):
            return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        naive = dt.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
        tz = params.get("TZID")
        try:
            return naive.replace(tzinfo=ZoneInfo(tz)) if tz else naive.replace(tzinfo=dt.timezone.utc)
        except Exception:  # noqa: BLE001 — TZID de Windows u otro no estándar
            return naive.replace(tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    except ValueError:
        return None


def parse_ics(text: str) -> Dict[str, Any]:
    """Devuelve {'method': ..., 'events': [...]} con los VEVENT del calendario."""
    method, events, cur = "", [], None
    for line in _unfold(text):
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *rawp = head.split(";")
        params = {p.split("=", 1)[0].upper(): p.split("=", 1)[1].strip('"') for p in rawp if "=" in p}
        name = name.upper()
        if name == "METHOD":
            method = value.strip().upper()
        elif name == "BEGIN" and value.strip().upper() == "VEVENT":
            cur = {"attendees": []}
        elif name == "END" and value.strip().upper() == "VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None:
            if name in ("DTSTART", "DTEND"):
                cur[name.lower()] = _parse_dt(value, params)
            elif name in ("SUMMARY", "LOCATION", "DESCRIPTION", "URL", "UID", "STATUS", "SEQUENCE",
                          "X-GOOGLE-CONFERENCE", "X-MICROSOFT-SKYPETEAMSMEETINGURL"):
                cur[name.lower()] = _unescape(value.strip())
            elif name == "ORGANIZER":
                cur["organizer"] = value.split(":", 1)[-1].strip().lower()
            elif name == "ATTENDEE":
                cur["attendees"].append(value.split(":", 1)[-1].strip().lower())
    return {"method": method, "events": events}


def meeting_url_of(ev: Dict[str, Any]) -> Optional[str]:
    return recall_service.extract_meeting_url(
        ev.get("x-google-conference"), ev.get("x-microsoft-skypeteamsmeetingurl"),
        ev.get("location"), ev.get("url"), ev.get("description"),
    )


# ---------------------------------------------------------------------------
# Correo entrante (Resend)
# ---------------------------------------------------------------------------

def _fetch_received(email_id: str) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{RESEND_API}/emails/receiving/{email_id}",
                       headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"})
        r.raise_for_status()
        return r.json()


def _ics_from_raw(raw_bytes: bytes) -> List[str]:
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    found = []
    for part in msg.walk():
        ctype = part.get_content_type()
        fname = (part.get_filename() or "").lower()
        if ctype in ("text/calendar", "application/ics") or fname.endswith(".ics"):
            payload = part.get_payload(decode=True) or b""
            found.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    return found


def _auth_failed(received: Dict[str, Any]) -> bool:
    auth = received.get("authentication") or {}
    if not isinstance(auth, dict) or not auth:
        return False
    results = {str(k).lower(): str((v or {}).get("result") if isinstance(v, dict) else v).lower() for k, v in auth.items()}
    return results.get("spf") not in ("pass", "none", "") and results.get("dkim") not in ("pass", "none", "")


def _users_by_email(db: Dict[str, Any]) -> Dict[str, str]:
    return {str(u.get("email", "")).lower(): uid for uid, u in db["users"].items() if u.get("email")}


def process_inbound_email(email_id: str) -> Dict[str, Any]:
    received = _fetch_received(email_id)
    if _auth_failed(received):
        return {"status": "rejected", "reason": "spf_dkim"}
    raw_url = (received.get("raw") or {}).get("download_url")
    if not raw_url:
        return {"status": "ignored", "reason": "no_raw"}
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        raw = client.get(raw_url).content
    sender = email.utils.parseaddr(str(received.get("from") or ""))[1].lower()
    results = []
    for ics in _ics_from_raw(raw):
        cal = parse_ics(ics)
        for ev in cal["events"]:
            results.append(apply_event(ev, cal["method"], sender, str(received.get("subject") or "")))
    return {"status": "processed" if results else "ignored", "events": results}


def apply_event(ev: Dict[str, Any], method: str, sender: str, subject: str = "") -> Dict[str, Any]:
    """Guarda / actualiza / cancela el evento en la cuenta dueña y programa el bot."""
    with supabase_service._lock:
        db = supabase_service._load_db()
        by_email = _users_by_email(db)
    owner_email = sender if sender in by_email else (ev.get("organizer") if ev.get("organizer") in by_email else None)
    if not owner_email:
        return {"status": "ignored", "reason": "unknown_account"}
    user_id = by_email[owner_email]
    uid = ev.get("uid") or recall_service.new_uid()
    cancelled = method == "CANCEL" or str(ev.get("status", "")).upper() == "CANCELLED"
    start = ev.get("dtstart")
    url = meeting_url_of(ev)

    with supabase_service._lock:
        db = supabase_service._load_db()
        events = db.setdefault("calendar_events", {}).setdefault(user_id, {})
        prev = events.get(uid) or {}
        user = db["users"].get(user_id) or {}
    if prev.get("bot_id") and (cancelled or (start and prev.get("start") != start.isoformat())):
        recall_service.cancel_bot(prev["bot_id"])
        prev["bot_id"] = None

    record = {
        "uid": uid, "title": ev.get("summary") or subject or "Reunión",
        "start": start.isoformat() if start else None,
        "end": ev["dtend"].isoformat() if ev.get("dtend") else None,
        "meeting_url": url, "status": "cancelled" if cancelled else "scheduled",
        "bot_id": prev.get("bot_id"), "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    paid = str(user.get("plan", "free")).lower() in ("pro", "trial")
    now = dt.datetime.now(dt.timezone.utc)
    if (not cancelled and url and start and start > now and not record["bot_id"]
            and paid and recall_service.is_configured()):
        try:
            bot = recall_service.create_bot(user_id, url, record["title"], join_at=start - dt.timedelta(minutes=1),
                                            source="invite", event_uid=uid)
            record["bot_id"] = bot["bot_id"]
        except recall_service.RecallError as exc:
            record["bot_error"] = str(exc)
    with supabase_service._lock:
        db = supabase_service._load_db()
        db.setdefault("calendar_events", {}).setdefault(user_id, {})[uid] = record
        supabase_service._save_db(db)
    return {"status": record["status"], "uid": uid, "bot": bool(record["bot_id"])}


def upcoming_events(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    with supabase_service._lock:
        events = list((supabase_service._load_db().get("calendar_events") or {}).get(user_id, {}).values())
    keep = []
    for e in events:
        try:
            if e.get("start") and dt.datetime.fromisoformat(e["start"]) >= now and e.get("status") != "cancelled":
                keep.append(dict(e))
        except ValueError:
            continue
    return sorted(keep, key=lambda e: e["start"])[:limit]
