"""A job that fails gives back what it used, exactly once and on the right day."""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import groq_service, job_manager as job_module
from app.services.job_manager import QuotaCharge, job_manager
from app.services.supabase_service import supabase_service
from tests.fixtures.audio_generator import create_synthetic_wav

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def wav(tmp_path: Path) -> bytes:
    path = tmp_path / "a.wav"
    create_synthetic_wav(path, [(3.0, 440.0)])
    return path.read_bytes()


def _account() -> tuple[str, dict]:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    return profile.user_id, {"Authorization": f"Bearer {profile.access_token}"}


def _used(uid: str) -> float:
    return supabase_service.get_user_quota(uid).used_today_seconds


def _boom(*args, **kwargs):
    raise RuntimeError("provider down")


def _upload(wav: bytes, headers: dict) -> str:
    res = client.post("/api/upload", files=[("files", ("a.wav", wav, "audio/wav"))], headers=headers)
    assert res.status_code == 200
    return res.json()["session_id"]


def test_failed_job_gives_back_the_quota(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    uid, auth = _account()
    session_id = _upload(wav, auth)
    monkeypatch.setattr(job_module, "transcribe_chunks_sequence", _boom)
    res = client.post("/api/transcribe?sync=true", json={"session_id": session_id, "diarization_engine": "Mc-Norris"}, headers=auth)
    assert res.status_code == 500
    assert _used(uid) == 0


def test_successful_job_keeps_the_charge(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    uid, auth = _account()
    session_id = _upload(wav, auth)
    monkeypatch.setattr(job_module, "transcribe_chunks_sequence", lambda **kw: [])
    res = client.post("/api/transcribe?sync=true", json={"session_id": session_id, "diarization_engine": "Mc-Norris"}, headers=auth)
    assert res.status_code == 200
    assert _used(uid) == pytest.approx(3.0, abs=0.2)
    assert job_manager._charges.get(res.json()["job_id"]) is None


def test_quota_rejection_refunds_nothing(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    uid, auth = _account()
    supabase_service.check_and_consume_quota(uid, 5.0)
    session_id = _upload(wav, auth)
    monkeypatch.setattr(settings, "FREE_DAILY_SECONDS", 6)
    res = client.post("/api/transcribe?sync=true", json={"session_id": session_id}, headers=auth)
    assert res.status_code == 402
    assert _used(uid) == pytest.approx(5.0)


def test_settling_twice_refunds_once() -> None:
    uid, _ = _account()
    supabase_service.check_and_consume_quota(uid, 10.0)
    supabase_service.check_and_consume_quota(uid, 10.0)
    day = supabase_service.usage_day()
    job_manager.record_charge("job_once", QuotaCharge(owner=uid, day=day, audios=1, seconds=10.0))
    job_manager._settle_charge("job_once", refund=True)
    job_manager._settle_charge("job_once", refund=True)
    assert _used(uid) == pytest.approx(10.0)


def test_refund_goes_to_the_day_it_was_charged() -> None:
    uid, _ = _account()
    db = supabase_service._load_db()
    db["daily_usage"][f"{uid}:2020-01-01"] = {"used_seconds": 60.0, "audios_count": 2}
    supabase_service._save_db(db)
    supabase_service.check_and_consume_quota(uid, 30.0)

    supabase_service.refund_quota(uid, 60.0, "2020-01-01", audios=2)

    entry = supabase_service._load_db()["daily_usage"][f"{uid}:2020-01-01"]
    assert entry["used_seconds"] == 0 and entry["audios_count"] == 0
    assert _used(uid) == pytest.approx(30.0)


def test_refund_never_goes_below_zero_or_creates_a_day() -> None:
    uid, _ = _account()
    supabase_service.check_and_consume_quota(uid, 5.0)
    supabase_service.refund_quota(uid, 500.0, supabase_service.usage_day(), audios=9)
    assert _used(uid) == 0
    supabase_service.refund_quota(uid, 5.0, "2020-01-01")
    assert f"{uid}:2020-01-01" not in supabase_service._load_db()["daily_usage"]


def test_failed_guest_job_gives_back_audios_and_leaves_no_file(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    headers = {"X-Forwarded-For": f"10.{uuid.uuid4().int % 250}.1.1"}
    session_id = _upload(wav, headers)
    session_dir = job_manager.get_session(session_id).session_dir
    guest = job_manager.get_session(session_id).owner
    monkeypatch.setattr(job_module, "transcribe_chunks_sequence", _boom)
    res = client.post("/api/transcribe?sync=true", json={"session_id": session_id, "diarization_engine": "Mc-Norris"}, headers=headers)
    assert res.status_code == 500
    assert supabase_service.guest_audios_used_today(guest) == 0
    assert not session_dir.exists()
    assert job_manager.get_session(session_id) is None


def test_create_job_failure_gives_back_guest_audios(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    headers = {"X-Forwarded-For": f"10.{uuid.uuid4().int % 250}.2.2"}
    session_id = _upload(wav, headers)
    guest = job_manager.get_session(session_id).owner
    monkeypatch.setattr(job_manager, "create_job", _boom)
    res = client.post("/api/transcribe", json={"session_id": session_id}, headers=headers)
    assert res.status_code == 400
    assert supabase_service.guest_audios_used_today(guest) == 0


def test_box_block_without_real_transcript_is_not_charged(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    uid, auth = _account()
    monkeypatch.setattr(groq_service, "transcribe_chunk", _boom)
    box = client.post("/api/box/sessions", json={"title": "x"}, headers=auth).json()["box_session_id"]
    res = client.post(f"/api/box/sessions/{box}/blocks", files={"file": ("b.wav", wav, "audio/wav")}, headers=auth)
    assert res.status_code == 200
    assert res.json()["block"]["placeholder"] is True
    assert res.json()["block"]["transcribed"] is True  # the stand-in text still reaches the client
    assert _used(uid) == 0


def test_box_block_with_transcript_is_charged(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    uid, auth = _account()
    monkeypatch.setattr(groq_service, "transcribe_chunk", lambda **kw: [{"start": 0, "end": 1, "text": "Hola."}])
    box = client.post("/api/box/sessions", json={"title": "x"}, headers=auth).json()["box_session_id"]
    res = client.post(f"/api/box/sessions/{box}/blocks", files={"file": ("b.wav", wav, "audio/wav")}, headers=auth)
    assert res.json()["block"]["placeholder"] is False
    assert _used(uid) == pytest.approx(3.0, abs=0.2)
