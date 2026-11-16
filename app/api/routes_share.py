"""
Share links (app/api/routes_share.py)
-------------------------------------
- `POST/GET/DELETE /api/jobs/{job_id}/share`: the owner creates, reads or revokes the read-only link.
  Registered accounts only; a guest result is never saved, so it cannot be shared.
- `GET /s/{token}`: the public, read-only page. Rendered on the server, never indexed, sent with
  `Referrer-Policy: no-referrer` (the token is in the URL) and rate limited per network.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api.deps import (
    client_ip,
    media_token,
    public_base_url,
    request_language,
    require_job_owner,
    require_user,
    throttle,
)
from app.config import settings
from app.errors import EXPIRED_RESULT
from app.models.schemas import ShareLinkRequest, ShareLinkResponse, TranscriptionResult
from app.services import report_view, share_links
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.api.routes_share")
router = APIRouter(tags=["Share links"])

_PAGE_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Cache-Control": "private, no-store",
}

_MESSAGES = {
    "es": {
        404: ("Enlace no disponible", "Este enlace no existe o su dueño dejó de compartirlo."),
        410: ("Esta transcripción venció", "El resultado ya no está disponible: venció según el plan de su dueño."),
        429: ("Demasiadas visitas", "Abriste demasiadas páginas en poco tiempo. Intenta de nuevo en un minuto."),
        "back": "Ir a Apex Vox",
    },
    "en": {
        404: ("Link not available", "This link does not exist or its owner stopped sharing it."),
        410: ("This transcript has expired", "The result is no longer available: it expired under its owner's plan."),
        429: ("Too many visits", "You opened too many pages in a short time. Please try again in a minute."),
        "back": "Go to Apex Vox",
    },
}


def _share_url(token: str, request: Optional[Request] = None) -> str:
    return f"{public_base_url(request)}/s/{token}"


def _response(link: Optional[Dict[str, Any]], request: Request) -> ShareLinkResponse:
    if not link:
        return ShareLinkResponse(active=False)
    return ShareLinkResponse(
        active=True,
        url=_share_url(link["token"], request),
        include_audio=link["include_audio"],
        created_at=link.get("created_at"),
    )


def _shareable_result(job_id: str) -> TranscriptionResult:
    result = job_manager.get_job_result(job_id)
    if result:
        return result
    if job_manager.is_expired(job_id):
        raise HTTPException(status_code=410, detail=EXPIRED_RESULT)
    raise HTTPException(status_code=404, detail="Resultado no encontrado. Espera a que termine la transcripción.")


@router.post("/api/jobs/{job_id}/share", response_model=ShareLinkResponse)
def create_share_link(
    payload: ShareLinkRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_user),
    job_id: str = Depends(require_job_owner),
) -> ShareLinkResponse:
    """Create the read-only link of one of your results, or change whether it plays the audio."""
    result = _shareable_result(job_id)
    if result.plan == "guest" or result.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Solo puedes compartir resultados guardados en tu cuenta.")
    throttle(f"share-create:{user['user_id']}", limit=30, window_seconds=3600)
    try:
        link = share_links.create_or_update(job_id, user["user_id"], payload.include_audio)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.") from exc
    return _response(link, request)


@router.get("/api/jobs/{job_id}/share", response_model=ShareLinkResponse)
def get_share_link(
    request: Request,
    user: Dict[str, Any] = Depends(require_user),
    job_id: str = Depends(require_job_owner),
) -> ShareLinkResponse:
    """The result's link, or `{"active": false}`."""
    return _response(share_links.get_for_job(job_id, user["user_id"]), request)


@router.delete("/api/jobs/{job_id}/share", response_model=ShareLinkResponse)
def revoke_share_link(
    user: Dict[str, Any] = Depends(require_user),
    job_id: str = Depends(require_job_owner),
) -> ShareLinkResponse:
    """Stop sharing: the link stops working at once."""
    share_links.revoke(job_id, user["user_id"])
    return ShareLinkResponse(active=False)


# -----------------------------------------------------------------------------
# Public page
# -----------------------------------------------------------------------------


def _asset_version() -> str:
    from app.main import _asset_version as version

    return version()


def _message_page(code: int, lang: str) -> HTMLResponse:
    texts = _MESSAGES[lang]
    heading, body = texts[code]
    html = report_view.render(
        "share_message.html",
        lang=lang, code=code, heading=heading, body=body, back=texts["back"], asset_version=_asset_version(),
    )
    return HTMLResponse(html, status_code=code, headers=_PAGE_HEADERS)


def _shared_by(owner_id: Optional[str], lang: str) -> str:
    L = report_view.LABELS[lang]
    user = supabase_service._read_snapshot()["users"].get(owner_id) if owner_id else None
    first = str((user or {}).get("full_name") or "").strip().split(" ")[0][:40]
    return L["shared_by"].format(name=first) if first else L["shared_by_anon"]


@router.get("/s/{token}", include_in_schema=False, response_class=HTMLResponse)
def shared_page(token: str, request: Request) -> HTMLResponse:
    """The read-only page of a shared result."""
    lang = "en" if request_language(request) == "en" else "es"
    try:
        throttle(f"share-view:{client_ip(request)}", limit=settings.SHARE_VIEWS_PER_MINUTE, window_seconds=60)
    except HTTPException:
        return _message_page(429, lang)

    link = share_links.resolve(token)
    if not link:
        return _message_page(404, lang)
    result = job_manager.get_job_result(link["job_id"])
    if not result:
        return _message_page(410 if job_manager.is_expired(link["job_id"]) else 404, lang)
    if result.user_id != link["user_id"]:
        logger.warning("Share link points to a result of another account; ignored")
        return _message_page(404, lang)

    audio_url = None
    if link["include_audio"] and (settings.OUTPUT_DIR / f"{result.job_id}_merged.mp3").exists():
        audio_url = f"/api/jobs/{result.job_id}/audio?t={media_token(f'job:{result.job_id}')}"

    paid = report_view.owner_has_pro(result.user_id)
    context = report_view.report_context(result, lang, paid, audio_url=audio_url)
    html = report_view.render(
        "share.html",
        **context,
        title=report_view.report_title(result, lang),
        shared_by=_shared_by(result.user_id, lang),
        other_lang="es" if lang == "en" else "en",
        asset_version=_asset_version(),
    )
    return HTMLResponse(html, headers=_PAGE_HEADERS)
