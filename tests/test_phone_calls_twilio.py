"""Llamadas grabadas con número enmascarado (Twilio): verificación, webhooks firmados y procesamiento."""

import base64
import datetime as dt
import hashlib
import hmac
import subprocess
import time
import uuid
from urllib.parse import urlencode

import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.schemas import DiarizedSegment
from app.services import twilio_service
from app.services.supabase_service import supabase_service

TOKEN = "test_auth_token_123"
CALLER = "+15005550006"
BASE = "https://apex.test"


@pytest.fixture()
def twilio(monkeypatch):
    calls = []

    def fake_request(method, url, data=None):
        calls.append((method, url, list(data or [])))
        if url.endswith("/Verifications"):
            return {"status": "pending"}
        if url.endswith("/VerificationCheck"):
            code = dict(data or []).get("Code")
            return {"status": "approved" if code == "123456" else "pending"}
        if url.endswith("/Calls.json"):
            return {"sid": "CA" + uuid.uuid4().hex}
        return {}

    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "TWILIO_VERIFY_SERVICE_SID", "VA" + "0" * 32)
    monkeypatch.setattr(settings, "TWILIO_CALLER_ID", CALLER)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", BASE)
    monkeypatch.setattr(settings, "CALL_ALLOWED_PREFIXES", ["+57", "+1"])
    monkeypatch.setattr(twilio_service, "_request", fake_request)
    return calls


def _sign(url: str, params: dict) -> str:
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def _webhook(client: TestClient, path: str, params: dict, sign: bool = True):
    url = BASE + path
    headers = {"content-type": "application/x-www-form-urlencoded"}
    if sign:
        headers["x-twilio-signature"] = _sign(url, params)
    return client.post(path, content=urlencode(params), headers=headers)


def _user(client: TestClient, pro: bool = True) -> dict:
    p = client.post("/api/auth/register", json={"email": f"call_{uuid.uuid4().hex[:8]}@apexvox.ai",
                                                "password": "longpassword1", "full_name": "Ana Pérez"}).json()
    if pro:
        supabase_service.activate_paid_period(p["user_id"], f"CALLTEST-{p['user_id'][:8]}", "USD", "test")
    return p


def _auth(p: dict) -> dict:
    return {"Authorization": f"Bearer {p['access_token']}"}


def _verified(client: TestClient, pro: bool = True) -> dict:
    p = _user(client, pro)
    assert client.post("/api/phone/verify/start", json={"phone": "+57 300 123 4567"}, headers=_auth(p)).status_code == 200
    r = client.post("/api/phone/verify/check", json={"phone": "+573001234567", "code": "123456"}, headers=_auth(p))
    assert r.status_code == 200 and r.json()["status"] == "verified"
    return p


def test_phone_helpers() -> None:
    assert twilio_service.normalize_phone("+57 (300) 123-4567") == "+573001234567"
    assert twilio_service.normalize_phone("0057 300 123 4567") == "+573001234567"
    with pytest.raises(twilio_service.TwilioError):
        twilio_service.normalize_phone("3001234567")  # sin indicativo
    assert twilio_service.mask_phone("+573001234567") == "+57 ••• ••4567"
    assert twilio_service.mask_phone("+13055551234") == "+1 ••• ••1234"


