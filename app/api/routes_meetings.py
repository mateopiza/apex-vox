"""
Bot de reuniones e invitaciones (app/api/routes_meetings.py)
------------------------------------------------------------
- GET    /api/meetings                 : bots y próximas reuniones de la cuenta
- POST   /api/meetings/bot             : enviar el bot a una reunión ahora (Apex Pro)
- DELETE /api/meetings/bot/{bot_id}    : cancelar / sacar el bot
- POST   /api/recall/webhook           : estados del bot (Recall.ai, firma Svix)
- POST   /api/inbound/resend           : invitaciones recibidas en agenda@apexbox.ialabs.app
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import is_paid, require_user, throttle
from app.config import settings
from app.services import calendar_invites, recall_service

router = APIRouter(tags=["Bot de reuniones"])


class BotRequest(BaseModel):
    meeting_url: str
    title: Optional[str] = None


@router.get("/api/meetings")
async def my_meetings(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {
        "invites_address": settings.INVITES_ADDRESS,
        "bot_enabled": recall_service.is_configured(),
        "bot_allowed": is_paid(user),
        "bots": recall_service.list_bots(user["user_id"])[:20],
        "events": calendar_invites.upcoming_events(user["user_id"]),
    }


@router.post("/api/meetings/bot")
async def send_bot(payload: BotRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    if not is_paid(user):
        raise HTTPException(status_code=402, detail="El bot de reuniones está incluido en Apex Pro.")
    throttle(f"bot:{user['user_id']}", limit=10, window_seconds=3600)
    try:
        return recall_service.create_bot(user["user_id"], payload.meeting_url, payload.title or "Reunión")
    except recall_service.RecallError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/meetings/bot/{bot_id}")
async def cancel_bot(bot_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    if not any(b["bot_id"] == bot_id for b in recall_service.list_bots(user["user_id"])):
        raise HTTPException(status_code=404, detail="Bot no encontrado.")
    recall_service.cancel_bot(bot_id)
    return {"status": "cancelled"}


@router.post("/api/recall/webhook", include_in_schema=False)
async def recall_webhook(request: Request) -> Dict[str, Any]:
    body = await request.body()
    if not recall_service.verify_svix(settings.RECALL_WEBHOOK_SECRET, dict(request.headers), body):
        raise HTTPException(status_code=401, detail="Firma inválida")
    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    return recall_service.handle_status_event(payload)


@router.post("/api/inbound/resend", include_in_schema=False)
async def resend_inbound(request: Request) -> Dict[str, Any]:
    body = await request.body()
    if not recall_service.verify_svix(settings.RESEND_INBOUND_WEBHOOK_SECRET, dict(request.headers), body):
        raise HTTPException(status_code=401, detail="Firma inválida")
    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    if payload.get("type") != "email.received":
        return {"status": "ignored"}
    email_id = (payload.get("data") or {}).get("email_id")
    if email_id:
        # Responder rápido: la descarga y el análisis del .ics van en segundo plano.
        threading.Thread(target=_safe_process, args=(str(email_id),), daemon=True).start()
    return {"status": "accepted"}


def _safe_process(email_id: str) -> None:
    import logging

    try:
        calendar_invites.process_inbound_email(email_id)
    except Exception:  # noqa: BLE001
        logging.getLogger("app.api.routes_meetings").exception("Invitación %s no procesada", email_id)
