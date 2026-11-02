"""
Telegram bot routes (app/api/routes_telegram.py)
------------------------------------------------
- POST /api/telegram/webhook      : Telegram updates (secret header required)
- GET  /api/telegram/link         : link status of the signed-in account
- POST /api/telegram/link-code    : one-time code to link a chat (Apex Pro only)
- DELETE /api/telegram/link       : unlink the chat
- POST /api/telegram/setup        : (admin) register the webhook with Telegram
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.deps import public_base_url, require_admin, require_user
from app.services import telegram_service

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])


@router.post("/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
) -> Dict[str, Any]:
    if not telegram_service.verify_webhook(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    telegram_service.handle_update_async(update if isinstance(update, dict) else {})
    return {"ok": True}


@router.get("/link")
async def telegram_link_status(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return telegram_service.link_status(user)


@router.post("/link-code")
async def telegram_link_code(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    if not telegram_service.is_configured():
        raise HTTPException(status_code=503, detail="El bot de Telegram aún no está configurado.")
    try:
        return telegram_service.create_link_code(user["user_id"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/link")
async def telegram_unlink(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    telegram_service.unlink(user["user_id"])
    return {"linked": False}


@router.post("/setup", dependencies=[Depends(require_admin)], include_in_schema=False)
async def telegram_setup(request: Request) -> Dict[str, Any]:
    if not telegram_service.is_configured():
        raise HTTPException(status_code=503, detail="TELEGRAM_BOT_TOKEN no está configurado.")
    return telegram_service.set_webhook(public_base_url(request))
