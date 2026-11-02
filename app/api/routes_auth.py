"""
Authentication, User Portal & Quota Routes (app/api/routes_auth.py)
-------------------------------------------------------------------
Provides endpoints for:
- User Registration (grants 2 hours free per day across 1 or multiple audios + 24h storage)
- User Login & Profile lookup (backed by Supabase Cloud)
- User Portal Dashboard Summary (quota meter, Mega S4 objects, transcription history,
  and Apex Vox / Apex Summa / Apex Box product suite status)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.api.deps import optional_user, public_base_url, require_user
from app.config import settings
from app.models.schemas import (
    OAuthExchangeRequest,
    QuotaUsageResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
)
from app.services import oauth_service
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

_OAUTH_COOKIE = "apx_oauth"
_OAUTH_COOKIE_PATH = "/api/auth/oauth"

router = APIRouter(prefix="/api", tags=["Auth, User Portal & Quotas"])


@router.post("/auth/register", response_model=UserProfileResponse)
async def register_user_endpoint(payload: UserRegisterRequest) -> UserProfileResponse:
    """
    Register a new user in Supabase Cloud.
    Automatically activates the Free Plan:
    - 2 hours free per day (7,200 seconds) across 1 or multiple audios.
    - 24-hour storage retention in Mega S4.
    """
    try:
        return supabase_service.register_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            preferred_language=payload.preferred_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/login", response_model=UserProfileResponse)
async def login_user_endpoint(payload: UserLoginRequest) -> UserProfileResponse:
    """Authenticate an existing user and return profile + daily quota state."""
    try:
        return supabase_service.login_user(
            email=payload.email,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/auth/me", response_model=UserProfileResponse)
async def get_current_profile(user: Dict[str, Any] = Depends(require_user)) -> UserProfileResponse:
    """Profile, plan and quota of the signed-in account."""
    return supabase_service.get_profile(user["user_id"])


@router.post("/auth/logout")
async def logout_endpoint(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Revoke the current session token."""
    supabase_service.revoke_token(authorization)
    return {"status": "signed_out"}


@router.get("/auth/config")
async def auth_config() -> Dict[str, Any]:
    """Public client configuration: social providers and playground rules."""
    return {
        "oauth_providers": oauth_service.enabled_providers(),
        "plan_simulator": settings.ALLOW_PLAN_SIMULATOR,
        "require_login": settings.REQUIRE_LOGIN_TO_TRANSCRIBE,
        "trial_days": settings.PRO_TRIAL_DAYS,
        "pro_period_days": settings.PRO_PERIOD_DAYS,
        "billing_configured": settings.is_bold_configured,
    }


@router.get("/auth/oauth/callback", include_in_schema=False)
async def oauth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None) -> RedirectResponse:
    """Supabase redirects here after Google / GitHub; hands a one-time code to the UI."""
    provider, verifier = oauth_service.extract_provider(request.cookies.get(_OAUTH_COOKIE))

    def finish(query: str) -> RedirectResponse:
        resp = RedirectResponse(url=f"/?{query}", status_code=303)
        resp.delete_cookie(_OAUTH_COOKIE, path=_OAUTH_COOKIE_PATH)
        return resp

    if error or not code:
        return finish("auth_error=cancelled")
    if not provider or not verifier:
        return finish("auth_error=expired")
    try:
        sb_user = oauth_service.exchange_code(code, verifier)
        profile = supabase_service.upsert_oauth_user(
            email=sb_user["email"],
            full_name=oauth_service.display_name(sb_user),
            provider=oauth_service.provider_of(sb_user, provider),
        )
    except (oauth_service.OAuthError, ValueError):
        return finish("auth_error=failed")
    handoff = supabase_service.create_handoff_code(profile.access_token)
    return finish(f"auth_code={handoff}")


@router.get("/auth/oauth/{provider}", include_in_schema=False)
async def oauth_start(provider: str, request: Request) -> RedirectResponse:
    """Start Google / GitHub sign-in through Supabase Auth (PKCE)."""
    if provider not in oauth_service.enabled_providers():
        return RedirectResponse(url="/?auth_error=provider_disabled", status_code=303)
    verifier, challenge = oauth_service.new_pkce_pair()
    callback = f"{public_base_url(request)}/api/auth/oauth/callback"
    resp = RedirectResponse(url=oauth_service.authorize_url(provider, callback, challenge), status_code=303)
    resp.set_cookie(
        _OAUTH_COOKIE,
        f"{provider}:{verifier}",
        max_age=600,
        httponly=True,
        secure=callback.startswith("https://"),
        samesite="lax",
        path=_OAUTH_COOKIE_PATH,
    )
    return resp


