"""API routers package."""
from app.api.routes_auth import router as auth_router
from app.api.routes_billing import router as billing_router
from app.api.routes_box import router as box_router
from app.api.routes_export import router as export_router
from app.api.routes_telegram import router as telegram_router
from app.api.routes_transcribe import router as transcribe_router
from app.api.routes_upload import router as upload_router

__all__ = [
    "auth_router",
    "billing_router",
    "box_router",
    "upload_router",
    "transcribe_router",
    "export_router",
    "telegram_router",
]
