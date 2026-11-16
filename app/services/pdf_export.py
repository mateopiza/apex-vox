"""
PDF export (app/services/pdf_export.py)
---------------------------------------
The same report template as the share page (`templates/report/_report.html`), printed with
WeasyPrint. Charts are SVG drawn on the server. Plan rules are those of the summary and the
minutes: without active Apex Pro, the preview and no minutes; guests, the transcript only.

WeasyPrint is imported when a PDF is requested: a server without Pango still starts, and the
endpoint answers 503. The renderer fetches nothing: fonts are the system's and the stylesheet
is inlined, so a result can never make the server request a URL.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.errors import UserFacingError
from app.models.schemas import TranscriptionResult
from app.services import report_view

logger = logging.getLogger("app.services.pdf_export")

PRINT_CSS = Path(__file__).resolve().parent.parent / "templates" / "report" / "print.css"

PDF_UNAVAILABLE = (
    "La exportación a PDF no está disponible en este servidor. / PDF export is not available on this server."
)


class PdfUnavailableError(UserFacingError):
    """WeasyPrint or its system libraries are missing."""


def _no_fetch(url: str, *args, **kwargs):
    raise ValueError("External resources are not loaded in PDF exports")


def report_html(result: TranscriptionResult, lang: str) -> str:
    """The printable HTML of a result, with what its owner's plan allows."""
    lang = lang if lang in ("es", "en") else "es"
    paid = report_view.owner_has_pro(result.user_id)
    context = report_view.report_context(result, lang, paid, for_print=True)
    return report_view.render(
        "report_pdf.html",
        **context,
        title=report_view.report_title(result, lang),
        print_css=PRINT_CSS.read_text(encoding="utf-8"),
    )


def render_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:  # OSError: Pango/HarfBuzz missing on the system
        logger.error("WeasyPrint is not usable: %s", type(exc).__name__)
        raise PdfUnavailableError(PDF_UNAVAILABLE) from exc
    return HTML(string=html, url_fetcher=_no_fetch).write_pdf()


def result_pdf(result: TranscriptionResult, lang: str) -> bytes:
    """
    For its owner with active Apex Pro, the full report in `lang` is built first if it was not yet
    (as when they open the summary in the app); it is then kept. Otherwise nothing is generated.
    """
    if result.plan != "guest" and report_view.owner_has_pro(result.user_id):
        from app.services.job_manager import job_manager

        job_manager.get_or_build_summa(result, lang)
    return render_pdf(report_html(result, lang))
