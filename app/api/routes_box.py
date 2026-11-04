"""
Apex Box — Unlimited Block Recording, Virtual/In-Person Meetings & Live Notes Routes
(app/api/routes_box.py)
------------------------------------------------------------------------------------
Provides REST endpoints for the Chrome Extension (Manifest V3) and Mobile/Desktop
Web App to:
1. Calculate optimal block duration & constant O(1) RAM profile for 10+ hour recordings.
2. Create & manage Presencial (Mic/Room/Mobile) and Virtual (Zoom, Google Meet,
   Microsoft Teams, Webex) block-recording sessions.
3. Upload audio blocks continuously and receive incremental live transcriptions
   while freeing client RAM after each block.
4. Take, edit, and delete live timestamped notes ('acuerdo', 'tarea', 'alerta', 'nota')
   during meetings and weave them into Apex Summa & Corporate Minutes ('Actas').
5. Download the ready-to-install Chrome Extension package (`/api/box/extension.zip`).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.logsafe import clean
from app.api.deps import is_paid, require_user, run_heavy
from app.config import settings
from app.models.schemas import (
    BoxBlockUploadResponse,
    BoxCreateSessionRequest,
    BoxFinalizeRequest,
    BoxFinalizeResponse,
    BoxNoteItem,
    BoxNoteRequest,
    BoxOptimalConfigResponse,
    BoxSessionStateResponse,
)
from app.services.apex_box import (
    BoxConflictError,
    OPTIMAL_BLOCK_SECONDS,
    RECOMMENDED_BITRATE_BPS,
    apex_box_manager,
    build_extension_zip_bytes,
    calculate_optimal_block_config,
    ensure_extension_published_to_s4,
    extension_download_name,
)
from app.services.job_manager import UploadTooLargeError
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.api.routes_box")


def _owned_session(box_session_id: str, user: Dict[str, Any]):
    """La sesión debe pertenecer a la cuenta; si no existe o es de otra, 404 (sin revelar cuál)."""
    try:
        session = apex_box_manager.get_session(box_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Sesión de Apex Box no encontrada.") from exc
    if session.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail="Sesión de Apex Box no encontrada.")
    return session
router = APIRouter(prefix="/api/box", tags=["Apex Box — Grabación Ilimitada por Bloques & Notas"])


@router.get("/optimal-config", response_model=BoxOptimalConfigResponse)
async def get_optimal_block_configuration(
    target_hours: float = Query(default=10.0, ge=0.5, le=72.0, description="Target continuous recording hours"),
    bitrate_bps: int = Query(default=RECOMMENDED_BITRATE_BPS, ge=16000, le=256000),
    block_seconds: int = Query(default=OPTIMAL_BLOCK_SECONDS, ge=10, le=600),
) -> BoxOptimalConfigResponse:
    """
    Calculate optimal block duration (default 180s = 3 minutes) and constant O(1) RAM
    footprint so 10+ hour recordings never cut audio or exhaust client/mobile memory.
    """
    return calculate_optimal_block_config(
        target_hours=target_hours,
        bitrate_bps=bitrate_bps,
        block_seconds=block_seconds,
    )


@router.post("/sessions", response_model=BoxSessionStateResponse)
async def create_box_recording_session(
    payload: BoxCreateSessionRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> BoxSessionStateResponse:
    """
    Initialize a block-recording session in Presencial (Mic/Room/Mobile) or Virtual
    (Zoom, Google Meet, Microsoft Teams, Webex) mode. Requires a signed-in account:
    the owner and plan come from the session token, never from the request body.
    """
    quota = supabase_service.get_user_quota(user["user_id"])
    if not quota.is_unlimited and (quota.remaining_today_seconds or 0) <= 0:
        raise HTTPException(
            status_code=402,
            detail="Ya usaste tus horas gratis de hoy. Activa Apex Pro (USD 10 / mes) para grabar sin límite.",
        )
    payload.user_id = user["user_id"]
    payload.plan = "pro" if is_paid(user) else "free"
    return apex_box_manager.create_session(payload)


@router.get("/sessions", response_model=List[BoxSessionStateResponse])
async def list_box_recording_sessions(
    user: Dict[str, Any] = Depends(require_user),
) -> List[BoxSessionStateResponse]:
    """List the signed-in account's active and recent Apex Box recording sessions."""
    return apex_box_manager.list_sessions(user_id=user["user_id"])


