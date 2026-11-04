"""
Transcription, Diarization & Voice Profile Routes (app/api/routes_transcribe.py)
--------------------------------------------------------------------------------
Provides endpoints to trigger transcription + speaker diarization jobs,
poll progress, retrieve structured chronological results, stream merged
timeline audio, rename speakers, and manage enrolled speaker Voice Profiles.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response

from app.api.deps import (
    is_paid,
    media_token,
    optional_user,
    require_admin,
    require_job_media,
    require_job_owner,
    require_user,
    requester_key,
    run_heavy,
)
from app.config import resolve_engine_code, settings
from app.models.schemas import (
    ApexSummaReport,
    JobStatusResponse,
    MinutesDocumentResponse,
    MinutesGenerationRequest,
    RenameSpeakersRequest,
    TranscribeRequest,
    TranscribeResponse,
    TranscriptionResult,
    VoiceProfile,
)
from app.services.acoustic_diarizer import (
    delete_voice_profile,
    enroll_voice_profile,
    list_voice_profiles,
)
from app.services.apex_summa import (
    generate_apex_summa_report,
    generate_ics_calendar,
    generate_meeting_minutes,
)
from app.services.job_manager import QuotaCharge, job_manager, upload_too_large_message
from app.services.state_store import StateCorruptError
from app.services.supabase_service import supabase_service
from app.services.usage_reporter import (
    compute_usage_report,
    format_report_message,
    send_daily_bot_notification,
)

logger = logging.getLogger("app.api.routes_transcribe")
router = APIRouter(prefix="/api", tags=["Transcription, Diarization & Voice Profiles"])


@router.post("/transcribe", response_model=TranscribeResponse)
def start_transcription_job(
    payload: TranscribeRequest,
    request: Request,
    sync: bool = Query(default=False, description="Run synchronously before returning (non-production only)"),
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> TranscribeResponse:
    """
    Queue and launch an end-to-end audio slicing, transcription (Potenciado por Groq),
    speaker diarization (Mc-Ayrton, Mc-Lewis, Mc-Norris, Mc-Piastri), Mega S4 storage,
    and Apex Summa AI intelligence job.
    """
    # Identity, plan and API keys come from the server, never from the request body.
    owner = requester_key(request, user)
    payload.user_id = user["user_id"] if user else None
    payload.guest_key = None if user else owner
    payload.api_key = None
    payload.deepgram_api_key = None
    if settings.is_production:
        sync = False

    if not job_manager.session_owned_by(payload.session_id, owner):
        raise HTTPException(status_code=404, detail=f"Sesión '{payload.session_id}' no encontrada.")

    raw_engine = (payload.diarization_engine or settings.DEFAULT_DIARIZATION_ENGINE or "Mc-Lewis").strip()
    engine = resolve_engine_code(raw_engine)
    if not (settings.GROQ_API_KEY or "").strip() and not (engine == "deepgram" and settings.DEEPGRAM_API_KEY):
        raise HTTPException(status_code=503, detail="El servicio de transcripción no está disponible en este momento.")

    charge: Optional[QuotaCharge] = None
    if not user:
        tracks = job_manager.get_session_files(payload.session_id)
        too_long = [t.filename for t in tracks if t.duration_sec > settings.GUEST_MAX_AUDIO_SECONDS]
        if too_long:
            raise HTTPException(
                status_code=413,
                detail=f"Sin cuenta cada audio puede durar hasta {settings.GUEST_MAX_AUDIO_MINUTES:.0f} minutos.",
            )
        charge_day = supabase_service.usage_day()
        try:
            supabase_service.consume_guest_audios(owner, len(tracks))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        charge = QuotaCharge(owner=owner, day=charge_day, audios=len(tracks), guest=True)

    try:
        job_status = job_manager.create_job(payload)
    except Exception as exc:
        if charge:
            supabase_service.refund_guest_audios(charge.owner, charge.audios, charge.day)
        status = 404 if isinstance(exc, KeyError) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if charge:
        job_manager.record_charge(job_status.job_id, charge)

    if sync:
        try:
            job_manager.execute_job(job_status.job_id, payload)
        except PermissionError as exc:
            raise HTTPException(status_code=402, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return TranscribeResponse(
            job_id=job_status.job_id,
            session_id=payload.session_id,
            status="completed",
        )

    def _worker() -> None:
        try:
            job_manager.execute_job(job_status.job_id, payload)
        except Exception as exc:
            logger.error("Background job %s failed: %s", job_status.job_id, exc)

    thread = threading.Thread(target=_worker, name=f"worker-{job_status.job_id}", daemon=True)
    thread.start()

    return TranscribeResponse(
        job_id=job_status.job_id,
        session_id=payload.session_id,
        status=job_status.status,
    )


def _with_media_token(result: TranscriptionResult) -> TranscriptionResult:
    """Copia del resultado con el token de descarga (el token nunca se guarda)."""
    return result.model_copy(update={"media_token": media_token(f"job:{result.job_id}")})


@router.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: str = Depends(require_job_owner)) -> JobStatusResponse:
    """Poll the current status and progress percentage of a transcription job."""
    status = job_manager.get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Trabajo '{job_id}' no encontrado.")
    return status


@router.get("/jobs/{job_id}/result", response_model=TranscriptionResult)
def get_job_result(job_id: str = Depends(require_job_owner)) -> TranscriptionResult:
    """Retrieve the complete chronological transcription and speaker diarization result."""
    result = job_manager.get_job_result(job_id)
    if result:
        return _with_media_token(result)

    status = job_manager.get_job_status(job_id)
    if status:
        if status.status == "failed":
            raise HTTPException(
                status_code=500,
                detail=status.error or "El trabajo de transcripción falló.",
            )
        raise HTTPException(
            status_code=202,
            detail=f"El trabajo aún está en estado '{status.status}' ({status.progress}%).",
        )

    raise HTTPException(status_code=404, detail=f"Resultado para '{job_id}' no encontrado.")


@router.patch("/jobs/{job_id}/speakers", response_model=TranscriptionResult)
async def rename_job_speakers(
    payload: RenameSpeakersRequest, job_id: str = Depends(require_job_owner)
) -> TranscriptionResult:
    """Rename speaker labels across all segments of a completed transcription job."""
    try:
        return _with_media_token(await run_heavy(job_manager.rename_speakers, job_id, payload.speaker_map))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/audio")
def stream_merged_job_audio(job_id: str = Depends(require_job_media)) -> FileResponse:
    """Stream the merged continuous MP3 timeline audio for interactive playback."""
    merged_path = settings.OUTPUT_DIR / f"{job_id}_merged.mp3"
    if not merged_path.exists():
        raise HTTPException(status_code=404, detail="Audio combinado no disponible.")
    return FileResponse(
        path=merged_path,
        media_type="audio/mpeg",
        filename=f"{job_id}_merged.mp3",
    )


# -----------------------------------------------------------------------------
# Voice Profile Enrollment & Speaker Recognition Endpoints
# -----------------------------------------------------------------------------

@router.get("/voice-profiles", response_model=List[VoiceProfile])
def get_enrolled_voice_profiles(
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> List[VoiceProfile]:
    """Voice profiles enrolled by the signed-in account (empty for visitors)."""
    return list_voice_profiles(user["user_id"]) if user else []


@router.post("/voice-profiles", response_model=VoiceProfile)
async def create_voice_profile(
    name: str = Form(..., description="Speaker name, e.g. 'Carlos' or 'Dra. Gómez'"),
    role: Optional[str] = Form(default="", description="Optional role description"),
    file: UploadFile = File(..., description="Short audio sample (5-30s) of this speaker's voice"),
    user: Dict[str, Any] = Depends(require_user),
) -> VoiceProfile:
    """Enroll a speaker's acoustic voiceprint from a sample audio file."""
    limit = settings.MAX_VOICE_SAMPLE_MB * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=upload_too_large_message(limit))
    try:
        return await run_heavy(
            enroll_voice_profile,
            name=name,
            audio_bytes=content,
            filename=file.filename or "sample.mp3",
            role=role or "",
            owner_id=user["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StateCorruptError:
        raise
    except Exception as exc:
        logger.exception("Voice profile enrollment failed")
        raise HTTPException(status_code=500, detail=f"Error al registrar perfil de voz: {exc}") from exc


@router.delete("/voice-profiles/{profile_id}", response_model=List[VoiceProfile])
def remove_voice_profile(
    profile_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> List[VoiceProfile]:
    """Delete one of the account's voice profiles."""
    return delete_voice_profile(profile_id, user["user_id"])


# -----------------------------------------------------------------------------
# Daily Usage, Cost, Revenue & Bot Notification Endpoints
# -----------------------------------------------------------------------------

@router.get("/metrics/daily", dependencies=[Depends(require_admin)], include_in_schema=False)
def get_daily_usage_metrics(
    date: Optional[str] = Query(default=None, description="Target date YYYY-MM-DD (defaults to today)"),
) -> dict:
    """Return daily and cumulative audio consumption, API expenditure (Groq + Deepgram), and estimated revenue."""
    report = compute_usage_report(target_date=date)
    return {
        "report": report,
        "formatted_message": format_report_message(report),
    }


@router.post("/metrics/send-report", dependencies=[Depends(require_admin)], include_in_schema=False)
def trigger_daily_bot_report(
    date: Optional[str] = Query(default=None, description="Target date YYYY-MM-DD (defaults to today)"),
) -> dict:
    """Save the daily report to `outputs/reports/` and send it to the configured Telegram chat / webhook.

    Destinations come only from the server configuration: accepting a URL or bot token in the
    request would let the endpoint post data to arbitrary hosts (SSRF).
    """
    report = compute_usage_report(target_date=date)
    return send_daily_bot_notification(report=report)


# -----------------------------------------------------------------------------
# Apex Summa — AI Intelligence Summary, Charts, Calendar & Minutes ('Actas')
# -----------------------------------------------------------------------------

def _require_summa_access(result, user: Optional[Dict[str, Any]]) -> None:
    """Minutes and calendar export are Apex Pro features."""
    if result.plan == "guest":
        raise HTTPException(
            status_code=402,
            detail="Crea tu cuenta para usar Apex Summa / Create an account to use Apex Summa.",
        )
    if result.plan == "free" and not is_paid(user):
        raise HTTPException(
            status_code=402,
            detail="Las actas y el calendario de Apex Summa están incluidos en Apex Pro / Included in Apex Pro.",
        )


@router.get("/jobs/{job_id}/summa", response_model=ApexSummaReport)
async def get_job_apex_summa_report(
    job_id: str = Depends(require_job_owner),
    lang: str = Query(default="es", description="Language: es or en"),
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> ApexSummaReport:
    """
    Retrieve the 7-part Apex Summa AI report for a completed transcription:
    1. Quién habló más (speaker_stats & dominant_speaker)
    2. De qué se habló (executive_summary & topics)
    3. Objetivos (objectives)
    4. Llamados de atención (callouts)
    5. Próximas tareas en forma de calendario (calendar_tasks)
    6. Gráficas de la transcripción (charts)
    7. Opciones de actas (available_minutes_templates)
    """
    return await run_heavy(_summa_report, job_id, lang, user)


def _summa_report(job_id: str, lang: str, user: Optional[Dict[str, Any]]) -> ApexSummaReport:
    result = job_manager.get_job_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Resultado '{job_id}' no encontrado.")

    if result.plan == "guest":
        raise HTTPException(status_code=402, detail="Crea tu cuenta para usar Apex Summa / Create an account to use Apex Summa.")
    is_locked = result.plan == "free" and not is_paid(user)
    report = generate_apex_summa_report(
        result=result,
        language=lang,
        is_locked=is_locked,
    )
    result.summa_report = report
    return report


@router.post("/jobs/{job_id}/minutes", response_model=MinutesDocumentResponse)
async def create_job_meeting_minutes(
    payload: MinutesGenerationRequest,
    job_id: str = Depends(require_job_owner),
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> MinutesDocumentResponse:
    """
    Generate formal meeting minutes ('Acta') in the selected template:
    - consejo: Acta de Reunión de Consejo / Junta Directiva
    - comite: Acta de Comité Ejecutivo y Operativo
    - asamblea: Acta de Asamblea General de Socios
    - seguimiento: Acta de Seguimiento de Proyecto
    - ejecutiva: Minuta Ejecutiva de Decisiones Rápidas
    """
    return await run_heavy(_meeting_minutes, job_id, payload, user)


def _meeting_minutes(
    job_id: str, payload: MinutesGenerationRequest, user: Optional[Dict[str, Any]]
) -> MinutesDocumentResponse:
    result = job_manager.get_job_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Resultado '{job_id}' no encontrado.")

    _require_summa_access(result, user)
    report = generate_apex_summa_report(
        result=result,
        language=payload.language,
        is_locked=False,
    )
    return generate_meeting_minutes(
        result=result,
        report=report,
        req=payload,
    )


@router.get("/jobs/{job_id}/calendar.ics")
async def download_job_tasks_calendar_ics(
    job_id: str = Depends(require_job_media),
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> Response:
    """Download the upcoming tasks ('Próximas tareas') as an iCalendar (.ics) file."""
    return await run_heavy(_calendar_file, job_id, user)


def _calendar_file(job_id: str, user: Optional[Dict[str, Any]]) -> Response:
    result = job_manager.get_job_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Resultado '{job_id}' no encontrado.")

    _require_summa_access(result, user)
    report = generate_apex_summa_report(
        result=result,
        language=result.language or "es",
        is_locked=False,
    )
    ics_content = generate_ics_calendar(report)
    return Response(
        content=ics_content.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}_apex_summa_tasks.ics"',
        },
    )
