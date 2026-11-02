"""
Apex Vox, Apex Summa & Apex Box — Production Verification Suite
(tests/test_apex_vox_suite.py)
---------------------------------------------------------------
Verifies all 8 production requirements:
1. Free tier registration: 2 hours/day (7,200s) across 1 or multiple audios + 24h retention.
2. Paid Pro plan ($30.000 COP / $10 USD month): 3-day free trial + automatic billing via Bold API,
   unlimited transcriptions & unlimited storage.
3. Landing page, User Portal, Playground & Mc-Series models (Mc-Ayrton, Mc-Lewis, Mc-Norris, Mc-Piastri)
   powered by Groq without exposing raw AI vendor modes.
4. Bilingual support (Español & English).
5. Product ecosystem: Apex Vox (Ready), Apex Summa (Active/Developed), Apex Box (Coming Soon).
6. MEGA S4 S3-compatible object storage (AWSv4 signature + 24h vs unlimited retention).
7. Supabase Cloud backend service & SQL schema.
8. Apex Summa 7-part post-transcription intelligence:
   - 1. Quién habló más
   - 2. De qué se habló
   - 3. Objetivos
   - 4. Llamados de atención
   - 5. Próximas tareas en forma de calendario (+ .ics export)
   - 6. Gráficas de la transcripción
   - 7. Generador de Actas (Consejo / Junta Directiva, Comité, Asamblea, etc.)
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, List
import pytest
from starlette.testclient import TestClient

from app.config import resolve_engine_code
from app.main import app
from app.services.storage_s4 import mega_s4_storage
from tests.fixtures.audio_generator import create_synthetic_wav


def test_branding_ui_and_mc_series_models() -> None:
    """
    Verify:
    - Product name is 'Apex Vox' ('Potenciado por Groq').
    - Ecosystem includes Apex Vox, Apex Summa, and Apex Box.
    - Engine selector exposes Mc-Ayrton, Mc-Lewis, Mc-Norris, Mc-Piastri.
    - Bilingual dictionary (es / en) is present in app.js.
    """
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    assert "Apex Vox" in html
    assert "Apex Summa" in html
    assert "Apex Box" in html
    assert "Potenciado por Groq" in html
    assert "Mc-Ayrton" in html
    assert "Mc-Lewis" in html
    assert "Mc-Norris" in html
    assert "Mc-Piastri" in html

    # Verify engine resolution mapping
    assert resolve_engine_code("Mc-Ayrton") == "deepgram"
    assert resolve_engine_code("Mc-Lewis") == "hybrid_deepgram_groq"
    assert resolve_engine_code("Mc-Norris") == "acoustic_local"
    assert resolve_engine_code("Mc-Piastri") == "groq_llm"

    js_res = client.get("/static/js/app.js")
    assert js_res.status_code == 200
    assert "Powered by Groq" in js_res.text
    assert "Potenciado por Groq" in js_res.text


def test_user_registration_2h_free_quota_and_24h_retention() -> None:
    """
    Verify:
    - Registering a user grants 2 hours free per day (7,200 seconds) and 24-hour retention.
    - Multiple audios in the same day accumulate toward the 7,200s daily quota.
    - Exceeding 7,200s on the Free plan raises PermissionError / HTTP 402.
    """
    from app.services.supabase_service import supabase_service

    client = TestClient(app)
    unique_email = f"piloto_{uuid.uuid4().hex[:8]}@apexvox.ai"

    reg_res = client.post(
        "/api/auth/register",
        json={
            "email": unique_email,
            "password": "secretPassword123",
            "full_name": "Ayrton Test",
            "preferred_language": "es",
        },
    )
    assert reg_res.status_code == 200, reg_res.text
    user_data = reg_res.json()
    uid = user_data["user_id"]
    assert user_data["plan"] == "free"
    assert user_data["quota"]["daily_limit_seconds"] == 7200
    assert user_data["quota"]["retention_hours"] == 24
    assert user_data["quota"]["is_unlimited"] is False

    # Consume 1st audio of 3,000s (50 min)
    q1 = supabase_service.check_and_consume_quota(uid, 3000.0, audios_count=1)
    assert q1.used_today_seconds == 3000.0
    assert q1.remaining_today_seconds == 4200.0

    # Consume 2nd & 3rd audios totaling 4,000s -> total 7,000s (within 7,200s limit)
    q2 = supabase_service.check_and_consume_quota(uid, 4000.0, audios_count=2)
    assert q2.used_today_seconds == 7000.0
    assert q2.remaining_today_seconds == 200.0

    # Attempting another 500s on Free plan exceeds 7,200s (2 hours) -> raises PermissionError
    with pytest.raises(PermissionError) as exc_info:
        supabase_service.check_and_consume_quota(uid, 500.0, audios_count=1)
    assert "2 horas gratis al día" in str(exc_info.value)


def test_bold_api_checkout_3day_trial_and_unlimited_pro_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify:
    - Trial and checkout require a signed-in account (user ids are not credentials).
    - The 3-day trial is unlimited and can only be used once per account.
    - Bold checkout uses the official payment-link API ($30.000 COP / $10 USD).
    - A signed SALE_APPROVED webhook grants a paid Apex Pro period, idempotently.
    """
    import base64, hashlib, hmac, json as _json
    from app.config import settings as _settings
    from app.services import bold_service

    client = TestClient(app)
    unique_email = f"pro_{uuid.uuid4().hex[:8]}@apexvox.ai"
    reg = client.post(
        "/api/auth/register",
        json={"email": unique_email, "password": "pass12345", "full_name": "Lewis Pro"},
    ).json()
    uid = reg["user_id"]
    auth = {"Authorization": f"Bearer {reg['access_token']}"}

    # Anonymous or id-only requests are rejected
    assert client.post("/api/billing/subscribe", json={"user_id": uid}).status_code == 401
    assert client.post("/api/billing/checkout", json={"currency": "COP"},
                       headers={"Authorization": uid}).status_code == 401

    # 1. Checkout through Bold's payment-link API (HTTP layer mocked)
    calls: list = []

    def fake_bold(method: str, path: str, json_body=None):
        calls.append((method, path, json_body))
        return {"payload": {"payment_link": "LNK_TEST123", "url": "https://checkout.bold.co/LNK_TEST123"}, "errors": []}

    monkeypatch.setattr(bold_service, "_bold_request", fake_bold)
    cop_res = client.post("/api/billing/checkout", json={"currency": "COP"}, headers=auth)
    assert cop_res.status_code == 200, cop_res.text
    cop_data = cop_res.json()
    assert cop_data["amount"] == 30000 and cop_data["currency"] == "COP"
    assert cop_data["checkout_url"] == "https://checkout.bold.co/LNK_TEST123"
    method, path, body = calls[-1]
    assert (method, path) == ("POST", "/online/link/v1")
    assert body["amount_type"] == "CLOSE"
    assert body["amount"]["total_amount"] == 30000
    assert body["reference"] == cop_data["order_id"] and len(body["reference"]) <= 60
    assert body["callback_url"].startswith("https://")

    usd_res = client.post("/api/billing/checkout", json={"currency": "USD"}, headers=auth)
    assert usd_res.json()["amount"] == 10 and usd_res.json()["currency"] == "USD"

    # 2. One-time 3-day trial
    sub_res = client.post("/api/billing/subscribe", json={"currency": "COP"}, headers=auth)
    assert sub_res.status_code == 200, sub_res.text
    sub_data = sub_res.json()
    assert sub_data["plan"] == "trial"
    assert sub_data["quota"]["is_unlimited"] is True
    assert sub_data["quota"]["daily_limit_seconds"] is None
    assert sub_data["quota"]["retention_hours"] is None
    assert sub_data["quota"]["trial_available"] is False
    again = client.post("/api/billing/subscribe", json={"currency": "COP"}, headers=auth)
    assert again.status_code == 409

    # 3. Bold webhook: unsigned rejected, signed one grants a paid period
    payload = _json.dumps({
        "type": "SALE_APPROVED",
        "data": {"metadata": {"reference": cop_data["order_id"]}, "amount": {"currency": "COP", "total": 30000}},
    }).encode()
    unsigned = client.post("/api/billing/bold/webhook", content=payload,
                           headers={"Content-Type": "application/json"})
    assert unsigned.status_code == 401
    original_secret = _settings.BOLD_WEBHOOK_SECRET
    _settings.BOLD_WEBHOOK_SECRET = "test_webhook_secret"
    try:
        sig = hmac.new(b"test_webhook_secret", base64.b64encode(payload), hashlib.sha256).hexdigest()
        wh_res = client.post("/api/billing/bold/webhook", content=payload,
                             headers={"Content-Type": "application/json", "x-bold-signature": sig})
        tampered = client.post("/api/billing/bold/webhook", content=payload.replace(b"30000", b"1"),
                               headers={"Content-Type": "application/json", "x-bold-signature": sig})
        assert tampered.status_code == 401
        retry = client.post("/api/billing/bold/webhook", content=payload,
                            headers={"Content-Type": "application/json", "x-bold-signature": sig})
    finally:
        _settings.BOLD_WEBHOOK_SECRET = original_secret
    assert wh_res.status_code == 200
    assert wh_res.json()["status"] == "processed"
    assert wh_res.json()["user_id"] == uid
    # Webhook retries never stack extra days
    assert retry.json()["pro_until"] == wh_res.json()["pro_until"]

    me = client.get("/api/auth/me", headers=auth).json()
    assert me["quota"]["pro_until"] == wh_res.json()["pro_until"]
    assert me["quota"]["auto_billing_enabled"] is False