@router.get("/sessions/{box_session_id}", response_model=BoxSessionStateResponse)
async def get_box_recording_session(
    box_session_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> BoxSessionStateResponse:
    """Retrieve live state, uploaded blocks, incremental transcript segments, and notes."""
    _owned_session(box_session_id, user)
    try:
        return apex_box_manager.get_session_state(box_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/sessions/{box_session_id}/status", response_model=BoxSessionStateResponse)
async def update_box_recording_status(
    box_session_id: str,
    status: str = Query(..., description="recording | paused"),
    user: Dict[str, Any] = Depends(require_user),
) -> BoxSessionStateResponse:
    """Pause or resume an active Apex Box recording session."""
    _owned_session(box_session_id, user)
    try:
        return apex_box_manager.update_session_status(box_session_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BoxConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/sessions/{box_session_id}/blocks", response_model=BoxBlockUploadResponse)
async def upload_recording_block(
    box_session_id: str,
    file: UploadFile = File(..., description="Self-contained audio block (.webm, .ogg, .mp4, .wav, .mp3)"),
    block_index: Optional[int] = Form(default=None),
    duration_hint_sec: Optional[float] = Form(default=None),
    transcribe_immediately: bool = Form(default=True),
    user: Dict[str, Any] = Depends(require_user),
) -> BoxBlockUploadResponse:
    """
    Upload a single recorded block, align it to the continuous global timeline (00:00:00 -> 10:00:00+),
    transcribe it incrementally, and return the new segments so the client can immediately free RAM.
    """
    _owned_session(box_session_id, user)
    try:
        # La duración del cliente solo sirve para rechazar pronto: lo que se cobra es lo medido.
        if duration_hint_sec and duration_hint_sec > 0:
            supabase_service.check_quota(user["user_id"], duration_hint_sec)
        return await run_heavy(
            apex_box_manager.ingest_block,
            box_session_id=box_session_id,
            filename=file.filename or "block.webm",
            content=file.file,
            block_index=block_index,
            transcribe_immediately=transcribe_immediately,
            max_bytes=settings.MAX_BOX_BLOCK_MB * 1024 * 1024,
            charge_quota=True,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except BoxConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error processing block for session %s", clean(box_session_id))
        raise HTTPException(status_code=500, detail="Error al procesar el bloque de audio.") from exc


@router.post("/sessions/{box_session_id}/notes", response_model=BoxNoteItem)
async def add_live_meeting_note(
    box_session_id: str,
    payload: BoxNoteRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> BoxNoteItem:
    """Add a timestamped note ('nota', 'acuerdo', 'tarea', 'alerta', 'idea', 'pregunta') during a meeting."""
    _owned_session(box_session_id, user)
    try:
        return apex_box_manager.add_note(box_session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/sessions/{box_session_id}/notes/{note_id}", response_model=BoxNoteItem)
async def update_live_meeting_note(
    box_session_id: str,
    note_id: str,
    payload: BoxNoteRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> BoxNoteItem:
    """Update an existing live timestamped note."""
    _owned_session(box_session_id, user)
    try:
        return apex_box_manager.update_note(box_session_id, note_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/sessions/{box_session_id}/notes/{note_id}", response_model=List[BoxNoteItem])
async def delete_live_meeting_note(
    box_session_id: str,
    note_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> List[BoxNoteItem]:
    """Delete a live timestamped note from the session."""
    _owned_session(box_session_id, user)
    try:
        return apex_box_manager.delete_note(box_session_id, note_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{box_session_id}/finalize", response_model=BoxFinalizeResponse)
async def finalize_box_recording_session(
    box_session_id: str,
    payload: Optional[BoxFinalizeRequest] = None,
    user: Dict[str, Any] = Depends(require_user),
) -> BoxFinalizeResponse:
    """
    Finalize a multi-hour block recording session, merge timeline audio, integrate
    all live notes into Apex Summa (Objectives, Callouts, Calendar Tasks, Corporate Minutes),
    and return the complete TranscriptionResult + MinutesDocumentResponse.
    """
    _owned_session(box_session_id, user)
    try:
        return await run_heavy(apex_box_manager.finalize_session, box_session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BoxConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error finalizing Apex Box session %s", clean(box_session_id))
        raise HTTPException(status_code=500, detail="Error al finalizar la sesión.") from exc


_extension_cache: Dict[str, bytes] = {}


@router.get("/extension/download")
async def download_chrome_extension() -> Response:
    """
    Descarga de la extensión desde nuestro dominio. El archivo vive en el almacenamiento
    privado; el servidor lo trae y lo entrega, así el cliente nunca ve el proveedor ni
    URLs firmadas. Sin almacenamiento configurado, o si falla, se arma el ZIP localmente.
    """
    name = extension_download_name()
    data: Optional[bytes] = None
    if mega_s4_storage.is_cloud_configured:
        try:
            key = await run_in_threadpool(ensure_extension_published_to_s4)
            data = _extension_cache.get(key)
            if data is None:
                data = await run_in_threadpool(mega_s4_storage.get_bytes, key)
                _extension_cache.clear()
                _extension_cache[key] = data
        except Exception:
            logger.exception("Extensión no disponible en el almacenamiento; se usa el ZIP local")
            data = None
    if data is None:
        data = build_extension_zip_bytes()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.get("/extension.zip")
async def download_chrome_extension_package() -> Response:
    """Download the packaged Chrome Extension (Manifest V3) ZIP archive."""
    try:
        zip_bytes = build_extension_zip_bytes()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="apex-box-chrome-extension-mv3.zip"',
        },
    )
