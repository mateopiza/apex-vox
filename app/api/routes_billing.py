"""
Billing routes (app/api/routes_billing.py)
------------------------------------------
- POST /api/billing/subscribe : one-time 3-day Apex Pro trial (signed-in accounts only).
- POST /api/billing/checkout  : Bold payment link for 30 days of Apex Pro.
- POST /api/billing/confirm   : re-check the account's pending Bold links (after redirect).
- POST /api/billing/bold/webhook : signed Bold notifications (SALE_APPROVED).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import public_base_url, require_user
from app.models.schemas import (
    BoldCheckoutRequest,
    BoldCheckoutResponse,
    SubscribeActionRequest,
    UserProfileResponse,
)
from app.services import bold_service, email_service
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.api.billing")
router = APIRouter(prefix="/api/billing", tags=["Billing & Bold API"])


@router.post("/subscribe", response_model=UserProfileResponse)
async def start_pro_trial(
    payload: SubscribeActionRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> UserProfileResponse:
    """Activate the 3-day free trial of Apex Pro. Once per account, no card required."""
    try:
        profile = supabase_service.start_trial(user["user_id"])
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    email_service.send_async(
        profile.email,
        email_service.render_trial_started(profile.full_name, profile.quota.trial_ends_at, profile.preferred_language),
        tags=[{"name": "category", "value": "trial_started"}],
    )
    return profile


@router.post("/checkout", response_model=BoldCheckoutResponse)
async def create_checkout(
    payload: BoldCheckoutRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_user),
) -> BoldCheckoutResponse:
    """Create a Bold payment link ($30.000 COP or $10 USD) for 30 days of Apex Pro."""
    callback = f"{public_base_url(request)}/?billing=return"
    if not callback.startswith("https://"):
        # Bold only accepts https callbacks; local development returns to the portal manually.
        callback = "https://apex-vox.ialabs.app/?billing=return"
    try:
        checkout = bold_service.create_payment_link(
            user_id=user["user_id"],
            payer_email=user.get("email"),
            currency=payload.currency,
            callback_url=callback,
        )
    except bold_service.BoldNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="Los pagos con Bold no están configurados.") from exc
    except bold_service.BoldAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    supabase_service.record_pending_payment(
        user_id=user["user_id"],
        reference=checkout.order_id,
        payment_link=checkout.payment_link,
        amount=checkout.amount,
        currency=checkout.currency,
    )
    return checkout


@router.post("/confirm", response_model=UserProfileResponse)
async def confirm_payments(user: Dict[str, Any] = Depends(require_user)) -> UserProfileResponse:
    """
    Ask Bold for the status of this account's pending links and activate the paid ones.
    Covers the case where the payer returns before (or without) the webhook arriving.
    """
    for pending in supabase_service.list_pending_payments(user["user_id"]):
        link = pending.get("payment_link")
        if not link:
            continue
        try:
            status = bold_service.get_payment_link(link)
        except (bold_service.BoldAPIError, bold_service.BoldNotConfiguredError) as exc:
            logger.info("Bold link %s not confirmed: %s", link, exc)
            continue
        if str(status.get("status", "")).upper() == "PAID" and status.get("reference", pending["reference"]) == pending["reference"]:
            supabase_service.activate_paid_period(
                user_id=user["user_id"],
                reference=pending["reference"],
                currency=pending.get("currency", "COP"),
                source="bold_link_status",
                on_activated=bold_service.notify_payment_activated,
            )
    return supabase_service.get_profile(user["user_id"])


@router.post("/bold/webhook")
async def bold_webhook_receiver(request: Request) -> Dict[str, Any]:
    """Webhook endpoint for Bold payment events. Rejects unsigned or tampered payloads."""
    raw = await request.body()
    if not bold_service.verify_bold_webhook_signature(raw, request.headers.get("x-bold-signature")):
        raise HTTPException(status_code=401, detail="Invalid Bold signature")
    try:
        body = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    return bold_service.process_bold_webhook_event(body)
