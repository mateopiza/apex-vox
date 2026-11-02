"""
Account security, social sign-in, plan gating and language detection
(tests/test_auth_billing.py)
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import oauth_service
from app.services.supabase_service import _legacy_hash_password, supabase_service


def _register(client: TestClient, password: str = "correcthorse1") -> dict:
    email = f"user_{uuid.uuid4().hex[:8]}@apexvox.ai"
    res = client.post("/api/auth/register", json={"email": email, "password": password, "full_name": "Test"})
    assert res.status_code == 200, res.text
    return res.json()


def test_passwords_are_salted_and_short_ones_rejected() -> None:
    client = TestClient(app)
    weak = client.post("/api/auth/register", json={"email": f"w_{uuid.uuid4().hex[:6]}@x.co", "password": "1234"})
    assert weak.status_code == 400

    profile = _register(client)
    stored = supabase_service._load_db()["users"][profile["user_id"]]["password_hash"]
    assert stored.startswith("pbkdf2_sha256$")


def test_legacy_password_hash_is_migrated_on_login() -> None:
    client = TestClient(app)
    profile = _register(client)
    db = supabase_service._load_db()
    db["users"][profile["user_id"]]["password_hash"] = _legacy_hash_password("oldpassword")
    supabase_service._save_db(db)

    res = client.post("/api/auth/login", json={"email": profile["email"], "password": "oldpassword"})
    assert res.status_code == 200
    migrated = supabase_service._load_db()["users"][profile["user_id"]]["password_hash"]
    assert migrated.startswith("pbkdf2_sha256$")


def test_user_id_is_not_a_credential() -> None:
    client = TestClient(app)
    profile = _register(client)
    assert client.get("/api/auth/me", headers={"Authorization": profile["user_id"]}).status_code == 401
    summary = client.get("/api/portal/summary", params={"user_id": profile["user_id"]},
                         headers={"Authorization": f"Bearer {profile['user_id']}"}).json()
    assert summary["user"]["email"] != profile["email"]

    ok = client.get("/api/auth/me", headers={"Authorization": f"Bearer {profile['access_token']}"})
    assert ok.status_code == 200 and ok.json()["email"] == profile["email"]


def test_logout_revokes_the_session() -> None:
    client = TestClient(app)
    profile = _register(client)
    auth = {"Authorization": f"Bearer {profile['access_token']}"}
    assert client.post("/api/auth/logout", headers=auth).status_code == 200
    assert client.get("/api/auth/me", headers=auth).status_code == 401


def test_client_cannot_choose_plan_or_api_keys(tmp_path) -> None:
    """The removed simulator/key fields are ignored: plan and keys come from the server."""
    from app.models.schemas import TranscribeRequest

    req = TranscribeRequest(session_id="x", plan_override="pro", api_key="gsk_evil")
    assert not hasattr(req, "plan_override")
    cfg = TestClient(app).get("/api/auth/config").json()
    assert "plan_simulator" not in cfg and "require_login" not in cfg
    assert cfg["guest_max_audios"] >= 1


def test_free_plan_minutes_and_calendar_are_pro_only() -> None:
    from app.api.routes_transcribe import _require_summa_access

    class Result:
        plan = "free"

    with pytest.raises(Exception) as exc:
        _require_summa_access(Result(), None)
    assert getattr(exc.value, "status_code", None) == 402
    _require_summa_access(Result(), {"plan": "trial"})  # paid users pass


def test_trial_expiry_downgrades_to_free() -> None:
    client = TestClient(app)
    profile = _register(client)
    auth = {"Authorization": f"Bearer {profile['access_token']}"}
    assert client.post("/api/billing/subscribe", json={}, headers=auth).json()["plan"] == "trial"

    db = supabase_service._load_db()
    db["users"][profile["user_id"]]["trial_ends_at"] = "2020-01-01T00:00:00+00:00"
    supabase_service._save_db(db)
    me = client.get("/api/auth/me", headers=auth).json()
    assert me["plan"] == "free"
    assert me["quota"]["trial_available"] is False


def test_oauth_start_redirects_to_supabase_with_pkce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(oauth_service, "enabled_providers", lambda force=False: ["google", "github"])
    client = TestClient(app, base_url="https://apex-vox.test")

    res = client.get("/api/auth/oauth/google", follow_redirects=False)
    assert res.status_code == 303
    target = urlparse(res.headers["location"])
    assert target.netloc == "example.supabase.co" and target.path == "/auth/v1/authorize"
    q = parse_qs(target.query)
    assert q["provider"] == ["google"]
    assert q["code_challenge_method"] == ["s256"]
    assert q["redirect_to"] == ["https://apex-vox.test/api/auth/oauth/callback"]
    cookie = res.headers["set-cookie"]
    assert "apx_oauth=" in cookie and "HttpOnly" in cookie

    disabled = TestClient(app).get("/api/auth/oauth/facebook", follow_redirects=False)
    assert "auth_error=provider_disabled" in disabled.headers["location"]


def test_oauth_callback_creates_account_and_hands_off_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon")
    email = f"gh_{uuid.uuid4().hex[:8]}@example.com"
    seen = {}

    def fake_exchange(code: str, verifier: str) -> dict:
        seen.update(code=code, verifier=verifier)
        return {"email": email, "email_confirmed_at": "2026-01-01T00:00:00Z",
                "user_metadata": {"full_name": "Grace Hopper"}, "app_metadata": {"provider": "github"}}

    monkeypatch.setattr(oauth_service, "exchange_code", fake_exchange)
    client = TestClient(app, base_url="https://apex-vox.test")
    client.cookies.set("apx_oauth", "github:verifier123", path="/api/auth/oauth")
    res = client.get("/api/auth/oauth/callback?code=abc", follow_redirects=False)
    assert res.status_code == 303
    assert seen == {"code": "abc", "verifier": "verifier123"}
    location = res.headers["location"]
    assert location.startswith("/?auth_code=")

    code = location.split("auth_code=", 1)[1]
    first = client.post("/api/auth/oauth/exchange", json={"code": code})
    assert first.status_code == 200
    data = first.json()
    assert data["email"] == email and data["full_name"] == "Grace Hopper"
    assert data["access_token"].startswith("apx_")
    # One-time code
    assert client.post("/api/auth/oauth/exchange", json={"code": code}).status_code == 401

    # Without the PKCE cookie the callback refuses
    fresh = TestClient(app).get("/api/auth/oauth/callback?code=abc", follow_redirects=False)
    assert "auth_error=expired" in fresh.headers["location"]


def test_page_language_follows_browser() -> None:
    client = TestClient(app)
    es = client.get("/", headers={"Accept-Language": "es-CO,es;q=0.9,en;q=0.8"}).text
    en = client.get("/", headers={"Accept-Language": "en-US,en;q=0.9"}).text
    other = client.get("/", headers={"Accept-Language": "fr-FR,fr;q=0.9"}).text
    assert '<html lang="es" data-default-lang="es"' in es
    assert '<html lang="en" data-default-lang="en"' in en
    assert '<html lang="en"' in other
