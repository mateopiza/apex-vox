"""Sending a result by email: summary, share link and PDF; others only with Apex Pro; daily cap.
Resend is replaced by a mock transport: no real email leaves the test."""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import List, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.config import settings
from app.main import app
from app.models.schemas import ApexSummaReport, DiarizedSegment, SpeakerAnalyticsItem, TranscriptionResult
from app.services import email_service, share_links
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service

PAST = "2020-01-01T00:00:00+00:00"
SUMMARY = "Acordamos cerrar el presupuesto el viernes."


class FakeResend:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.sent: List[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.resend.com"
        self.sent.append(json.loads(request.content))
        return httpx.Response(self.status, json={"id": "email_test"})


@pytest.fixture
def resend(monkeypatch: pytest.MonkeyPatch):
    def install(status: int = 200) -> FakeResend:
        fake = FakeResend(status)
        real_client = httpx.Client
        monkeypatch.setattr(email_service.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(fake), **kw))
        monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_placeholder")
        return fake

    deps._throttle_hits.clear()
    yield install
    deps._throttle_hits.clear()


def _client(pro: bool = False) -> TestClient:
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    profile = supabase_service.register_user(email, "password123", full_name="Ana Pérez")
    if pro:
        db = supabase_service._load_db()
        db["users"][profile.user_id].update(plan="pro", pro_until="2099-01-01T00:00:00+00:00")
        supabase_service._save_db(db)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {profile.access_token}"})
    client.user_id, client.email = profile.user_id, email
    return client


def _job(owner: TestClient, plan: str = "free", locked: bool = True, expires_at: Optional[str] = None) -> str:
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    stats = [SpeakerAnalyticsItem(speaker="Ana", talk_percentage=70.0), SpeakerAnalyticsItem(speaker="Luis", talk_percentage=30.0)]
    report = ApexSummaReport(job_id=job_id, generated_at="2026-11-15T10:00:00+00:00", language="es", is_locked=locked,
                             speaker_stats=stats, objectives=[] if locked else ["Cerrar el presupuesto"],
                             executive_summary="" if locked else SUMMARY)
    seg = DiarizedSegment(id=0, start=1, end=3, speaker="Ana", text="Hola.", start_formatted="00:00:01",
                          end_formatted="00:00:03", source_file="comite.mp3", file_order_index=0)
    result = TranscriptionResult(job_id=job_id, session_id="s", user_id=owner.user_id, plan=plan, language="es",
                                 segments=[seg], total_duration_formatted="00:00:03", file_order=["comite.mp3"],
                                 expires_at=expires_at, summa_report=report)
    (settings.OUTPUT_DIR / f"{job_id}_result.json").write_text(result.model_dump_json(), encoding="utf-8")
    job_manager._job_owners[job_id] = owner.user_id
    return job_id


def _send(client: TestClient, job_id: str, recipients: list, **extra) -> httpx.Response:
    return client.post(f"/api/jobs/{job_id}/email", json={"recipients": recipients, **extra})


# Who can send to whom ------------------------------------------------------------------------------


def test_free_account_sends_the_preview_to_itself(resend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_manager, "get_or_build_summa", lambda *a, **k: None)
    fake = resend()
    owner = _client()
    job_id = _job(owner)
    res = _send(owner, job_id, [owner.email.upper()], language="es")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sent"] == 1 and body["failed"] == [] and "/s/" in body["share_url"]

    email = fake.sent[0]
    assert email["to"] == [owner.email.upper()] and email["reply_to"] == owner.email
    assert "Ana Pérez te compartió" in email["subject"]
    assert body["share_url"].replace("&", "&amp;") in email["html"] and "Ana: 70.0%" in email["text"]
    assert SUMMARY not in email["html"]  # Gratis: vista previa
    token = body["share_url"].split("/s/", 1)[1].split("?", 1)[0]
    assert share_links.resolve(token)["job_id"] == job_id
    if body["attached_pdf"]:
        pdf = email["attachments"][0]
        assert pdf["filename"].endswith(".pdf") and base64.b64decode(pdf["content"]).startswith(b"%PDF")


def test_free_account_cannot_send_to_others(resend) -> None:
    fake = resend()
    owner = _client()
    res = _send(owner, _job(owner), [owner.email, "otra@example.com"])
    assert res.status_code == 402 and "Apex Pro" in res.json()["detail"]
    assert fake.sent == []


