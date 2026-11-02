"""
Bold API Payment & Subscription Service (app/services/bold_service.py)
----------------------------------------------------------------------
Integrates Bold API (bold.co) for Apex Vox Pro subscriptions:
- Monthly Plan: $30.000 COP / $10 USD per month.
- 3-Day Free Trial ('prueba gratis de 3 días') with automatic recurring charge ('cobro automático').
- Generates official Bold SHA-256 integrity signature:
    SHA256(f"{order_id}{amount}{currency}{secret_key}")
- Handles Bold Webhook notifications (SALE_APPROVED, SUBSCRIPTION_ACTIVE, etc.).
"""

from __future__ import annotations

import hashlib
import hmac
import base64
import logging
import re
import uuid
from typing import Any, Dict, Optional

from app.config import settings
from app.models.schemas import BoldCheckoutResponse

logger = logging.getLogger("app.services.bold_service")


def compute_bold_integrity_signature(
    order_id: str,
    amount: int | str,
    currency: str,
    secret_key: Optional[str] = None,
) -> str:
    """
    Compute Bold's required SHA-256 integrity hash:
    SHA256(f"{order_id}{amount}{currency}{secret_key}")
    """
    sec = (secret_key if secret_key is not None else settings.BOLD_SECRET_KEY) or "bold_test_secret_key"
    raw = f"{order_id}{amount}{currency.upper()}{sec}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_bold_checkout_session(
    user_id: Optional[str] = None,
    currency: str = "COP",
    start_trial: bool = True,
    redirect_url: Optional[str] = None,
) -> BoldCheckoutResponse:
    """
    Build a Bold API Checkout payload for the Apex Pro Plan:
    $30.000 COP / $10 USD monthly with 3-day free trial and automatic billing.
    """
    curr = (currency or "COP").strip().upper()
    if curr not in ("COP", "USD"):
        curr = "COP"

    amount = settings.PRO_PRICE_COP if curr == "COP" else int(settings.PRO_PRICE_USD)
    amount_display = "$30.000 COP / mes" if curr == "COP" else "$10 USD / month"
    order_id = build_order_reference(user_id)

    signature = compute_bold_integrity_signature(
        order_id=order_id,
        amount=amount,
        currency=curr,
    )
    api_key = settings.BOLD_API_KEY or "bold_pk_live_apex_vox"
    ret_url = redirect_url or "http://localhost:8000/?view=portal&billing=success"

    checkout_url = (
        f"https://checkout.bold.co/payment/{order_id}"
        f"?api-key={api_key}"
        f"&amount={amount}"
        f"&currency={curr}"
        f"&integrity-signature={signature}"
        f"&trial-days={settings.PRO_TRIAL_DAYS if start_trial else 0}"
        f"&auto-renew=true"
        f"&redirection-url={ret_url}"
    )

    return BoldCheckoutResponse(
        order_id=order_id,
        amount=amount,
        currency=curr,
        amount_display=amount_display,
        trial_days=settings.PRO_TRIAL_DAYS if start_trial else 0,
        auto_billing=True,
        bold_api_key=api_key,
        integrity_signature=signature,
        checkout_url=checkout_url,
        plan_summary=(
            f"Apex Vox Pro — Prueba gratis de {settings.PRO_TRIAL_DAYS} días, "
            f"luego cobro automático de $30.000 COP / $10 USD al mes. "
            f"Transcripciones y almacenamiento ilimitados en Mega S4 + Apex Summa IA."
        ),
    )


ORDER_PREFIX = "APEXVOX"
_PAID_EVENTS = {"SALE_APPROVED"}


def build_order_reference(user_id: Optional[str]) -> str:
    """Order reference sent to Bold; embeds our user id so the webhook can map it back."""
    suffix = uuid.uuid4().hex[:8].upper()
    uid = (user_id or "").strip()
    if not uid or uid == "guest_default" or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", uid):
        return f"{ORDER_PREFIX}-{suffix}"
    return f"{ORDER_PREFIX}-{uid}-{suffix}"


def user_id_from_order_reference(reference: Optional[str]) -> Optional[str]:
    """Inverse of build_order_reference(); returns None for anonymous references."""
    ref = (reference or "").strip()
    if not ref.startswith(f"{ORDER_PREFIX}-"):
        return None
    body = ref[len(ORDER_PREFIX) + 1 :]
    if "-" not in body:
        return None
    uid = body.rsplit("-", 1)[0]
    return uid or None


def _webhook_secret() -> Optional[str]:
    """Key Bold uses to sign notifications. Empty string = Bold sandbox mode."""
    secret = settings.BOLD_WEBHOOK_SECRET or settings.BOLD_SECRET_KEY
    if secret:
        return secret
    # Without a key every payload would be accepted with the sandbox (empty) key:
    # never allow that in production.
    return None if settings.is_production else ""


def verify_bold_webhook_signature(raw_body: bytes, signature: Optional[str]) -> bool:
    """
    Bold signs webhooks as hex(HMAC-SHA256(secret, base64(raw_body))) in the
    `x-bold-signature` header.
    """
    secret = _webhook_secret()
    if secret is None or not signature:
        return False
    encoded = base64.b64encode(raw_body)
    expected = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def process_bold_webhook_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a verified Bold webhook (CloudEvents format) and upgrade the user
    referenced by `data.metadata.reference` to Apex Pro.
    """
    from app.services.supabase_service import supabase_service

    event_type = str(payload.get("type") or "").upper()
    data = payload.get("data") or {}
    metadata = data.get("metadata") or {}
    reference = metadata.get("reference") or data.get("order_id") or data.get("reference")
    amount = data.get("amount") or {}
    currency = str((amount.get("currency") if isinstance(amount, dict) else None) or data.get("currency") or "COP").upper()
    user_id = user_id_from_order_reference(reference)

    if event_type not in _PAID_EVENTS or not user_id:
        logger.info("Bold webhook ignored: type=%s reference=%s", event_type or "-", reference)
        return {"status": "ignored", "event_type": event_type or None, "order_id": reference}

    profile = supabase_service.upgrade_user_to_pro(
        user_id=user_id,
        start_trial=False,
        currency=currency,
        order_id=str(reference),
        auto_billing=True,
    )
    return {
        "status": "processed",
        "event_type": event_type,
        "order_id": reference,
        "user_id": user_id,
        "upgraded_plan": profile.plan,
        "auto_billing": True,
    }
