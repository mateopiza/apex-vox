"""
File Upload & Session Ordering Routes (app/api/routes_upload.py)
----------------------------------------------------------------
Handles multi-file audio upload (MP3, OGG, WAV, M4A, FLAC, WEBM), metadata
probing, interactive reordering, track removal, and audio preview streaming.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.models.schemas import ReorderRequest, UploadResponse
from app.services.job_manager import job_manager

logger = logging.getLogger("app.api.routes_upload")
router = APIRouter(prefix="/api", tags=["Upload & Ordering"])


@router.post("/upload", response_model=UploadResponse)
async def upload_audio_files(
    files: List[UploadFile] = File(..., description="Audio files (MP3, OGG, WAV, etc.)"),
    session_id: Optional[str] = Form(default=None),
) -> UploadResponse:
    """
    Upload one or more audio files, probe their duration/format/size,
    and register them in an ordered session.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No se recibieron archivos de audio.")

    session = job_manager.create_or_get_session(session_id)

    for upload in files:
        filename = upload.filename or "audio.mp3"
        content = await upload.read()
        try:
            job_manager.add_file_to_session(
                session_id=session.session_id,
                filename=filename,
                content=content,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Unexpected error uploading %s", filename)
            raise HTTPException(
                status_code=500, detail=f"Error al procesar '{filename}': {exc}"
            ) from exc

    ordered_files = job_manager.get_session_files(session.session_id)
    return UploadResponse(session_id=session.session_id, files=ordered_files)


@router.get("/sessions/{session_id}", response_model=UploadResponse)
async def get_session_files(session_id: str) -> UploadResponse:
    """Retrieve the current ordered list of audio files in a session."""
    try:
        files = job_manager.get_session_files(session_id)
        return UploadResponse(session_id=session_id, files=files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/sessions/{session_id}/order", response_model=UploadResponse)
async def update_session_order(session_id: str, payload: ReorderRequest) -> UploadResponse:
    """Update the processing sequence order of uploaded audio files."""
    try:
        files = job_manager.reorder_session_files(session_id, payload.file_order)
        return UploadResponse(session_id=session_id, files=files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}/files/{file_id}", response_model=UploadResponse)
async def delete_session_file(session_id: str, file_id: str) -> UploadResponse:
    """Remove a specific audio track from the session."""
    try:
        files = job_manager.remove_file_from_session(session_id, file_id)
        return UploadResponse(session_id=session_id, files=files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


_AUDIO_MIME_MAP = {
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}


@router.get("/sessions/{session_id}/files/{file_id}/audio")
async def stream_session_track_audio(session_id: str, file_id: str) -> FileResponse:
    """Stream an individual uploaded audio file inline for interactive preview in the UI."""
    session = job_manager.get_session(session_id)
    if not session or file_id not in session.tracks:
        raise HTTPException(status_code=404, detail="Archivo de audio no encontrado.")
    track = session.tracks[file_id]
    if not track.file_path.exists():
        raise HTTPException(status_code=404, detail="Archivo físico no encontrado.")
    ext = track.file_path.suffix.lower()
    media_type = _AUDIO_MIME_MAP.get(ext, "audio/mpeg")
    return FileResponse(
        path=track.file_path,
        media_type=media_type,
        filename=track.filename,
        content_disposition_type="inline",
    )
