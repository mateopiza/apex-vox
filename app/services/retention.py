"""
Retention sweep (app/services/retention.py)
-------------------------------------------
Deletes what the plans promise to delete: free results after their window, a lapsed Pro account's
files after its grace period, original uploads and leftovers. Pro data is never touched.

With RETENTION_DRY_RUN (the default) it only reports what it would delete. Expired results stop
being served either way; that check lives in `JobManager.get_job_result`.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.logsafe import clean
from app.services import usage_reporter
from app.services.acoustic_diarizer import update_voice_profiles
from app.services.apex_box import apex_box_manager
from app.services.job_manager import job_manager
from app.services.state_store import StateCorruptError, read_json
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.services.retention")

_RESULT_SUFFIX = "_result.json"
_MERGED_SUFFIX = "_merged.mp3"


def _is_expired(stored: Optional[str], owner_id: Optional[str]) -> bool:
    expiry = supabase_service.effective_expiry(stored, owner_id)
    return bool(expiry and dt.datetime.now(dt.timezone.utc) >= expiry)


def _read_result(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        data = read_json(settings.OUTPUT_DIR / f"{job_id}{_RESULT_SUFFIX}")
    except StateCorruptError:
        return None
    return data if isinstance(data, dict) else None


def delete_job_files(job_id: str, record: Optional[Dict[str, Any]] = None) -> bool:
    """
    Remove one job from the bucket, the disk and memory. False if the bucket could not confirm:
    the caller keeps its record and tries again later.
    """
    keys = {meta["object_key"] for meta in mega_s4_storage._load_index().values() if meta.get("job_id") == job_id}
    keys.update(k for k in ((record or {}).get("s4_audio_key"), (record or {}).get("s4_result_key")) if k)
    if not all([mega_s4_storage.delete_object(key) for key in sorted(keys)]):
        return False
    for suffix in (_MERGED_SUFFIX, "_merged_concat.txt", _RESULT_SUFFIX):
        (settings.OUTPUT_DIR / f"{job_id}{suffix}").unlink(missing_ok=True)
    job_manager.forget_job(job_id)
    return True


def _sweep_jobs(report: Dict[str, Any], dry_run: bool) -> None:
    records = supabase_service._read_snapshot().get("transcriptions", {})
    on_disk = {p.name[: -len(_RESULT_SUFFIX)] for p in settings.OUTPUT_DIR.glob(f"*{_RESULT_SUFFIX}")}
    for job_id in sorted(on_disk | set(records)):
        if job_manager.is_active(job_id):
            continue
        record = records.get(job_id)
        data = None if record else _read_result(job_id)
        source = record or data
        if not source or not _is_expired(source.get("expires_at"), source.get("user_id")):
            continue
        report["jobs"].append(job_id)
        if dry_run:
            continue
        # La cuenta pudo pagar justo ahora: se vuelve a mirar antes de borrar.
        fresh = supabase_service._load_db().get("transcriptions", {}).get(job_id) or source
        if not _is_expired(fresh.get("expires_at"), fresh.get("user_id")):
            report["jobs"].remove(job_id)
            continue
        result = data or _read_result(job_id)
        if result:
            usage_reporter.record_in_ledger(settings.OUTPUT_DIR / f"{job_id}{_RESULT_SUFFIX}", result)
        if not delete_job_files(job_id, fresh):
            report["failed"].append(job_id)
            continue
        if not supabase_service.delete_transcription_record(job_id):
            report["failed"].append(job_id)


def _sweep_uploads(report: Dict[str, Any], dry_run: bool, cutoff: float) -> None:
    active = job_manager.active_session_ids() | apex_box_manager.open_upload_session_ids()
    for session_dir in sorted(p for p in settings.UPLOAD_DIR.iterdir() if p.is_dir()):
        if session_dir.name in active:
            continue
        newest = max((p.stat().st_mtime for p in session_dir.rglob("*")), default=session_dir.stat().st_mtime)
        if newest >= cutoff:
            continue
        report["uploads"].append(session_dir.name)
        if not dry_run:
            job_manager.discard_session(session_dir.name)
            shutil.rmtree(session_dir, ignore_errors=True)


def _sweep_leftovers(report: Dict[str, Any], dry_run: bool, cutoff: float) -> None:
    """Merged audio with no result (a restart cut off its guest's purge) and old job statuses."""
    candidates: List[Path] = [
        p for p in settings.OUTPUT_DIR.glob(f"*{_MERGED_SUFFIX}")
        if not (settings.OUTPUT_DIR / f"{p.name[: -len(_MERGED_SUFFIX)]}{_RESULT_SUFFIX}").exists()
        and not job_manager.is_active(p.name[: -len(_MERGED_SUFFIX)])
        and not job_manager.has_live_result(p.name[: -len(_MERGED_SUFFIX)])
    ]
    candidates += [
        p for p in (settings.OUTPUT_DIR / "jobs").glob("*.json")
        if not (settings.OUTPUT_DIR / f"{p.stem}{_RESULT_SUFFIX}").exists()
        and not job_manager.is_active(p.stem)
        and not job_manager.has_live_result(p.stem)
    ]
    for path in candidates:
        if path.stat().st_mtime >= cutoff:
            continue
        report["leftovers"].append(path.name)
        if not dry_run:
            path.unlink(missing_ok=True)


def _sweep_index(report: Dict[str, Any], dry_run: bool) -> None:
    """Objects with their own expiry whose job is already gone from the disk."""
    for key, meta in mega_s4_storage._load_index().items():
        if meta.get("job_id") in report["jobs"]:
            continue
        if not _is_expired(meta.get("expires_at"), meta.get("user_id")):
            continue
        report["objects"].append(key)
        if not dry_run and not mega_s4_storage.delete_object(key):
            report["failed"].append(key)


def process_pending_erasures(only_user: Optional[str] = None) -> int:
    """
    Finish deleting accounts: the user asked for it, so RETENTION_DRY_RUN does not apply. What a
    provider could not confirm stays pending for the next sweep. Returns how many remain.
    """
    pending = supabase_service._read_snapshot().get("pending_erasures", {})
    remaining = 0
    for user_id, entry in list(pending.items()):
        if only_user and user_id != only_user:
            continue
        try:
            if _erase_account_data(user_id, entry):
                supabase_service.finish_erasure(user_id)
                continue
        except (OSError, StateCorruptError):
            logger.exception("Could not finish deleting an account")
        remaining += 1
    return remaining


def _erase_account_data(user_id: str, entry: Dict[str, Any]) -> bool:
    job_manager.forget_owner(user_id)
    apex_box_manager.forget_owner(user_id)
    done = [delete_job_files(job_id, record) for job_id, record in (entry.get("jobs") or {}).items()]
    done += [
        mega_s4_storage.delete_object(key)
        for key, meta in mega_s4_storage._load_index().items() if meta.get("user_id") == user_id
    ]
    # Voiceprints are biometric data: also those of accounts deleted before this existed.
    users = supabase_service._read_snapshot()["users"]
    update_voice_profiles(lambda profiles: [p for p in profiles if p.owner_id in users])
    done.append(supabase_service.delete_remote_account_rows(user_id, entry.get("supabase_id")))
    return all(done)


def sweep(dry_run: Optional[bool] = None) -> Dict[str, Any]:
    """One pass. Returns what it deleted, or in a dry run what it would have."""
    dry_run = settings.RETENTION_DRY_RUN if dry_run is None else dry_run
    report: Dict[str, Any] = {"dry_run": dry_run, "jobs": [], "uploads": [], "leftovers": [], "objects": [], "failed": []}
    cutoff = time.time() - settings.JOB_RETENTION_HOURS * 3600
    for step in (
        lambda: _sweep_jobs(report, dry_run),
        lambda: _sweep_uploads(report, dry_run, cutoff),
        lambda: _sweep_leftovers(report, dry_run, cutoff),
        lambda: _sweep_index(report, dry_run),
    ):
        try:
            step()
        except (OSError, StateCorruptError):
            logger.exception("Retention sweep step failed")
    try:
        mega_s4_storage.retry_unsynced_uploads()
        process_pending_erasures()
    except (OSError, StateCorruptError):
        logger.exception("Could not retry pending uploads or account deletions")

    logger.info(
        "Retention sweep%s: %d job(s), %d upload folder(s), %d leftover(s), %d object(s), %d failed. Jobs: %s",
        " (dry run, nothing was deleted)" if dry_run else "",
        len(report["jobs"]), len(report["uploads"]), len(report["leftovers"]), len(report["objects"]),
        len(report["failed"]), clean(",".join(report["jobs"][:50])),
    )
    return report
