"""Retention deletes what the plans promise, only when told to, and never Pro data."""

import datetime as dt
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.api.deps import media_token
from app.config import settings
from app.main import app
from app.models.schemas import JobStatusResponse, TranscriptionResult
from app.services import retention, usage_reporter
from app.services.job_manager import job_manager
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

client = TestClient(app)
PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


def _account(**fields) -> tuple[str, dict]:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    if fields:
        db = supabase_service._load_db()
        db["users"][profile.user_id].update(fields)
        supabase_service._save_db(db)
    return profile.user_id, {"Authorization": f"Bearer {profile.access_token}"}


def _job(owner: Optional[str], expires_at: Optional[str]) -> str:
    """A finished job, as it stays on disk after a restart."""
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    result = TranscriptionResult(
        job_id=job_id, session_id="s", user_id=owner, plan="free", status="completed", detected_speakers_count=1,
        total_duration_sec=60, total_duration_formatted="00:01:00", model_used="m", diarization_engine_used="groq_llm",
        engine_brand="b", file_order=[], segments=[], full_text="confidential", expires_at=expires_at,
    )
    (settings.OUTPUT_DIR / f"{job_id}_result.json").write_text(result.model_dump_json(), encoding="utf-8")
    (settings.OUTPUT_DIR / f"{job_id}_merged.mp3").write_bytes(b"audio")
    if owner:
        supabase_service.save_transcription_record({
            "job_id": job_id, "user_id": owner, "expires_at": expires_at,
            "s4_result_key": f"users/{owner}/jobs/{job_id}/result.json",
            "s4_audio_key": f"users/{owner}/jobs/{job_id}/merged.mp3",
        })
    mega_s4_storage.upload_object(f"users/{owner}/jobs/{job_id}/result.json", b"{}", job_id=job_id, user_id=owner, expires_at=expires_at)
    return job_id


def _files_of(job_id: str) -> list:
    return [p for p in settings.OUTPUT_DIR.iterdir() if p.name.startswith(job_id)]


def _old(path: Path) -> None:
    long_ago = time.time() - (settings.JOB_RETENTION_HOURS + 1) * 3600
    os.utime(path, (long_ago, long_ago))


# What is expired -----------------------------------------------------------


def test_effective_expiry_rules() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    free, _ = _account()
    paying, _ = _account(plan="pro", pro_until=FUTURE)
    lifetime, _ = _account(plan="pro", pro_until=None)
    lapsed_at = (now - dt.timedelta(days=30)).isoformat()
    lapsed, _ = _account(plan="free", pro_until=lapsed_at)
    just_lapsed_at = (now - dt.timedelta(days=1)).isoformat()
    just_lapsed, _ = _account(plan="free", pro_until=just_lapsed_at)

    expiry = supabase_service.effective_expiry
    assert expiry(PAST, free) < now
    assert expiry(None, free) is None  # unknown: kept
    assert expiry("not a date", free) is None  # unreadable: kept
    assert expiry(PAST, paying) is None  # paying keeps even what expired on Free
    assert expiry(PAST, lifetime) is None
    assert expiry(None, lapsed) < now  # Pro files: grace and Free retention are over
    assert expiry(None, just_lapsed) > now  # still within the grace period
    assert expiry(PAST, just_lapsed) > now  # the grace period also protects older files
    assert expiry(PAST, "no-such-account") < now
    assert expiry(None, None) is None


# Serving -------------------------------------------------------------------


def test_expired_result_is_not_served_even_in_a_dry_run() -> None:
    uid, auth = _account()
    job_id = _job(uid, PAST)
    assert job_manager.get_job_result(job_id) is None
    for path in ("result", "audio", "export/txt", "calendar.ics", "summa"):
        res = client.get(f"/api/jobs/{job_id}/{path}", headers=auth)
        assert res.status_code == 410, path
        assert "confidential" not in res.text
        assert " / " in res.json()["detail"]
    assert client.post(f"/api/jobs/{job_id}/minutes", json={"template_type": "ejecutiva"}, headers=auth).status_code == 410


def test_download_links_stop_working_when_the_result_expires() -> None:
    job_id = _job("no-such-account", PAST)
    token = media_token(f"job:{job_id}")
    for path in ("audio", "export/txt", "calendar.ics"):
        assert client.get(f"/api/jobs/{job_id}/{path}", params={"t": token}).status_code == 410, path


