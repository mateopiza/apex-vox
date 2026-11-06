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

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.api.deps import client_ip, enforce_ip_limit, optional_user, public_base_url, require_user, requester_key, throttle
from app.config import settings
from app.models.schemas import (
    NewsletterSubscribeRequest,
    OAuthExchangeRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    QuotaUsageResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
)
from app.services import email_service, oauth_service
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

_OAUTH_COOKIE = "apx_oauth"
_PROVIDER_NAMES = {"google": "google", "github": "github"}
_OAUTH_COOKIE_PATH = "/api/auth/oauth"

router = APIRouter(prefix="/api", tags=["Auth, User Portal & Quotas"])


@router.post("/auth/register", response_model=UserProfileResponse)
def register_user_endpoint(payload: UserRegisterRequest, request: Request) -> UserProfileResponse:
    """
    Register a new user in Supabase Cloud.
    Automatically activates the Free Plan:
    - 2 hours free per day (7,200 seconds) across 1 or multiple audios.
    - 24-hour storage retention in Mega S4.
    """
    try:
        profile = supabase_service.register_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            preferred_language=payload.preferred_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    enforce_ip_limit(request, profile.user_id)
    email_service.send_async(
        profile.email,
        email_service.render_welcome(profile.full_name, profile.preferred_language, _promo_ends(profile)),
        tags=[{"name": "category", "value": "welcome"}],
    )
    return profile


