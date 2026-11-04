"""
OAuth 2.1 para el conector MCP de Apex Vox (app/services/mcp_oauth.py)
---------------------------------------------------------------------
Permite que ChatGPT, Claude u otro cliente MCP accedan, en nombre de un usuario y solo
con su autorización explícita, a sus reuniones (lectura).

- Registro dinámico de clientes (RFC 7591): clientes públicos, sin secreto.
- Código de autorización con PKCE S256 obligatorio (OAuth 2.1), un solo uso, 5 minutos.
- Token de acceso de 1 hora y token de renovación de 30 días con rotación.
- Los códigos y tokens se guardan solo como HMAC (nunca en claro).
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.services.supabase_service import supabase_service

SCOPE = "meetings:read"
CODE_TTL = dt.timedelta(minutes=5)
ACCESS_TTL = dt.timedelta(hours=1)
REFRESH_TTL = dt.timedelta(days=30)
MAX_CLIENTS = 5000


class OAuthError(Exception):
    """Error OAuth con código estándar (invalid_request, invalid_grant, ...)."""

    def __init__(self, error: str, description: str = "") -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse(value: Optional[str]) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _h(kind: str, value: str) -> str:
    return supabase_service._digest(f"mcp-{kind}:{value}")


def _tables(db: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    for key in ("oauth_clients", "oauth_codes", "oauth_tokens"):
        db.setdefault(key, {})
    return db


def valid_redirect_uri(uri: str) -> bool:
    """https en cualquier host, o http solo en loopback (clientes locales)."""
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    if parsed.fragment or not parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")


# ---------------------------------------------------------------------------
# Clientes (registro dinámico)
# ---------------------------------------------------------------------------

def register_client(metadata: Dict[str, Any]) -> Dict[str, Any]:
    uris = metadata.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or len(uris) > 10:
        raise OAuthError("invalid_redirect_uri", "redirect_uris es obligatorio (1 a 10 URIs).")
    for uri in uris:
        if not isinstance(uri, str) or not valid_redirect_uri(uri):
            raise OAuthError("invalid_redirect_uri", f"redirect_uri no permitida: {uri!r}")
    name = str(metadata.get("client_name") or "Cliente MCP").strip()[:80] or "Cliente MCP"
    client_id = "apx_mcp_" + secrets.token_urlsafe(18)
    record = {
        "client_id": client_id,
        "client_name": name,
        "redirect_uris": uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
        "client_id_issued_at": int(_now().timestamp()),
    }
    with supabase_service._lock:
        db = _tables(supabase_service._load_db())
        if len(db["oauth_clients"]) >= MAX_CLIENTS:
            raise OAuthError("temporarily_unavailable", "Límite de clientes registrados alcanzado.")
        db["oauth_clients"][client_id] = record
        supabase_service._save_db(db)
    return record


def get_client(client_id: str) -> Optional[Dict[str, Any]]:
    clients = supabase_service._read_snapshot().get("oauth_clients", {})
    return dict(clients.get(client_id or "", {})) or None


def validate_authorize_request(params: Dict[str, str]) -> Dict[str, Any]:
    """Valida la petición /oauth/authorize y devuelve el cliente. Lanza OAuthError."""
    client = get_client(params.get("client_id", ""))
    if not client:
        raise OAuthError("invalid_client", "Cliente desconocido. Vuelve a conectar desde tu aplicación.")
    redirect_uri = params.get("redirect_uri", "")
    if redirect_uri not in client["redirect_uris"]:
        raise OAuthError("invalid_request", "redirect_uri no registrada para este cliente.")
    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "Solo se admite response_type=code.")
    if params.get("code_challenge_method") != "S256" or not params.get("code_challenge"):
        raise OAuthError("invalid_request", "PKCE S256 es obligatorio.")
    return client


# ---------------------------------------------------------------------------
# Código de autorización y tokens
# ---------------------------------------------------------------------------

def create_authorization_code(
    client_id: str, user_id: str, redirect_uri: str, code_challenge: str, resource: str = ""
) -> str:
    code = secrets.token_urlsafe(32)
    with supabase_service._lock:
        db = _tables(supabase_service._load_db())
        now = _now()
        db["oauth_codes"] = {
            k: v for k, v in db["oauth_codes"].items() if (_parse(v.get("expires_at")) or now) > now
        }
        db["oauth_codes"][_h("code", code)] = {
            "client_id": client_id,
            "user_id": user_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "resource": resource,
            "expires_at": (now + CODE_TTL).isoformat(),
        }
        supabase_service._save_db(db)
    return code


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not verifier or not 43 <= len(verifier) <= 128:
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return secrets.compare_digest(digest, challenge)


def _issue_tokens(db: Dict[str, Any], client_id: str, user_id: str, resource: str) -> Dict[str, Any]:
    access, refresh = "apx_at_" + secrets.token_urlsafe(32), "apx_rt_" + secrets.token_urlsafe(32)
    now = _now()
    db["oauth_tokens"][_h("access", access)] = {
        "kind": "access", "client_id": client_id, "user_id": user_id, "resource": resource,
        "expires_at": (now + ACCESS_TTL).isoformat(), "created_at": now.isoformat(),
    }
    db["oauth_tokens"][_h("refresh", refresh)] = {
        "kind": "refresh", "client_id": client_id, "user_id": user_id, "resource": resource,
        "expires_at": (now + REFRESH_TTL).isoformat(), "created_at": now.isoformat(),
    }
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": SCOPE,
    }


def exchange_code(code: str, client_id: str, redirect_uri: str, code_verifier: str) -> Dict[str, Any]:
    with supabase_service._lock:
        db = _tables(supabase_service._load_db())
        entry = db["oauth_codes"].pop(_h("code", code or ""), None)  # un solo uso
        supabase_service._save_db(db)
        if not entry or (_parse(entry.get("expires_at")) or _now()) <= _now():
            raise OAuthError("invalid_grant", "Código inválido o vencido.")
        if entry["client_id"] != client_id or entry["redirect_uri"] != redirect_uri:
            raise OAuthError("invalid_grant", "El código no corresponde a este cliente.")
        if not _pkce_ok(code_verifier, entry["code_challenge"]):
            raise OAuthError("invalid_grant", "code_verifier inválido.")
        if entry["user_id"] not in db["users"]:
            raise OAuthError("invalid_grant", "La cuenta ya no existe.")
        tokens = _issue_tokens(db, client_id, entry["user_id"], entry.get("resource", ""))
        supabase_service._save_db(db)
    return tokens


def refresh_tokens(refresh_token: str, client_id: str) -> Dict[str, Any]:
    with supabase_service._lock:
        db = _tables(supabase_service._load_db())
        entry = db["oauth_tokens"].pop(_h("refresh", refresh_token or ""), None)  # rotación
        if (
            not entry or entry.get("kind") != "refresh" or entry["client_id"] != client_id
            or (_parse(entry.get("expires_at")) or _now()) <= _now() or entry["user_id"] not in db["users"]
        ):
            supabase_service._save_db(db)
            raise OAuthError("invalid_grant", "Token de renovación inválido o vencido.")
        tokens = _issue_tokens(db, client_id, entry["user_id"], entry.get("resource", ""))
        supabase_service._save_db(db)
    return tokens


def user_for_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Usuario dueño de un token de acceso vigente, o None."""
    if not token or not token.startswith("apx_at_"):
        return None
    snapshot = supabase_service._read_snapshot()
    entry = snapshot.get("oauth_tokens", {}).get(_h("access", token))
    if not entry or entry.get("kind") != "access" or (_parse(entry.get("expires_at")) or _now()) <= _now():
        return None
    user = snapshot["users"].get(entry["user_id"])
    if not user:
        return None
    if not supabase_service._plan_expired(user):
        return copy.deepcopy(user)
    with supabase_service._lock:
        db = _tables(supabase_service._load_db())
        entry = db["oauth_tokens"].get(_h("access", token))
        if not entry or entry.get("kind") != "access" or (_parse(entry.get("expires_at")) or _now()) <= _now():
            return None
        user = db["users"].get(entry["user_id"])
        if not user:
            return None
        if supabase_service._refresh_plan_expiry(user):
            supabase_service._save_db(db)
        return dict(user)


