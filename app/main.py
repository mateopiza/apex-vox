"""
Main FastAPI Application Module
-------------------------------
Provides the web application entrypoint, static/template serving, middleware,
and core API endpoints including upload, ordering, transcription, diarization,
exporting, and the /api/health container healthcheck.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from app.api import (
    auth_router,
    billing_router,
    box_router,
    export_router,
    transcribe_router,
    upload_router,
)
from app.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

# Initialize FastAPI application (interactive docs are off in production
# unless ENABLE_DOCS=true).
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
_wildcard_origins = "*" in settings.CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # Credentials are never combined with a wildcard origin.
    allow_credentials=not _wildcard_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
if settings.ALLOWED_HOSTS and "*" not in settings.ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# Content-Security-Policy for the web UI. Fonts come from Google Fonts; inline
# style attributes are used for progress bars and charts rendered from JS.
_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob: https://console.groq.com",
        "media-src 'self' blob: https:",
        "connect-src 'self'",
        "frame-src https://checkout.bold.co",
        "form-action 'self' https://checkout.bold.co",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
)
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach security headers to every response."""
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=(self), display-capture=(self)")
    headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    if not request.url.path.startswith(_DOCS_PATHS):
        headers.setdefault("Content-Security-Policy", _CSP)
    if settings.ENABLE_HSTS:
        headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unexpected errors and return a generic message (no internals leaked)."""
    if isinstance(exc, (FastAPIHTTPException, StarletteHTTPException)):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    detail = "Internal server error" if settings.is_production else f"{type(exc).__name__}: {exc}"
    return JSONResponse(status_code=500, content={"detail": detail})


class CachedStaticFiles(StaticFiles):
    """Static files with long-lived caching for versioned assets (?v=...)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            query = scope.get("query_string", b"")
            if b"v=" in query:
                response.headers["Cache-Control"] = (
                    f"public, max-age={settings.STATIC_CACHE_SECONDS}, immutable"
                )
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"
        return response


# Mount Static Assets
app.mount("/static", CachedStaticFiles(directory=str(STATIC_DIR)), name="static")

# Include API Routers
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(box_router)
app.include_router(upload_router)
app.include_router(transcribe_router)
app.include_router(export_router)


@lru_cache(maxsize=1)
def _render_index() -> str | None:
    """Read the UI shell once and stamp the asset version for cache busting."""
    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        return None
    html = index_file.read_text(encoding="utf-8")
    return html.replace("{{ASSET_VERSION}}", _asset_version())


def _asset_version() -> str:
    """Content hash of the CSS/JS bundle, so every deploy busts long-lived caches."""
    digest = hashlib.sha256()
    for rel in ("css/tokens.css", "css/styles.css", "js/app.js"):
        path = STATIC_DIR / rel
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _preferred_language(accept_language: str) -> str:
    """'es' when the visitor's browser prefers Spanish, otherwise 'en'."""
    best_lang, best_q = "en", -1.0
    for part in accept_language.split(","):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        q = 1.0
        if params.strip().startswith("q="):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                q = 0.0
        base = tag.strip().lower().split("-")[0]
        if base in ("es", "en") and q > best_q:
            best_lang, best_q = base, q
    return best_lang


