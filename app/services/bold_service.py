"""
Bold payments for Apex Vox Pro (app/services/bold_service.py)
-------------------------------------------------------------
- Each payment buys PRO_PERIOD_DAYS of Apex Pro: USD 10 (USD 8 with the welcome promo).
- Bold has no subscriptions: every month is a new, manual payment link.
- Payments are created through Bold's official "API Link de pagos":
    POST {BOLD_API_BASE_URL}/online/link/v1   (Authorization: x-api-key <llave de identidad>)
  and the payer is redirected to the returned checkout.bold.co URL.
- Bold links are one-off charges; there is no automatic recurring billing.
- Approved payments arrive on the signed webhook (x-bold-signature) and can also be
  confirmed on demand by querying GET /online/link/v1/{payment_link}.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import time
import uuid
from typing import Any, Dict, Optional

import httpx

from app.config import settings
from app.models.schemas import BoldCheckoutResponse

logger = logging.getLogger("app.services.bold_service")

ORDER_PREFIX = "APEXVOX"
_PAID_EVENTS = {"SALE_APPROVED"}
_BOLD_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class BoldNotConfiguredError(RuntimeError):
    """BOLD_API_KEY is missing."""


class BoldAPIError(RuntimeError):
    """Bold rejected the request or returned an unexpected payload."""


# ---------------------------------------------------------------------------
# Order references (our id <-> Bold)
# ---------------------------------------------------------------------------

def build_order_reference(user_id: Optional[str]) -> str:
    """Reference sent to Bold (max 60 chars, [A-Za-z0-9_-]); embeds our user id."""
    suffix = f"{int(time.time()):x}{uuid.uuid4().hex[:4]}".upper()
    uid = (user_id or "").strip()
    if not uid or uid == "guest_default" or not re.fullmatch(r"[A-Za-z0-9-]{1,40}", uid):
        return f"{ORDER_PREFIX}-{suffix}"
    return f"{ORDER_PREFIX}-{uid}-{suffix}"


def user_id_from_order_reference(reference: Optional[str]) -> Optional[str]:
    """Inverse of build_order_reference(); None for anonymous or foreign references."""
    ref = (reference or "").strip()
    if not ref.startswith(f"{ORDER_PREFIX}-"):
        return None
    body = ref[len(ORDER_PREFIX) + 1 :]
    if "-" not in body:
        return None
    uid = body.rsplit("-", 1)[0]
    return uid or None


def compute_bold_integrity_signature(
    order_id: str,
    amount: int | str,
    currency: str = "COP",
    secret_key: Optional[str] = None,
) -> str:
    """Botón de pagos integrity hash: SHA256(f"{order_id}{amount}{currency}{secret_key}")."""
    sec = secret_key if secret_key is not None else settings.BOLD_SECRET_KEY
    raw = f"{order_id}{amount}{currency.upper()}{sec}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Link de pagos API
# ---------------------------------------------------------------------------

def format_usd(amount: float) -> str:
    """10 -> "USD 10", 8.5 -> "USD 8.50"."""
    value = float(amount)
    return f"USD {value:.0f}" if value.is_integer() else f"USD {value:.2f}"


def _bold_amount(amount: float) -> int | float:
    value = round(float(amount), 2)
    return int(value) if value.is_integer() else value


def _bold_request(method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Call the Bold integrations API. Isolated so tests can replace it."""
    if not settings.BOLD_API_KEY:
        raise BoldNotConfiguredError("BOLD_API_KEY no está configurada.")
    url = f"{settings.BOLD_API_BASE_URL}{path}"
    headers = {
        "Authorization": f"x-api-key {settings.BOLD_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=_BOLD_TIMEOUT) as client:
            resp = client.request(method, url, json=json_body, headers=headers)
    except httpx.HTTPError as exc:
        raise BoldAPIError(f"No se pudo contactar a Bold: {exc}") from exc
    try:
        data = resp.json()
    except ValueError as exc:
        raise BoldAPIError(f"Bold respondió {resp.status_code} sin JSON.") from exc
    if resp.status_code >= 400 or data.get("errors"):
        logger.warning("Bold API %s %s -> %s %s", method, path, resp.status_code, data.get("errors"))
        raise BoldAPIError(f"Bold rechazó la solicitud ({resp.status_code}).")
    return data


def create_payment_link(
    user_id: str,
    payer_email: Optional[str],
    callback_url: str,
    amount_usd: float,
    promo: bool = False,
) -> BoldCheckoutResponse:
    """Create a closed-amount Bold payment link (USD) for one Apex Pro period."""
    amount = _bold_amount(amount_usd)
    reference = build_order_reference(user_id)
    description = f"Apex Vox Pro - {settings.PRO_PERIOD_DAYS} dias"
    if promo:
        description += f" (bienvenida -{settings.PROMO_DISCOUNT_PCT}%)"
    body: Dict[str, Any] = {
        "amount_type": "CLOSE",
        "amount": {"currency": "USD", "total_amount": amount, "tip_amount": 0},
        "reference": reference,
        "description": description,
        "callback_url": callback_url,
    }
    if payer_email and "@" in payer_email and not payer_email.endswith(".local"):
        body["payer_email"] = payer_email

    data = _bold_request("POST", "/online/link/v1", body)
    payload = data.get("payload") or {}
    link_id = payload.get("payment_link")
    url = payload.get("url")
    if not link_id or not url:
        raise BoldAPIError("Bold no devolvió la URL del link de pago.")

    return BoldCheckoutResponse(
        order_id=reference,
        payment_link=link_id,
        checkout_url=url,
        amount=float(amount),
        currency="USD",
        amount_display=f"{format_usd(amount)} / {settings.PRO_PERIOD_DAYS} días",
        period_days=settings.PRO_PERIOD_DAYS,
        promo_applied=promo,
        regular_amount=float(settings.PRO_PRICE_USD),
        discount_pct=settings.PROMO_DISCOUNT_PCT if promo else 0,
        plan_summary=(
            f"Apex Vox Pro por {settings.PRO_PERIOD_DAYS} días: transcripciones y almacenamiento "
            f"ilimitados + Apex Summa IA. Pago único con Bold; no se renueva solo."
        ),
    )


def get_payment_link(payment_link: str) -> Dict[str, Any]:
    """Status of a Bold link: ACTIVE, PROCESSING, PAID, REJECTED, CANCELLED, EXPIRED."""
    if not re.fullmatch(r"LNK_[A-Za-z0-9]+", payment_link or ""):
        raise BoldAPIError("Identificador de link inválido.")
    data = _bold_request("GET", f"/online/link/v1/{payment_link}")
    return data.get("payload") or data


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def _webhook_secret() -> Optional[str]:
    """Key Bold uses to sign notifications. Empty string = Bold sandbox mode."""
    secret = settings.BOLD_WEBHOOK_SECRET or settings.BOLD_SECRET_KEY
    if secret:
        return secret
    # Without a key every payload would verify against the sandbox (empty) key:
    # never allow that in production.
    return None if settings.is_production else ""


def verify_bold_webhook_signature(raw_body: bytes, signature: Optional[str]) -> bool:
    """Bold signs webhooks as hex(HMAC-SHA256(secret, base64(raw_body))) in `x-bold-signature`."""
    secret = _webhook_secret()
    if secret is None or not signature:
        return False
    encoded = base64.b64encode(raw_body)
    expected = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def notify_payment_activated(user: Dict[str, Any], payment: Dict[str, Any]) -> None:
    """Receipt e-mail, sent once per approved payment."""
    from app.services import email_service

    amount_display = format_usd(payment.get("amount") or settings.PRO_PRICE_USD)
    if payment.get("promo"):
        amount_display += f" (-{settings.PROMO_DISCOUNT_PCT}% bienvenida)"
    email_service.send_async(
        user.get("email", ""),
        email_service.render_payment_confirmed(
            user.get("full_name", ""),
            user.get("pro_until"),
            amount_display,
            str(payment.get("reference", "")),
            user.get("preferred_language", "es"),
        ),
        tags=[{"name": "category", "value": "payment_receipt"}],
    )


def process_bold_webhook_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle a verified Bold notification (CloudEvents format): SALE_APPROVED grants one
    Apex Pro period to the account referenced by `data.metadata.reference`.
    """
    from app.services.supabase_service import supabase_service

    event_type = str(payload.get("type") or "").upper()
    data = payload.get("data") or {}
    metadata = data.get("metadata") or {}
    reference = metadata.get("reference") or data.get("reference") or data.get("order_id")
    amount = data.get("amount") or {}
    currency = str((amount.get("currency") if isinstance(amount, dict) else None) or "USD").upper()
    user_id = user_id_from_order_reference(reference)

    if event_type not in _PAID_EVENTS or not user_id:
        logger.info("Bold webhook ignored: type=%s reference=%s", event_type or "-", reference)
        return {"status": "ignored", "event_type": event_type or None, "order_id": reference}

    try:
        profile = supabase_service.activate_paid_period(
            user_id=user_id,
            reference=str(reference),
            currency=currency,
            source="bold_webhook",
            on_activated=notify_payment_activated,
        )
    except (LookupError, PermissionError) as exc:
        logger.warning("Bold webhook for %s not applied: %s", reference, exc)
        return {"status": "ignored", "event_type": event_type, "order_id": reference}

    return {
        "status": "processed",
        "event_type": event_type,
        "order_id": reference,
        "user_id": user_id,
        "upgraded_plan": profile.plan,
        "pro_until": profile.quota.pro_until,
    }
