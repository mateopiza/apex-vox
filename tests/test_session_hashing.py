"""The state file must never hold a usable session."""

import datetime as dt
import json
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services.supabase_service import SupabaseCloudService, supabase_service

client = TestClient(app)


def _register():
    return supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")


def test_no_raw_token_on_disk_after_login() -> None:
    profile = _register()
    login = supabase_service.login_user(profile.email, "password123")
    raw = supabase_service._db_file.read_text(encoding="utf-8")
    assert profile.access_token not in raw
    assert login.access_token not in raw
    assert supabase_service.get_user_by_token(login.access_token)["user_id"] == profile.user_id


def test_stored_digest_is_not_accepted_as_a_token() -> None:
    profile = _register()
    digest = supabase_service._token_key(profile.access_token)
    assert supabase_service.get_user_by_token(digest) is None
    assert supabase_service.get_user_by_token(f"apx_{digest}") is None


def test_user_id_is_not_a_session() -> None:
    profile = _register()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {profile.user_id}"}).status_code == 401


def test_logout_and_password_reset_end_sessions() -> None:
    profile = _register()
    supabase_service.revoke_token(profile.access_token)
    assert supabase_service.get_user_by_token(profile.access_token) is None

    other = supabase_service.login_user(profile.email, "password123")
    token, _ = supabase_service.create_password_reset(profile.email)
    fresh = supabase_service.reset_password(token, "another-password-1")
    assert supabase_service.get_user_by_token(other.access_token) is None
    assert supabase_service.get_user_by_token(fresh.access_token)["user_id"] == profile.user_id


def test_raw_backup_is_migrated_and_keeps_working() -> None:
    profile = _register()
    token = "apx_" + uuid.uuid4().hex
    legacy = "apx_" + uuid.uuid4().hex
    expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
    db = supabase_service._load_db()
    db["tokens"][token] = {"user_id": profile.user_id, "expires_at": expires}
    db["tokens"][legacy] = profile.user_id  # very old format: a bare user id, no expiry
    db["handoffs"]["old-code"] = {"token": token, "expires_at": expires}
    # Written directly, as a restored backup would be.
    supabase_service._db_file.write_text(json.dumps(db), encoding="utf-8")

    # A new process start rewrites the file without raw secrets.
    SupabaseCloudService()
    raw = supabase_service._db_file.read_text(encoding="utf-8")
    assert token not in raw
    assert legacy not in raw
    assert "old-code" not in raw

    assert supabase_service.get_user_by_token(token)["user_id"] == profile.user_id
    assert supabase_service.get_user_by_token(legacy)["user_id"] == profile.user_id
    entry = supabase_service._load_db()["tokens"][supabase_service._token_key(legacy)]
    assert entry["user_id"] == profile.user_id and entry["expires_at"]


def test_migration_runs_on_every_parse_not_only_at_start() -> None:
    profile = _register()
    token = "apx_" + uuid.uuid4().hex
    expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
    db = supabase_service._load_db()
    db["tokens"][token] = {"user_id": profile.user_id, "expires_at": expires}
    supabase_service._db_file.write_text(json.dumps(db), encoding="utf-8")
    assert supabase_service.get_user_by_token(token)["user_id"] == profile.user_id


def test_expired_token_is_rejected() -> None:
    profile = _register()
    db = supabase_service._load_db()
    db["tokens"][supabase_service._token_key(profile.access_token)]["expires_at"] = "2020-01-01T00:00:00+00:00"
    supabase_service._save_db(db)
    assert supabase_service.get_user_by_token(profile.access_token) is None


def test_handoff_code_is_single_use_hashed_and_makes_a_new_session() -> None:
    profile = _register()
    code = supabase_service.create_handoff_code(profile.user_id)
    raw = supabase_service._db_file.read_text(encoding="utf-8")
    assert code not in raw

    picked_up = supabase_service.consume_handoff_code(code)
    assert picked_up.user_id == profile.user_id
    assert picked_up.access_token and picked_up.access_token != profile.access_token
    assert supabase_service.get_user_by_token(picked_up.access_token)["user_id"] == profile.user_id
    assert supabase_service.consume_handoff_code(code) is None


def test_expired_handoff_code_is_rejected() -> None:
    profile = _register()
    code = supabase_service.create_handoff_code(profile.user_id, ttl_seconds=-1)
    assert supabase_service.consume_handoff_code(code) is None
