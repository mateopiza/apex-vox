"""
Read-only share links (app/services/share_links.py)
---------------------------------------------------
An account can publish one of its results at `/s/<token>`. The token is random
(`secrets.token_urlsafe`), unrelated to the job id and revocable. The state keeps only its random
part: the link also carries an HMAC of it with the app secret, so a copy of the state (or of its
Postgres replica) is not enough to rebuild a working link. The owner can still copy it again.

One link per job. Links disappear when the result expires (retention sweep), when the job is
forgotten and when the account is deleted.
"""

from __future__ import annotations

import datetime as dt
import hmac
import logging
import re
import secrets
from typing import Any, Dict, Iterable, Optional

from app.logsafe import clean
from app.services.state_store import StateCorruptError
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.services.share_links")

COLLECTION = "share_links"
_NONCE_BYTES = 18  # 24 caracteres URL-safe, 144 bits aleatorios
_SIG_CHARS = 22
_TOKEN = re.compile(r"[A-Za-z0-9_-]{24}\.[0-9a-f]{22}")


def _sig(nonce: str) -> str:
    return supabase_service._digest(f"share:{nonce}")[:_SIG_CHARS]


def token_for(nonce: str) -> str:
    """The public token of a stored link."""
    return f"{nonce}.{_sig(nonce)}"


def _nonce_of(token: Optional[str]) -> Optional[str]:
    if not token or not _TOKEN.fullmatch(token):
        return None
    nonce, sig = token.split(".", 1)
    return nonce if hmac.compare_digest(sig, _sig(nonce)) else None


def _public(nonce: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "token": token_for(nonce),
        "job_id": entry["job_id"],
        "user_id": entry["user_id"],
        "include_audio": bool(entry.get("include_audio")),
        "created_at": entry.get("created_at"),
    }


def _find(links: Dict[str, Any], job_id: str) -> Optional[str]:
    return next((n for n, e in links.items() if isinstance(e, dict) and e.get("job_id") == job_id), None)


def get_for_job(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """The owner's link to this job, or None."""
    links = supabase_service._read_snapshot().get(COLLECTION) or {}
    nonce = _find(links, job_id)
    if not nonce or links[nonce].get("user_id") != user_id:
        return None
    return _public(nonce, links[nonce])


def create_or_update(job_id: str, user_id: str, include_audio: bool) -> Dict[str, Any]:
    """Create the job's link, or keep the existing one and change whether it plays the audio."""
    with supabase_service._lock:
        db = supabase_service._load_db()
        links = db.setdefault(COLLECTION, {})
        nonce = _find(links, job_id)
        if nonce and links[nonce].get("user_id") != user_id:
            raise PermissionError("Este resultado no es tuyo.")
        if not nonce:
            nonce = secrets.token_urlsafe(_NONCE_BYTES)
            links[nonce] = {
                "job_id": job_id,
                "user_id": user_id,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
        links[nonce]["include_audio"] = bool(include_audio)
        supabase_service._save_db(db)
        return _public(nonce, links[nonce])


def resolve(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """The link behind a public token, or None if it is malformed, forged or revoked."""
    nonce = _nonce_of(token)
    if not nonce:
        return None
    entry = (supabase_service._read_snapshot().get(COLLECTION) or {}).get(nonce)
    return _public(nonce, entry) if isinstance(entry, dict) and entry.get("job_id") else None


def _delete_where(match, reason: str) -> int:
    """Remove the links `match(entry)` selects. Reads the shared snapshot first: most calls find none."""
    try:
        if not any(isinstance(e, dict) and match(e) for e in (supabase_service._read_snapshot().get(COLLECTION) or {}).values()):
            return 0
        with supabase_service._lock:
            db = supabase_service._load_db()
            links = db.setdefault(COLLECTION, {})
            gone = [n for n, e in links.items() if isinstance(e, dict) and match(e)]
            for nonce in gone:
                links.pop(nonce, None)
            if gone:
                supabase_service._save_db(db)
            return len(gone)
    except StateCorruptError:
        logger.warning("Could not remove share links (%s): the state is unreadable", clean(reason))
        return 0


def revoke(job_id: str, user_id: str) -> bool:
    """The owner stops sharing the job. True if there was a link."""
    return _delete_where(lambda e: e.get("job_id") == job_id and e.get("user_id") == user_id, "revoke") > 0


def delete_for_job(job_id: str) -> int:
    return _delete_where(lambda e: e.get("job_id") == job_id, job_id)


def delete_for_owner(user_id: str) -> int:
    return _delete_where(lambda e: e.get("user_id") == user_id, "account")


def job_ids() -> Iterable[str]:
    """Jobs that have a link (for the retention sweep)."""
    links = supabase_service._read_snapshot().get(COLLECTION) or {}
    return sorted({e["job_id"] for e in links.values() if isinstance(e, dict) and e.get("job_id")})
