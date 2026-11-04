"""Supabase Auth login must never take over an account it does not own."""

import json
import uuid
from typing import Any, Dict, List

import httpx
import pytest

from app.config import settings
from app.services import supabase_service as module
from app.services.supabase_service import _verify_password, supabase_service

CONFIRMED = "2026-01-01T00:00:00+00:00"


def _email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


@pytest.fixture
def gotrue(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Fake Supabase: `auth` is what /auth/v1/token answers; `posts` records REST writes."""
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon")
    state: Dict[str, Any] = {"auth": None, "posts": []}
    posts: List[Dict[str, Any]] = state["posts"]

    def handler(request: httpx.Request) -> httpx.Response:
        if "/auth/v1/token" in str(request.url):
            if state["auth"] is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"user": state["auth"]})
        posts.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(201, json=[])

    real_client = httpx.Client
    monkeypatch.setattr(
        module.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    return state


def _auth_user(email: str, **extra: Any) -> Dict[str, Any]:
    return {"id": str(uuid.uuid4()), "email": email, "email_confirmed_at": CONFIRMED, **extra}


def test_unconfirmed_auth_user_is_rejected(gotrue: Dict[str, Any]) -> None:
    email = _email()
    gotrue["auth"] = {**_auth_user(email), "email_confirmed_at": None}
    with pytest.raises(ValueError, match="Credenciales"):
        supabase_service.login_user(email, "cloud-password-1")
    assert not supabase_service.email_registered(email)


def test_matching_email_cannot_take_over_a_local_account(gotrue: Dict[str, Any]) -> None:
    email = _email()
    victim = supabase_service.register_user(email, "victim-password-1")
    gotrue["auth"] = _auth_user(email)  # the attacker signed up to Supabase with the victim's address

    with pytest.raises(ValueError, match="Credenciales"):
        supabase_service.login_user(email, "attacker-password-1")

    record = supabase_service._load_db()["users"][victim.user_id]
    assert _verify_password("victim-password-1", record["password_hash"])
    assert not _verify_password("attacker-password-1", record["password_hash"])


def test_new_cloud_account_is_created_linked_and_synced(gotrue: Dict[str, Any]) -> None:
    email = _email()
    gotrue["auth"] = _auth_user(email)
    profile = supabase_service.login_user(email, "cloud-password-1")

    assert profile.user_id == gotrue["auth"]["id"]
    assert supabase_service._load_db()["users"][profile.user_id]["supabase_id"] == profile.user_id
    assert [p["body"]["id"] for p in gotrue["posts"] if "/profiles" in p["url"]] == [profile.user_id]


def test_linked_local_account_accepts_a_changed_cloud_password(gotrue: Dict[str, Any]) -> None:
    email = _email()
    local = supabase_service.register_user(email, "old-password-1")
    gotrue["auth"] = _auth_user(email)
    db = supabase_service._load_db()
    db["users"][local.user_id]["supabase_id"] = gotrue["auth"]["id"]
    supabase_service._save_db(db)

    assert supabase_service.login_user(email, "new-cloud-password-1").user_id == local.user_id
    assert supabase_service.login_user(email, "new-cloud-password-1").user_id == local.user_id
    record = supabase_service._load_db()["users"][local.user_id]
    assert _verify_password("new-cloud-password-1", record["password_hash"])


def test_lifetime_pro_is_applied_on_accepted_logins(gotrue: Dict[str, Any]) -> None:
    email = _email()
    gotrue["auth"] = _auth_user(email, app_metadata={"plan": "pro"})
    assert supabase_service.login_user(email, "cloud-password-1").plan == "pro"


def test_user_metadata_cannot_grant_pro(gotrue: Dict[str, Any]) -> None:
    email = _email()
    gotrue["auth"] = _auth_user(email, user_metadata={"plan": "pro"})
    assert supabase_service.login_user(email, "cloud-password-1").plan == "free"
