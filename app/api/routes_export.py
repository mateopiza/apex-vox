"""
Transcript Export Routes (app/api/routes_export.py)
---------------------------------------------------
Provides endpoints to download completed transcripts in TXT, SRT, VTT, JSON,
CSV, or Markdown (.md) formats.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import require_job_media, run_heavy
from app.services.exporter import format_transcript_export
from app.errors import EXPIRED_RESULT
from app.services import pdf_export
from app.services.job_manager import job_manager

router = APIRouter(prefix="/api", tags=["Export"])


@router.get("/jobs/{job_id}/export/pdf")
async def export_job_pdf(
    job_id: str = Depends(require_job_media),
    lang: str = Query(default="", description="Language of the report: es or en (default: the transcript's)"),
) -> Response:
    """
    The report as a PDF: figures, Apex Summa summary and charts, minutes and transcript. What it
    includes follows the same plan rules as the summary and the minutes.
    """
    pdf = await run_heavy(_job_pdf, job_id, lang)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{job_id}_apex_vox.pdf"'},
    )


def _job_pdf(job_id: str, lang: str) -> bytes:
    result = job_manager.get_job_result(job_id)
    if not result and job_manager.is_expired(job_id):
        raise HTTPException(status_code=410, detail=EXPIRED_RESULT)
    if not result:
        raise HTTPException(status_code=404, detail=f"Transcripción '{job_id}' no encontrada.")
    language = lang if lang in ("es", "en") else (result.language if result.language in ("es", "en") else "es")
    try:
        return pdf_export.result_pdf(result, language)
    except pdf_export.PdfUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/export/{fmt}")
def export_job_transcript(fmt: str, job_id: str = Depends(require_job_media)) -> Response:
    """Download the formatted transcript for a completed job."""
    result = job_manager.get_job_result(job_id)
    if not result and job_manager.is_expired(job_id):
        raise HTTPException(status_code=410, detail=EXPIRED_RESULT)
    if not result:
        raise HTTPException(
            status_code=404, detail=f"Transcripción '{job_id}' no encontrada."
        )

    try:
        content, media_type, ext = format_transcript_export(result, fmt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = f"{job_id}_transcript.{ext}"
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
