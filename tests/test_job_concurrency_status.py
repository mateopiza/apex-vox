"""Jobs are limited, survive restarts honestly, and do not pile up in memory."""

import json
import threading
import time
import uuid
from pathlib import Path

import pytest

from app.api import deps
from app.config import settings
from app.models.schemas import JobStatusResponse, TranscribeRequest, TranscriptionResult
from app.services import job_manager as job_module, recall_service, twilio_service
from app.services.apex_box import apex_box_manager
from app.services.job_manager import JobManager, QuotaCharge, job_manager
from app.services.supabase_service import supabase_service
from tests.fixtures.audio_generator import create_synthetic_wav


@pytest.fixture
def fresh(monkeypatch: pytest.MonkeyPatch) -> JobManager:
    """A manager with empty memory, like the process after a restart."""
    return JobManager()


def _status(job_id: str, status: str) -> JobStatusResponse:
    return JobStatusResponse(job_id=job_id, session_id="s", status=status, progress=10, current_step="x")


def _job_id() -> str:
    return f"job_{uuid.uuid4().hex[:16]}"


def _session_with_audio(tmp_path: Path, owner: str = "owner") -> str:
    wav = tmp_path / "a.wav"
    create_synthetic_wav(wav, [(1.0, 440.0)])
    session = job_manager.create_or_get_session(owner=owner)
    job_manager.add_file_to_session(session.session_id, "a.wav", wav.read_bytes(), owner=owner)
    return session.session_id


# Concurrency ---------------------------------------------------------------