def test_signature_validation(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", TOKEN)
    params = {"CallSid": "CA1", "Digits": "1"}
    sig = _sign(BASE + "/x?leg=owner", params)
    assert twilio_service.validate_signature(BASE + "/x?leg=owner", params, sig)
    assert not twilio_service.validate_signature(BASE + "/x?leg=contact", params, sig)
    assert not twilio_service.validate_signature(BASE + "/x?leg=owner", {**params, "Digits": "2"}, sig)
    assert not twilio_service.validate_signature(BASE + "/x?leg=owner", params, None)


def test_verification_requires_pro_and_correct_code(twilio) -> None:
    client = TestClient(app)
    free = _user(client, pro=False)
    assert client.post("/api/phone/verify/start", json={"phone": "+573001234567"}, headers=_auth(free)).status_code == 402

    p = _user(client)
    bad_prefix = client.post("/api/phone/verify/start", json={"phone": "+447700900123"}, headers=_auth(p))
    assert bad_prefix.status_code == 400
    assert client.post("/api/phone/verify/start", json={"phone": "+573001234567"}, headers=_auth(p)).status_code == 200
    wrong = client.post("/api/phone/verify/check", json={"phone": "+573001234567", "code": "000000"}, headers=_auth(p))
    assert wrong.status_code == 400
    other = client.post("/api/phone/verify/check", json={"phone": "+573009999999", "code": "123456"}, headers=_auth(p))
    assert other.status_code == 400  # nunca se pidió código para ese número
    ok = client.post("/api/phone/verify/check", json={"phone": "+573001234567", "code": "123456"}, headers=_auth(p))
    assert ok.status_code == 200
    state = client.get("/api/phone", headers=_auth(p)).json()
    assert state["phone_verified"] is True and state["phone_masked"].endswith("4567") and state["caller_id"] == CALLER


def test_call_needs_verified_phone_and_allowed_destination(twilio) -> None:
    client = TestClient(app)
    p = _user(client)
    r = client.post("/api/calls", json={"to": "+573105556677"}, headers=_auth(p))
    assert r.status_code == 400 and "verifica" in r.json()["detail"]
    p = _verified(client)
    assert client.post("/api/calls", json={"to": "+447700900123"}, headers=_auth(p)).status_code == 400
    assert client.post("/api/calls", json={"to": "+573001234567"}, headers=_auth(p)).status_code == 400  # a sí mismo
    assert client.post("/api/calls", json={"to": CALLER}, headers=_auth(p)).status_code == 400


def test_full_call_flow_with_masked_number_and_notes(twilio, monkeypatch) -> None:
    client = TestClient(app)
    p = _verified(client)
    r = client.post("/api/calls", json={"to": "+57 310 555 6677", "contact_name": "Carlos"}, headers=_auth(p))
    assert r.status_code == 200, r.text
    call = r.json()
    cid = call["call_id"]
    assert call["status"] == "calling_you" and call["caller_id"] == CALLER

    # Twilio llama primero al celular verificado del usuario, desde el número enmascarado
    method, url, data = twilio[-1]
    sent = dict(data)
    assert url.endswith("/Calls.json") and sent["To"] == "+573001234567" and sent["From"] == CALLER
    assert sent["Url"] == f"{BASE}/api/twilio/voice/{cid}"
    assert {v for k, v in data if k == "StatusCallbackEvent"} == {"initiated", "ringing", "answered", "completed"}
    sid = twilio_service.get_call(cid)["call_sid"]
    assert client.post("/api/calls", json={"to": "+573105550000"}, headers=_auth(p)).status_code == 400  # una a la vez

    # Firma inválida o CallSid ajeno: rechazados
    assert _webhook(client, f"/api/twilio/voice/{cid}", {"CallSid": sid}, sign=False).status_code == 403
    foreign = _webhook(client, f"/api/twilio/voice/{cid}", {"CallSid": "CAother"})
    assert "<Gather" not in foreign.text

    voice = _webhook(client, f"/api/twilio/voice/{cid}", {"CallSid": sid})
    assert voice.status_code == 200 and "<Gather" in voice.text and "Carlos" in voice.text
    retry = _webhook(client, f"/api/twilio/connect/{cid}", {"CallSid": sid, "Digits": "9"})
    assert "<Gather" in retry.text and "<Dial" not in retry.text
    connect = _webhook(client, f"/api/twilio/connect/{cid}", {"CallSid": sid, "Digits": "1"})
    body = connect.text
    assert f'callerId="{CALLER}"' in body and 'record="record-from-answer-dual"' in body
    assert "+573105556677</Number>" in body and "+573001234567" not in body  # el contacto no ve tu número
    assert f"{BASE}/api/twilio/recording/{cid}" in body and f"{BASE}/api/twilio/notice/{cid}" in body
    notice = _webhook(client, f"/api/twilio/notice/{cid}", {"CallSid": "CAchild", "ParentCallSid": sid})
    assert "grabada" in notice.text

    _webhook(client, f"/api/twilio/status/{cid}?leg=contact",
             {"CallSid": "CAchild", "ParentCallSid": sid, "CallStatus": "in-progress"})
    assert client.get(f"/api/calls/{cid}", headers=_auth(p)).json()["status"] == "in_call"

    note = client.post(f"/api/calls/{cid}/notes", json={"text": "Enviar cotización el viernes", "tag": "tarea"},
                       headers=_auth(p))
    assert note.status_code == 200
    stranger = _user(client)
    assert client.post(f"/api/calls/{cid}/notes", json={"text": "x"}, headers=_auth(stranger)).status_code == 404

    _webhook(client, f"/api/twilio/status/{cid}?leg=owner", {"CallSid": sid, "CallStatus": "completed", "CallDuration": "75"})
    assert twilio_service.get_call(cid)["status"] == "awaiting_recording"

    processed = []
    monkeypatch.setattr(twilio_service, "process_recording", lambda call_id: processed.append(call_id))
    rec_params = {"CallSid": sid, "RecordingSid": "RE123", "RecordingStatus": "completed",
                  "RecordingUrl": "https://api.twilio.com/2010-04-01/Accounts/AC/Recordings/RE123",
                  "RecordingChannels": "2", "RecordingDuration": "70",
                  "RecordingStartTime": "Mon, 02 Nov 2026 14:00:00 +0000"}
    assert _webhook(client, f"/api/twilio/recording/{cid}", rec_params).json()["status"] == "accepted"
    assert _webhook(client, f"/api/twilio/recording/{cid}", rec_params).json()["status"] == "ignored"  # sin duplicar
    time.sleep(0.2)
    assert processed == [cid]
    assert client.post(f"/api/calls/{cid}/notes", json={"text": "tarde"}, headers=_auth(p)).status_code == 409
    listed = client.get("/api/calls", headers=_auth(p)).json()["calls"]
    assert listed[0]["call_id"] == cid and listed[0]["notes"][0]["tag"] == "tarea"


def test_dial_done_contact_busy(twilio) -> None:
    client = TestClient(app)
    p = _verified(client)
    cid = client.post("/api/calls", json={"to": "+573105551111"}, headers=_auth(p)).json()["call_id"]
    sid = twilio_service.get_call(cid)["call_sid"]
    done = _webhook(client, f"/api/twilio/dial-done/{cid}", {"CallSid": sid, "DialCallStatus": "busy"})
    assert "<Hangup/>" in done.text
    assert twilio_service.get_call(cid)["status"] == "contact_busy"


def _stereo_mp3(path) -> None:
    """Canal 1 (usuario) habla de 0 a 2 s; canal 2 (contacto) de 2 a 4 s."""
    expr = "if(lt(t,2),0.6*sin(2*PI*440*t),0)|if(lt(t,2),0,0.6*sin(2*PI*660*t))"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=8000:d=4",
                    "-c:a", "libmp3lame", "-b:a", "32k", str(path)], check=True)


