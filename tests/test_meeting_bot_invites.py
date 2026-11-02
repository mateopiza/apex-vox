"""Bot de reuniones (Recall.ai) e invitaciones por correo (Resend Inbound)."""

import base64
import datetime as dt
import hashlib
import hmac
import json
import time
import uuid

import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import calendar_invites, recall_service
from app.services.supabase_service import supabase_service

SECRET = "whsec_" + base64.b64encode(b"test-signing-key-1234567890").decode()


def _sign(body: bytes, prefix: str = "svix") -> dict:
    mid, ts = "msg_" + uuid.uuid4().hex[:8], str(int(time.time()))
    sig = base64.b64encode(hmac.new(b"test-signing-key-1234567890", f"{mid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {f"{prefix}-id": mid, f"{prefix}-timestamp": ts, f"{prefix}-signature": f"v1,{sig}", "content-type": "application/json"}


def _user(client: TestClient, pro: bool) -> dict:
    p = client.post("/api/auth/register", json={"email": f"bot_{uuid.uuid4().hex[:8]}@apexvox.ai",
                                                "password": "longpassword1", "full_name": "Bot"}).json()
    if pro:
        supabase_service.activate_paid_period(p["user_id"], f"BOTTEST-{p['user_id'][:8]}", "USD", "test")
    return p


@pytest.fixture()
def fake_recall(monkeypatch):
    calls = []

    def fake_request(method, path, json_body=None):
        calls.append((method, path, json_body))
        if method == "POST" and path == "/bot/":
            return {"id": "bot_" + uuid.uuid4().hex[:8]}
        return {}

    monkeypatch.setattr(settings, "RECALL_API_KEY", "test-key")
    monkeypatch.setattr(recall_service, "_request", fake_request)
    return calls


def test_svix_signature() -> None:
    body = b'{"a":1}'
    assert recall_service.verify_svix(SECRET, _sign(body), body)
    assert recall_service.verify_svix(SECRET, _sign(body, "webhook"), body)  # cabeceras de Recall
    assert not recall_service.verify_svix(SECRET, _sign(body), b'{"a":2}')
    old = _sign(body)
    old["svix-timestamp"] = str(int(time.time()) - 3600)
    assert not recall_service.verify_svix(SECRET, old, body)


ICS = """BEGIN:VCALENDAR
METHOD:REQUEST
BEGIN:VEVENT
UID:evt-123@google.com
SUMMARY:Comité semanal
DTSTART;TZID=America/Bogota:{start}
DTEND;TZID=America/Bogota:{end}
ORGANIZER;CN=Dueño:mailto:{organizer}
ATTENDEE;CN=Agenda:mailto:agenda@apexbox.ialabs.app
DESCRIPTION:Únete con Google Meet: https://meet.google.com/abc-defg-hij\\n
 Más info
END:VEVENT
END:VCALENDAR"""


def _ics(organizer: str, hours_ahead: int = 3) -> str:
    start = (dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))) + dt.timedelta(hours=hours_ahead)).replace(microsecond=0)
    fmt = "%Y%m%dT%H%M%S"
    return ICS.format(start=start.strftime(fmt), end=(start + dt.timedelta(hours=1)).strftime(fmt), organizer=organizer)


def test_parse_ics_extracts_event_and_meeting_link() -> None:
    cal = calendar_invites.parse_ics(_ics("ana@example.com"))
    assert cal["method"] == "REQUEST" and len(cal["events"]) == 1
    ev = cal["events"][0]
    assert ev["summary"] == "Comité semanal" and ev["organizer"] == "ana@example.com"
    assert ev["dtstart"].utcoffset() == dt.timedelta(hours=-5)
    assert calendar_invites.meeting_url_of(ev) == "https://meet.google.com/abc-defg-hij"


def test_invite_schedules_bot_only_for_owner_with_pro(fake_recall) -> None:
    client = TestClient(app)
    pro, free = _user(client, pro=True), _user(client, pro=False)
    ev = calendar_invites.parse_ics(_ics(pro["email"]))["events"][0]

    # Un tercero que solo pone a la víctima como invitada no crea nada en su cuenta
    ev_attendee = dict(ev, organizer="atacante@example.com", attendees=[pro["email"]])
    assert calendar_invites.apply_event(ev_attendee, "REQUEST", "atacante@example.com")["reason"] == "unknown_account"

    res = calendar_invites.apply_event(ev, "REQUEST", "otro@example.com")  # organizador = dueño
    assert res["status"] == "scheduled" and res["bot"] is True
    method, path, body = fake_recall[-1]
    assert (method, path) == ("POST", "/bot/") and body["meeting_url"] == "https://meet.google.com/abc-defg-hij"
    assert body["metadata"]["user_id"] == pro["user_id"] and "join_at" in body

    events = client.get("/api/meetings", headers={"Authorization": f"Bearer {pro['access_token']}"}).json()
    assert any(b["source"] == "invite" for b in events["bots"])

    # Cancelación: se cancela el bot programado
    assert calendar_invites.apply_event(ev, "CANCEL", pro["email"])["status"] == "cancelled"
    assert fake_recall[-1][0] == "DELETE"

    # Plan gratis: el evento se guarda, pero sin bot
    ev_free = calendar_invites.parse_ics(_ics(free["email"]))["events"][0]
    assert calendar_invites.apply_event(ev_free, "REQUEST", free["email"])["bot"] is False


def test_bot_endpoint_requires_pro_and_valid_link(fake_recall) -> None:
    client = TestClient(app)
    free, pro = _user(client, pro=False), _user(client, pro=True)
    url = "https://meet.google.com/abc-defg-hij"
    assert client.post("/api/meetings/bot", json={"meeting_url": url}).status_code == 401
    assert client.post("/api/meetings/bot", json={"meeting_url": url},
                       headers={"Authorization": f"Bearer {free['access_token']}"}).status_code == 402
    auth = {"Authorization": f"Bearer {pro['access_token']}"}
    assert client.post("/api/meetings/bot", json={"meeting_url": "https://evil.example/x"}, headers=auth).status_code == 400
    ok = client.post("/api/meetings/bot", json={"meeting_url": url, "title": "Daily"}, headers=auth)
    assert ok.status_code == 200 and ok.json()["status"] == "joining"
    other = _user(client, pro=True)
    foreign = client.delete(f"/api/meetings/bot/{ok.json()['bot_id']}",
                            headers={"Authorization": f"Bearer {other['access_token']}"})
    assert foreign.status_code == 404


def test_webhooks_require_valid_signature(monkeypatch, fake_recall) -> None:
    monkeypatch.setattr(settings, "RECALL_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(settings, "RESEND_INBOUND_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(recall_service, "process_finished_bot", lambda bot_id: None)
    client = TestClient(app)
    body = json.dumps({"event": "bot.in_call_recording", "data": {"bot": {"id": "bot_x"}, "data": {"code": "x"}}}).encode()
    assert client.post("/api/recall/webhook", content=body, headers={"content-type": "application/json"}).status_code == 401
    assert client.post("/api/recall/webhook", content=body, headers=_sign(body, "webhook")).json()["status"] == "ok"

    seen = []
    monkeypatch.setattr(calendar_invites, "process_inbound_email", lambda eid: seen.append(eid))
    inbound = json.dumps({"type": "email.received", "data": {"email_id": "em_1"}}).encode()
    assert client.post("/api/inbound/resend", content=inbound, headers={"content-type": "application/json"}).status_code == 401
    assert client.post("/api/inbound/resend", content=inbound, headers=_sign(inbound)).json()["status"] == "accepted"
    time.sleep(0.2)
    assert seen == ["em_1"]
