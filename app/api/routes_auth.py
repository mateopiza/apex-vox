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

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import settings
from app.models.schemas import (
    QuotaUsageResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
)
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

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


@router.get("/auth/quota", response_model=QuotaUsageResponse)
async def get_quota_status(
    user_id: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> QuotaUsageResponse:
    """Return daily audio quota usage (2h/day free vs unlimited Pro) and retention policy."""
    user = supabase_service.get_user_by_token_or_id(authorization or user_id)
    uid = user["user_id"] if user else (user_id or "guest_default")
    return supabase_service.get_user_quota(uid)


@router.get("/portal/summary")
async def get_user_portal_summary(
    user_id: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Return complete User Portal dashboard state:
    - User profile & active plan (Free 2h/day + 24h vs Pro $30.000 COP / $10 USD unlimited)
    - Daily quota meter
    - Transcriptions stored in Supabase Cloud & Mega S4
    - Product suite roadmap (Apex Vox, Apex Summa, Apex Box)
    """
    user = supabase_service.get_user_by_token_or_id(authorization or user_id)
    uid = user["user_id"] if user else (user_id or "guest_default")
    quota = supabase_service.get_user_quota(uid)
    transcriptions = supabase_service.list_user_transcriptions(uid if user else None)
    s4_objects = mega_s4_storage.list_user_objects(uid if user else None)

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
                "status": "active_session",
                "badge_es": "En Desarrollo (Activo en Pro)",
                "badge_en": "In Development (Active in Pro)",
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
