"""
Conector MCP + OAuth 2.1 (app/api/routes_mcp.py)
-------------------------------------------------
- GET  /.well-known/oauth-protected-resource[/mcp]  : metadatos del recurso (RFC 9728)
- GET  /.well-known/oauth-authorization-server       : metadatos del servidor OAuth (RFC 8414)
- POST /oauth/register                                : registro dinámico de clientes (RFC 7591)
- GET  /oauth/authorize                               : pantalla de autorización con la marca Apex Vox
- POST /oauth/authorize/decision                      : el usuario (con su sesión web) permite o rechaza
- POST /oauth/token                                   : authorization_code (PKCE) y refresh_token
- POST /oauth/revoke                                  : revocar un token (RFC 7009)
- POST /mcp                                           : servidor MCP (Streamable HTTP, JSON)
- GET/DELETE /api/mcp/connections                     : apps conectadas de la cuenta
"""

from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.api.deps import client_ip, public_base_url, require_user, throttle
from app.services import mcp_oauth, mcp_server
from app.services.mcp_oauth import OAuthError

router = APIRouter(tags=["MCP (ChatGPT, Claude)"])

ALLOWED_ORIGINS = ("https://claude.ai", "https://chatgpt.com", "https://chat.openai.com")
BRAND_MARK = (
    '<svg class="brand-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    '<path fill="currentColor" d="M8 0h8v8H8zM0 8h8v8H0zM16 8h8v8h-8zM0 16h24v8H0z"/></svg>'
)


def _oauth_error(exc: OAuthError, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": exc.error, "error_description": exc.description}, status_code=status,
                        headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Metadatos
# ---------------------------------------------------------------------------

def _resource_metadata(request: Request) -> Dict[str, Any]:
    base = public_base_url(request)
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "scopes_supported": [mcp_oauth.SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Apex Vox",
        "resource_documentation": f"{base}/?view=portal",
    }


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
async def protected_resource_metadata(request: Request) -> JSONResponse:
    return JSONResponse(_resource_metadata(request))


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
@router.get("/.well-known/openid-configuration", include_in_schema=False)
async def authorization_server_metadata(request: Request) -> JSONResponse:
    base = public_base_url(request)
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [mcp_oauth.SCOPE],
        "service_documentation": f"{base}/?view=portal",
    })


# ---------------------------------------------------------------------------
# Registro, autorización y tokens
# ---------------------------------------------------------------------------

@router.post("/oauth/register", include_in_schema=False)
async def register_client(request: Request) -> JSONResponse:
    throttle(f"mcp-register:{client_ip(request)}", limit=20, window_seconds=3600)
    try:
        metadata = await request.json()
    except ValueError:
        return _oauth_error(OAuthError("invalid_client_metadata", "JSON inválido."))
    if not isinstance(metadata, dict):
        return _oauth_error(OAuthError("invalid_client_metadata", "Se esperaba un objeto JSON."))
    try:
        record = mcp_oauth.register_client(metadata)
    except OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(record, status_code=201, headers={"Cache-Control": "no-store"})


def _page(title: str, body: str, script: bool = False) -> HTMLResponse:
    js = '<script src="/static/js/oauth-consent.js" defer></script>' if script else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)} · Apex Vox</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600&amp;family=Share+Tech+Mono&amp;family=IBM+Plex+Mono:wght@400;500&amp;display=swap">
<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/styles.css">
{js}
</head>
<body class="oauth-page">
<main class="oauth-card">
  <div class="oauth-brand">{BRAND_MARK}<span class="brand-wordmark">Apex Vox</span></div>
  {body}