def test_only_job_concurrency_jobs_run_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_module, "_pipeline_slots", threading.BoundedSemaphore(2))
    running, peak, lock = [0], [0], threading.Lock()

    def work(job_id, req):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1

    monkeypatch.setattr(job_manager, "_run_job", work)
    threads = [threading.Thread(target=job_manager.execute_job, args=(f"j{i}", None)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak[0] == 2


def test_job_stays_queued_while_waiting_for_a_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session_id = _session_with_audio(tmp_path)
    req = TranscribeRequest(session_id=session_id)
    status = job_manager.create_job(req)
    monkeypatch.setattr(job_module, "_pipeline_slots", threading.BoundedSemaphore(1))
    job_module._pipeline_slots.acquire()
    runner = threading.Thread(target=lambda: _ignore(job_manager.execute_job, status.job_id, req))
    runner.start()
    time.sleep(0.1)
    assert job_manager.get_job_status(status.job_id).status == "queued"
    job_module._pipeline_slots.release()
    runner.join(30)


def _ignore(func, *args):
    try:
        func(*args)
    except Exception:
        pass


def test_timeout_fails_the_job_and_gives_back_quota(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    uid = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123").user_id
    session_id = _session_with_audio(tmp_path, owner=uid)
    req = TranscribeRequest(session_id=session_id, user_id=uid, diarization_engine="Mc-Norris")
    status = job_manager.create_job(req)
    monkeypatch.setattr(settings, "JOB_TIMEOUT_SECONDS", -1)
    monkeypatch.setattr(job_module, "transcribe_chunks_sequence", lambda **kw: [])
    with pytest.raises(job_module.JobTimeoutError):
        job_manager.execute_job(status.job_id, req)
    final = job_manager.get_job_status(status.job_id)
    assert final.status == "failed" and " / " in final.error
    assert supabase_service.get_user_quota(uid).used_today_seconds == 0


# Restart -------------------------------------------------------------------


def test_finished_job_status_survives_a_restart(fresh: JobManager) -> None:
    job_id = _job_id()
    job_manager.register_job(_status(job_id, "completed"), None, owner="owner-1")
    assert fresh.get_job_status(job_id).status == "completed"
    assert fresh.job_owner(job_id) == "owner-1"


def test_old_job_with_only_a_result_file_reports_completed(fresh: JobManager) -> None:
    job_id = _job_id()
    (settings.OUTPUT_DIR / f"{job_id}_result.json").write_text("{}", encoding="utf-8")
    assert fresh.get_job_status(job_id).status == "completed"


@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "a/b", "", "x" * 65])
def test_unsafe_job_ids_never_reach_the_filesystem(fresh: JobManager, bad_id: str) -> None:
    assert fresh.get_job_status(bad_id) is None
    assert fresh.job_owner(bad_id) is None


def test_interrupted_job_fails_with_a_message_and_refund(fresh: JobManager) -> None:
    uid = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123").user_id
    supabase_service.check_and_consume_quota(uid, 30.0)
    job_id = _job_id()
    job_manager.register_job(_status(job_id, "processing"), None, owner=uid)
    job_manager.record_charge(job_id, QuotaCharge(owner=uid, day=supabase_service.usage_day(), audios=1, seconds=30.0))

    assert fresh.recover_interrupted_jobs() >= 1

    status = fresh.get_job_status(job_id)
    assert status.status == "failed" and "reinició" in status.error and "restarted" in status.error
    assert fresh.job_owner(job_id) == uid
    assert supabase_service.get_user_quota(uid).used_today_seconds == 0
    # A second restart finds nothing to refund again.
    assert JobManager().recover_interrupted_jobs() == 0
    assert supabase_service.get_user_quota(uid).used_today_seconds == 0
    job_manager._charges.pop(job_id, None)


def test_recovery_leaves_jobs_of_this_process_alone() -> None:
    job_id = _job_id()
    job_manager.register_job(_status(job_id, "processing"), None, owner="o")
    job_manager.recover_interrupted_jobs()
    assert job_manager.get_job_status(job_id).status == "processing"
    job_manager._update_job(job_id, status="completed")


def test_progress_updates_are_not_written_to_disk() -> None:
    job_id = _job_id()
    job_manager.register_job(_status(job_id, "processing"), None, owner="o")
    job_file = job_manager._job_file(job_id)
    before = job_file.read_bytes()
    job_manager._update_job(job_id, progress=55, current_step="working")
    assert job_file.read_bytes() == before
    job_manager._update_job(job_id, status="completed", progress=100)
    assert json.loads(job_file.read_bytes())["status"]["status"] == "completed"


# Duplicate webhooks and resuming -------------------------------------------


def _bot(status: str = "recording", **extra) -> str:
    bot_id = f"bot-{uuid.uuid4().hex}"
    db = supabase_service._load_db()
    db.setdefault("meeting_bots", {})[bot_id] = {"bot_id": bot_id, "user_id": "u", "status": status, **extra}
    supabase_service._save_db(db)
    return bot_id


def test_repeated_bot_done_processes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(recall_service, "process_finished_bot", lambda bot_id: calls.append(bot_id))
    bot_id = _bot()
    event = {"event": "bot.done", "data": {"bot": {"id": bot_id}}}
    recall_service.handle_status_event({"event": "bot.call_ended", "data": {"bot": {"id": bot_id}}})
    recall_service.handle_status_event(event)
    recall_service.handle_status_event(event)
    time.sleep(0.05)
    assert calls == [bot_id]


def test_interrupted_bot_is_resumed_then_given_up(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(recall_service, "process_finished_bot", lambda bot_id: calls.append(bot_id))
    bot_id = _bot("processing", processing_started_at="2026-01-01T00:00:00+00:00")
    waiting_for_done = _bot("processing")  # call ended, bot.done has not arrived: not ours to start
    for _ in range(recall_service.MAX_PROCESSING_ATTEMPTS):
        recall_service.resume_interrupted_bots()
    time.sleep(0.05)
    assert calls.count(bot_id) == recall_service.MAX_PROCESSING_ATTEMPTS
    assert waiting_for_done not in calls

    recall_service.resume_interrupted_bots()
    assert supabase_service._load_db()["meeting_bots"][bot_id]["status"] == "failed"
    assert "gsk" not in supabase_service._load_db()["meeting_bots"][bot_id]["error"]


def test_interrupted_call_is_resumed_then_given_up(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(twilio_service, "process_recording", lambda call_id: calls.append(call_id))
    call_id = f"call-{uuid.uuid4().hex}"
    db = supabase_service._load_db()
    db.setdefault("phone_calls", {})[call_id] = {"call_id": call_id, "user_id": "u", "status": "processing"}
    supabase_service._save_db(db)
    for _ in range(twilio_service.MAX_PROCESSING_ATTEMPTS):
        twilio_service.resume_interrupted_calls()
    time.sleep(0.05)
    assert calls.count(call_id) == twilio_service.MAX_PROCESSING_ATTEMPTS
    twilio_service.resume_interrupted_calls()
    assert supabase_service._load_db()["phone_calls"][call_id]["status"] == "failed"


# Memory --------------------------------------------------------------------


def _result(job_id: str) -> TranscriptionResult:
    return TranscriptionResult(
        job_id=job_id, session_id="s", user_id="u", plan="pro", status="completed", detected_speakers_count=0,
        total_duration_sec=1, total_duration_formatted="00:00:01", model_used="m", diarization_engine_used="e",
        engine_brand="b", file_order=[], segments=[], full_text="x",
    )


def test_results_are_capped_and_reload_from_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    monkeypatch.setattr(job_module, "_MAX_RESULTS_IN_MEMORY", 2)
    ids = [_job_id() for _ in range(4)]
    for job_id in ids:
        (settings.OUTPUT_DIR / f"{job_id}_result.json").write_text(_result(job_id).model_dump_json(), encoding="utf-8")
        assert manager.get_job_result(job_id) is not None
    manager.get_job_result(ids[0])  # recently used, so it stays
    manager.evict()
    assert len(manager._results) == 2
    assert ids[0] in manager._results
    assert manager.get_job_result(ids[1]).job_id == ids[1]


def test_result_without_a_file_is_never_evicted(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    monkeypatch.setattr(job_module, "_MAX_RESULTS_IN_MEMORY", 0)
    manager._results["job_memory_only"] = _result("job_memory_only")
    manager.evict()
    assert "job_memory_only" in manager._results


def test_finished_jobs_leave_memory_but_still_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    job_id = _job_id()
    manager.register_job(_status(job_id, "completed"), None, owner="o")
    manager._finished_at[job_id] = time.monotonic() - job_module._FINISHED_JOB_MEMORY_SECONDS - 1
    manager.evict()
    assert job_id not in manager._jobs and job_id not in manager._job_owners
    assert manager.get_job_status(job_id).status == "completed"
    assert manager.job_owner(job_id) == "o"


def test_running_jobs_are_never_evicted() -> None:
    manager = JobManager()
    job_id = _job_id()
    manager.register_job(_status(job_id, "processing"), None, owner="o")
    manager.evict()
    assert job_id in manager._jobs


def test_expired_guest_result_is_purged_with_its_files() -> None:
    manager = JobManager()
    job_id = _job_id()
    merged = settings.OUTPUT_DIR / f"{job_id}_merged.mp3"
    merged.write_bytes(b"x")
    manager.register_job(_status(job_id, "completed"), _result(job_id), owner="guest_x")
    manager._guest_expiry[job_id] = time.time() + 1000
    manager.evict()
    assert job_id in manager._results  # not yet

    manager._guest_expiry[job_id] = time.time() - 1
    manager.evict()
    assert job_id not in manager._results
    assert not merged.exists()
    assert not manager._job_file(job_id).exists()
    assert manager.get_job_status(job_id) is None


def test_completed_box_sessions_are_forgotten() -> None:
    from app.models.schemas import BoxCreateSessionRequest

    done = apex_box_manager.create_session(BoxCreateSessionRequest(title="a", user_id="u")).box_session_id
    open_box = apex_box_manager.create_session(BoxCreateSessionRequest(title="b", user_id="u")).box_session_id
    session = apex_box_manager.get_session(done)
    session.status = "completed"
    session.updated_at = "2020-01-01T00:00:00+00:00"
    apex_box_manager.get_session(open_box).updated_at = "2020-01-01T00:00:00+00:00"
    apex_box_manager.evict_completed()
    assert done not in apex_box_manager._sessions
    assert open_box in apex_box_manager._sessions


def test_old_rate_limit_keys_are_forgotten() -> None:
    deps._throttle_hits["old"] = [time.monotonic() - 7200]
    deps._throttle_hits["recent"] = [time.monotonic()]
    deps.prune_throttle()
    assert "old" not in deps._throttle_hits
    assert "recent" in deps._throttle_hits
