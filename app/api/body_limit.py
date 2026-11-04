"""
Request size limits (app/api/body_limit.py)
-------------------------------------------
Multipart bodies are parsed and spooled to disk before any route code runs, and before the caller
is authenticated, so route-level checks come too late. This middleware runs first and refuses
oversized requests: by `Content-Length` when sent, otherwise by counting bytes as they arrive.
"""

from __future__ import annotations

import json
import re

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings

_MB = 1024 * 1024
# Room for multipart boundaries and form fields next to the file itself.
_MULTIPART_OVERHEAD = _MB
_BOX_BLOCK_PATH = re.compile(r"^/api/box/sessions/[^/]+/blocks/?$")


def _limit_for(path: str) -> int:
    if path.rstrip("/") == "/api/upload":
        return settings.MAX_TOTAL_UPLOAD_SIZE_MB * _MB + _MULTIPART_OVERHEAD
    if _BOX_BLOCK_PATH.match(path):
        return settings.MAX_BOX_BLOCK_MB * _MB + _MULTIPART_OVERHEAD
    if path.rstrip("/") == "/api/voice-profiles":
        return settings.MAX_VOICE_SAMPLE_MB * _MB + _MULTIPART_OVERHEAD
    return settings.MAX_REQUEST_BODY_MB * _MB


def _detail(limit: int) -> str:
    limit_mb = limit // _MB
    return f"La solicitud supera el límite de {limit_mb} MB. / The request is over the {limit_mb} MB limit."


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = _limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            body = json.dumps({"detail": _detail(limit)}, ensure_ascii=False).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI passes HTTPException through form parsing; anything else becomes a 400.
                    raise HTTPException(status_code=413, detail=_detail(limit))
            return message

        await self.app(scope, counting_receive, send)
