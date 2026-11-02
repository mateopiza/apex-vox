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
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response

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
    OPTIMAL_BLOCK_SECONDS,
    RECOMMENDED_BITRATE_BPS,
    apex_box_manager,
    build_extension_zip_bytes,
    calculate_optimal_block_config,
    ensure_extension_published_to_s4,
    extension_download_name,
)
from app.services.storage_s4 import mega_s4_storage

logger = logging.getLogger("app.api.routes_box")
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
) -> BoxSessionStateResponse:
    """
    Initialize an unlimited block-recording session in Presencial (Mic/Room/Mobile)
    or Virtual (Zoom, Google Meet, Microsoft Teams, Webex) mode.
    """
    return apex_box_manager.create_session(payload)


@router.get("/sessions", response_model=List[BoxSessionStateResponse])
async def list_box_recording_sessions(
    user_id: Optional[str] = Query(default=None),
) -> List[BoxSessionStateResponse]:
    """List active and recent Apex Box recording sessions."""
    return apex_box_manager.list_sessions(user_id=user_id)


@router.get("/sessions/{box_session_id}", response_model=BoxSessionStateResponse)
async def get_box_recording_session(
    box_session_id: str,
) -> BoxSessionStateResponse:
    """Retrieve live state, uploaded blocks, incremental transcript segments, and notes."""
    try:
        return apex_box_manager.get_session_state(box_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/sessions/{box_session_id}/status", response_model=BoxSessionStateResponse)
async def update_box_recording_status(
    box_session_id: str,
    status: str = Query(..., description="recording | paused"),
) -> BoxSessionStateResponse:
    """Pause or resume an active Apex Box recording session."""
    try:
        return apex_box_manager.update_session_status(box_session_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{box_session_id}/blocks", response_model=BoxBlockUploadResponse)
async def upload_recording_block(
    box_session_id: str,
    file: UploadFile = File(..., description="Self-contained audio block (.webm, .ogg, .mp4, .wav, .mp3)"),
    block_index: Optional[int] = Form(default=None),
    duration_hint_sec: Optional[float] = Form(default=None),
    transcribe_immediately: bool = Form(default=True),
    api_key: Optional[str] = Form(default=None),
) -> BoxBlockUploadResponse:
    """
    Upload a single recorded block, align it to the continuous global timeline (00:00:00 -> 10:00:00+),
    transcribe it incrementally, and return the new segments so the client can immediately free RAM.
    """
    content = await file.read()
    try:
        return apex_box_manager.ingest_block(
            box_session_id=box_session_id,
            filename=file.filename or "block.webm",
            content=content,
            block_index=block_index,
            duration_hint_sec=duration_hint_sec,
            transcribe_immediately=transcribe_immediately,
            api_key=api_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error processing block for session %s", box_session_id)
        raise HTTPException(status_code=500, detail=f"Error al procesar bloque de audio: {exc}") from exc


@router.post("/sessions/{box_session_id}/notes", response_model=BoxNoteItem)
async def add_live_meeting_note(
    box_session_id: str,
    payload: BoxNoteRequest,
) -> BoxNoteItem:
    """Add a timestamped note ('nota', 'acuerdo', 'tarea', 'alerta', 'idea', 'pregunta') during a meeting."""
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
) -> BoxNoteItem:
    """Update an existing live timestamped note."""
    try:
        return apex_box_manager.update_note(box_session_id, note_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/sessions/{box_session_id}/notes/{note_id}", response_model=List[BoxNoteItem])
async def delete_live_meeting_note(
    box_session_id: str,
    note_id: str,
) -> List[BoxNoteItem]:
    """Delete a live timestamped note from the session."""
    try:
        return apex_box_manager.delete_note(box_session_id, note_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{box_session_id}/finalize", response_model=BoxFinalizeResponse)
async def finalize_box_recording_session(
    box_session_id: str,
    payload: Optional[BoxFinalizeRequest] = None,
) -> BoxFinalizeResponse:
    """
    Finalize a multi-hour block recording session, merge timeline audio, integrate
    all live notes into Apex Summa (Objectives, Callouts, Calendar Tasks, Corporate Minutes),
    and return the complete TranscriptionResult + MinutesDocumentResponse.
    """
    try:
        return apex_box_manager.finalize_session(box_session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error finalizing Apex Box session %s", box_session_id)
        raise HTTPException(status_code=500, detail=f"Error al finalizar la sesión: {exc}") from exc


@router.get("/extension/download")
async def download_chrome_extension_from_s4() -> RedirectResponse:
    """
    Enlace estable de descarga de la extensión: redirige a una URL firmada de MEGA S4
    (caduca en 10 minutos; el bucket sigue privado). Sin MEGA S4 configurado, o si
    falla, sirve el ZIP directamente desde el servidor.
    """
    headers = {"Cache-Control": "no-store"}
    if mega_s4_storage.is_cloud_configured:
        try:
            key = await run_in_threadpool(ensure_extension_published_to_s4)
            url = mega_s4_storage.presigned_get_url(
                key, expires_sec=600, download_name=extension_download_name()
            )
            return RedirectResponse(url, status_code=302, headers=headers)
        except Exception:
            logger.exception("Descarga de la extensión desde MEGA S4 no disponible; se usa el ZIP local")
    return RedirectResponse("/api/box/extension.zip", status_code=302, headers=headers)


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