@router.post("/auth/oauth/exchange", response_model=UserProfileResponse)
async def oauth_exchange(payload: OAuthExchangeRequest) -> UserProfileResponse:
    """Swap the one-time code from the OAuth redirect for a session."""
    profile = supabase_service.consume_handoff_code(payload.code)
    if not profile:
        raise HTTPException(status_code=401, detail="El código de inicio de sesión expiró. Intenta de nuevo.")
    return profile


@router.get("/auth/quota", response_model=QuotaUsageResponse)
async def get_quota_status(user: Optional[Dict[str, Any]] = Depends(optional_user)) -> QuotaUsageResponse:
    """Daily audio quota (2h/day free vs unlimited Pro) of the signed-in account."""
    return supabase_service.get_user_quota(user["user_id"] if user else "guest_default")


@router.get("/portal/summary")
async def get_user_portal_summary(user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
    """
    User Portal dashboard for the signed-in account (guest view without a session):
    profile & plan, daily quota, Supabase/Mega S4 transcription history, product suite.
    """
    uid = user["user_id"] if user else "guest_default"
    quota = supabase_service.get_user_quota(uid)
    transcriptions = supabase_service.list_user_transcriptions(uid) if user else []
    s4_objects = mega_s4_storage.list_user_objects(uid) if user else []

    return {
        "user": {
            "user_id": uid,
            "email": user.get("email", "invitado@apexvox.ai") if user else "invitado@apexvox.ai",
            "full_name": user.get("full_name", "Usuario Invitado") if user else "Usuario Invitado",
            "plan": quota.plan,
            "preferred_language": user.get("preferred_language", "es") if user else "es",
        },
        "quota": quota.model_dump(mode="json"),
        "storage": {
            "provider": "MEGA S4 (S3-Compatible Object Storage)",
            "endpoint": mega_s4_storage.endpoint_url,
            "bucket": mega_s4_storage.bucket,
            "cloud_configured": mega_s4_storage.is_cloud_configured,
            "retention_policy": "Ilimitado (Plan Pro)" if quota.is_unlimited else f"{settings.FREE_RETENTION_HOURS} horas (Plan Gratis)",
            "objects_count": len(s4_objects),
            "objects": s4_objects[:20],
        },
        "backend": {
            "provider": "Supabase Cloud",
            "cloud_configured": supabase_service.is_cloud_configured,
        },
        "transcriptions": transcriptions[:25],
        "suite": [
            {
                "part": "Transcripción (el núcleo)",
                "name": "Apex Vox",
                "status": "ready",
                "badge_es": "Producto Listo",
                "badge_en": "Product Ready",
            },
            {
                "part": "Notas, analítica y resúmenes IA",
                "name": "Apex Summa",
                "status": "active",
                "badge_es": "Activo en Plan Pro",
                "badge_en": "Active on Pro Plan",
            },
            {
                "part": "Bot de reuniones / llamadas / grabación estática",
                "name": "Apex Box",
                "status": "coming_soon",
                "badge_es": "Próximamente",
                "badge_en": "Coming Soon",
            },
        ],
        "engines": [
            {
                "id": "Mc-Ayrton",
                "name": "Mc-Ayrton",
                "role_es": "El Mejor · Máxima Precisión Acústica",
                "role_en": "The Best · Maximum Acoustic Precision",
                "powered_by": "Groq",
            },
            {
                "id": "Mc-Lewis",
                "name": "Mc-Lewis",
                "role_es": "Modo Híbrido · Balance Ideal",
                "role_en": "Hybrid Mode · Optimal Balance",
                "powered_by": "Groq",
            },
            {
                "id": "Mc-Norris",
                "name": "Mc-Norris",
                "role_es": "Separación por Timbre y Huella Vocal",
                "role_en": "Voiceprint & Timbre Separation",
                "powered_by": "Groq",
            },
            {
                "id": "Mc-Piastri",
                "name": "Mc-Piastri",
                "role_es": "Velocidad Contextual Ultra-Rápida",
                "role_en": "Ultra-Fast Contextual Speed",
                "powered_by": "Groq",
            },
        ],
    }