def test_valid_result_is_still_served() -> None:
    uid, auth = _account()
    job_id = _job(uid, FUTURE)
    assert client.get(f"/api/jobs/{job_id}/result", headers=auth).status_code == 200
    assert client.get(f"/api/jobs/{job_id}/audio", headers=auth).status_code == 200


def test_another_account_gets_404_not_410() -> None:
    uid, _ = _account()
    _, other = _account()
    assert client.get(f"/api/jobs/{_job(uid, PAST)}/result", headers=other).status_code == 404


def test_expired_result_never_answers_202_forever() -> None:
    uid, auth = _account()
    job_id = _job(uid, PAST)
    job_manager.register_job(
        JobStatusResponse(job_id=job_id, session_id="s", status="completed", progress=100, current_step="x"), None, uid
    )
    assert client.get(f"/api/jobs/{job_id}/result", headers=auth).status_code == 410


def test_history_hides_expired_and_shows_what_paying_recovers() -> None:
    uid, _ = _account()
    job_id = _job(uid, PAST)
    assert all(r["job_id"] != job_id for r in supabase_service.list_user_transcriptions(uid))
    db = supabase_service._load_db()
    db["users"][uid].update(plan="pro", pro_until=FUTURE)
    supabase_service._save_db(db)
    assert any(r["job_id"] == job_id for r in supabase_service.list_user_transcriptions(uid))
    assert job_manager.get_job_result(job_id) is not None


# Sweeping ------------------------------------------------------------------


def test_dry_run_is_the_default_and_deletes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings.RETENTION_DRY_RUN is True
    uid, _ = _account()
    job_id = _job(uid, PAST)
    before = {p.name for p in _files_of(job_id)}
    report = retention.sweep()
    assert report["dry_run"] is True
    assert job_id in report["jobs"]
    assert {p.name for p in _files_of(job_id)} == before
    assert job_id in supabase_service._load_db()["transcriptions"]
    assert mega_s4_storage.get_object_metadata(f"users/{uid}/jobs/{job_id}/result.json")


def test_real_sweep_deletes_an_expired_job_everywhere() -> None:
    uid, _ = _account()
    job_id = _job(uid, PAST)
    report = retention.sweep(dry_run=False)
    assert job_id in report["jobs"] and report["failed"] == []
    assert _files_of(job_id) == []
    assert job_id not in supabase_service._load_db()["transcriptions"]
    assert mega_s4_storage.get_object_metadata(f"users/{uid}/jobs/{job_id}/result.json") is None


def test_pro_data_is_never_deleted() -> None:
    uid, _ = _account(plan="pro", pro_until=FUTURE)
    no_expiry, stale_expiry = _job(uid, None), _job(uid, PAST)
    report = retention.sweep(dry_run=False)
    assert no_expiry not in report["jobs"] and stale_expiry not in report["jobs"]
    assert _files_of(no_expiry) and _files_of(stale_expiry)


def test_lapse_then_renewal_keeps_the_data() -> None:
    lapsed_at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    uid, _ = _account(plan="free", pro_until=lapsed_at)
    job_id = _job(uid, None)
    assert job_id in retention.sweep(dry_run=True)["jobs"]
    db = supabase_service._load_db()
    db["users"][uid].update(plan="pro", pro_until=FUTURE)
    supabase_service._save_db(db)
    assert job_id not in retention.sweep(dry_run=False)["jobs"]
    assert _files_of(job_id)


def test_running_job_is_left_alone() -> None:
    uid, _ = _account()
    job_id = _job(uid, PAST)
    job_manager.register_job(
        JobStatusResponse(job_id=job_id, session_id="s", status="processing", progress=5, current_step="x"), None, uid
    )
    assert job_id not in retention.sweep(dry_run=False)["jobs"]
    job_manager.forget_job(job_id)


def test_failed_bucket_delete_keeps_the_record_for_the_next_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    uid, _ = _account()
    job_id = _job(uid, PAST)
    monkeypatch.setattr(mega_s4_storage, "delete_object", lambda key: False)
    report = retention.sweep(dry_run=False)
    assert job_id in report["failed"]
    assert job_id in supabase_service._load_db()["transcriptions"]
    monkeypatch.undo()
    assert job_id in retention.sweep(dry_run=False)["jobs"]
    assert job_id not in supabase_service._load_db()["transcriptions"]


