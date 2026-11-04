"""Apex Box charges what was measured, survives retries and cannot be reopened."""

import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import apex_box, groq_service
from app.services.apex_box import BoxConflictError, apex_box_manager
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service
from tests.fixtures.audio_generator import create_synthetic_wav

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_real_transcription(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        groq_service, "transcribe_chunk", lambda **kw: [{"start": 0.1, "end": 0.9, "text": "Hola equipo."}]
    )


@pytest.fixture
def wav(tmp_path: Path) -> bytes:
    path = tmp_path / "b.wav"
    create_synthetic_wav(path, [(3.0, 440.0)])
    return path.read_bytes()


def _account(pro: bool = False) -> tuple[str, dict]:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    if pro:
        db = supabase_service._load_db()
        db["users"][profile.user_id].update(plan="pro", pro_until="2099-01-01T00:00:00+00:00")
        supabase_service._save_db(db)
    return profile.user_id, {"Authorization": f"Bearer {profile.access_token}"}


def _session(auth: dict) -> str:
    return client.post("/api/box/sessions", json={"title": "Reunión"}, headers=auth).json()["box_session_id"]


def _block(box: str, auth: dict, wav: bytes, index: int = 0, **data):
    return client.post(
        f"/api/box/sessions/{box}/blocks",
        files={"file": (f"{index}.wav", wav, "audio/wav")},
        data={"block_index": str(index), **data},
        headers=auth,
    )


def _used(uid: str) -> float:
    return supabase_service.get_user_quota(uid).used_today_seconds


# Quota --------------------------------------------------------------------


def test_large_hint_charges_the_measured_duration(wav: bytes) -> None:
    uid, auth = _account()
    box = _session(auth)
    res = _block(box, auth, wav, duration_hint_sec="180")
    assert res.status_code == 200
    assert _used(uid) == pytest.approx(3.0, abs=0.2)
    assert res.json()["total_duration_sec"] == pytest.approx(3.0, abs=0.2)


def test_omitting_the_hint_no_longer_records_for_free(wav: bytes) -> None:
    uid, auth = _account()
    assert _block(_session(auth), auth, wav).status_code == 200
    assert _used(uid) == pytest.approx(3.0, abs=0.2)


def test_low_hint_cannot_shorten_the_charge_or_the_timeline(wav: bytes) -> None:
    uid, auth = _account()
    res = _block(_session(auth), auth, wav, duration_hint_sec="0.1")
    assert _used(uid) == pytest.approx(3.0, abs=0.2)
    assert res.json()["block"]["duration_sec"] == pytest.approx(3.0, abs=0.2)


def test_real_audio_over_quota_is_refused_and_removed(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    uid, auth = _account()
    box = _session(auth)
    monkeypatch.setattr(settings, "FREE_DAILY_SECONDS", 1)
    res = _block(box, auth, wav, duration_hint_sec="0.1")
    assert res.status_code == 402
    assert "Apex Pro" in res.json()["detail"]
    upload_id = apex_box_manager.get_session(box).upload_session_id
    assert job_manager.get_session_files(upload_id) == []
    assert _used(uid) == 0
    # A rejected block can be sent again once there is room: it left nothing behind.
    assert apex_box_manager.get_session(box).block_responses == {}


def test_hint_over_quota_is_refused_without_charging(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    uid, auth = _account()
    box = _session(auth)
    res = _block(box, auth, b"garbage", duration_hint_sec=str(3 * 3600))
    assert res.status_code == 402
    assert _used(uid) == 0


def test_retried_block_is_not_charged_twice_and_returns_the_same_answer(wav: bytes) -> None:
    uid, auth = _account()
    box = _session(auth)
    first = _block(box, auth, wav)
    used = _used(uid)
    again = _block(box, auth, wav)
    assert again.status_code == 200
    assert again.json() == first.json()
    assert _used(uid) == used
    state = client.get(f"/api/box/sessions/{box}", headers=auth).json()
    assert state["total_duration_sec"] == pytest.approx(3.0, abs=0.2)


def test_block_in_progress_answers_409(wav: bytes) -> None:
    _, auth = _account()
    box = _session(auth)
    apex_box_manager.get_session(box).blocks_in_progress.add(0)
    try:
        assert _block(box, auth, wav).status_code == 409
    finally:
        apex_box_manager.get_session(box).blocks_in_progress.discard(0)


def test_server_recordings_are_not_charged(wav: bytes) -> None:
    uid, auth = _account(pro=False)
    box = _session(auth)
    apex_box_manager.ingest_block(box, "call.wav", wav, block_index=0)  # Recall and Twilio call it like this
    assert _used(uid) == 0


def test_client_api_key_is_ignored(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return [{"start": 0.1, "end": 0.9, "text": "Hola."}]

    monkeypatch.setattr(groq_service, "transcribe_chunk", spy)
    _, auth = _account()
    assert _block(_session(auth), auth, wav, api_key="client-key").status_code == 200
    assert seen["api_key"] != "client-key"


# Lifecycle ----------------------------------------------------------------


def test_finalize_twice_returns_the_same_job(wav: bytes) -> None:
    _, auth = _account(pro=True)
    box = _session(auth)
    _block(box, auth, wav)
    first = client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth)
    second = client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth)
    assert first.status_code == second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]


