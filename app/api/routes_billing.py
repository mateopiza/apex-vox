"""
Billing routes (app/api/routes_billing.py)
------------------------------------------
- GET  /api/billing/offer     : current price (USD 10, or USD 8 with the welcome promo).
- POST /api/billing/checkout  : Bold payment link (USD) for 30 days of Apex Pro.
  Bold has no subscriptions: each month is paid manually; nothing renews by itself.
- POST /api/billing/subscribe : retired (the 3-day free trial no longer exists) -> 410.
- POST /api/billing/confirm   : re-check the account's pending Bold links (after redirect).
- POST /api/billing/bold/webhook : signed Bold notifications (SALE_APPROVED).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import client_ip, public_base_url, require_user
from app.models.schemas import (
    BillingOfferResponse,
    BoldCheckoutRequest,
    BoldCheckoutResponse,
    UserProfileResponse,
)
from app.services import bold_service
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.api.billing")
router = APIRouter(prefix="/api/billing", tags=["Billing & Bold API"])


@router.post("/subscribe", status_code=410)
async def trial_retired() -> Dict[str, Any]:
    """The free trial was retired: Apex Pro is activated only by paying."""
    raise HTTPException(
        status_code=410,
        detail=(
            "La prueba gratis ya no está disponible: Apex Pro se activa con el pago del mes. "
            "/ The free trial is no longer available: Apex Pro is activated by paying for the month."
        ),
    )


@router.get("/offer", response_model=BillingOfferResponse)
async def billing_offer(request: Request, user: Dict[str, Any] = Depends(require_user)) -> BillingOfferResponse:
    """Price this account would pay now, including the first-24-hours welcome promo."""
    return BillingOfferResponse(**supabase_service.billing_offer(user["user_id"], client_ip(request)))


@router.post("/checkout", response_model=BoldCheckoutResponse)
async def create_checkout(
    payload: BoldCheckoutRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_user),
) -> BoldCheckoutResponse:
    """Create a Bold payment link in USD for 30 days of Apex Pro (welcome promo applied server-side)."""
    callback = f"{public_base_url(request)}/?billing=return"
    if not callback.startswith("https://"):
        # Bold only accepts https callbacks; local development returns to the portal manually.
        callback = "https://apex-vox.ialabs.app/?billing=return"
    ip = client_ip(request)
    offer = supabase_service.billing_offer(user["user_id"], ip)
    try:
        checkout = bold_service.create_payment_link(
            user_id=user["user_id"],
            payer_email=user.get("email"),
            callback_url=callback,
            amount_usd=offer["price"],
            promo=offer["promo_eligible"],
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
        promo=checkout.promo_applied,
        client_ip=ip,
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
                currency=pending.get("currency", "USD"),
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