@app.api_route("/", methods=["GET", "HEAD"], tags=["UI & Root"], response_model=None)
async def root(request: Request) -> Response:
    """
    Root endpoint:
    - Serves the Apex Vox web UI (HTML) to browsers.
    - Returns service metadata JSON when 'Accept: application/json' or '?format=json' is requested.
    """
    accept = request.headers.get("accept", "")
    wants_json = (
        request.query_params.get("format") == "json"
        or ("application/json" in accept and "text/html" not in accept)
    )
    html = None if wants_json else _render_index()

    if html is not None:
        lang = _preferred_language(request.headers.get("accept-language", ""))
        html = html.replace('<html lang="es"', f'<html lang="{lang}" data-default-lang="{lang}"', 1)
        return HTMLResponse(
            content=html,
            status_code=200,
            headers={"Cache-Control": "no-cache", "Vary": "Accept-Language"},
        )

    return JSONResponse(
        status_code=200,
        content={
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs_url": "/docs" if settings.ENABLE_DOCS else None,
            "health_url": "/api/health",
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Serve the SVG pixel mark for browsers that request /favicon.ico."""
    icon = STATIC_DIR / "favicon.svg"
    if icon.exists():
        return FileResponse(icon, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})
    return Response(status_code=204)


@app.get("/manifest.webmanifest", include_in_schema=False)
async def web_app_manifest() -> JSONResponse:
    """Serve PWA manifest for mobile web app installation (Modo App Web en Celular)."""
    return JSONResponse(
        content={
            "name": "Apex Vox & Apex Box — Grabador Ilimitado por Bloques",
            "short_name": "Apex Box",
            "description": "Grabación ilimitada por bloques sin llenar RAM, modo Reunión Presencial y Virtual (Zoom, Meet, Teams), notas en vivo y transcripción continua.",
            "start_url": "/?view=box",
            "display": "standalone",
            "background_color": "#f3f3ee",
            "theme_color": "#f43e01",
            "orientation": "any",
            "icons": [
                {
                    "src": "/static/favicon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        },
        media_type="application/manifest+json",
    )


@app.get("/robots.txt", include_in_schema=False)
async def robots() -> Response:
    """Allow the landing page, keep API and job artefacts out of indexes."""
    return Response(
        content="User-agent: *\nAllow: /$\nDisallow: /api/\n",
        media_type="text/plain",
    )


@app.get("/api/info", tags=["Root"])
async def api_info() -> Dict[str, Any]:
    """Service metadata endpoint."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs_url": "/docs" if settings.ENABLE_DOCS else None,
        "health_url": "/api/health",
    }


@app.get("/api/health", tags=["Health"])
async def health_check() -> JSONResponse:
    """
    Container and application health check endpoint.
    Verifies system runtime, storage accessibility, ffmpeg binaries,
    and Groq API key configuration status.
    Returns HTTP 200 (ok) when healthy, or HTTP 503 (degraded) if storage
    or multimedia binaries are unavailable.
    """
    uploads_writable = False
    outputs_writable = False
    temp_writable = False

    try:
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        test_file = settings.UPLOAD_DIR / ".health_test"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
        uploads_writable = True
    except Exception as e:
        logger.error("Upload directory write test failed: %s", e)

    try:
        settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        test_file = settings.OUTPUT_DIR / ".health_test"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
        outputs_writable = True
    except Exception as e:
        logger.error("Output directory write test failed: %s", e)

    try:
        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        test_file = settings.TEMP_DIR / ".health_test"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
        temp_writable = True
    except Exception as e:
        logger.error("Temp directory write test failed: %s", e)

    ffmpeg_available = shutil.which("ffmpeg") is not None
    ffprobe_available = shutil.which("ffprobe") is not None

    if not ffmpeg_available:
        logger.warning("Health check warning: 'ffmpeg' binary not found in PATH")
    if not ffprobe_available:
        logger.warning("Health check warning: 'ffprobe' binary not found in PATH")

    is_healthy = (
        uploads_writable
        and outputs_writable
        and temp_writable
        and ffmpeg_available
        and ffprobe_available
    )

    health_status: Dict[str, Any] = {
        "status": "ok" if is_healthy else "degraded",
        "product": settings.PRODUCT_NAME,
        "powered_by": "Groq",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "groq_configured": settings.is_groq_configured,
        "deepgram_configured": settings.is_deepgram_configured,
        "supabase_configured": settings.is_supabase_configured,
        "mega_s4_configured": settings.is_mega_s4_configured,
        "bold_configured": settings.is_bold_configured,
        "default_diarization_engine": settings.DEFAULT_DIARIZATION_ENGINE,
        "engines_lineup": ["Mc-Ayrton", "Mc-Lewis", "Mc-Norris", "Mc-Piastri"],
        "suite": {
            "apex_vox": "ready",
            "apex_summa": "active",
            "apex_box": "ready",
        },
        "system": {
            "ffmpeg": ffmpeg_available,
            "ffprobe": ffprobe_available,
        },
        "storage": {
            "provider": "mega_s4",
            "endpoint": settings.MEGA_S4_ENDPOINT_URL,
            "bucket": settings.MEGA_S4_BUCKET_NAME,
            "uploads_writable": uploads_writable,
            "outputs_writable": outputs_writable,
            "temp_writable": temp_writable,
        },
        "models": {
            "default_speech_model": settings.DEFAULT_MODEL,
            "default_llm_model": settings.DEFAULT_LLM_MODEL,
        },
    }

    if not is_healthy:
        logger.warning(
            "Health check degraded: system=%s, storage=%s",
            health_status["system"],
            health_status["storage"],
        )
        return JSONResponse(status_code=503, content=health_status)

    return JSONResponse(status_code=200, content=health_status)