</main>
</body>
</html>""", headers={"Cache-Control": "no-store"})


@router.get("/oauth/authorize", include_in_schema=False)
async def authorize(request: Request) -> HTMLResponse:
    params = dict(request.query_params)
    try:
        client = mcp_oauth.validate_authorize_request(params)
    except OAuthError as exc:
        return _page("No se pudo conectar", f"""
  <h1 class="oauth-title">No se pudo conectar</h1>
  <p class="oauth-lead">{html.escape(exc.description or exc.error)}</p>
  <p class="oauth-note"><a class="text-link-strong" href="/">Volver a Apex Vox</a></p>""")
    name = html.escape(client["client_name"])
    return _page("Conectar app", f"""
  <p class="overline">Conectar app</p>
  <h1 class="oauth-title"><span data-client>{name}</span> quiere acceder a tu cuenta de Apex Vox</h1>
  <ul class="oauth-perms">
    <li>Ver la lista de tus reuniones transcritas.</li>
    <li>Leer y buscar en tus transcripciones.</li>
    <li>Leer los resúmenes y tareas de Apex Summa (Apex Pro).</li>
  </ul>
  <p class="oauth-note">Solo lectura: no puede borrar, grabar ni pagar nada. Puedes desconectarla cuando quieras en <strong>Mi cuenta</strong>.</p>
  <p class="oauth-account" id="oauth-account">Comprobando tu sesión…</p>
  <div class="oauth-actions">
    <button type="button" class="btn-primary hidden" id="oauth-allow">Permitir acceso</button>
    <a class="btn-primary hidden" id="oauth-login" href="/?login=1">Iniciar sesión para continuar</a>
    <button type="button" class="btn-secondary" id="oauth-deny">Cancelar</button>
  </div>
  <p class="oauth-error hidden" id="oauth-error" role="alert"></p>""", script=True)


@router.post("/oauth/authorize/decision", include_in_schema=False)
async def authorize_decision(request: Request, user: Dict[str, Any] = Depends(require_user)) -> JSONResponse:
    """La pantalla envía la decisión con la sesión web del usuario (Bearer apx_...)."""
    data = await request.json()
    params = {k: str(v) for k, v in (data.get("params") or {}).items()}
    try:
        client = mcp_oauth.validate_authorize_request(params)
    except OAuthError as exc:
        return _oauth_error(exc)
    redirect_uri, state = params["redirect_uri"], params.get("state")
    if not data.get("approve"):
        query = {"error": "access_denied", **({"state": state} if state else {})}
    else:
        code = mcp_oauth.create_authorization_code(
            client["client_id"], user["user_id"], redirect_uri, params["code_challenge"], params.get("resource", "")
        )
        query = {"code": code, **({"state": state} if state else {})}
    sep = "&" if "?" in redirect_uri else "?"
    return JSONResponse({"redirect_to": f"{redirect_uri}{sep}{urlencode(query)}"}, headers={"Cache-Control": "no-store"})


@router.post("/oauth/token", include_in_schema=False)
async def token(request: Request) -> JSONResponse:
    throttle(f"mcp-token:{client_ip(request)}", limit=60, window_seconds=600)
    form = await request.form()
    grant, client_id = form.get("grant_type"), str(form.get("client_id") or "")
    try:
        if not mcp_oauth.get_client(client_id):
            raise OAuthError("invalid_client", "Cliente desconocido.")
        if grant == "authorization_code":
            tokens = mcp_oauth.exchange_code(
                str(form.get("code") or ""), client_id, str(form.get("redirect_uri") or ""), str(form.get("code_verifier") or "")
            )
        elif grant == "refresh_token":
            tokens = mcp_oauth.refresh_tokens(str(form.get("refresh_token") or ""), client_id)
        else:
            raise OAuthError("unsupported_grant_type", "grant_type no soportado.")
    except OAuthError as exc:
        return _oauth_error(exc, 401 if exc.error == "invalid_client" else 400)
    return JSONResponse(tokens, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/oauth/revoke", include_in_schema=False)
async def revoke(request: Request) -> Response:
    form = await request.form()
    mcp_oauth.revoke_token(str(form.get("token") or ""))
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Servidor MCP
# ---------------------------------------------------------------------------

def _unauthorized(request: Request) -> JSONResponse:
    base = public_base_url(request)
    return JSONResponse(
        {"error": "invalid_token", "error_description": "Conecta tu cuenta de Apex Vox."},
        status_code=401,
        headers={"WWW-Authenticate": f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource", scope="{mcp_oauth.SCOPE}"'},
    )


@router.post("/mcp", include_in_schema=False)
async def mcp_endpoint(request: Request) -> Response:
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS and origin != public_base_url(request):
        return JSONResponse({"error": "origin_not_allowed"}, status_code=403)  # anti DNS-rebinding
    auth = request.headers.get("authorization", "")
    user = mcp_oauth.user_for_access_token(auth[7:].strip() if auth.lower().startswith("bearer ") else "")
    if not user:
        return _unauthorized(request)
    throttle(f"mcp:{user['user_id']}", limit=120, window_seconds=60)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(mcp_server._error(None, -32700, "Parse error"), status_code=400)

    messages = payload if isinstance(payload, list) else [payload]
    responses = [r for r in (mcp_server.handle_message(m, user) for m in messages) if r is not None]
    if not responses:
        return Response(status_code=202)
    body = responses if isinstance(payload, list) else responses[0]
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
async def mcp_other_methods() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


# ---------------------------------------------------------------------------
# Apps conectadas (Mi cuenta)
# ---------------------------------------------------------------------------

@router.get("/api/mcp/connections")
async def list_connections(request: Request, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"mcp_url": f"{public_base_url(request)}/mcp", "connections": mcp_oauth.list_connections(user["user_id"])}


@router.delete("/api/mcp/connections")
async def revoke_connections(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"revoked_tokens": mcp_oauth.revoke_all_for_user(user["user_id"])}
