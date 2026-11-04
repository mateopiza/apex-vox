"""Paths, provider text and keys belong in the logs, never in what a client can read."""

import io
import json
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.errors import GENERIC_ERROR, UserFacingError, detail_of, public_error
from app.main import app
from app.services import bold_service, job_manager as job_module, recall_service, twilio_service
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service
from tests.fixtures.audio_generator import create_synthetic_wav

client = TestClient(app, raise_server_exceptions=False)
SECRET_TEXT = "/app/outputs/job_x_merged.mp3 failed with key gsk_real_secret"


def _auth() -> dict:
    token = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123").access_token
    return {"Authorization": f"Bearer {token}"}


def _boom(*args, **kwargs):
    raise RuntimeError(SECRET_TEXT)


@pytest.fixture
def wav(tmp_path: Path) -> bytes:
    path = tmp_path / "a.wav"
    create_synthetic_wav(path, [(1.0, 440.0)])
    return path.read_bytes()


def test_public_error_only_passes_messages_written_for_users() -> None:
    assert public_error(RuntimeError(SECRET_TEXT)) == GENERIC_ERROR
    assert public_error(ValueError(SECRET_TEXT)) == GENERIC_ERROR
    assert public_error(UserFacingError("Texto para el usuario")) == "Texto para el usuario"
    assert public_error(PermissionError("Límite del plan")) == "Límite del plan"
    assert " / " in GENERIC_ERROR


def test_detail_of_has_no_stray_quotes() -> None:
    assert detail_of(KeyError("Sesión no encontrada.")) == "Sesión no encontrada."
    assert str(KeyError("x")) == "'x'"  # what the routes used to show


def test_failed_job_status_shows_no_internals(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    auth = _auth()
    session_id = client.post("/api/upload", files=[("files", ("a.wav", wav, "audio/wav"))], headers=auth).json()["session_id"]
    monkeypatch.setattr(job_module, "transcribe_chunks_sequence", _boom)

    res = client.post("/api/transcribe?sync=true", json={"session_id": session_id, "diarization_engine": "Mc-Norris"}, headers=auth)
    assert res.status_code == 500
    assert "gsk_real_secret" not in res.text and "/app/outputs" not in res.text

    failed = [job for job in job_manager._jobs.values() if job.session_id == session_id][0]
    status = client.get(f"/api/jobs/{failed.job_id}/status", headers=auth)
    result = client.get(f"/api/jobs/{failed.job_id}/result", headers=auth)
    for body in (status.text, result.text):
        assert "gsk_real_secret" not in body and "/app/outputs" not in body
    assert status.json()["status"] == "failed"
    assert status.json()["error"] == GENERIC_ERROR


def test_quota_message_still_reaches_the_user(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    auth = _auth()
    session_id = client.post("/api/upload", files=[("files", ("a.wav", wav, "audio/wav"))], headers=auth).json()["session_id"]
    monkeypatch.setattr("app.config.settings.FREE_DAILY_SECONDS", 0)
    res = client.post("/api/transcribe?sync=true", json={"session_id": session_id}, headers=auth)
    assert res.status_code == 402
    assert "Apex Pro" in res.json()["detail"]


def test_invalid_audio_message_has_no_paths_or_tool_output() -> None:
    res = client.post("/api/upload", files=[("files", ("a.wav", io.BytesIO(b"not audio"), "audio/wav"))], headers=_auth())
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "a.wav" in detail and " / " in detail
    assert "ffprobe" not in detail and "/" not in detail.replace(" / ", "").replace("uploads", "")


def test_missing_session_message_has_no_stray_quotes() -> None:
    auth = _auth()
    box = client.post("/api/box/sessions", json={"title": "x"}, headers=auth).json()["box_session_id"]
    res = client.put(f"/api/box/sessions/{box}/notes/none", json={"text": "x"}, headers=auth)
    assert res.status_code == 404
    assert not res.json()["detail"].startswith("'")


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(SECRET_TEXT)


def _no_network(monkeypatch: pytest.MonkeyPatch, module) -> None:
    real = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(_refuse), **kw))


def test_provider_connection_errors_hide_details(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(twilio_service, "is_configured", lambda: True)
    monkeypatch.setattr(twilio_service, "_auth", lambda: ("a", "b"))
    _no_network(monkeypatch, twilio_service)
    with pytest.raises(twilio_service.TwilioError) as twilio_error:
        twilio_service._request("GET", "https://api.twilio.com/x")
    assert "gsk_real_secret" not in str(twilio_error.value)

    with pytest.raises(recall_service.RecallError) as recall_error:
        recall_service._request("GET", "/bot/abc/")
    assert "gsk_real_secret" not in str(recall_error.value)

    monkeypatch.setattr(bold_service.settings, "BOLD_API_KEY", "k")
    with pytest.raises(bold_service.BoldAPIError) as bold_error:
        bold_service._bold_request("GET", "/x")
    assert "gsk_real_secret" not in str(bold_error.value)


def test_twilio_response_text_stays_out_of_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(twilio_service, "is_configured", lambda: True)
    monkeypatch.setattr(twilio_service, "_auth", lambda: ("a", "b"))
    real = httpx.Client
    reply = httpx.MockTransport(lambda request: httpx.Response(400, json={"message": SECRET_TEXT}))
    monkeypatch.setattr(twilio_service.httpx, "Client", lambda **kw: real(transport=reply, **kw))
    with pytest.raises(twilio_service.TwilioError) as error:
        twilio_service._request("GET", "https://api.twilio.com/x")
    assert "gsk_real_secret" not in str(error.value)
    assert "400" in str(error.value)


def test_failed_bot_stores_a_public_message(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    bot_id = f"bot-{uuid.uuid4().hex}"
    db = supabase_service._load_db()
    db.setdefault("meeting_bots", {})[bot_id] = {"bot_id": bot_id, "user_id": profile.user_id, "status": "processing"}
    supabase_service._save_db(db)
    monkeypatch.setattr(recall_service, "_request", _boom)
    recall_service.process_finished_bot(bot_id)
    stored = json.dumps(supabase_service._load_db()["meeting_bots"][bot_id])
    assert "gsk_real_secret" not in stored
