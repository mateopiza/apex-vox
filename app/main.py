"""
Main FastAPI Application Module
-------------------------------
Provides the web application entrypoint, static/template serving, middleware,
and core API endpoints including upload, ordering, transcription, diarization,
exporting, and the /api/health container healthcheck.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, Request
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
    telegram_router,
    transcribe_router,
    upload_router,
)
from app.api.deps import public_base_url, request_language
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


@app.on_event("startup")
async def start_background_services() -> None:
    """Register the Telegram webhook and schedule the nightly usage report."""
    import threading

    def boot() -> None:
        from app.services import telegram_service

        if telegram_service.is_configured() and settings.PUBLIC_BASE_URL:
            result = telegram_service.set_webhook(settings.PUBLIC_BASE_URL)
            logger.info("Telegram webhook registered: %s", result.get("ok"))
        _daily_report_loop()

    threading.Thread(target=boot, name="background-services", daemon=True).start()
    threading.Thread(target=_billing_email_loop, name="billing-emails", daemon=True).start()
    if not settings.is_email_configured:
        logger.warning("RESEND_API_KEY no está configurada: no se enviará ningún correo.")


def _billing_email_loop() -> None:
    """Cada 15 min: promoción por vencer, aviso de renovación y mes vencido (una vez cada uno)."""
    import time

    from app.services import email_service
    from app.services.supabase_service import supabase_service

    while True:
        try:
            for kind, user in supabase_service.collect_due_billing_emails():
                name, lang = user.get("full_name", ""), user.get("preferred_language", "es")
                if kind == "promo_reminder":
                    rendered = email_service.render_promo_reminder(name, user.get("promo_ends_at"), lang)
                elif kind == "renewal_reminder":
                    rendered = email_service.render_renewal_reminder(name, user.get("pro_until"), lang)
                else:
                    rendered = email_service.render_expired(name, lang)
                email_service.send_email(user["email"], rendered, tags=[{"name": "category", "value": kind}])
        except Exception as exc:
            logger.warning("Billing email sweep failed: %s", exc)
        time.sleep(900)


def _daily_report_loop() -> None:
    """Send the usage report to TELEGRAM_CHAT_ID every day at 23:55 (America/Bogota, UTC-5)."""
    import datetime as _dt
    import os
    import time

    if not (settings.TELEGRAM_BOT_TOKEN and os.getenv("TELEGRAM_CHAT_ID", "").strip()):
        return
    from app.services.usage_reporter import compute_usage_report, send_daily_bot_notification

    bogota = _dt.timezone(_dt.timedelta(hours=-5))
    while True:
        now = _dt.datetime.now(bogota)
        target = now.replace(hour=23, minute=55, second=0, microsecond=0)
        if target <= now:
            target += _dt.timedelta(days=1)
        time.sleep((target - now).total_seconds())
        try:
            send_daily_bot_notification(report=compute_usage_report(target_date=target.date().isoformat()))
        except Exception as exc:
            logger.warning("Daily report failed: %s", exc)


# Mount Static Assets
app.mount("/static", CachedStaticFiles(directory=str(STATIC_DIR)), name="static")

# Include API Routers
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(box_router)
from app.api.routes_mcp import router as mcp_router  # noqa: E402

app.include_router(mcp_router)
from app.api.routes_meetings import router as meetings_router  # noqa: E402

app.include_router(meetings_router)
app.include_router(upload_router)
app.include_router(transcribe_router)
app.include_router(export_router)
app.include_router(telegram_router)


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


# Países donde el español es el idioma principal (código ISO de CF-IPCountry)


_SEO = {
    "es": {
        "title": "Apex Vox — Transcribe y resume tus reuniones con IA",
        "description": "Transcribe audios y reuniones con oradores identificados, resúmenes, tareas y actas. "
                       "Graba en Zoom, Meet o Teams y en persona. 2 horas gratis al día.",
        "image_alt": "Apex Vox: cada audio, en orden; cada voz, con nombre; cada reunión, con acta.",
        "locale": "es_CO", "locale_alt": "en_US",
    },
    "en": {
        "title": "Apex Vox — Transcribe and summarize your meetings with AI",
        "description": "Transcribe audio and meetings with identified speakers, summaries, tasks and minutes. "
                       "Record Zoom, Meet, Teams and in-person meetings. 2 free hours a day.",
        "image_alt": "Apex Vox: every audio in order, every voice with a name, every meeting with minutes.",
        "locale": "en_US", "locale_alt": "es_CO",
    },
}


# Título y descripción de ambos idiomas para que la web cambie de idioma sin otra copia de los textos
_PAGE_META_JSON = json.dumps(
    {k: {"title": v["title"], "description": v["description"]} for k, v in _SEO.items()}, ensure_ascii=False
).replace("</", "<\\/")


def _fill_seo(html: str, lang: str, base: str) -> str:
    """Título, descripción, Open Graph y JSON-LD según idioma (se escapan para HTML/JSON)."""
    import html as _html

    seo = _SEO.get(lang, _SEO["es"])
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "SoftwareApplication",
                "name": "Apex Vox",
                "url": f"{base}/",
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "Web, Android, iOS, Chrome",
                "inLanguage": ["es", "en"],
                "description": seo["description"],
                "image": f"{base}/static/og/og-{lang}.png",
                "offers": [
                    {"@type": "Offer", "name": "Free", "price": "0", "priceCurrency": "USD"},
                    {"@type": "Offer", "name": "Apex Pro", "price": f"{settings.PRO_PRICE_USD:g}", "priceCurrency": "USD"},
                ],
            },
            {
                "@type": "Organization",
                "name": settings.LEGAL_ENTITY_NAME,
                "url": f"{base}/",
                "logo": f"{base}/static/icons/icon-512.png",
                "email": settings.CONTACT_EMAIL,
            },
            {"@type": "WebSite", "name": "Apex Vox", "url": f"{base}/", "inLanguage": lang},
        ],
    }
    return (
        html.replace("{{TITLE}}", _html.escape(seo["title"]))
        .replace("{{DESCRIPTION}}", _html.escape(seo["description"]))
        .replace("{{OG_IMAGE_ALT}}", _html.escape(seo["image_alt"]))
        .replace("{{OG_LOCALE}}", seo["locale"])
        .replace("{{OG_LOCALE_ALT}}", seo["locale_alt"])
        .replace("{{JSON_LD}}", json.dumps(ld, ensure_ascii=False).replace("</", "<\\/"))
        .replace("{{PAGE_META}}", _PAGE_META_JSON)
    )


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap(request: Request) -> Response:
    """Páginas públicas con sus versiones por idioma."""
    base = public_base_url(request)
    pages = [("/", "1.0"), ("/legal/terminos", "0.3"), ("/legal/habeas-data", "0.3"),
             ("/legal/privacidad", "0.3"), ("/legal/seguridad", "0.2")]
    urls = []
    for path, prio in pages:
        sep = "&" if "?" in path else "?"
        alts = "".join(
            f'<xhtml:link rel="alternate" hreflang="{l}" href="{base}{path}{sep}lang={l}"/>' for l in ("es", "en")
        )
        for l in ("es", "en"):
            urls.append(f"<url><loc>{base}{path}{sep}lang={l}</loc>{alts}<priority>{prio}</priority></url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
           + "".join(urls) + "</urlset>")
    return Response(xml, media_type="application/xml", headers={"Cache-Control": "public, max-age=86400"})


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
        lang = request_language(request)
        html = html.replace('<html lang="es"', f'<html lang="{lang}" data-default-lang="{lang}"', 1)
        base = public_base_url(request)
        html = _fill_seo(html, lang, base).replace("{{BASE_URL}}", base).replace("{{OG_LANG}}", lang)
        return HTMLResponse(
            content=html,
            status_code=200,
            headers={"Cache-Control": "no-cache", "Vary": "Accept-Language, CF-IPCountry"},
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


@app.get("/legal/{slug}", include_in_schema=False, response_class=HTMLResponse)
async def legal_page(slug: str, request: Request) -> HTMLResponse:
    """Privacy policy, terms of service and security policy (ES / EN)."""
    from app.services.legal_content import PAGES, render_page

    if slug not in PAGES:
        return HTMLResponse("Not Found", status_code=404)
    page = render_page(slug, request_language(request), _asset_version(), public_base_url(request))
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/.well-known/security.txt", include_in_schema=False)
async def security_txt(request: Request) -> Response:
    from app.services.legal_content import security_txt as build

    return Response(content=build(public_base_url(request)), media_type="text/plain")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Serve the SVG pixel mark for browsers that request /favicon.ico."""
    icon = STATIC_DIR / "favicon.svg"
    if icon.exists():
        return FileResponse(icon, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})
    return Response(status_code=204)


