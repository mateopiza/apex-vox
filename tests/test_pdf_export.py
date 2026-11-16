"""PDF export: the owner (or a download link) gets the report, with the same plan rules as the summary
and the minutes, drawn from the template the share page uses."""

from __future__ import annotations

import sys
import uuid
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.config import settings
from app.main import app
from app.models.schemas import (
    ApexSummaReport,
    DiarizedSegment,
    SpeakerAnalyticsItem,
    TimelineDensityPoint,
    TopicItem,
    TranscriptionChartsData,
    TranscriptionResult,
)
from app.services import pdf_export
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service

PAST = "2020-01-01T00:00:00+00:00"
SUMMARY = "Acordamos cerrar el presupuesto el viernes."


def _weasyprint_usable() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


needs_weasyprint = pytest.mark.skipif(not _weasyprint_usable(), reason="WeasyPrint or Pango not installed")


def _client(pro: bool = False) -> TestClient:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    if pro:
        db = supabase_service._load_db()
        db["users"][profile.user_id].update(plan="pro", pro_until="2099-01-01T00:00:00+00:00")
        supabase_service._save_db(db)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {profile.access_token}"})
    client.user_id = profile.user_id
    return client


def _job(owner: Optional[TestClient], plan: str = "free", locked: bool = False, expires_at: Optional[str] = None) -> str:
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    stats = [SpeakerAnalyticsItem(speaker="Ana", talk_percentage=70.0, word_count=20, turn_count=2),
             SpeakerAnalyticsItem(speaker="Luis", talk_percentage=30.0, word_count=8, turn_count=1)]
    timeline = [TimelineDensityPoint(bucket_label="00:00 - 00:30", start_sec=0, end_sec=30, word_count=12, active_speakers=2)]
    report = ApexSummaReport(
        job_id=job_id, generated_at="2026-11-15T10:00:00+00:00", language="es", is_locked=locked, speaker_stats=stats,
        dominant_speaker="Ana", dominant_speaker_pct=70.0, executive_summary="" if locked else SUMMARY,
        topics=[] if locked else [TopicItem(title="Presupuesto", summary="Se revisó.")],
        charts=TranscriptionChartsData(speaker_distribution=stats, timeline_density=timeline),
    )
    seg = DiarizedSegment(id=0, start=1, end=3, speaker="Ana", text="Hola equipo, ¿empezamos?", start_formatted="00:00:01",
                          end_formatted="00:00:03", source_file="reunion.mp3", file_order_index=0)
    result = TranscriptionResult(
        job_id=job_id, session_id="s", user_id=owner.user_id if owner else None, plan=plan, language="es",
        segments=[seg], full_text="Hola equipo.", total_duration_formatted="00:00:03", engine_brand="Mc-Lewis",
        file_order=["reunion.mp3"], expires_at=expires_at, summa_report=None if plan == "guest" else report,
    )
    if plan == "guest":
        job_manager._results[job_id] = result
        job_manager._job_owners[job_id] = supabase_service.guest_key("testclient")
    else:
        (settings.OUTPUT_DIR / f"{job_id}_result.json").write_text(result.model_dump_json(), encoding="utf-8")
        job_manager._job_owners[job_id] = owner.user_id
    return job_id


# Access ----------------------------------------------------------------------------------------------


@needs_weasyprint
def test_owner_downloads_a_real_pdf() -> None:
    owner = _client(pro=True)
    res = owner.get(f"/api/jobs/{_job(owner, plan='pro')}/export/pdf")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert "attachment" in res.headers["content-disposition"]
    assert res.content.startswith(b"%PDF") and len(res.content) > 2000


@needs_weasyprint
def test_download_link_works_and_others_get_404() -> None:
    owner, stranger, visitor = _client(), _client(), TestClient(app)
    job_id = _job(owner)
    assert stranger.get(f"/api/jobs/{job_id}/export/pdf").status_code == 404
    assert visitor.get(f"/api/jobs/{job_id}/export/pdf").status_code == 404
    token = deps.media_token(f"job:{job_id}")
    assert visitor.get(f"/api/jobs/{job_id}/export/pdf", params={"t": token}).status_code == 200
    other = _job(owner)
    assert visitor.get(f"/api/jobs/{other}/export/pdf", params={"t": token}).status_code == 404


def test_expired_result_is_410() -> None:
    owner = _client()
    job_id = _job(owner, expires_at=PAST)
    res = owner.get(f"/api/jobs/{job_id}/export/pdf")
    assert res.status_code == 410 and "venció" in res.json()["detail"]


def test_missing_weasyprint_answers_503(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client()
    monkeypatch.setitem(sys.modules, "weasyprint", None)  # import falla como en un servidor sin la librería
    res = owner.get(f"/api/jobs/{_job(owner)}/export/pdf")
    assert res.status_code == 503 and "PDF" in res.json()["detail"]


def test_the_renderer_never_fetches_urls() -> None:
    with pytest.raises(ValueError):
        pdf_export._no_fetch("http://169.254.169.254/latest/meta-data/")


# Plan rules (same as the summary and the minutes) ----------------------------------------------------


def test_free_owner_gets_the_preview_without_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    built = []
    monkeypatch.setattr(job_manager, "get_or_build_summa", lambda *a, **k: built.append(a))
    monkeypatch.setattr(pdf_export, "render_pdf", lambda html: html.encode("utf-8"))
    owner = _client()
    html = owner.get(f"/api/jobs/{_job(owner, locked=True)}/export/pdf", params={"lang": "es"}).text
    assert "Ana lideró la conversación" in html and "<svg" in html  # oradores y gráficas SVG
    assert SUMMARY not in html and "7. Acta" not in html and "incluidos en Apex Pro" in html
    assert "Hola equipo, ¿empezamos?" in html
    assert built == []  # sin Apex Pro no se genera nada


def test_pro_owner_gets_the_full_report_and_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    built = []
    monkeypatch.setattr(job_manager, "get_or_build_summa", lambda result, lang=None: built.append(lang))
    monkeypatch.setattr(pdf_export, "render_pdf", lambda html: html.encode("utf-8"))
    owner = _client(pro=True)
    html = owner.get(f"/api/jobs/{_job(owner, plan='pro')}/export/pdf", params={"lang": "es"}).text
    assert SUMMARY in html and "7. Acta" in html and "incluidos en Apex Pro" not in html
    assert built == ["es"]  # como al abrir el resumen en la app


def test_guest_pdf_has_the_transcript_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_export, "render_pdf", lambda html: html.encode("utf-8"))
    job_id = _job(None, plan="guest")
    html = TestClient(app).get(f"/api/jobs/{job_id}/export/pdf", params={"lang": "en"}).text
    assert "Hola equipo, ¿empezamos?" in html and "Transcript" in html
    assert "Apex Summa" not in html and "Minutes" not in html


def test_text_is_escaped(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client()
    job_id = _job(owner)
    result = job_manager.get_job_result(job_id)
    result.segments[0].text = "<img src=http://evil.example/x>"
    html = pdf_export.report_html(result, "es")
    assert "<img" not in html and "&lt;img" in html
