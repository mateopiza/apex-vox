"""
Llamadas grabadas con número enmascarado (app/api/routes_calls.py)
-----------------------------------------------------------------
Cuenta (sesión web, Apex Pro):
- GET    /api/phone                      : estado del celular verificado y de las llamadas
- POST   /api/phone/verify/start         : enviar código SMS al celular
- POST   /api/phone/verify/check         : confirmar el código
- DELETE /api/phone                      : quitar el celular
- GET    /api/calls                      : llamadas recientes
- POST   /api/calls                      : llamar (Twilio llama primero a tu celular)
- GET    /api/calls/{call_id}            : estado de una llamada
- POST   /api/calls/{call_id}/notes      : apunte durante la llamada
- POST   /api/calls/{call_id}/hangup     : colgar / cancelar

Webhooks de Twilio (firma X-Twilio-Signature):
- POST /api/twilio/voice/{call_id}       : contestaste → «pulsa 1»
- POST /api/twilio/connect/{call_id}     : pulsaste 1 → marcar al contacto y grabar
- POST /api/twilio/notice/{call_id}      : aviso de grabación para el contacto
- POST /api/twilio/dial-done/{call_id}   : resultado de la marcación
- POST /api/twilio/status/{call_id}      : estados de cada tramo
- POST /api/twilio/recording/{call_id}   : grabación lista
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import client_ip, is_paid, require_user, throttle
from app.services import twilio_service
from app.services.twilio_service import TwilioError

router = APIRouter(tags=["Llamadas"])

PRO_DETAIL = "Las llamadas grabadas están incluidas en Apex Pro."


class PhoneStart(BaseModel):
    phone: str = Field(max_length=32)


class PhoneCheck(BaseModel):
    phone: str = Field(max_length=32)
    code: str = Field(max_length=10)


class CallRequest(BaseModel):
    to: str = Field(max_length=32)
    title: Optional[str] = Field(default=None, max_length=120)
    contact_name: Optional[str] = Field(default=None, max_length=80)


class CallNote(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    tag: str = "nota"


def _require_calling(user: Dict[str, Any]) -> None:
    if not twilio_service.is_configured():
        raise HTTPException(status_code=503, detail="Las llamadas no están disponibles todavía.")
    if not is_paid(user):
        raise HTTPException(status_code=402, detail=PRO_DETAIL)


def _own_call(user: Dict[str, Any], call_id: str) -> Dict[str, Any]:
    rec = twilio_service.get_call(call_id)
    if not rec or rec.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="Llamada no encontrada.")
    return rec


def _bad(exc: TwilioError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Celular verificado
# ---------------------------------------------------------------------------

@router.get("/api/phone")
async def phone_status(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {**twilio_service.phone_state(user), "calling_allowed": is_paid(user)}


@router.post("/api/phone/verify/start")
def phone_verify_start(payload: PhoneStart, request: Request,
                       user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _require_calling(user)
    throttle(f"phone-verify:{user['user_id']}", limit=5, window_seconds=3600)
    throttle(f"phone-verify-ip:{client_ip(request)}", limit=10, window_seconds=3600)
    try:
        return twilio_service.start_verification(user, payload.phone)
    except TwilioError as exc:
        raise _bad(exc) from exc


@router.post("/api/phone/verify/check")
def phone_verify_check(payload: PhoneCheck, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _require_calling(user)
    throttle(f"phone-check:{user['user_id']}", limit=10, window_seconds=3600)
    try:
        return twilio_service.check_verification(user, payload.phone, payload.code)
    except TwilioError as exc:
        raise _bad(exc) from exc


@router.delete("/api/phone")
async def phone_remove(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    twilio_service.remove_phone(user["user_id"])
    return {"status": "removed"}


# ---------------------------------------------------------------------------
# Llamadas
# ---------------------------------------------------------------------------

@router.get("/api/calls")
async def my_calls(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"phone": {**twilio_service.phone_state(user), "calling_allowed": is_paid(user)},
            "calls": twilio_service.list_calls(user["user_id"], limit=20)}


@router.post("/api/calls")
def start_call(payload: CallRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _require_calling(user)
    throttle(f"call:{user['user_id']}", limit=10, window_seconds=600)
    try:
        return twilio_service.create_call(user, payload.to, payload.title or "", payload.contact_name or "")
    except TwilioError as exc:
        raise _bad(exc) from exc


@router.get("/api/calls/{call_id}")
async def call_status(call_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return twilio_service.public_call(_own_call(user, call_id))


@router.post("/api/calls/{call_id}/notes")
async def call_note(call_id: str, payload: CallNote, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _own_call(user, call_id)
    try:
        return twilio_service.add_note(user["user_id"], call_id, payload.text, payload.tag)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Llamada no encontrada.") from exc
    except TwilioError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/calls/{call_id}/hangup")
def call_hangup(call_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _own_call(user, call_id)
    twilio_service.hangup(call_id)
    return twilio_service.public_call(twilio_service.get_call(call_id) or {})


# ---------------------------------------------------------------------------
# Webhooks de Twilio
# ---------------------------------------------------------------------------

async def _signed_params(request: Request) -> Dict[str, str]:
    """Parámetros del webhook, solo si la firma de Twilio es válida para la URL pública."""
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    url = twilio_service.webhook_base() + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not twilio_service.validate_signature(url, params, request.headers.get("x-twilio-signature")):
        raise HTTPException(status_code=403, detail="Firma inválida")
    return params


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


def _call_for_webhook(call_id: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """La llamada, si el CallSid/ParentCallSid del webhook es el que creamos."""
    rec = twilio_service.get_call(call_id)
    if not rec:
        return None
    sids = {params.get("CallSid"), params.get("ParentCallSid")}
    return rec if rec.get("call_sid") and rec["call_sid"] in sids else None


@router.post("/api/twilio/voice/{call_id}", include_in_schema=False)
async def twilio_voice(call_id: str, request: Request) -> Response:
    params = await _signed_params(request)
    rec = _call_for_webhook(call_id, params)
    if not rec or rec.get("status") not in twilio_service.ACTIVE_STATUSES:
        return _xml(twilio_service.twiml_unavailable(rec))
    return _xml(twilio_service.twiml_owner_answered(rec, twilio_service.webhook_base()))


@router.post("/api/twilio/connect/{call_id}", include_in_schema=False)
async def twilio_connect(call_id: str, request: Request) -> Response:
    params = await _signed_params(request)
    rec = _call_for_webhook(call_id, params)
    if not rec or rec.get("status") not in twilio_service.ACTIVE_STATUSES:
        return _xml(twilio_service.twiml_unavailable(rec))
    if params.get("Digits") != "1":
        return _xml(twilio_service.twiml_owner_answered(rec, twilio_service.webhook_base()))
    twilio_service.on_owner_pressed(call_id)
    return _xml(twilio_service.twiml_connect(rec, twilio_service.webhook_base()))


@router.post("/api/twilio/notice/{call_id}", include_in_schema=False)
async def twilio_notice(call_id: str, request: Request) -> Response:
    params = await _signed_params(request)
    rec = _call_for_webhook(call_id, params)
    return _xml(twilio_service.twiml_contact_notice(rec or {}))


@router.post("/api/twilio/dial-done/{call_id}", include_in_schema=False)
async def twilio_dial_done(call_id: str, request: Request) -> Response:
    params = await _signed_params(request)
    rec = _call_for_webhook(call_id, params)
    status = params.get("DialCallStatus", "")
    if rec:
        twilio_service.on_dial_done(call_id, status)
    return _xml(twilio_service.twiml_dial_done(rec or {}, status))


@router.post("/api/twilio/status/{call_id}", include_in_schema=False)
async def twilio_status(call_id: str, request: Request) -> Dict[str, Any]:
    params = await _signed_params(request)
    if _call_for_webhook(call_id, params):
        twilio_service.on_status(call_id, request.query_params.get("leg", "owner"), params)
    return {"status": "ok"}


@router.post("/api/twilio/recording/{call_id}", include_in_schema=False)
async def twilio_recording(call_id: str, request: Request) -> Dict[str, Any]:
    params = await _signed_params(request)
    if not _call_for_webhook(call_id, params):
        return {"status": "ignored"}
    return {"status": "accepted" if twilio_service.on_recording(call_id, params) else "ignored"}