def test_finalize_in_progress_answers_409(wav: bytes) -> None:
    _, auth = _account()
    box = _session(auth)
    session = apex_box_manager.get_session(box)
    session.status = "finalizing"
    assert client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth).status_code == 409


def test_failed_finalize_can_be_retried(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    _, auth = _account(pro=True)
    box = _session(auth)
    _block(box, auth, wav)
    real = apex_box_manager._finalize

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(apex_box_manager, "_finalize", boom)
    assert client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth).status_code == 500
    assert apex_box_manager.get_session(box).status == "recording"

    monkeypatch.setattr(apex_box_manager, "_finalize", real)
    assert client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth).status_code == 200


def test_late_block_and_status_change_after_finalize_are_refused(wav: bytes) -> None:
    _, auth = _account(pro=True)
    box = _session(auth)
    _block(box, auth, wav)
    client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth)
    assert _block(box, auth, wav, index=1).status_code == 409
    res = client.patch(f"/api/box/sessions/{box}/status", params={"status": "recording"}, headers=auth)
    assert res.status_code == 409
    assert " / " in res.json()["detail"]
    assert apex_box_manager.get_session(box).status == "completed"


@pytest.mark.parametrize("status", ["completed", "finalizing", "anything"])
def test_client_cannot_set_internal_status(status: str) -> None:
    _, auth = _account()
    box = _session(auth)
    res = client.patch(f"/api/box/sessions/{box}/status", params={"status": status}, headers=auth)
    assert res.status_code == 400
    assert apex_box_manager.get_session(box).status == "recording"


def test_pause_and_resume_still_work() -> None:
    _, auth = _account()
    box = _session(auth)
    assert client.patch(f"/api/box/sessions/{box}/status", params={"status": "paused"}, headers=auth).status_code == 200
    assert apex_box_manager.get_session(box).status == "paused"
    assert client.patch(f"/api/box/sessions/{box}/status", params={"status": "recording"}, headers=auth).status_code == 200


def test_finalize_waits_for_a_block_still_being_transcribed(monkeypatch: pytest.MonkeyPatch) -> None:
    _, auth = _account()
    box = _session(auth)
    session = apex_box_manager.get_session(box)
    session.blocks_in_progress.add(0)
    timer = threading.Timer(0.3, session.blocks_in_progress.discard, args=(0,))
    timer.start()
    apex_box_manager._wait_for_blocks_in_progress(session)
    timer.join()
    assert session.blocks_in_progress == set()

    session.blocks_in_progress.add(1)
    monkeypatch.setattr(apex_box, "_FINALIZE_WAIT_SECONDS", 0.0)
    with pytest.raises(BoxConflictError):
        apex_box_manager._wait_for_blocks_in_progress(session)
    session.blocks_in_progress.clear()


def test_transcript_and_audio_follow_the_timeline(wav: bytes) -> None:
    _, auth = _account(pro=True)
    box = _session(auth)
    _block(box, auth, wav, index=0)
    _block(box, auth, wav, index=1)
    session = apex_box_manager.get_session(box)
    session.segments.reverse()  # blocks finished transcribing out of order
    session.chunks.reverse()
    result = client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth).json()["result"]
    starts = [s["start"] for s in result["segments"]]
    assert starts == sorted(starts)
    assert [s["id"] for s in result["segments"]] == list(range(len(starts)))


# Plan ---------------------------------------------------------------------


def test_free_account_gets_the_preview_and_no_minutes(wav: bytes) -> None:
    _, auth = _account()
    box = _session(auth)
    _block(box, auth, wav)
    client.post(f"/api/box/sessions/{box}/notes", json={"text": "Comprar equipos", "tag": "tarea"}, headers=auth)
    body = client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth).json()
    assert body["minutes"] is None and body["minutes_document"] is None
    report = body["result"]["summa_report"]
    assert report["is_locked"] is True
    assert not any("Comprar equipos" in task["title"] for task in report["calendar_tasks"])
    assert body["result"]["expires_at"]  # free retention


def test_pro_account_keeps_the_full_report_and_minutes(wav: bytes) -> None:
    _, auth = _account(pro=True)
    box = _session(auth)
    _block(box, auth, wav)
    client.post(f"/api/box/sessions/{box}/notes", json={"text": "Comprar equipos", "tag": "tarea"}, headers=auth)
    body = client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth).json()
    assert body["minutes"] is not None
    report = body["result"]["summa_report"]
    assert report["is_locked"] is False
    assert any("Comprar equipos" in task["title"] for task in report["calendar_tasks"])
    assert body["result"]["expires_at"] is None


def test_upgrade_during_a_recording_counts_at_finalize(wav: bytes) -> None:
    uid, auth = _account()
    box = _session(auth)
    _block(box, auth, wav)
    db = supabase_service._load_db()
    db["users"][uid].update(plan="pro", pro_until="2099-01-01T00:00:00+00:00")
    supabase_service._save_db(db)
    body = client.post(f"/api/box/sessions/{box}/finalize", json={}, headers=auth).json()
    assert body["result"]["summa_report"]["is_locked"] is False
    assert body["minutes"] is not None
