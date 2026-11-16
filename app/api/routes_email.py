"""
Send a result by email (app/api/routes_email.py)
------------------------------------------------
`POST /api/jobs/{job_id}/email`: the owner sends the summary their plan includes, a button to the
result's share page (created if it has none) and the PDF report attached. Up to 10 recipients;
anyone other than the account itself needs Apex Pro. Replies go to the sender (Reply-To). Each
recipient counts toward EMAIL_SHARE_DAILY_LIMIT per account and day.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import public_base_url, require_job_owner, require_user, run_heavy, throttle, throttle_release
from app.config import settings
from app.errors import EXPIRED_RESULT
from app.models.schemas import EmailResultRequest, EmailResultResponse
from app.services import email_service, pdf_export, report_view, share_links
from app.services.job_manager import job_manager

logger = logging.getLogger("app.api.routes_email")
router = APIRouter(prefix="/api", tags=["Share links"])

MAX_RECIPIENTS = 10
DAY_SECONDS = 24 * 3600


def _clean_recipients(raw: List[str]) -> List[str]:
    seen: Dict[str, str] = {}
    for value in raw:
        for part in str(value or "").replace(";", ",").split(","):
            email = part.strip()
            if email:
                seen.setdefault(email.lower(), email)
    recipients = list(seen.values())
    if not recipients:
        raise HTTPException(status_code=400, detail="Escribe al menos un correo.")
    if len(recipients) > MAX_RECIPIENTS:
        raise HTTPException(status_code=400, detail=f"Puedes enviar a máximo {MAX_RECIPIENTS} correos a la vez.")
    invalid = [r for r in recipients if len(r) > 254 or not email_service.valid_email(r)]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Correo inválido: {invalid[0][:80]}")
    return recipients


@router.post("/jobs/{job_id}/email", response_model=EmailResultResponse)
async def email_result(
    payload: EmailResultRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_user),
    job_id: str = Depends(require_job_owner),
) -> EmailResultResponse:
    """Email the result: summary in the body, button to the share page and the PDF attached."""
    recipients = _clean_recipients(payload.recipients)
    own = str(user.get("email") or "").lower()
    others = [r for r in recipients if r.lower() != own]
    if others and not report_view.owner_has_pro(user["user_id"]):
        raise HTTPException(
            status_code=402,
            detail="Enviar a otras personas está incluido en Apex Pro. Con tu plan puedes enviártelo a ti mismo.",
        )
    if not settings.is_email_configured:
        raise HTTPException(status_code=503, detail="El envío de correos no está disponible en este momento.")
    lang = payload.language if payload.language in ("es", "en") else "es"
    key = f"email-share:{user['user_id']}"
    throttle(
        key, limit=settings.EMAIL_SHARE_DAILY_LIMIT, window_seconds=DAY_SECONDS, cost=len(recipients),
        detail=f"Llegaste al tope de {settings.EMAIL_SHARE_DAILY_LIMIT} destinatarios por día. Intenta mañana.",
    )
    try:
        response = await run_heavy(_send, job_id, user, recipients, payload.message, lang, public_base_url(request))
    except Exception:
        throttle_release(key, len(recipients))
        raise
    throttle_release(key, len(response.failed))
    return response


def _send(
    job_id: str, user: Dict[str, Any], recipients: List[str], message: str, lang: str, base: str
) -> EmailResultResponse:
    result = job_manager.get_job_result(job_id)
    if not result and job_manager.is_expired(job_id):
        raise HTTPException(status_code=410, detail=EXPIRED_RESULT)
    if not result:
        raise HTTPException(status_code=404, detail="Resultado no encontrado. Espera a que termine la transcripción.")
    if result.plan == "guest" or result.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Solo puedes enviar resultados guardados en tu cuenta.")

    link = share_links.get_for_job(job_id, user["user_id"]) or share_links.create_or_update(job_id, user["user_id"], False)
    share_url = f"{base}/s/{link['token']}?lang={lang}"

    attachments = []
    try:
        pdf = pdf_export.result_pdf(result, lang)  # para Apex Pro, también deja listo el resumen en `lang`
        attachments.append({"filename": f"{report_view.report_title(result, lang)[:80]}.pdf".replace("/", "-"), "content": pdf})
    except pdf_export.PdfUnavailableError:
        logger.warning("Result emailed without its PDF: WeasyPrint is not available")
    report = report_view.visible_report(result, report_view.owner_has_pro(user["user_id"]), lang)
    rendered = email_service.render_result_share(
        sender_name=str(user.get("full_name") or ""),
        sender_email=str(user.get("email") or ""),
        title=report_view.report_title(result, lang),
        duration=result.total_duration_formatted,
        report=report,
        share_url=share_url,
        message=message,
        attached_pdf=bool(attachments),
        lang=lang,
    )
    failed = [
        r for r in recipients
        if not email_service.send_email(
            r, rendered, tags=[{"name": "category", "value": "result_share"}],
            attachments=attachments, reply_to=str(user.get("email") or "") or None,
        )
    ]
    if len(failed) == len(recipients):
        raise HTTPException(status_code=502, detail="No pudimos enviar el correo. Intenta de nuevo en unos minutos.")
    return EmailResultResponse(
        sent=len(recipients) - len(failed), failed=failed, share_url=share_url, attached_pdf=bool(attachments),
    )
