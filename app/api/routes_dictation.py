"""
Dictation routes (app/api/routes_dictation.py)
----------------------------------------------
Short clips from the mobile keyboard and app: transcribed and, optionally, rewritten in a tone,
in one request. Apex Pro only. Nothing is stored.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.api.deps import is_paid, optional_user, request_language, require_user, run_heavy, throttle, throttle_release
from app.config import settings
from app.errors import GENERIC_ERROR
from app.models.schemas import DictationResponse, DictationRewriteRequest
from app.services import dictation

logger = logging.getLogger("app.api.routes_dictation")

router = APIRouter(prefix="/api/dictation", tags=["Dictation"])

PRO_DETAIL = "El dictado es una función de Apex Pro. / Dictation is an Apex Pro feature."
RATE_DETAIL = "Demasiados dictados seguidos. Espera un momento. / Too many dictations in a row. Please wait a moment."
DAILY_DETAIL = "Llegaste al límite de dictados de hoy. / You reached today's dictation limit."


def _require_pro(user: Dict[str, Any]) -> None:
    if not is_paid(user):
        raise HTTPException(status_code=402, detail=PRO_DETAIL)


def _take_allowance(user: Dict[str, Any]) -> None:
    throttle(f"dictation:min:{user['user_id']}", settings.DICTATION_PER_MINUTE, 60, detail=RATE_DETAIL)
    try:
        throttle(f"dictation:day:{user['user_id']}", settings.DICTATION_PER_DAY, 86400, detail=DAILY_DETAIL)
    except HTTPException:
        throttle_release(f"dictation:min:{user['user_id']}")
        raise


def _give_back_allowance(user: Dict[str, Any]) -> None:
    """A dictation that failed on our side does not count against the user's limits."""
    throttle_release(f"dictation:min:{user['user_id']}")
    throttle_release(f"dictation:day:{user['user_id']}")


@router.get("/tones")
def dictation_tones(request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
    """Tones the client can offer, labelled in the request language, and the limits it must respect."""
    return {
        "tones": dictation.list_tones(request_language(request)),
        "default": dictation.DEFAULT_TONE,
        "allowed": is_paid(user),
        "max_audio_mb": settings.DICTATION_MAX_MB,
        "max_instructions_chars": dictation.MAX_INSTRUCTIONS_CHARS,
        "max_text_chars": settings.DICTATION_MAX_TEXT_CHARS,
    }


@router.post("", response_model=DictationResponse)
async def dictate(
    file: UploadFile = File(..., description="One short clip (.m4a, .wav, .mp3, .ogg, .webm, .mp4, .flac)"),
    tone: str = Form(default=dictation.DEFAULT_TONE),
    instructions: str = Form(default="", description="Extra style request, required for tone=custom"),
    language: str = Form(default="auto", description="ISO 639-1 code, or auto"),
    vocabulary: str = Form(default="", description="Names and terms likely to be dictated"),
    user: Dict[str, Any] = Depends(require_user),
) -> DictationResponse:
    """Transcribe a clip and return it in the chosen tone. `raw_text` is always what was said."""
    _require_pro(user)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Formato de audio no admitido. / Unsupported audio format.")
    limit = settings.DICTATION_MAX_MB * 1024 * 1024
    audio = await file.read(limit + 1)
    if len(audio) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"El dictado supera {settings.DICTATION_MAX_MB} MB. / The dictation is over {settings.DICTATION_MAX_MB} MB.",
        )
    if not audio:
        raise HTTPException(status_code=400, detail="El audio está vacío. / The audio is empty.")
    _take_allowance(user)
    try:
        result = await run_heavy(
            dictation.dictate,
            audio,
            f"dictation{extension}",
            tone=tone,
            instructions=instructions,
            language=language,
            vocabulary=vocabulary,
        )
    except dictation.DictationError as exc:
        _give_back_allowance(user)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        _give_back_allowance(user)
        logger.exception("Dictation failed")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR) from exc
    return DictationResponse(**result.__dict__)


@router.post("/rewrite", response_model=DictationResponse)
async def rewrite_text(body: DictationRewriteRequest, user: Dict[str, Any] = Depends(require_user)) -> DictationResponse:
    """Rewrite text already on screen in another tone, without recording again."""
    _require_pro(user)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No hay texto para reformular. / There is no text to rewrite.")
    if len(text) > settings.DICTATION_MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"El texto supera {settings.DICTATION_MAX_TEXT_CHARS} caracteres. / "
                f"The text is over {settings.DICTATION_MAX_TEXT_CHARS} characters."
            ),
        )
    _take_allowance(user)
    tone_id = dictation.resolve_tone(body.tone, body.instructions)
    try:
        rewritten = await run_heavy(dictation.rewrite, text, tone_id, body.instructions)
    except dictation.DictationError as exc:
        _give_back_allowance(user)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        _give_back_allowance(user)
        logger.exception("Dictation rewrite failed")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR) from exc
    return DictationResponse(text=rewritten or text, raw_text=text, tone=tone_id, rewritten=rewritten is not None)
