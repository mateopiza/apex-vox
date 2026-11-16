"""
File Upload & Session Ordering Routes (app/api/routes_upload.py)
----------------------------------------------------------------
Handles multi-file audio upload (MP3, OGG, WAV, M4A, FLAC, WEBM), metadata
probing, interactive reordering, track removal, and audio preview streaming.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import uuid
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
    throttle,
)
from app.config import settings
from app.errors import GENERIC_ERROR, detail_of
from app.models.schemas import (
    DiarizedSegment,
    ReorderRequest,
    TranscriptionResult,
    UploadResponse,
    UrlIngestRequest,
    UrlIngestResponse,
)
from app.services import url_ingest
from app.services.apex_summa import generate_apex_summa_report
from app.services.audio_engine import format_timestamp_hhmmss
from app.services.job_manager import UploadTooLargeError, job_manager, upload_too_large_message
from app.services.storage_s4 import mega_s4_storage
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
            raise HTTPException(status_code=500, detail=GENERIC_ERROR) from exc

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
        raise HTTPException(status_code=404, detail=detail_of(exc)) from exc


@router.put("/sessions/{session_id}/order", response_model=UploadResponse)
def update_session_order(
    payload: ReorderRequest, session_id: str = Depends(require_session_owner)
) -> UploadResponse:
    """Update the processing sequence order of uploaded audio files."""
    try:
        files = job_manager.reorder_session_files(session_id, payload.file_order)
        return _upload_response(session_id, files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_of(exc)) from exc


@router.delete("/sessions/{session_id}/files/{file_id}", response_model=UploadResponse)
def delete_session_file(
    file_id: str, session_id: str = Depends(require_session_owner)
) -> UploadResponse:
    """Remove a specific audio track from the session."""
    try:
        files = job_manager.remove_file_from_session(session_id, file_id)
        return _upload_response(session_id, files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=detail_of(exc)) from exc


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


# -----------------------------------------------------------------------------
# Audio from a pasted link (YouTube or a direct audio file)
# -----------------------------------------------------------------------------


@router.post("/upload/url", response_model=UrlIngestResponse)
async def upload_from_url(
    payload: UrlIngestRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> UrlIngestResponse:
    """
    Download only the audio of a link and add it to the caller's upload session as one more track.
    YouTube: the length is checked against the plan before anything is downloaded; if YouTube
    refuses the audio, the video's captions become a transcript without speakers (`kind: captions`).
    Direct links: http/https to public addresses only, capped in size and time.
    """
    owner = requester_key(request, user)
    throttle(f"url-ingest:{owner}", limit=20, window_seconds=3600)
    try:
        return await run_heavy(_ingest_url, request, payload, user, owner)
    except url_ingest.UrlIngestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _guest_audio_limit(owner: str, session_tracks: int) -> None:
    allowed = supabase_service.guest_audios_remaining(owner)
    if session_tracks + 1 > allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Sin cuenta puedes transcribir {settings.GUEST_MAX_AUDIOS_PER_DAY} audios al día "
                f"(te quedan {allowed}). Crea tu cuenta gratis para tener 2 horas diarias. / "
                f"Without an account: {settings.GUEST_MAX_AUDIOS_PER_DAY} audios per day ({allowed} left)."
            ),
        )


def _check_length(seconds: float, user: Optional[Dict[str, Any]], session_seconds: float) -> None:
    """The plan's limits for this much more audio, before it is downloaded or transcribed."""
    if not user:
        if seconds > settings.GUEST_MAX_AUDIO_SECONDS:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Sin cuenta cada audio puede durar hasta {settings.GUEST_MAX_AUDIO_MINUTES:.0f} minutos. / "
                    f"Without an account each audio can be up to {settings.GUEST_MAX_AUDIO_MINUTES:.0f} minutes."
                ),
            )
        return
    if seconds > settings.URL_INGEST_MAX_MINUTES * 60:
        raise HTTPException(
            status_code=413,
            detail=(
                f"El audio de un enlace puede durar hasta {settings.URL_INGEST_MAX_MINUTES} minutos. / "
                f"Audio from a link can be up to {settings.URL_INGEST_MAX_MINUTES} minutes."
            ),
        )
    try:
        supabase_service.check_quota(user["user_id"], session_seconds + seconds)
    except PermissionError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc


