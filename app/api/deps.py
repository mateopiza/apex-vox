"""Shared request helpers: session resolution and public base URL."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request

from app.config import settings
from app.services.supabase_service import supabase_service


IP_LIMIT_DETAIL = (
    "Esta cuenta ya se usó desde {limit} redes distintas este mes. Por seguridad no se puede usar "
    "desde una nueva hasta el próximo mes. / This account was already used from {limit} different "
    "networks this month."
)


def enforce_ip_limit(request: Request, user_id: str) -> None:
    """403 when the account is used from a new network beyond MAX_IPS_PER_MONTH."""
    if not supabase_service.register_account_ip(user_id, client_ip(request)):
        raise HTTPException(status_code=403, detail=IP_LIMIT_DETAIL.format(limit=settings.MAX_IPS_PER_MONTH))


def optional_user(request: Request, authorization: Optional[str] = Header(default=None)) -> Optional[Dict[str, Any]]:
    """User behind the `Authorization: Bearer apx_...` session token, if any."""
    user = supabase_service.get_user_by_token(authorization)
    if user:
        enforce_ip_limit(request, user["user_id"])
    return user


def require_user(request: Request, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    user = supabase_service.get_user_by_token(authorization)
    if user:
        enforce_ip_limit(request, user["user_id"])
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Inicia sesión o crea tu cuenta para continuar / Please sign in to continue.",
        )
    return user


def is_paid(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user) and str(user.get("plan", "free")).lower() in ("pro", "trial")


def client_ip(request: Request) -> str:
    """
    Visitor IP. Behind Traefik the right-most X-Forwarded-For entry is the address
    the proxy saw; earlier entries are client-supplied and can be forged.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def requester_key(request: Request, user: Optional[Dict[str, Any]]) -> str:
    """Owner id for sessions/jobs: the account id, or a pseudonymous guest key."""
    if user:
        return user["user_id"]
    return supabase_service.guest_key(client_ip(request))


def require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    """Operational endpoints: disabled unless ADMIN_API_KEY is set and matches."""
    import hmac

    if not settings.ADMIN_API_KEY or not x_admin_key or not hmac.compare_digest(x_admin_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=404, detail="Not Found")


def public_base_url(request: Request) -> str:
    """Absolute origin of the app, e.g. https://apex-vox.ialabs.app."""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")


_throttle_lock = threading.Lock()
_throttle_hits: Dict[str, list] = {}


def throttle(key: str, limit: int, window_seconds: int) -> None:
    """Simple in-process rate limit for e-mail-sending endpoints (429 when exceeded)."""
    now = time.monotonic()
    with _throttle_lock:
        hits = [t for t in _throttle_hits.get(key, []) if now - t < window_seconds]
        if len(hits) >= limit:
            _throttle_hits[key] = hits
            raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en unos minutos.")
        hits.append(now)
        _throttle_hits[key] = hits