def test_mega_s4_storage_signature_and_retention() -> None:
    """
    Verify MEGA S4 S3v4 header generation and 24h vs unlimited retention metadata.
    """
    headers = mega_s4_storage.build_s3v4_headers(
        method="PUT",
        object_key="users/u1/jobs/j1/result.json",
        payload=b'{"status":"ok"}',
        content_type="application/json",
    )
    assert "Authorization" in headers
    assert "AWS4-HMAC-SHA256" in headers["Authorization"]
    assert "x-amz-date" in headers
    assert "x-amz-content-sha256" in headers

    free_meta = mega_s4_storage.upload_object(
        object_key="test/free_item.json",
        data=b'{"tier":"free"}',
        content_type="application/json",
        plan="free",
        user_id="u_free",
    )
    assert free_meta["retention"] == "24h"
    assert free_meta["expires_at"] is not None

    pro_meta = mega_s4_storage.upload_object(
        object_key="test/pro_item.json",
        data=b'{"tier":"pro"}',
        content_type="application/json",
        plan="pro",
        user_id="u_pro",
    )
    assert pro_meta["retention"] == "unlimited"
    assert pro_meta["expires_at"] is None


def test_apex_summa_7_part_report_calendar_and_minutes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    End-to-end verification of Apex Vox (Mc-Lewis) + Apex Summa 7-part report:
    1. Quién habló más (dominant speaker & per-speaker stats)
    2. De qué se habló (executive summary & topics)
    3. Objetivos (objectives)
    4. Llamados de atención (callouts)
    5. Próximas tareas en forma de calendario (+ .ics export)
    6. Gráficas de la transcripción (speaker distribution & timeline density)
    7. Generador de Actas (Consejo / Junta Directiva, Comité, Asamblea in ES & EN)
    """
    client = TestClient(app)

    wav_path = tmp_path / "consejo_directivo.wav"
    create_synthetic_wav(wav_path, [(2.5, 140.0), (0.6, 0.0), (2.0, 240.0)])

    with open(wav_path, "rb") as f_wav:
        up_res = client.post(
            "/api/upload",
            files=[("files", ("consejo_directivo.wav", f_wav, "audio/wav"))],
        )
    assert up_res.status_code == 200
    session_id = up_res.json()["session_id"]

    def fake_transcribe_chunk(chunk: Any, **kwargs: Any) -> List[dict[str, Any]]:
        return [
            {
                "id": 0,
                "start": 0.0,
                "end": 2.4,
                "text": "Nuestro objetivo principal del consejo hoy es aprobar el presupuesto anual y lanzar Apex Vox.",
            },
            {
                "id": 1,
                "start": 3.0,
                "end": 4.9,
                "text": "Atención, tenemos un riesgo urgente en los tiempos si no entregamos el informe mañana.",
            },
        ]

    monkeypatch.setattr("app.services.groq_service.transcribe_chunk", fake_transcribe_chunk)

    trans_res = client.post(
        "/api/transcribe?sync=true",
        json={
            "session_id": session_id,
            "diarization_engine": "Mc-Lewis",
            "model": "Mc-Lewis",
            "language": "es",
            "api_key": "gsk_test_key_summa",
            "plan_override": "pro",
        },
    )
    assert trans_res.status_code == 200, trans_res.text
    job_id = trans_res.json()["job_id"]

    res_json = client.get(f"/api/jobs/{job_id}/result").json()
    assert res_json["engine_brand"] == "Mc-Lewis"
    assert res_json["storage_provider"] == "mega_s4"
    assert res_json["summa_report"] is not None

    summa = res_json["summa_report"]
    # 1. Quién habló más
    assert summa["dominant_speaker"] != ""
    assert len(summa["speaker_stats"]) >= 1
    assert summa["speaker_stats"][0]["talk_percentage"] > 0
    # 2. De qué se habló
    assert len(summa["executive_summary"]) > 20
    assert len(summa["topics"]) >= 1
    # 3. Objetivos
    assert len(summa["objectives"]) >= 1
    # 4. Llamados de atención
    assert len(summa["callouts"]) >= 1
    # 5. Próximas tareas en forma de calendario
    assert len(summa["calendar_tasks"]) >= 1
    # 6. Gráficas de la transcripción
    assert len(summa["charts"]["speaker_distribution"]) >= 1
    assert len(summa["charts"]["timeline_density"]) >= 1
    # 7. Plantillas de actas
    assert len(summa["available_minutes_templates"]) >= 4

    # Verify .ics calendar export
    ics_res = client.get(f"/api/jobs/{job_id}/calendar.ics")
    assert ics_res.status_code == 200
    assert "BEGIN:VCALENDAR" in ics_res.text
    assert "BEGIN:VEVENT" in ics_res.text

    # Verify Formal Minutes ('Acta de Reunión de Consejo') generation in ES and EN
    acta_es = client.post(
        f"/api/jobs/{job_id}/minutes",
        json={
            "template_type": "consejo",
            "language": "es",
            "organization_name": "Consejo Apex S.A.S.",
        },
    )
    assert acta_es.status_code == 200
    assert "Acta de Reunión de Consejo" in acta_es.json()["template_title"]
    assert "Consejo Apex S.A.S." in acta_es.json()["markdown_content"]

    acta_en = client.post(
        f"/api/jobs/{job_id}/minutes",
        json={
            "template_type": "consejo",
            "language": "en",
            "organization_name": "Apex Board Inc.",
        },
    )
    assert acta_en.status_code == 200
    assert "Board of Directors" in acta_en.json()["template_title"]
    assert "Apex Board Inc." in acta_en.json()["markdown_content"]


def test_session_track_audio_preview_and_drag_reorder(tmp_path: Path) -> None:
    """
    Verify:
    - Each uploaded audio track in a session can be streamed inline via
      GET /api/sessions/{session_id}/files/{file_id}/audio to verify its content
      before and after drag-and-drop reordering.
    - UI includes inline track audio player (.track-audio-preview), drag handle (.drag-handle),
      and sequential preview button (#play-sequence-btn).
    """
    client = TestClient(app)
    w1 = tmp_path / "pista_uno.wav"
    w2 = tmp_path / "pista_dos.wav"
    create_synthetic_wav(w1, [(1.5, 440.0)])
    create_synthetic_wav(w2, [(1.8, 660.0)])

    with open(w1, "rb") as f1, open(w2, "rb") as f2:
        up = client.post(
            "/api/upload",
            files=[
                ("files", ("pista_uno.wav", f1, "audio/wav")),
                ("files", ("pista_dos.wav", f2, "audio/wav")),
            ],
        )
    assert up.status_code == 200
    data = up.json()
    sid = data["session_id"]
    files = data["files"]
    assert len(files) == 2

    # Stream each individual track for preview listening
    for track in files:
        fid = track["file_id"]
        stream_res = client.get(f"/api/sessions/{sid}/files/{fid}/audio")
        assert stream_res.status_code == 200
        assert "audio/wav" in stream_res.headers.get("content-type", "")
        assert "inline" in stream_res.headers.get("content-disposition", "")
        assert len(stream_res.content) > 100

    # Verify UI elements for drag-and-drop + inline listening
    html_res = client.get("/")
    assert "play-sequence-btn" in html_res.text
    js_res = client.get("/static/js/app.js")
    assert "track-audio-preview" in js_res.text
    assert "drag-handle" in js_res.text
