"""Shared request helpers: session resolution and public base URL."""

from __future__ import annotations

import hmac
import ipaddress
import threading
import time
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Header, Query, Request

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


# -----------------------------------------------------------------------------
# Acceso a trabajos y sesiones de subida
# -----------------------------------------------------------------------------
# Solo el dueño (cuenta o invitado por IP) puede leer o modificar un trabajo.
# Para lo que el navegador pide con un enlace normal (<audio src>, descargas, .ics)
# y que no puede llevar la cabecera Authorization, el dueño recibe un token firmado
# (HMAC con el secreto de la app) que caduca a las MEDIA_TOKEN_TTL_SECONDS.

MEDIA_TOKEN_TTL_SECONDS = 6 * 3600


def _media_sig(resource: str, exp: int) -> str:
    return supabase_service._digest(f"media:{resource}:{exp}")[:32]


def media_token(resource: str, ttl: int = MEDIA_TOKEN_TTL_SECONDS) -> str:
    """Token de solo lectura para un recurso, p. ej. 'job:<id>' o 'session:<id>'."""
    exp = int(time.time()) + ttl
    return f"{exp}.{_media_sig(resource, exp)}"


def media_token_valid(resource: str, token: Optional[str]) -> bool:
    try:
        exp_text, sig = (token or "").split(".", 1)
        exp = int(exp_text)
    except ValueError:
        return False
    return exp >= time.time() and hmac.compare_digest(sig, _media_sig(resource, exp))


def job_owner(job_id: str) -> Optional[str]:
    """Cuenta dueña del trabajo, o la clave del invitado que lo creó."""
    from app.services.job_manager import job_manager

    owner = job_manager.job_owner(job_id)
    if owner:
        return owner
    result = job_manager.get_job_result(job_id)  # resultados recargados del disco tras un reinicio
    return result.user_id if result else None


def require_job_owner(
    job_id: str, request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)
) -> str:
    """El trabajo debe pertenecer a quien lo pide; si no, 404 (no se revela si existe)."""
    owner = job_owner(job_id)
    if not owner or owner != requester_key(request, user):
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    return job_id


def require_job_media(
    job_id: str,
    request: Request,
    t: Optional[str] = Query(default=None, description="Token de descarga firmado"),
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> str:
    """Audio, exportaciones y calendario: dueño o token de descarga válido."""
    if media_token_valid(f"job:{job_id}", t):
        return job_id
    return require_job_owner(job_id, request, user)


def require_session_owner(
    session_id: str, request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)
) -> str:
    """La sesión de subida debe pertenecer a quien la pide; si no, 404."""
    from app.services.job_manager import job_manager

    if not job_manager.session_owned_by(session_id, requester_key(request, user)):
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")
    return session_id


def require_session_media(
    session_id: str,
    request: Request,
    t: Optional[str] = Query(default=None, description="Token de descarga firmado"),
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> str:
    """Pistas de una sesión de subida: dueño o token de descarga válido."""
    if media_token_valid(f"session:{session_id}", t):
        return session_id
    return require_session_owner(session_id, request, user)


def require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    """Operational endpoints: disabled unless ADMIN_API_KEY is set and matches."""
    if not settings.ADMIN_API_KEY or not x_admin_key or not hmac.compare_digest(x_admin_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=404, detail="Not Found")


# -----------------------------------------------------------------------------
# Idioma de la página según la petición
# -----------------------------------------------------------------------------

_SPANISH_COUNTRIES = {
    "ES", "MX", "CO", "AR", "PE", "VE", "CL", "EC", "GT", "CU", "BO", "DO", "HN",
    "PY", "SV", "NI", "CR", "PA", "UY", "PR", "GQ",
}


def _default_language(accept_language: str, country: str = "") -> str:
    """
    Idioma inicial: el del dispositivo si es español o inglés; si el dispositivo usa otro
    idioma (o no lo indica), el del país del visitante (cabecera CF-IPCountry de Cloudflare).
    """
    device = _preferred_language(accept_language, default="")
    if device:
        return device
    return "es" if (country or "").strip().upper() in _SPANISH_COUNTRIES else "en"


def _preferred_language(accept_language: str, default: str = "en") -> str:
    """'es' o 'en' según la preferencia del navegador; `default` si no pide ninguno de los dos."""
    best_lang, best_q = default, -1.0
    for part in accept_language.split(","):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        q = 1.0
        if params.strip().startswith("q="):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                q = 0.0
        base = tag.strip().lower().split("-")[0]
        if base in ("es", "en") and q > best_q:
            best_lang, best_q = base, q
    return best_lang


def request_language(request: Request) -> str:
    """?lang=es|en si viene en la URL; si no, el del dispositivo y luego el del país."""
    forced = request.query_params.get("lang")
    if forced in ("es", "en"):
        return forced
    return _default_language(request.headers.get("accept-language", ""), request.headers.get("cf-ipcountry", ""))


def public_base_url(request: Optional[Request] = None) -> str:
    """Absolute origin of the app, e.g. https://apex-vox.ialabs.app (from the request if not configured)."""
    if settings.PUBLIC_BASE_URL or request is None:
        return settings.PUBLIC_BASE_URL or "https://apex-vox.ialabs.app"
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