def _seg(i: int, start: float, end: float, speaker: str = "Hablante 1", text: str = "hola") -> DiarizedSegment:
    return DiarizedSegment(id=i, start=start, end=end, speaker=speaker, text=text,
                           start_formatted="00:00:00",
                           end_formatted="00:00:00", source_file="b.mp3", file_order_index=0)


def test_speakers_from_dual_channel_energy(tmp_path) -> None:
    src = tmp_path / "call.mp3"
    _stereo_mp3(src)
    energy = twilio_service.channel_energy(src)
    assert energy is not None and energy.shape[1] == 2
    out = twilio_service.label_by_channel([_seg(0, 0.2, 1.8), _seg(1, 2.3, 3.8)], energy, "Ana", "Carlos")
    assert [s.speaker for s in out] == ["Ana", "Carlos"]


def test_process_recording_builds_meeting_with_notes(twilio, monkeypatch, tmp_path) -> None:
    from app.services.apex_box import apex_box_manager

    client = TestClient(app)
    p = _verified(client)
    cid = client.post("/api/calls", json={"to": "+573105552222", "contact_name": "Carlos"}, headers=_auth(p)).json()["call_id"]
    start = dt.datetime(2026, 11, 2, 14, 0, tzinfo=dt.timezone.utc)
    twilio_service._update(cid, status="processing", recording_sid="RE9", recording_channels=2,
                           recording_url="https://api.twilio.com/x/Recordings/RE9",
                           recording_start=start.strftime("%a, %d %b %Y %H:%M:%S +0000"),
                           notes=[{"note_id": "n1", "text": "Enviar propuesta", "tag": "tarea",
                                   "at": (start + dt.timedelta(seconds=3)).isoformat()}])

    def fake_download(rec, dst):
        _stereo_mp3(dst)
        return 2

    def fake_ingest(box_session_id, filename, content, block_index=None, duration_hint_sec=None, **kw):
        s = apex_box_manager.get_session(box_session_id)
        with apex_box_manager._lock:
            s.segments = [
                DiarizedSegment(id=0, start=0.2, end=1.8, speaker="Hablante 1", text="Hola Carlos, te llamo por la propuesta.",
                                start_formatted="00:00:00", end_formatted="00:00:01", source_file=filename, file_order_index=0),
                DiarizedSegment(id=1, start=2.2, end=3.8, speaker="Hablante 1", text="Perfecto, la espero el viernes.",
                                start_formatted="00:00:02", end_formatted="00:00:03", source_file=filename, file_order_index=0),
            ]
            s.total_duration_sec = 4.0

    monkeypatch.setattr(twilio_service, "_download_recording", fake_download)
    monkeypatch.setattr(apex_box_manager, "ingest_block", fake_ingest)
    job_id = twilio_service.process_recording(cid)
    assert job_id, twilio_service.get_call(cid).get("error")
    rec = twilio_service.get_call(cid)
    assert rec["status"] == "done" and rec["job_id"] == job_id
    assert ("DELETE", f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Recordings/RE9.json", []) in twilio

    from app.services.job_manager import job_manager
    result = job_manager.get_job_result(job_id)
    assert [s.speaker for s in result.segments] == ["Ana", "Carlos"]
    assert result.live_notes and result.live_notes[0]["timestamp_formatted"] == "00:00:03"
    meta = next(r for r in supabase_service.list_user_transcriptions(p["user_id"]) if r["job_id"] == job_id)
    assert meta["source"] == "phone_call" and meta["contact_name"] == "Carlos" and meta["contact_number"] == "+573105552222"