def _promo_ends(profile: UserProfileResponse) -> str | None:
    import datetime as _dt

    try:
        created = _dt.datetime.fromisoformat(str(profile.created_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (created + _dt.timedelta(hours=settings.PROMO_WINDOW_HOURS)).isoformat()


@router.post("/auth/login", response_model=UserProfileResponse)
def login_user_endpoint(payload: UserLoginRequest, request: Request) -> UserProfileResponse:
    """Authenticate an existing user and return profile + daily quota state."""
    throttle(f"login-ip:{client_ip(request)}", limit=20, window_seconds=900)
    try:
        profile = supabase_service.login_user(
            email=payload.email,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        enforce_ip_limit(request, profile.user_id)
    except HTTPException:
        supabase_service.revoke_token(profile.access_token)
        raise
    return profile


class LanguagePreference(BaseModel):
    preferred_language: str


@router.patch("/auth/me/language", response_model=UserProfileResponse)
def update_language(payload: LanguagePreference, user: Dict[str, Any] = Depends(require_user)) -> UserProfileResponse:
    """Idioma de la cuenta (web, correos y extensión)."""
    try:
        return supabase_service.set_preferred_language(user["user_id"], payload.preferred_language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/auth/me", response_model=UserProfileResponse)
def get_current_profile(user: Dict[str, Any] = Depends(require_user)) -> UserProfileResponse:
    """Profile, plan and quota of the signed-in account."""
    return supabase_service.get_profile(user["user_id"])


@router.post("/auth/logout")
def logout_endpoint(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Revoke the current session token."""
    supabase_service.revoke_token(authorization)
    return {"status": "signed_out"}


@router.delete("/auth/account")
def delete_account(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Delete the signed-in account and its data (Ley 1581 de 2012: derecho de supresión)."""
    from app.services import twilio_service

    twilio_service.hangup_all(user["user_id"])  # una llamada en curso no debe seguir grabando
    summary = supabase_service.delete_account(user["user_id"])
    if summary.get("email"):
        email_service.unsubscribe_newsletter_contact(summary["email"])
    return {"status": "deleted", "jobs_deleted": summary["jobs_deleted"]}


@router.get("/auth/security")
def account_security(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Networks used this month vs. the monthly limit."""
    return supabase_service.account_ip_usage(user["user_id"])


@router.get("/auth/config")
def auth_config(request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
    """Public client configuration: sign-in providers, plans and visitor limits."""
    guest_remaining = None if user else supabase_service.guest_audios_remaining(requester_key(request, user))
    return {
        "oauth_providers": oauth_service.enabled_providers(),
        "pro_period_days": settings.PRO_PERIOD_DAYS,
        "pro_price_usd": settings.PRO_PRICE_USD,
        "promo_discount_pct": settings.PROMO_DISCOUNT_PCT,
        "promo_window_hours": settings.PROMO_WINDOW_HOURS,
        "promo_ip_cooldown_days": settings.PROMO_IP_COOLDOWN_DAYS,
        "billing_configured": settings.is_bold_configured,
        "guest_max_audios": settings.GUEST_MAX_AUDIOS_PER_DAY,
        "guest_max_minutes": settings.GUEST_MAX_AUDIO_MINUTES,
        "guest_audios_remaining": guest_remaining,
        "newsletter_enabled": settings.is_email_configured,
    }


@router.post("/auth/password/forgot")
def forgot_password(payload: PasswordForgotRequest, request: Request) -> Dict[str, Any]:
    """E-mail a one-time reset link. Always answers the same way (no account enumeration)."""
    email = (payload.email or "").strip().lower()
    throttle(f"forgot-ip:{client_ip(request)}", limit=5, window_seconds=3600)
    throttle(f"forgot-mail:{email}", limit=1, window_seconds=60)
    issued = supabase_service.create_password_reset(email, ttl_minutes=60)
    if issued:
        token, user = issued
        lang = payload.lang if payload.lang in ("es", "en") else user.get("preferred_language", "es")
        reset_url = f"{public_base_url(request)}/?reset_token={token}"
        email_service.send_async(
            user["email"],
            email_service.render_password_reset(user.get("full_name", ""), reset_url, 60, lang),
            tags=[{"name": "category", "value": "password_reset"}],
        )
    return {"status": "sent_if_exists"}


@router.post("/auth/password/reset", response_model=UserProfileResponse)
def reset_password(payload: PasswordResetRequest, request: Request) -> UserProfileResponse:
    """Set a new password with a valid reset token; signs out other sessions."""
    throttle(f"reset-ip:{client_ip(request)}", limit=10, window_seconds=3600)
    try:
        return supabase_service.reset_password(payload.token, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/newsletter/subscribe")
def newsletter_subscribe(payload: NewsletterSubscribeRequest, request: Request) -> Dict[str, Any]:
    """Start a double opt-in subscription: we e-mail a confirmation link."""
    email = (payload.email or "").strip().lower()
    throttle(f"news-ip:{client_ip(request)}", limit=5, window_seconds=3600)
    throttle(f"news-mail:{email}", limit=1, window_seconds=120)
    lang = payload.lang if payload.lang in ("es", "en") else "es"
    try:
        token = supabase_service.newsletter_request(email, lang)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if token:
        confirm_url = f"{public_base_url(request)}/api/newsletter/confirm?token={token}"
        email_service.send_async(
            email,
            email_service.render_newsletter_confirm(confirm_url, lang),
            tags=[{"name": "category", "value": "newsletter_confirm"}],
        )
    return {"status": "pending_confirmation"}


@router.get("/newsletter/confirm", include_in_schema=False)
def newsletter_confirm(request: Request, token: str = "") -> RedirectResponse:
    """Confirmation link from the e-mail: adds the contact to the Resend segment + topic."""
    confirmed = supabase_service.newsletter_confirm(token)
    if not confirmed:
        return RedirectResponse(url="/?newsletter=invalid", status_code=303)
    email = confirmed["email"]
    lang = confirmed["lang"]
    email_service.upsert_newsletter_contact(email)
    unsub = (
        f"{public_base_url(request)}/api/newsletter/unsubscribe?email={email}"
        f"&token={supabase_service.newsletter_unsubscribe_token(email)}"
    )
    email_service.send_async(
        email,
        email_service.render_newsletter_welcome(unsub, lang),
        tags=[{"name": "category", "value": "newsletter_welcome"}],
        headers={"List-Unsubscribe": f"<{unsub}>"},
    )
    return RedirectResponse(url="/?newsletter=confirmed", status_code=303)


@router.get("/newsletter/unsubscribe", include_in_schema=False)
def newsletter_unsubscribe(email: str = "", token: str = "") -> RedirectResponse:
    """One-click unsubscribe link (also used in the List-Unsubscribe header)."""
    if not supabase_service.newsletter_unsubscribe(email, token):
        return RedirectResponse(url="/?newsletter=invalid", status_code=303)
    email_service.unsubscribe_newsletter_contact(email.strip().lower())
    return RedirectResponse(url="/?newsletter=unsubscribed", status_code=303)


@router.get("/auth/oauth/callback", include_in_schema=False)
def oauth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None) -> RedirectResponse:
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
        is_new = not supabase_service.email_registered(sb_user["email"])
        profile = supabase_service.upsert_oauth_user(
            email=sb_user["email"],
            full_name=oauth_service.display_name(sb_user),
            provider=oauth_service.provider_of(sb_user, provider),
            supabase_id=sb_user.get("id"),
            app_metadata=sb_user.get("app_metadata"),
        )
    except (oauth_service.OAuthError, ValueError):
        return finish("auth_error=failed")
    if is_new:
        email_service.send_async(
            profile.email,
            email_service.render_welcome(profile.full_name, profile.preferred_language, _promo_ends(profile)),
            tags=[{"name": "category", "value": "welcome"}],
        )
    supabase_service.revoke_token(profile.access_token)  # the browser gets its own session from the code
    handoff = supabase_service.create_handoff_code(profile.user_id)
    return finish(f"auth_code={handoff}")


@router.get("/auth/oauth/{provider}", include_in_schema=False)
def oauth_start(provider: str, request: Request) -> RedirectResponse:
    """Start Google / GitHub sign-in through Supabase Auth (PKCE)."""
    if provider not in oauth_service.enabled_providers():
        return RedirectResponse(url="/?auth_error=provider_disabled", status_code=303)
    provider = _PROVIDER_NAMES.get(provider, "")  # valor constante, nunca el texto de la URL
    if not provider:
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
def oauth_exchange(payload: OAuthExchangeRequest, request: Request) -> UserProfileResponse:
    """Swap the one-time code from the OAuth redirect for a session."""
    profile = supabase_service.consume_handoff_code(payload.code)
    if not profile:
        raise HTTPException(status_code=401, detail="El código de inicio de sesión expiró. Intenta de nuevo.")
    try:
        enforce_ip_limit(request, profile.user_id)
    except HTTPException:
        supabase_service.revoke_token(profile.access_token)
        raise
    return profile


@router.get("/auth/quota", response_model=QuotaUsageResponse)
def get_quota_status(user: Optional[Dict[str, Any]] = Depends(optional_user)) -> QuotaUsageResponse:
    """Daily audio quota (2h/day free vs unlimited Pro) of the signed-in account."""
    return supabase_service.get_user_quota(user["user_id"] if user else "guest_default")


@router.get("/portal/summary")
def get_user_portal_summary(user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
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
