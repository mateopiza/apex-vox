"""Shared request helpers: session resolution and public base URL."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request

from app.config import settings
from app.services.supabase_service import supabase_service


def optional_user(authorization: Optional[str] = Header(default=None)) -> Optional[Dict[str, Any]]:
    """User behind the `Authorization: Bearer apx_...` session token, if any."""
    return supabase_service.get_user_by_token(authorization)


def require_user(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    user = supabase_service.get_user_by_token(authorization)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Inicia sesión o crea tu cuenta para continuar / Please sign in to continue.",
        )
    return user


def is_paid(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user) and str(user.get("plan", "free")).lower() in ("pro", "trial")


def public_base_url(request: Request) -> str:
    """Absolute origin of the app, e.g. https://apex-vox.ialabs.app."""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")
