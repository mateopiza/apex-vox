"""
Transcript Export Routes (app/api/routes_export.py)
---------------------------------------------------
Provides endpoints to download completed transcripts in TXT, SRT, VTT, JSON,
CSV, or Markdown (.md) formats.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.deps import require_job_media
from app.services.exporter import format_transcript_export
from app.services.job_manager import job_manager

router = APIRouter(prefix="/api", tags=["Export"])


@router.get("/jobs/{job_id}/export/{fmt}")
async def export_job_transcript(fmt: str, job_id: str = Depends(require_job_media)) -> Response:
    """Download the formatted transcript for a completed job."""
    result = job_manager.get_job_result(job_id)
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