def test_pro_account_sends_the_full_summary_to_others(resend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_manager, "get_or_build_summa", lambda *a, **k: None)
    fake = resend()
    owner = _client(pro=True)
    job_id = _job(owner, plan="pro", locked=False)
    existing = share_links.create_or_update(job_id, owner.user_id, include_audio=True)
    res = _send(owner, job_id, ["a@example.com, b@example.com", "A@example.com"],
                message="Hola equipo,\n<script>x</script>", language="en")
    assert res.status_code == 200, res.text
    assert res.json()["sent"] == 2 and len(fake.sent) == 2  # sin duplicados, uno por destinatario
    assert {tuple(e["to"]) for e in fake.sent} == {("a@example.com",), ("b@example.com",)}
    email = fake.sent[0]
    assert SUMMARY in email["html"] and "Cerrar el presupuesto" in email["html"]
    assert "&lt;script&gt;" in email["html"] and "<script>" not in email["html"]
    assert "Ana Pérez shared" in email["subject"] and email["reply_to"] == owner.email
    assert existing["token"] in res.json()["share_url"]  # usa el enlace existente
    assert share_links.get_for_job(job_id, owner.user_id)["include_audio"] is True


def test_only_the_owner_can_send(resend) -> None:
    resend()
    owner, stranger = _client(pro=True), _client(pro=True)
    job_id = _job(owner)
    assert _send(stranger, job_id, [stranger.email]).status_code == 404
    assert _send(TestClient(app), job_id, ["a@example.com"]).status_code == 401


# Validation, expiry and limits -----------------------------------------------------------------------


@pytest.mark.parametrize("recipients, detail", [
    ([], "al menos un correo"),
    ([f"p{i}@example.com" for i in range(11)], "máximo 10"),
    (["no-es-un-correo"], "Correo inválido"),
])
def test_recipients_are_validated(resend, recipients, detail) -> None:
    fake = resend()
    owner = _client(pro=True)
    res = _send(owner, _job(owner), recipients)
    assert res.status_code == 400 and detail in res.json()["detail"]
    assert fake.sent == []


def test_expired_result_is_410_and_does_not_count(resend, monkeypatch: pytest.MonkeyPatch) -> None:
    resend()
    monkeypatch.setattr(settings, "EMAIL_SHARE_DAILY_LIMIT", 1)
    owner = _client()
    assert _send(owner, _job(owner, expires_at=PAST), [owner.email]).status_code == 410
    monkeypatch.setattr(job_manager, "get_or_build_summa", lambda *a, **k: None)
    assert _send(owner, _job(owner), [owner.email]).status_code == 200


def test_daily_cap_counts_recipients(resend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_manager, "get_or_build_summa", lambda *a, **k: None)
    fake = resend()
    monkeypatch.setattr(settings, "EMAIL_SHARE_DAILY_LIMIT", 3)
    owner = _client(pro=True)
    job_id = _job(owner)
    assert _send(owner, job_id, ["a@example.com", "b@example.com"]).status_code == 200
    capped = _send(owner, job_id, ["c@example.com", "d@example.com"])
    assert capped.status_code == 429 and "por día" in capped.json()["detail"]
    assert len(fake.sent) == 2
    assert _send(owner, job_id, ["c@example.com"]).status_code == 200
    # El tope es por día: la limpieza periódica no lo borra a la hora.
    key = f"email-share:{owner.user_id}"
    deps._throttle_hits[key] = [time.monotonic() - 7200] * 3
    deps.prune_throttle()
    assert key in deps._throttle_hits


def test_failed_deliveries_are_reported_and_given_back(resend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_manager, "get_or_build_summa", lambda *a, **k: None)
    resend(status=500)
    monkeypatch.setattr(settings, "EMAIL_SHARE_DAILY_LIMIT", 2)
    owner = _client(pro=True)
    job_id = _job(owner)
    res = _send(owner, job_id, ["a@example.com", "b@example.com"])
    assert res.status_code == 502
    assert deps._throttle_hits.get(f"email-share:{owner.user_id}", []) == []


def test_without_resend_it_answers_503() -> None:
    owner = _client()
    res = _send(owner, _job(owner), [owner.email])
    assert res.status_code == 503


def test_send_email_encodes_attachments_and_reply_to(resend) -> None:
    fake = resend()
    ok = email_service.send_email(
        "x@example.com", ("Asunto", "<p>hola</p>", "hola"),
        attachments=[{"filename": "informe.pdf", "content": b"%PDF-1.7 data"}], reply_to="ana@example.com",
    )
    assert ok
    sent = fake.sent[0]
    assert sent["reply_to"] == "ana@example.com"
    assert sent["attachments"] == [{"filename": "informe.pdf", "content": base64.b64encode(b"%PDF-1.7 data").decode()}]
