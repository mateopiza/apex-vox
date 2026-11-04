"""Authenticated reads must not reparse the state file, and slow login work must not hold the lock."""

import json
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import supabase_service as module
from app.services.supabase_service import supabase_service

client = TestClient(app)


def _register() -> tuple[str, str]:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    return profile.user_id, profile.access_token


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []
    real = module.read_json

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(module, "read_json", counting)
    return calls


def test_repeated_authenticated_requests_do_not_parse_again(parses: list) -> None:
    _, token = _register()
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200  # registers this network once
    parses.clear()
    for _ in range(5):
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert client.get("/api/auth/quota", headers=headers).status_code == 200
    assert parses == []


def test_saved_changes_are_seen_immediately() -> None:
    user_id, token = _register()
    assert supabase_service.get_user_by_token(token)["preferred_language"] == "es"
    supabase_service.set_preferred_language(user_id, "en")
    assert supabase_service.get_user_by_token(token)["preferred_language"] == "en"


def test_a_file_changed_from_outside_is_noticed() -> None:
    user_id, token = _register()
    supabase_service.get_user_by_token(token)
    db = json.loads(supabase_service._db_file.read_bytes())
    db["users"][user_id]["full_name"] = "Edited by hand"
    supabase_service._db_file.write_text(json.dumps(db), encoding="utf-8")
    assert supabase_service.get_user_by_token(token)["full_name"] == "Edited by hand"


def test_returned_data_cannot_change_the_shared_snapshot() -> None:
    user_id, token = _register()
    before = json.dumps(supabase_service._read_snapshot(), sort_keys=True)

    supabase_service.get_user_by_token(token)["full_name"] = "changed"
    supabase_service.get_user_by_id(user_id)["full_name"] = "changed"
    supabase_service.get_user_quota(user_id)
    supabase_service.guest_audios_used_today("guest_x")
    supabase_service.list_user_transcriptions(user_id).clear()

    assert json.dumps(supabase_service._read_snapshot(), sort_keys=True) == before


def test_quota_rejection_still_discards_unsaved_changes() -> None:
    uid = f"auto-{uuid.uuid4().hex}"
    with pytest.raises(PermissionError):
        supabase_service.check_and_consume_quota(uid, 10**9)
    assert uid not in supabase_service._load_db()["users"]


def test_expired_plan_is_downgraded_and_saved_on_read() -> None:
    user_id, token = _register()
    db = supabase_service._load_db()
    db["users"][user_id].update(plan="pro", pro_until="2020-01-01T00:00:00+00:00")
    supabase_service._save_db(db)

    assert supabase_service.get_user_by_token(token)["plan"] == "free"
    assert supabase_service._load_db()["users"][user_id]["plan"] == "free"


def test_expired_session_is_removed() -> None:
    _, token = _register()
    db = supabase_service._load_db()
    db["tokens"][supabase_service._token_key(token)]["expires_at"] = "2020-01-01T00:00:00+00:00"
    supabase_service._save_db(db)

    assert supabase_service.get_user_by_token(token) is None
    assert supabase_service._token_key(token) not in supabase_service._load_db()["tokens"]


def test_known_network_needs_no_lock_and_new_one_beyond_the_limit_is_refused(monkeypatch) -> None:
    user_id, _ = _register()
    monkeypatch.setattr(module.settings, "MAX_IPS_PER_MONTH", 1)
    assert supabase_service.register_account_ip(user_id, "10.0.0.1") is True
    assert supabase_service.register_account_ip(user_id, "10.0.0.1") is True
    assert supabase_service.register_account_ip(user_id, "10.0.0.2") is False


def test_login_does_not_hold_the_lock_during_a_slow_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    email = f"{uuid.uuid4().hex}@example.com"
    supabase_service.register_user(email, "password123")
    entered, release = threading.Event(), threading.Event()
    real_verify = module._verify_password

    def slow_verify(password: str, stored: str) -> bool:
        entered.set()
        release.wait(5)
        return real_verify(password, stored)

    monkeypatch.setattr(module, "_verify_password", slow_verify)
    login = threading.Thread(target=supabase_service.login_user, args=(email, "password123"))
    login.start()
    assert entered.wait(5)
    try:
        started = time.monotonic()
        assert supabase_service._lock.acquire(timeout=2)
        supabase_service._lock.release()
        assert time.monotonic() - started < 2
    finally:
        release.set()
        login.join()


def test_login_rejects_a_password_changed_during_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    email = f"{uuid.uuid4().hex}@example.com"
    user_id = supabase_service.register_user(email, "password123").user_id
    real_verify = module._verify_password

    def verify_then_change(password: str, stored: str) -> bool:
        ok = real_verify(password, stored)
        db = supabase_service._load_db()
        db["users"][user_id]["password_hash"] = module._hash_password("another-password")
        supabase_service._save_db(db)
        return ok

    monkeypatch.setattr(module, "_verify_password", verify_then_change)
    with pytest.raises(ValueError, match="Credenciales"):
        supabase_service.login_user(email, "password123")


def test_fake_reset_link_costs_no_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: str) -> str:
        raise AssertionError("a fake link must not reach the password hash")

    monkeypatch.setattr(module, "_hash_password", fail)
    with pytest.raises(PermissionError):
        supabase_service.reset_password("not-a-real-token", "password123")
