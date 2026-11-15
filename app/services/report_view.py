"""
Server-rendered report (app/services/report_view.py)
----------------------------------------------------
One Jinja template (`templates/report/_report.html`) draws a result: key figures, the Apex Summa
summary with its charts, the minutes and the transcript. The public share page uses it.

What it shows follows the owner's plan, as in the app: without active Apex Pro, the preview
(speakers and charts) and no minutes. It never calls an LLM: it shows the report already saved.
Everything is autoescaped; charts are SVG drawn here, so no script is needed to see them.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.schemas import ApexSummaReport, TranscriptionResult
from app.services.apex_summa import MINUTES_TEMPLATES_CATALOG, redact_report
from app.services.supabase_service import supabase_service

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"], default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)

CHART_COLORS = ["#f43e01", "#4646dd", "#225c05", "#a2003f", "#a27900", "#0090a2"]

LABELS: Dict[str, Dict[str, str]] = {
    "es": {
        "shared_by": "Compartido por {name} desde Apex Vox",
        "shared_by_anon": "Compartido desde Apex Vox",
        "read_only": "Solo lectura",
        "kpi_duration": "Duración Global",
        "kpi_speakers": "Oradores Detectados",
        "kpi_engine": "Modelo Serie Mc",
        "kpi_date": "Fecha",
        "player_caption": "Reproductor continuo (haz clic en cualquier marca de tiempo para saltar al instante exacto)",
        "summa_pill": "Apex Summa IA · Potenciado por Groq",
        "summa_title": "Resumen Inteligente, Gráficas y Calendario de Tareas",
        "summa_locked": "El resumen, los objetivos, las alertas, las tareas y el acta están incluidos en Apex Pro.",
        "sec_who": "1. ¿Quién Habló Más?",
        "sec_what": "2. ¿De Qué se Habló?",
        "sec_objectives": "3. Objetivos Identificados",
        "sec_callouts": "4. Llamados de Atención y Alertas",
        "sec_calendar": "5. Próximas Tareas en Forma de Calendario",
        "sec_charts": "6. Gráficas de la Transcripción",
        "sec_minutes": "7. Acta",
        "timeline_caption": "Densidad de palabras por tramo de tiempo:",
        "led": "{speaker} lideró la conversación ({pct}%)",
        "spoken": "Tiempo hablado",
        "words": "Palabras",
        "turns": "Intervenciones",
        "pace": "Ritmo",
        "wpm": "pal/min",
        "words_short": "pal.",
        "turns_short": "turnos",
        "voice_chart": "Distribución de voz por orador",
        "timeline_chart": "Palabras por tramo de tiempo",
        "none_yet": "Nada identificado.",
        "transcript": "Transcripción",
        "file": "Archivo #{n}: {name}",
        "start": "Inicio",
        "play_from": "Reproducir desde {ts}",
        "no_segments": "Esta transcripción no tiene segmentos.",
        "minutes_org": "Organización",
        "minutes_type": "Tipo de Documento",
        "minutes_date": "Fecha de Emisión",
        "minutes_duration": "Duración Total Registrada",
        "minutes_quorum": "1. Verificación de Quórum y Participación",
        "minutes_dominant": "Mayor intervención",
        "minutes_agenda": "2. Orden del Día y Desarrollo de la Sesión",
        "minutes_resolutions": "3. Objetivos, Acuerdos y Resoluciones",
        "minutes_callouts": "4. Llamados de Atención",
        "minutes_tasks": "5. Cronograma de Próximas Tareas y Compromisos",
        "minutes_col_date": "Fecha",
        "minutes_col_task": "Tarea",
        "minutes_col_owner": "Responsable",
        "minutes_col_priority": "Prioridad",
        "minutes_secretary": "Apex Summa · Secretaría",
        "footer": "Hecho con Apex Vox: transcribe, identifica quién habla y resume tus reuniones.",
        "footer_cta": "Prueba Apex Vox",
        "ai_notice": "Generado con inteligencia artificial: puede contener errores. Revísalo antes de tomar decisiones.",
    },
    "en": {
        "shared_by": "Shared by {name} from Apex Vox",
        "shared_by_anon": "Shared from Apex Vox",
        "read_only": "Read only",
        "kpi_duration": "Total Duration",
        "kpi_speakers": "Detected Speakers",
        "kpi_engine": "Mc Series Model",
        "kpi_date": "Date",
        "player_caption": "Continuous player (click any timestamp to jump to that moment)",
        "summa_pill": "Apex Summa AI · Powered by Groq",
        "summa_title": "Smart Summary, Charts and Task Calendar",
        "summa_locked": "The summary, objectives, alerts, tasks and minutes are included in Apex Pro.",
        "sec_who": "1. Who Spoke the Most?",
        "sec_what": "2. What Was Discussed?",
        "sec_objectives": "3. Identified Objectives",
        "sec_callouts": "4. Callouts and Alerts",
        "sec_calendar": "5. Upcoming Tasks as a Calendar",
        "sec_charts": "6. Transcript Charts",
        "sec_minutes": "7. Minutes",
        "timeline_caption": "Word density per time segment:",
        "led": "{speaker} led the conversation ({pct}%)",
        "spoken": "Speaking time",
        "words": "Words",
        "turns": "Turns",
        "pace": "Pace",
        "wpm": "wpm",
        "words_short": "words",
        "turns_short": "turns",
        "voice_chart": "Speaking time per speaker",
        "timeline_chart": "Words per time segment",
        "none_yet": "Nothing identified.",
        "transcript": "Transcript",
        "file": "File #{n}: {name}",
        "start": "Start",
        "play_from": "Play from {ts}",
        "no_segments": "This transcript has no segments.",
        "minutes_org": "Organization",
        "minutes_type": "Document Type",
        "minutes_date": "Date",
        "minutes_duration": "Total Audio Duration",
        "minutes_quorum": "1. Quorum & Speaker Participation",
        "minutes_dominant": "Dominant speaker",
        "minutes_agenda": "2. Agenda & Key Discussion Topics",
        "minutes_resolutions": "3. Objectives & Resolutions",
        "minutes_callouts": "4. Callouts & Critical Warnings",
        "minutes_tasks": "5. Action Items & Calendar Commitments",
        "minutes_col_date": "Date",
        "minutes_col_task": "Task",
        "minutes_col_owner": "Owner",
        "minutes_col_priority": "Priority",
        "minutes_secretary": "Apex Summa · Secretary",
        "footer": "Made with Apex Vox: transcribe, identify who speaks and summarize your meetings.",
        "footer_cta": "Try Apex Vox",
        "ai_notice": "Generated with artificial intelligence: it may contain errors. Review it before making decisions.",
    },
}


def owner_has_pro(owner_id: Optional[str]) -> bool:
    """Active Apex Pro (or trial) of the account that owns a result."""
    user = supabase_service._read_snapshot()["users"].get(owner_id) if owner_id else None
    return bool(user) and str(user.get("plan", "free")).lower() in ("pro", "trial") and not supabase_service._plan_expired(user)


def visible_report(result: TranscriptionResult, paid: bool, lang: str) -> Optional[ApexSummaReport]:
    """The saved report this plan may show, in `lang` when that translation exists. Never generated here."""
    report = result.summa_report
    if not report or result.plan == "guest":
        return None
    if not paid or report.is_locked:
        return redact_report(report)
    if report.language != lang and lang in result.summa_translations:
        return result.summa_translations[lang]
    return report


def donut_svg(stats: List[Any], label: str) -> Dict[str, Any]:
    """Arcs of the speaking-time donut (same geometry as the app)."""
    arcs, cumulative = [], 0.0
    for idx, s in enumerate(stats):
        pct = max(0.0, float(getattr(s, "talk_percentage", 0) or 0))
        arcs.append({
            "color": CHART_COLORS[idx % len(CHART_COLORS)],
            "dasharray": f"{pct:g} {max(0.0, 100 - pct):g}",
            "dashoffset": f"{25 - cumulative:g}",
        })
        cumulative += pct
    return {"arcs": arcs, "label": label}


def timeline_svg(points: List[Any]) -> Dict[str, Any]:
    """Bars of the word-density chart, in SVG units (one 40-unit column per bucket)."""
    max_words = max([int(getattr(p, "word_count", 0) or 0) for p in points] + [1])
    col, plot_h, top = 40, 58, 14
    bars = []
    for i, p in enumerate(points):
        words = int(getattr(p, "word_count", 0) or 0)
        h = max(4, round(words / max_words * plot_h))
        bars.append({
            "x": i * col + 8, "y": top + plot_h - h, "w": 24, "h": h,
            "color": CHART_COLORS[0] if i % 2 == 0 else "#ff9b71",
            "value": f"{words}w", "value_y": top + plot_h - h - 3,
            "label": str(getattr(p, "bucket_label", "")), "cx": i * col + 20,
        })
    return {"bars": bars, "width": max(col, len(points) * col), "height": top + plot_h + 26, "base_y": top + plot_h}


def minutes_context(result: TranscriptionResult, report: ApexSummaReport, lang: str, template_id: str = "consejo") -> Dict[str, Any]:
    tpl = next((t for t in MINUTES_TEMPLATES_CATALOG if t["id"] == template_id), MINUTES_TEMPLATES_CATALOG[0])
    return {
        "title": tpl["title_en"] if lang == "en" else tpl["title_es"],
        "date": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "duration": result.total_duration_formatted,
    }


def _speaker_index(result: TranscriptionResult) -> Dict[str, int]:
    order: Dict[str, int] = {}
    for seg in result.segments:
        order.setdefault(seg.speaker, len(order))
    return order


def report_context(
    result: TranscriptionResult,
    lang: str,
    paid: bool,
    audio_url: Optional[str] = None,
    for_print: bool = False,
) -> Dict[str, Any]:
    lang = lang if lang in LABELS else "es"
    L = LABELS[lang]
    report = visible_report(result, paid, lang)
    stats = report.speaker_stats if report else []
    speakers = _speaker_index(result)
    segments = [
        {
            "seg": seg,
            "badge": f"speaker-{speakers.get(seg.speaker, 0) % 4}",
            "alt": speakers.get(seg.speaker, 0) % 2 == 1,
        }
        for seg in result.segments
    ]
    created = (result.summa_report.generated_at if result.summa_report else "") or ""
    return {
        "L": L,
        "lang": lang,
        "result": result,
        "report": report,
        "locked": bool(report and report.is_locked),
        "donut": donut_svg(stats, L["voice_chart"]) if stats else None,
        "timeline": timeline_svg(report.charts.timeline_density) if report and report.charts.timeline_density else None,
        "minutes": minutes_context(result, report, lang) if report and not report.is_locked else None,
        "segments": segments,
        "audio_url": audio_url,
        "for_print": for_print,
        "date": created[:10],
    }


def render(template: str, **context: Any) -> str:
    return _env.get_template(template).render(**context)