def test_old_uploads_are_deleted_but_active_ones_stay() -> None:
    old = settings.UPLOAD_DIR / f"old{uuid.uuid4().hex[:8]}"
    old.mkdir()
    (old / "a.wav").write_bytes(b"x")
    _old(old / "a.wav")
    recent = settings.UPLOAD_DIR / f"new{uuid.uuid4().hex[:8]}"
    recent.mkdir()
    (recent / "a.wav").write_bytes(b"x")
    busy = job_manager.create_or_get_session(owner="o")
    (busy.session_dir / "a.wav").write_bytes(b"x")
    _old(busy.session_dir / "a.wav")
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    job_manager.register_job(
        JobStatusResponse(job_id=job_id, session_id=busy.session_id, status="processing", progress=5, current_step="x"), None, "o"
    )

    assert old.name in retention.sweep(dry_run=True)["uploads"]
    assert old.exists()
    retention.sweep(dry_run=False)
    assert not old.exists()
    assert recent.exists()
    assert busy.session_dir.exists()
    job_manager.forget_job(job_id)


def test_open_box_recording_keeps_its_blocks() -> None:
    from app.models.schemas import BoxCreateSessionRequest
    from app.services.apex_box import apex_box_manager

    box = apex_box_manager.create_session(BoxCreateSessionRequest(title="t", user_id="u"))
    folder = settings.UPLOAD_DIR / box.upload_session_id
    (folder / "b.webm").write_bytes(b"x")
    _old(folder / "b.webm")
    assert box.upload_session_id not in retention.sweep(dry_run=True)["uploads"]


def test_restart_orphans_are_gated_and_then_deleted() -> None:
    orphan = settings.OUTPUT_DIR / f"job_{uuid.uuid4().hex[:16]}_merged.mp3"
    orphan.write_bytes(b"guest audio")
    _old(orphan)
    assert orphan.name in retention.sweep(dry_run=True)["leftovers"]
    assert orphan.exists()
    retention.sweep(dry_run=False)
    assert not orphan.exists()


def test_guest_audio_is_kept_while_its_result_is_alive() -> None:
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    merged = settings.OUTPUT_DIR / f"{job_id}_merged.mp3"
    merged.write_bytes(b"x")
    _old(merged)
    job_manager._results[job_id] = TranscriptionResult(
        job_id=job_id, session_id="s", plan="guest", status="completed", detected_speakers_count=0,
        total_duration_sec=1, total_duration_formatted="00:00:01", model_used="m", diarization_engine_used="e",
        engine_brand="b", file_order=[], segments=[], full_text="x",
    )
    retention.sweep(dry_run=False)
    assert merged.exists()
    job_manager.forget_job(job_id)


# Usage metrics -------------------------------------------------------------


def test_usage_totals_survive_the_deletion() -> None:
    uid, _ = _account()
    job_id = _job(uid, PAST)
    before = usage_reporter.compute_usage_report()["cumulative"]["jobs_count"]
    retention.sweep(dry_run=False)
    after = usage_reporter.compute_usage_report()
    assert after["cumulative"]["jobs_count"] == before
    ledger = (settings.OUTPUT_DIR / "reports" / "usage_ledger.jsonl").read_text(encoding="utf-8")
    assert job_id in ledger
    assert uid not in ledger and "confidential" not in ledger
    assert all("user" not in key for key in json.loads(ledger.splitlines()[-1]))


def test_a_job_is_not_counted_twice() -> None:
    uid, _ = _account()
    job_id = _job(uid, FUTURE)
    result_file = settings.OUTPUT_DIR / f"{job_id}_result.json"
    usage_reporter.record_in_ledger(result_file, json.loads(result_file.read_text(encoding="utf-8")))
    jobs = usage_reporter.compute_usage_report()["daily_jobs"]
    assert [j["job_id"] for j in jobs].count(job_id) == 1


# Promises ------------------------------------------------------------------


def test_guest_policy_text_matches_what_happens() -> None:
    for lang, phrase in (("es", "una copia del audio"), ("en", "a copy of the audio")):
        assert phrase in client.get(f"/legal/privacidad?lang={lang}").text
