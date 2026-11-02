"""
Visitor limits, account protections, e-mail flows, Telegram linking and policies
(tests/test_guest_security.py)
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import email_service, telegram_service
from app.services.supabase_service import supabase_service
from tests.fixtures.audio_generator import create_synthetic_wav


def _ip_client(ip: str) -> TestClient:
    client = TestClient(app)
    client.headers.update({"X-Forwarded-For": ip})
    return client


def _register(client: TestClient) -> Dict[str, Any]:
    res = client.post(
        "/api/auth/register",
        json={"email": f"t_{uuid.uuid4().hex[:8]}@apexvox.ai", "password": "longpassword1", "full_name": "Tester"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    client.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    return data


@pytest.fixture
def sent_mail(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """Capture e-mails instead of calling Resend."""
    outbox: List[Dict[str, Any]] = []

    def fake_send_async(to, rendered, **kwargs):
        outbox.append({"to": to, "subject": rendered[0], "html": rendered[1], "text": rendered[2]})

    monkeypatch.setattr(email_service, "send_async", fake_send_async)
    monkeypatch.setattr(email_service, "upsert_newsletter_contact", lambda email, first_name="": True)
    monkeypatch.setattr(email_service, "unsubscribe_newsletter_contact", lambda email: True)
    return outbox


def _wav(tmp_path: Path, name: str = "a.wav", seconds: float = 2.0) -> Path:
    path = tmp_path / name
    create_synthetic_wav(path, [(seconds, 220.0)])
    return path


def _fake_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.groq_service.transcribe_chunk",
        lambda chunk, **kw: [{"id": 0, "start": 0.0, "end": 1.5, "text": "Hola, esto es una prueba de invitado."}],
    )


# ---------------------------------------------------------------------------
# Guests
# ---------------------------------------------------------------------------

def test_guest_transcription_is_ephemeral_and_unanalysed(tmp_path, monkeypatch) -> None:
    _fake_groq(monkeypatch)
    client = _ip_client(f"203.0.113.{uuid.uuid4().int % 200 + 1}")
    with open(_wav(tmp_path), "rb") as fh:
        up = client.post("/api/upload", files=[("files", ("a.wav", fh, "audio/wav"))])
    assert up.status_code == 200, up.text
    sid = up.json()["session_id"]

    res = client.post("/api/transcribe?sync=true", json={"session_id": sid, "diarization_engine": "Mc-Piastri"})
    assert res.status_code == 200, res.text
    job_id = res.json()["job_id"]
    result = client.get(f"/api/jobs/{job_id}/result").json()
    assert result["plan"] == "guest"
    assert result["summa_report"] is None
    assert result["storage_provider"] == "none"
    assert not (settings.OUTPUT_DIR / f"{job_id}_result.json").exists()
    assert not list((settings.UPLOAD_DIR / sid).glob("*")) if (settings.UPLOAD_DIR / sid).exists() else True
    assert client.get(f"/api/jobs/{job_id}/summa").status_code == 402
    assert client.post(f"/api/jobs/{job_id}/minutes", json={"template_type": "consejo"}).status_code == 402


def test_guest_daily_audio_limit(tmp_path, monkeypatch) -> None:
    _fake_groq(monkeypatch)
    monkeypatch.setattr(settings, "GUEST_MAX_AUDIOS_PER_DAY", 2)
    client = _ip_client(f"198.51.100.{uuid.uuid4().int % 200 + 1}")
    files = []
    for i in range(3):
        files.append(_wav(tmp_path, f"g{i}.wav"))
    with open(files[0], "rb") as a, open(files[1], "rb") as b:
        up = client.post("/api/upload", files=[("files", ("g0.wav", a, "audio/wav")), ("files", ("g1.wav", b, "audio/wav"))])
    assert up.status_code == 200
    assert client.post("/api/transcribe?sync=true", json={"session_id": up.json()["session_id"]}).status_code == 200
    with open(files[2], "rb") as c:
        blocked = client.post("/api/upload", files=[("files", ("g2.wav", c, "audio/wav"))])
    assert blocked.status_code == 403
    assert client.get("/api/auth/config").json()["guest_audios_remaining"] == 0


def test_guest_audio_length_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "GUEST_MAX_AUDIO_MINUTES", 0.01)  # 0.6 s
    client = _ip_client("192.0.2.77")
    with open(_wav(tmp_path, seconds=2.0), "rb") as fh:
        res = client.post("/api/upload", files=[("files", ("long.wav", fh, "audio/wav"))])
    assert res.status_code == 413


def test_sessions_belong_to_their_owner(tmp_path) -> None:
    owner = _ip_client("192.0.2.10")
    stranger = _ip_client("192.0.2.11")
    with open(_wav(tmp_path), "rb") as fh:
        sid = owner.post("/api/upload", files=[("files", ("a.wav", fh, "audio/wav"))]).json()["session_id"]
    assert stranger.post("/api/transcribe", json={"session_id": sid}).status_code == 404
    assert stranger.put(f"/api/sessions/{sid}/order", json={"session_id": sid, "file_order": ["a.wav"]}).status_code == 404


# ---------------------------------------------------------------------------
# Account protections
# ---------------------------------------------------------------------------

def test_account_limited_to_monthly_networks(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MAX_IPS_PER_MONTH", 3)
    client = _ip_client("10.0.0.1")
    profile = _register(client)
    auth = {"Authorization": f"Bearer {profile['access_token']}"}
    for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.2"):
        assert TestClient(app).get("/api/auth/me", headers={**auth, "X-Forwarded-For": ip}).status_code == 200
    fourth = TestClient(app).get("/api/auth/me", headers={**auth, "X-Forwarded-For": "10.0.0.4"})
    assert fourth.status_code == 403
    login = TestClient(app).post(
        "/api/auth/login",
        json={"email": profile["email"], "password": "longpassword1"},
        headers={"X-Forwarded-For": "10.0.0.5"},
    )
    assert login.status_code == 403
    usage = TestClient(app).get("/api/auth/security", headers={**auth, "X-Forwarded-For": "10.0.0.1"}).json()
    assert usage == {"used": 3, "limit": 3}
    # IPs are never stored in clear text
    stored = supabase_service._load_db()["users"][profile["user_id"]]["ip_months"]
    assert "10.0.0.1" not in str(stored)


def test_forged_forwarded_header_cannot_spoof_ip() -> None:
    from starlette.requests import Request as StarletteRequest

    from app.api.deps import client_ip

    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")], "client": ("172.18.0.2", 1)}
    assert client_ip(StarletteRequest(scope)) == "203.0.113.9"


def test_voice_profiles_require_account() -> None:
    client = TestClient(app)
    assert client.get("/api/voice-profiles").json() == []
    assert client.post("/api/voice-profiles", data={"name": "X"}, files=[("file", ("a.wav", b"x", "audio/wav"))]).status_code == 401


def test_admin_endpoints_hidden_without_key(monkeypatch) -> None:
    client = TestClient(app)
    assert client.get("/api/metrics/daily").status_code == 404
    assert client.post("/api/metrics/send-report?webhook_url=http://169.254.169.254/").status_code == 404
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "admin-secret")
    assert client.get("/api/metrics/daily", headers={"X-Admin-Key": "wrong"}).status_code == 404
    assert client.get("/api/metrics/daily", headers={"X-Admin-Key": "admin-secret"}).status_code == 200


def test_delete_account_removes_data(sent_mail) -> None:
    client = _ip_client("192.0.2.50")
    profile = _register(client)
    assert client.delete("/api/auth/account").json()["status"] == "deleted"
    assert profile["user_id"] not in supabase_service._load_db()["users"]
    assert client.get("/api/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# E-mail flows
# ---------------------------------------------------------------------------

def test_welcome_and_password_reset(sent_mail) -> None:
    client = _ip_client("192.0.2.60")
    profile = _register(client)
    assert sent_mail[-1]["subject"] in ("Bienvenido a Apex Vox", "Welcome to Apex Vox")

    unknown = client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    assert unknown.status_code == 200 and len(sent_mail) == 1  # no enumeration, no mail

    client.post("/api/auth/password/forgot", json={"email": profile["email"]})
    mail = sent_mail[-1]
    assert "contraseña" in mail["subject"].lower() or "password" in mail["subject"].lower()
    token = mail["text"].split("reset_token=", 1)[1].split()[0]

    reset = client.post("/api/auth/password/reset", json={"token": token, "password": "brandnewpass9"})
    assert reset.status_code == 200
    # Old session revoked, token single-use, new password works
    assert TestClient(app).get("/api/auth/me", headers={"Authorization": f"Bearer {profile['access_token']}"}).status_code == 401
    assert client.post("/api/auth/password/reset", json={"token": token, "password": "anotherpass9"}).status_code == 400
    login = TestClient(app).post("/api/auth/login", json={"email": profile["email"], "password": "brandnewpass9"},
                                 headers={"X-Forwarded-For": "192.0.2.60"})
    assert login.status_code == 200


def test_newsletter_double_opt_in(sent_mail) -> None:
    client = _ip_client("192.0.2.70")
    email = f"news_{uuid.uuid4().hex[:6]}@example.com"
    assert client.post("/api/newsletter/subscribe", json={"email": email, "lang": "en"}).status_code == 200
    confirm_mail = sent_mail[-1]
    assert confirm_mail["to"] == email and "Confirm" in confirm_mail["subject"]
    token = confirm_mail["text"].split("token=", 1)[1].split()[0]

    res = client.get(f"/api/newsletter/confirm?token={token}", follow_redirects=False)
    assert res.headers["location"] == "/?newsletter=confirmed"
    assert "subscribed" in sent_mail[-1]["subject"].lower()
    assert client.get(f"/api/newsletter/confirm?token={token}", follow_redirects=False).headers["location"] == "/?newsletter=invalid"

    unsub_token = supabase_service.newsletter_unsubscribe_token(email)
    bad = client.get(f"/api/newsletter/unsubscribe?email={email}&token=nope", follow_redirects=False)
    assert bad.headers["location"] == "/?newsletter=invalid"
    ok = client.get(f"/api/newsletter/unsubscribe?email={email}&token={unsub_token}", follow_redirects=False)
    assert ok.headers["location"] == "/?newsletter=unsubscribed"


def test_email_templates_render_in_both_languages() -> None:
    for lang in ("es", "en"):
        for rendered in (
            email_service.render_welcome("Ana", lang),
            email_service.render_trial_started("Ana", "2026-11-05T00:00:00+00:00", lang),
            email_service.render_payment_confirmed("Ana", "2026-12-05T00:00:00+00:00", "$30.000 COP", "APEXVOX-1", lang),
            email_service.render_password_reset("Ana", "https://x/?reset_token=t", 60, lang),
            email_service.render_newsletter_confirm("https://x/c", lang),
            email_service.render_newsletter_welcome("https://x/u", lang),
        ):
            subject, html, text = rendered
            assert subject and "<html" in html and text
            assert "<script" not in html


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def test_telegram_linking_one_chat_per_subscription(monkeypatch) -> None:
    sent: List[str] = []
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123:test")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "apexvox_bot")
    monkeypatch.setattr(telegram_service, "send_message", lambda chat_id, text: sent.append(text))
    monkeypatch.setattr(telegram_service, "handle_update_async", telegram_service.handle_update)

    client = _ip_client("192.0.2.80")
    _register(client)
    assert client.post("/api/telegram/link-code").status_code == 403  # free plan
    client.post("/api/billing/subscribe", json={})
    code = client.post("/api/telegram/link-code").json()
    assert code["deep_link"] == f"https://t.me/apexvox_bot?start={code['code']}"

    secret = telegram_service.webhook_secret()
    update = {"message": {"chat": {"id": 555001, "type": "private"}, "from": {"username": "ana"}, "text": f"/start {code['code']}"}}
    assert client.post("/api/telegram/webhook", json=update).status_code == 401  # no secret header
    assert client.post("/api/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": secret}).status_code == 200
    assert client.get("/api/telegram/link").json()["linked"] is True
    assert "Listo" in sent[-1]

    # Second code for the same account is refused (one chat per subscription)
    assert client.post("/api/telegram/link-code").status_code == 403

    # The same chat cannot be linked to another account
    other = _ip_client("192.0.2.81")
    _register(other)
    other.post("/api/billing/subscribe", json={})
    other_code = other.post("/api/telegram/link-code").json()["code"]
    update2 = {"message": {"chat": {"id": 555001, "type": "private"}, "text": f"/start {other_code}"}}
    client.post("/api/telegram/webhook", json=update2, headers={"X-Telegram-Bot-Api-Secret-Token": secret})
    assert "otra cuenta" in sent[-1]

    assert client.delete("/api/telegram/link").json()["linked"] is False


# ---------------------------------------------------------------------------
# Policies, OG and security.txt
# ---------------------------------------------------------------------------

def test_policies_security_txt_and_og() -> None:
    client = TestClient(app)
    for slug in ("privacidad", "terminos", "seguridad"):
        es = client.get(f"/legal/{slug}?lang=es")
        en = client.get(f"/legal/{slug}?lang=en")
        assert es.status_code == 200 and en.status_code == 200
    assert "Ley 1581" in client.get("/legal/privacidad?lang=es").text
    assert client.get("/legal/otra").status_code == 404

    txt = client.get("/.well-known/security.txt").text
    assert txt.startswith("Contact: mailto:") and "Policy:" in txt

    page = client.get("/", headers={"Accept-Language": "en-US"}).text
    assert "/static/og/og-en.png" in page and "{{" not in page
    assert client.get("/static/og/og-es.png").status_code == 200
