"""A damaged state file must stop the app, never be overwritten with an empty one."""

import json
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import VoiceProfile
from app.services import acoustic_diarizer, state_store
from app.services.state_store import StateCorruptError, atomic_write_bytes, atomic_write_json, read_json
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

client = TestClient(app, raise_server_exceptions=False)


def _email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


@pytest.fixture
def damaged_state():
    """Truncate the accounts file as a crash during a plain write would, then restore it."""
    path = supabase_service._db_file
    original = path.read_bytes()
    damaged = original[: len(original) // 2] or b"{"
    path.write_bytes(damaged)
    yield damaged
    path.write_bytes(original)


def test_truncated_state_returns_503_and_is_never_overwritten(damaged_state: bytes) -> None:
    response = client.post(
        "/api/auth/register", json={"email": _email(), "password": "password123", "full_name": "A"}
    )
    assert response.status_code == 503
    assert " / " in response.json()["detail"]  # Spanish and English
    assert supabase_service._db_file.read_bytes() == damaged_state


def test_health_reports_unreadable_state(damaged_state: bytes) -> None:
    assert client.get("/api/health").status_code == 503


def test_service_refuses_to_save_after_a_failed_load(damaged_state: bytes) -> None:
    with pytest.raises(StateCorruptError):
        supabase_service.register_user(_email(), "password123")
    assert supabase_service._db_file.read_bytes() == damaged_state


def test_state_file_missing_at_runtime_is_an_error_not_a_reset() -> None:
    path = supabase_service._db_file
    original = path.read_bytes()
    path.unlink()
    try:
        with pytest.raises(StateCorruptError):
            supabase_service._load_db()
        assert not path.exists()
    finally:
        path.write_bytes(original)


def test_non_object_state_is_corrupt() -> None:
    path = supabase_service._db_file
    original = path.read_bytes()
    path.write_bytes(b"[]")
    try:
        with pytest.raises(StateCorruptError):
            supabase_service._load_db()
    finally:
        path.write_bytes(original)


def test_failed_replace_keeps_the_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "state.json"
    atomic_write_json(target, {"keep": 1})

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(state_store.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_json(target, {"keep": 2})
    assert read_json(target) == {"keep": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]  # no temp file left behind


def test_atomic_write_keeps_existing_permissions(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_bytes(target, b"1")
    assert target.stat().st_mode & 0o777 == 0o600
    target.chmod(0o640)
    atomic_write_bytes(target, b"2")
    assert target.stat().st_mode & 0o777 == 0o640


def test_empty_app_secret_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.setattr(supabase_service, "_secret_cache", None)
    path = supabase_service._db_file.parent / ".app_secret"
    original = path.read_bytes() if path.exists() else None
    path.write_bytes(b"")
    try:
        assert len(supabase_service._app_secret()) == 64
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        if original is not None:
            path.write_bytes(original)
        else:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Storage index
# ---------------------------------------------------------------------------


def test_concurrent_uploads_keep_every_index_entry() -> None:
    prefix = f"users/{uuid.uuid4().hex}"
    keys = [f"{prefix}/{i}.json" for i in range(12)]
    threads = [
        threading.Thread(target=mega_s4_storage.upload_object, args=(key, b"{}"), kwargs={"plan": "pro"})
        for key in keys
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    index = mega_s4_storage._load_index()
    assert all(key in index for key in keys)


def test_damaged_index_is_left_alone_and_upload_still_succeeds() -> None:
    path = mega_s4_storage.index_path
    original = path.read_bytes() if path.exists() else None
    path.write_bytes(b"{broken")
    try:
        key = f"users/{uuid.uuid4().hex}/a.json"
        assert mega_s4_storage.upload_object(key, b"{}", plan="pro")["object_key"] == key
        assert mega_s4_storage.cleanup_expired_objects() == 0
        assert mega_s4_storage.get_object_metadata(key) is None
        assert path.read_bytes() == b"{broken"
    finally:
        if original is not None:
            path.write_bytes(original)
        else:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Voice profiles
# ---------------------------------------------------------------------------


def _profile(owner: str) -> VoiceProfile:
    return VoiceProfile(
        profile_id=f"vp_{uuid.uuid4().hex[:8]}", name="Ana", role="", sample_duration_sec=5.0,
        pitch_hz=120.0, embedding=[0.1, 0.2], created_at="2026-01-01T00:00:00+00:00", owner_id=owner,
    )


def test_one_bad_voice_record_never_wipes_other_accounts() -> None:
    path = acoustic_diarizer._profiles_file_path()
    original = path.read_bytes() if path.exists() else None
    damaged = json.dumps([_profile("victim").model_dump(mode="json"), {"not": "a profile"}]).encode()
    path.write_bytes(damaged)
    try:
        assert acoustic_diarizer.list_voice_profiles("victim") == []  # read path degrades
        with pytest.raises(StateCorruptError):
            acoustic_diarizer.update_voice_profiles(lambda profiles: profiles + [_profile("other")])
        with pytest.raises(StateCorruptError):
            acoustic_diarizer.delete_voice_profile("vp_x", "other")
        assert path.read_bytes() == damaged
    finally:
        if original is not None:
            path.write_bytes(original)
        else:
            path.unlink(missing_ok=True)


def test_voice_profile_update_keeps_other_accounts() -> None:
    owner, other = uuid.uuid4().hex, uuid.uuid4().hex
    mine, theirs = _profile(owner), _profile(other)
    acoustic_diarizer.update_voice_profiles(lambda profiles: profiles + [mine, theirs])
    acoustic_diarizer.delete_voice_profile(mine.profile_id, owner)
    assert acoustic_diarizer.list_voice_profiles(owner) == []
    assert [p.profile_id for p in acoustic_diarizer.list_voice_profiles(other)] == [theirs.profile_id]