def revoke_token(token: str) -> None:
    with supabase_service._lock:
        db = _tables(supabase_service._load_db())
        for kind in ("access", "refresh"):
            db["oauth_tokens"].pop(_h(kind, token or ""), None)
        supabase_service._save_db(db)


def list_connections(user_id: str) -> List[Dict[str, Any]]:
    """Apps conectadas (clientes con un token de renovación vigente)."""
    now = _now()
    with supabase_service._lock:
        db = _tables(supabase_service._load_db())
        seen: Dict[str, Dict[str, Any]] = {}
        for t in db["oauth_tokens"].values():
            if t.get("user_id") != user_id or t.get("kind") != "refresh":
                continue
            if (_parse(t.get("expires_at")) or now) <= now:
                continue
            client = db["oauth_clients"].get(t["client_id"], {})
            seen.setdefault(t["client_id"], {
                "client_id": t["client_id"],
                "client_name": client.get("client_name", "Cliente MCP"),
                "connected_at": t.get("created_at"),
            })
        return list(seen.values())


def revoke_all_for_user(user_id: str) -> int:
    with supabase_service._lock:
        db = _tables(supabase_service._load_db())
        before = len(db["oauth_tokens"])
        db["oauth_tokens"] = {k: v for k, v in db["oauth_tokens"].items() if v.get("user_id") != user_id}
        supabase_service._save_db(db)
        return before - len(db["oauth_tokens"])
