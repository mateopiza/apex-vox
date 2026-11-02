"""
Bold API Billing & Subscription Routes (app/api/routes_billing.py)
------------------------------------------------------------------
Handles subscription checkout and recurring billing via Bold API:
- Plan Apex Pro: $30.000 COP / $10 USD per month
- 3-day free trial ('prueba gratis de 3 días') + automatic billing ('cobro automático')
- Unlimited transcriptions + unlimited storage in MEGA S4 + Apex Summa IA
"""

from __future__ import annotations

import json

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Header, Request

from app.models.schemas import (
    BoldCheckoutRequest,
    BoldCheckoutResponse,
    SubscribeActionRequest,
    UserProfileResponse,
)
from app.services.bold_service import (
    create_bold_checkout_session,
    process_bold_webhook_event,
    verify_bold_webhook_signature,
)
from app.services.supabase_service import supabase_service

router = APIRouter(prefix="/api/billing", tags=["Billing & Bold API"])


@router.post("/checkout", response_model=BoldCheckoutResponse)
async def create_checkout(
    payload: BoldCheckoutRequest,
    authorization: Optional[str] = Header(default=None),
) -> BoldCheckoutResponse:
    """
    Generate a Bold API checkout session ($30.000 COP or $10 USD / month)
    with SHA-256 integrity signature, 3-day free trial, and automatic billing.
    """
    user = supabase_service.get_user_by_token_or_id(authorization or payload.user_id)
    uid = user["user_id"] if user else (payload.user_id or "guest_default")
    return create_bold_checkout_session(
        user_id=uid,
        currency=payload.currency,
        start_trial=payload.start_trial,
        redirect_url=payload.redirect_url,
    )


@router.post("/subscribe", response_model=UserProfileResponse)
async def activate_pro_subscription(
    payload: SubscribeActionRequest,
    authorization: Optional[str] = Header(default=None),
) -> UserProfileResponse:
    """
    Activate the 3-day free trial (with automatic $30.000 COP / $10 USD monthly billing via Bold)
    or immediate Apex Pro subscription for the current user.
    """
    user = supabase_service.get_user_by_token_or_id(authorization or payload.user_id)
    uid = user["user_id"] if user else (payload.user_id or "guest_default")
    checkout = create_bold_checkout_session(
        user_id=uid,
        currency=payload.currency,
        start_trial=True,
    )
    return supabase_service.upgrade_user_to_pro(
        user_id=uid,
        start_trial=True,
        currency=payload.currency,
        order_id=payload.payment_reference or checkout.order_id,
        auto_billing=payload.auto_billing,
    )


@router.post("/bold/webhook")
async def bold_webhook_receiver(request: Request) -> Dict[str, Any]:
    """Webhook endpoint for Bold payment events. Rejects unsigned or tampered payloads."""
    raw = await request.body()
    if not verify_bold_webhook_signature(raw, request.headers.get("x-bold-signature")):
        raise HTTPException(status_code=401, detail="Invalid Bold signature")
    try:
        body = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    return process_bold_webhook_event(body)
