"""Shared request helpers: session resolution and public base URL."""

from __future__ import annotations

import ipaddress

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


# Rangos oficiales de Cloudflare (https://www.cloudflare.com/ips/). El origen solo acepta
# tráfico desde ellos (Traefik ipAllowList), así que CF-Connecting-IP es fiable solo cuando
# la conexión llega desde uno de estos rangos.
_CLOUDFLARE_RANGES = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)]


def _is_cloudflare(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in _CLOUDFLARE_RANGES)


def client_ip(request: Request) -> str:
    """
    IP real del visitante. Traefik pone en el último X-Forwarded-For la dirección que vio
    (las anteriores las envía el cliente y se pueden falsificar). Si esa dirección es de
    Cloudflare, la IP del visitante es CF-Connecting-IP.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    peer = forwarded.split(",")[-1].strip() if forwarded else ""
    if not peer:
        peer = request.client.host if request.client else "unknown"
    if _is_cloudflare(peer):
        real = request.headers.get("cf-connecting-ip", "").strip()
        try:
            return str(ipaddress.ip_address(real))
        except ValueError:
            pass
    return peer


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