def _ingest_url(
    request: Request, payload: UrlIngestRequest, user: Optional[Dict[str, Any]], owner: str
) -> UrlIngestResponse:
    url = url_ingest.parse_link(payload.url)
    session = job_manager.create_or_get_session(payload.session_id, owner)
    if not user:
        _guest_audio_limit(owner, len(session.tracks))
    session_seconds = sum(t.duration_sec for t in job_manager.get_session_files(session.session_id))
    max_file = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    limit = min(max_file, settings.MAX_TOTAL_UPLOAD_SIZE_MB * 1024 * 1024 - job_manager.session_size_bytes(session.session_id))
    if limit <= 0:
        raise HTTPException(status_code=413, detail=upload_too_large_message(max_file))
    lang = payload.language if payload.language in ("es", "en") else "es"

    work_dir = settings.TEMP_DIR / f"url_{uuid.uuid4().hex[:12]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        info: Optional[Dict[str, Any]] = None
        if url_ingest.is_youtube(url):
            info = url_ingest.youtube_info(str(url))
            if info.get("duration"):
                _check_length(float(info["duration"]), user, session_seconds)
            try:
                fetched = url_ingest.youtube_audio(info, work_dir, limit)
            except url_ingest.UrlIngestError as audio_error:
                if audio_error.status_code == 413:
                    raise
                return _captions_result(info, lang, user, owner, session.session_id, audio_error)
        else:
            fetched = url_ingest.download_direct(str(url), work_dir, limit, settings.URL_INGEST_TIMEOUT_SECONDS)

        with fetched.path.open("rb") as fh:
            try:
                probed = job_manager.add_file_to_session(
                    session_id=session.session_id, filename=fetched.filename, content=fh, owner=owner, max_bytes=limit,
                )
            except UploadTooLargeError as exc:
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            _check_length(probed.duration_sec, user, session_seconds)  # enlaces directos: se sabe al tenerlo
        except HTTPException:
            job_manager.remove_file_from_session(session.session_id, probed.file_id)
            raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    files = job_manager.get_session_files(session.session_id)
    return UrlIngestResponse(
        session_id=session.session_id, files=files, media_token=media_token(f"session:{session.session_id}"),
        kind="audio", title=str((info or {}).get("title") or fetched.filename),
    )


def _captions_result(
    info: Dict[str, Any], lang: str, user: Optional[Dict[str, Any]], owner: str, session_id: str,
    audio_error: url_ingest.UrlIngestError,
) -> UrlIngestResponse:
    """YouTube refused the audio: the captions become a transcript without speakers."""
    cues = url_ingest.youtube_captions(info, lang)
    if not cues:
        raise HTTPException(
            status_code=502,
            detail=(
                "YouTube no permitió descargar el audio y el video no tiene subtítulos. Descarga el audio y súbelo. / "
                "YouTube did not allow the audio download and the video has no captions. Download it and upload the file."
            ),
        ) from audio_error
    if not user:
        _check_length(max(c.end for c in cues), None, 0.0)
        try:
            supabase_service.consume_guest_audios(owner, 1)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    title = str(info.get("title") or "YouTube")[:160]
    speaker = "Video"
    segments = [
        DiarizedSegment(
            id=i, start=round(c.start, 3), end=round(c.end, 3), speaker=speaker, text=c.text,
            start_formatted=format_timestamp_hhmmss(c.start), end_formatted=format_timestamp_hhmmss(c.end),
            source_file=title, file_order_index=0,
        )
        for i, c in enumerate(cues)
    ]
    full_text, total = url_ingest.captions_text(cues)
    plan = supabase_service.get_user_quota(user["user_id"]).plan if user else "guest"
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    result = TranscriptionResult(
        job_id=job_id, session_id=session_id, user_id=user["user_id"] if user else None, plan=plan,
        detected_speakers_count=1, speaker_roles={speaker: ""}, total_duration_sec=round(total, 3),
        total_duration_formatted=format_timestamp_hhmmss(total), model_used="youtube_captions",
        diarization_engine_used="captions", engine_brand="YouTube (subtítulos)" if lang == "es" else "YouTube (captions)",
        language=lang, file_order=[title], segments=segments,
        full_text="\n".join(f"[{s.start_formatted} - {s.end_formatted}] {s.text}" for s in segments) or full_text,
        storage_provider="none" if plan == "guest" else "apex_vox_cloud",
        expires_at=(
            (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.GUEST_RESULT_TTL_MINUTES)).isoformat()
            if plan == "guest" else mega_s4_storage.compute_expiration_iso(plan)
        ),
    )
    if plan != "guest":
        result.summa_report = generate_apex_summa_report(result, language=lang, is_locked=(plan == "free"))
    job_manager.register_finished_result(result, owner, {
        "job_id": job_id, "user_id": result.user_id, "session_id": session_id, "title": title,
        "engine_brand": result.engine_brand, "total_duration_sec": result.total_duration_sec,
        "total_duration_formatted": result.total_duration_formatted, "detected_speakers_count": 1,
        "storage_provider": "apex_vox_cloud", "s4_result_key": f"users/{result.user_id}/jobs/{job_id}/result.json",
        "retention_policy": "unlimited" if result.expires_at is None else "24h", "expires_at": result.expires_at,
        "plan": plan, "file_order": [title], "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "youtube_captions", "speakers": [speaker],
    })
    return UrlIngestResponse(
        session_id=session_id, files=job_manager.get_session_files(session_id),
        media_token=media_token(f"session:{session_id}"), kind="captions", title=title, job_id=job_id,
    )
