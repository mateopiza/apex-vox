"""
File Upload & Session Ordering Routes (app/api/routes_upload.py)
----------------------------------------------------------------
Handles multi-file audio upload (MP3, OGG, WAV, M4A, FLAC, WEBM), metadata
probing, interactive reordering, track removal, and audio preview streaming.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import (
    media_token,
    optional_user,
    requester_key,
    require_session_media,
    require_session_owner,
    run_heavy,
)
from app.config import settings
from app.models.schemas import ReorderRequest, UploadResponse
from app.services.job_manager import UploadTooLargeError, job_manager, upload_too_large_message
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.api.routes_upload")
router = APIRouter(prefix="/api", tags=["Upload & Ordering"])


@router.post("/upload", response_model=UploadResponse)
async def upload_audio_files(
    request: Request,
    files: List[UploadFile] = File(..., description="Audio files (MP3, OGG, WAV, etc.)"),
    session_id: Optional[str] = Form(default=None),
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> UploadResponse:
    """
    Upload one or more audio files, probe their duration/format/size,
    and register them in an ordered session.

    Without an account: up to GUEST_MAX_AUDIOS_PER_DAY audios per day, each of at
    most GUEST_MAX_AUDIO_MINUTES; nothing is stored once transcribed.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No se recibieron archivos de audio.")
    if len(files) > settings.MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Puedes subir hasta {settings.MAX_FILES_PER_UPLOAD} archivos a la vez. / "
                f"You can upload up to {settings.MAX_FILES_PER_UPLOAD} files at a time."
            ),
        )
    return await run_heavy(_store_uploads, request, files, session_id, user)


def _store_uploads(
    request: Request,
    files: List[UploadFile],
    session_id: Optional[str],
    user: Optional[Dict[str, Any]],
) -> UploadResponse:
    owner = requester_key(request, user)
    session = job_manager.create_or_get_session(session_id, owner)
    max_file = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    max_total = settings.MAX_TOTAL_UPLOAD_SIZE_MB * 1024 * 1024

    for upload in files:
        filename = upload.filename or "audio.mp3"
        if not user:
            allowed = supabase_service.guest_audios_remaining(owner)
            if len(session.tracks) + 1 > allowed:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Sin cuenta puedes transcribir {settings.GUEST_MAX_AUDIOS_PER_DAY} audios al día "
                        f"(te quedan {allowed}). Crea tu cuenta gratis para tener 2 horas diarias. / "
                        f"Without an account: {settings.GUEST_MAX_AUDIOS_PER_DAY} audios per day ({allowed} left)."
                    ),
                )
        limit = min(max_file, max_total - job_manager.session_size_bytes(session.session_id))
        if limit <= 0 or (upload.size is not None and upload.size > limit):
            raise HTTPException(status_code=413, detail=upload_too_large_message(max(limit, max_file)))
        try:
            probed = job_manager.add_file_to_session(
                session_id=session.session_id,
                filename=filename,
                content=upload.file,
                owner=owner,
                max_bytes=limit,
            )
            if not user and probed.duration_sec > settings.GUEST_MAX_AUDIO_SECONDS:
                job_manager.remove_file_from_session(session.session_id, probed.file_id)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"'{filename}' dura más de {settings.GUEST_MAX_AUDIO_MINUTES:.0f} minutos. "
                        f"Sin cuenta el máximo es {settings.GUEST_MAX_AUDIO_MINUTES:.0f} min por audio; "
                        f"con tu cuenta gratis tienes 2 horas al día. / "
                        f"Without an account each audio can be up to {settings.GUEST_MAX_AUDIO_MINUTES:.0f} minutes."
                    ),
                )
        except HTTPException:
            raise
        except UploadTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Unexpected error uploading %s", filename)
            raise HTTPException(
                status_code=500, detail=f"Error al procesar '{filename}': {exc}"
            ) from exc

    ordered_files = job_manager.get_session_files(session.session_id)
    return _upload_response(session.session_id, ordered_files)


def _upload_response(session_id: str, files) -> UploadResponse:
    return UploadResponse(session_id=session_id, files=files, media_token=media_token(f"session:{session_id}"))


@router.get("/sessions/{session_id}", response_model=UploadResponse)
def get_session_files(session_id: str = Depends(require_session_owner)) -> UploadResponse:
    """Retrieve the current ordered list of audio files in a session."""
    try:
        files = job_manager.get_session_files(session_id)
        return _upload_response(session_id, files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/sessions/{session_id}/order", response_model=UploadResponse)
def update_session_order(
    payload: ReorderRequest, session_id: str = Depends(require_session_owner)
) -> UploadResponse:
    """Update the processing sequence order of uploaded audio files."""
    try:
        files = job_manager.reorder_session_files(session_id, payload.file_order)
        return _upload_response(session_id, files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}/files/{file_id}", response_model=UploadResponse)
def delete_session_file(
    file_id: str, session_id: str = Depends(require_session_owner)
) -> UploadResponse:
    """Remove a specific audio track from the session."""
    try:
        files = job_manager.remove_file_from_session(session_id, file_id)
        return _upload_response(session_id, files)
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
def stream_session_track_audio(file_id: str, session_id: str = Depends(require_session_media)) -> FileResponse:
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
