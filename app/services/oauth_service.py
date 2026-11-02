"""
Social sign-in through Supabase Auth (app/services/oauth_service.py)
--------------------------------------------------------------------
Server-side PKCE flow, so no Supabase JS runs in the browser:

1. GET /api/auth/oauth/{provider}  -> verifier stored in an httpOnly cookie,
   browser redirected to {SUPABASE_URL}/auth/v1/authorize (Google / GitHub).
2. Supabase redirects back to /api/auth/oauth/callback?code=...
3. The code + verifier are exchanged at /auth/v1/token?grant_type=pkce and the
   verified e-mail is linked to (or creates) an Apex Vox account.

Providers must be enabled in the Supabase dashboard; only enabled ones are offered.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger("app.services.oauth_service")

SUPPORTED_PROVIDERS = ("google", "github")
_cache: Dict[str, Any] = {"at": 0.0, "providers": []}
_CACHE_SECONDS = 300


class OAuthError(RuntimeError):
    """Sign-in could not be completed."""


def _auth_base() -> str:
    return settings.SUPABASE_URL.rstrip("/") + "/auth/v1"


def _anon_headers() -> Dict[str, str]:
    key = settings.SUPABASE_ANON_KEY
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def is_configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY)


def enabled_providers(force: bool = False) -> List[str]:
    """Providers switched on in Supabase Auth (cached for a few minutes)."""
    if not is_configured():
        return []
    now = time.monotonic()
    if not force and now - _cache["at"] < _CACHE_SECONDS:
        return list(_cache["providers"])
    providers: List[str] = []
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{_auth_base()}/settings", headers=_anon_headers())
        external = (resp.json() or {}).get("external", {}) if resp.status_code == 200 else {}
        providers = [p for p in SUPPORTED_PROVIDERS if external.get(p)]
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not read Supabase auth settings: %s", exc)
        providers = list(_cache["providers"])
    _cache.update(at=now, providers=providers)
    return providers


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(provider: str, redirect_to: str, code_challenge: str) -> str:
    if provider not in SUPPORTED_PROVIDERS:
        raise OAuthError("Proveedor no soportado.")
    query = {
        "provider": provider,
        "redirect_to": redirect_to,
        "code_challenge": code_challenge,
        "code_challenge_method": "s256",
    }
    if provider == "github":
        query["scopes"] = "read:user user:email"
    return f"{_auth_base()}/authorize?{urlencode(query)}"


def exchange_code(auth_code: str, code_verifier: str) -> Dict[str, Any]:
    """Exchange the PKCE code; returns the Supabase user (id, email, metadata)."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{_auth_base()}/token",
                params={"grant_type": "pkce"},
                json={"auth_code": auth_code, "code_verifier": code_verifier},
                headers=_anon_headers(),
            )
    except httpx.HTTPError as exc:
        raise OAuthError("No se pudo contactar el servicio de autenticación.") from exc
    if resp.status_code != 200:
        logger.warning("Supabase PKCE exchange failed: %s %s", resp.status_code, resp.text[:200])
        raise OAuthError("El inicio de sesión expiró o fue cancelado.")
    user = (resp.json() or {}).get("user") or {}
    if not user.get("email") or not (user.get("email_confirmed_at") or user.get("confirmed_at")):
        raise OAuthError("La cuenta del proveedor no tiene un correo verificado.")
    return user


def display_name(user: Dict[str, Any]) -> str:
    meta = user.get("user_metadata") or {}
    return str(meta.get("full_name") or meta.get("name") or meta.get("user_name") or "").strip()


def provider_of(user: Dict[str, Any], fallback: str) -> str:
    app_meta = user.get("app_metadata") or {}
    provider = str(app_meta.get("provider") or fallback)
    return provider if provider in SUPPORTED_PROVIDERS else fallback


def extract_provider(cookie_value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Cookie format '<provider>:<verifier>'."""
    if not cookie_value or ":" not in cookie_value:
        return None, None
    provider, verifier = cookie_value.split(":", 1)
    return (provider if provider in SUPPORTED_PROVIDERS else None), verifier or None