@app.get("/manifest.webmanifest", include_in_schema=False)
async def web_app_manifest() -> JSONResponse:
    """Manifiesto de la app web instalable (Android, iPhone, escritorio)."""
    base = public_base_url()
    return JSONResponse(
        content={
            "id": "/",
            "name": "Apex Vox",
            "short_name": "Apex Vox",
            "description": "Transcripción de reuniones con oradores, resumen Apex Summa, actas y grabación Apex Box.",
            "lang": "es",
            "dir": "ltr",
            "start_url": "/?source=pwa",
            "scope": "/",
            "display": "standalone",
            "display_override": ["standalone", "minimal-ui"],
            "background_color": "#f3f3ee",
            "theme_color": "#f3f3ee",
            "orientation": "any",
            "categories": ["productivity", "business"],
            "icons": [
                {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
                {"src": "/static/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
            ],
            "shortcuts": [
                {"name": "Grabar con Apex Box", "short_name": "Grabar", "url": "/?view=box&source=pwa",
                 "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
                {"name": "Mi cuenta", "url": "/?view=portal&source=pwa",
                 "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
            ],
            "related_applications": [{"platform": "webapp", "url": f"{base}/manifest.webmanifest"}],
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> Response:
    """Service worker mínimo: hace la app instalable y muestra un aviso si no hay conexión."""
    js = """self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => new Response(
    '<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">' +
    '<title>Apex Vox</title><body style="font-family:sans-serif;background:#f3f3ee;color:#302b28;padding:32px">' +
    '<h1>Sin conexión</h1><p>Apex Vox necesita internet. Vuelve a intentarlo cuando tengas señal.</p>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
"""
    return Response(js, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/robots.txt", include_in_schema=False)
async def robots(request: Request) -> Response:
    """Allow the landing page, keep API and job artefacts out of indexes."""
    return Response(
        content=(
            "User-agent: *\nAllow: /$\nAllow: /legal/\nDisallow: /api/\nDisallow: /oauth/\nDisallow: /mcp\n"
            f"Sitemap: {public_base_url(request)}/sitemap.xml\n"
        ),
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
async def health_check(x_admin_key: Optional[str] = Header(default=None)) -> JSONResponse:
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
        "email_configured": settings.is_email_configured,
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
            "endpoint": settings.MEGA_S4_ENDPOINT_URL,  # solo visible para administradores
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

    # En producción el público solo ve el estado: sin proveedores, endpoints, bucket ni
    # modelos (información útil para un atacante). El detalle exige la cabecera X-Admin-Key.
    import hmac as _hmac

    is_admin = bool(
        settings.ADMIN_API_KEY and x_admin_key and _hmac.compare_digest(x_admin_key, settings.ADMIN_API_KEY)
    )
    if settings.is_production and not is_admin:
        health_status = {k: health_status[k] for k in ("status", "product", "version")}

    return JSONResponse(status_code=200 if is_healthy else 503, content=health_status)
