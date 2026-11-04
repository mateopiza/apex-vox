"""
Servidor MCP de Apex Vox (app/services/mcp_server.py)
----------------------------------------------------
Herramientas de solo lectura para que ChatGPT, Claude u otro cliente MCP respondan
preguntas sobre las reuniones y llamadas del usuario autenticado. Cada herramienta solo
ve los datos de esa cuenta.

- Identificar reuniones: find_meeting entiende descripciones como «la llamada con Ana de
  ayer» o «el comité del lunes sobre presupuesto» (fechas relativas, participantes,
  contacto, origen y palabras del contenido). list_meetings filtra por fecha, origen,
  orador o texto. En todas las herramientas meeting_id acepta «latest».
- Revisar: detalles, apuntes tomados en vivo (con el contexto de la transcripción),
  transcripción filtrada por orador o tramo, resumen, acta, tareas.
- Agenda: próximas reuniones con bot y llamadas grabadas.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service

logger = logging.getLogger("app.services.mcp_server")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "apex-vox", "title": "Apex Vox", "version": "1.1.0"}
INSTRUCTIONS = (
    "Apex Vox guarda las reuniones y llamadas transcritas del usuario (con oradores y marcas de tiempo), "
    "los apuntes que tomó en vivo y, en Apex Pro, su resumen ejecutivo, temas, objetivos, alertas, tareas y acta. "
    "Para identificar una reunión descrita en lenguaje natural («la llamada con Ana de ayer», «el comité del lunes») "
    "usa find_meeting; para listar con filtros, list_meetings. meeting_id acepta «latest» (la más reciente). "
    "Luego usa get_meeting_details, get_meeting_notes, get_meeting_transcript, get_meeting_summary, "
    "get_meeting_minutes o get_action_items. Cita la marca de tiempo [HH:MM:SS] cuando uses frases de la "
    "transcripción. Si find_meeting devuelve varias candidatas parecidas, pregúntale al usuario cuál es."
)
MAX_TRANSCRIPT_CHARS = 60_000
CONTENT_SCAN_LIMIT = 60  # reuniones recientes en las que find_meeting busca dentro del texto
SEARCH_SCAN_LIMIT = 200  # reuniones recientes que recorre search_meetings (acota el costo por llamada)

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

SOURCES = {
    "upload": "Audio subido",
    "box": "Grabación (Apex Box)",
    "meeting_bot": "Bot de reuniones",
    "phone_call": "Llamada telefónica",
}
_MEETING_ID = {"type": "string", "description": "id devuelto por list_meetings o find_meeting, o «latest»"}
_DATE = {"type": "string", "description": "AAAA-MM-DD"}


def _schema(props: Dict[str, Any], required: Iterable[str] = ()) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = list(required)
    return out


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "find_meeting",
        "title": "Identificar una reunión",
        "description": (
            "Encuentra la reunión o llamada que el usuario describe con sus palabras: fecha o fecha relativa "
            "(hoy, ayer, el lunes, la semana pasada, 30 de octubre), participante o contacto, tipo "
            "(llamada, bot, grabación, audio) y temas. Devuelve candidatas ordenadas con el motivo de cada coincidencia."
        ),
        "inputSchema": _schema({
            "description": {"type": "string", "minLength": 2, "description": "Cómo la describe el usuario"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        }, ["description"]),
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_meetings",
        "title": "Listar reuniones",
        "description": (
            "Lista las reuniones y llamadas del usuario, de la más reciente a la más antigua, con filtros "
            "opcionales de fecha (date_from/date_to o when en lenguaje natural), origen, orador y texto del título."
        ),
        "inputSchema": _schema({
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            "when": {"type": "string", "description": "Fecha en lenguaje natural: hoy, ayer, esta semana, 2026-10-30…"},
            "date_from": _DATE,
            "date_to": _DATE,
            "source": {"type": "string", "enum": list(SOURCES)},
            "speaker": {"type": "string", "description": "Nombre de un orador o contacto"},
            "query": {"type": "string", "description": "Palabras del título"},
        }),
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_meeting_details",
        "title": "Detalles de una reunión",
        "description": (
            "Ficha de una reunión: fecha, duración, origen (llamada con contacto, bot con plataforma, grabación o audio), "
            "participantes con su tiempo de palabra, cantidad de apuntes, temas, tareas y enlaces."
        ),
        "inputSchema": _schema({"meeting_id": _MEETING_ID}, ["meeting_id"]),
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_meeting_notes",
        "title": "Apuntes de una reunión",
        "description": (
            "Apuntes que el usuario tomó durante la reunión o llamada (nota, acuerdo, tarea, alerta, idea, pregunta), "
            "con su marca de tiempo y, si se pide, lo que se estaba diciendo en ese momento."
        ),
        "inputSchema": _schema({
            "meeting_id": _MEETING_ID,
            "tag": {"type": "string", "enum": ["nota", "acuerdo", "tarea", "alerta", "idea", "pregunta"]},
            "with_context": {"type": "boolean", "default": True},
        }, ["meeting_id"]),
        "annotations": _READ_ONLY,
    },
    {
        "name": "search_meetings",
        "title": "Buscar en reuniones",
        "description": (
            "Busca palabras o frases (sin importar tildes ni mayúsculas) en las transcripciones y apuntes del usuario. "
            "Todas las palabras deben aparecer en el fragmento. Filtros opcionales: reunión, orador y fechas."
        ),
        "inputSchema": _schema({
            "query": {"type": "string", "minLength": 2, "description": "Texto a buscar"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15},
            "meeting_id": _MEETING_ID,
            "speaker": {"type": "string"},
            "date_from": _DATE,
            "date_to": _DATE,
        }, ["query"]),
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_meeting_transcript",
        "title": "Transcripción de una reunión",
        "description": (
            "Transcripción con oradores y marcas de tiempo. Opcional: solo un orador, o un tramo (start/end en HH:MM:SS)."
        ),
        "inputSchema": _schema({
            "meeting_id": _MEETING_ID,
            "speaker": {"type": "string"},
            "start": {"type": "string", "description": "HH:MM:SS"},
            "end": {"type": "string", "description": "HH:MM:SS"},
        }, ["meeting_id"]),
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_meeting_summary",
        "title": "Resumen de una reunión",
        "description": "Resumen ejecutivo de Apex Summa: quién habló más, temas, objetivos, alertas y tareas (Apex Pro).",
        "inputSchema": _schema({"meeting_id": _MEETING_ID}, ["meeting_id"]),
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_meeting_minutes",
        "title": "Acta de una reunión",
        "description": (
            "Acta formal en Markdown, con los apuntes en vivo integrados (Apex Pro). Plantillas: ejecutiva (minuta de "
            "decisiones), seguimiento (proyecto), comite, consejo (junta directiva), asamblea."
        ),
        "inputSchema": _schema({
            "meeting_id": _MEETING_ID,
            "template": {"type": "string", "enum": ["ejecutiva", "seguimiento", "comite", "consejo", "asamblea"],
                         "default": "ejecutiva"},
        }, ["meeting_id"]),
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_action_items",
        "title": "Tareas y compromisos",
        "description": "Tareas con responsable y fecha de una reunión o de las últimas reuniones (Apex Pro).",
        "inputSchema": _schema({
            "meeting_id": {"type": "string", "description": "Opcional: solo esta reunión (o «latest»)"},
            "limit_meetings": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "assignee": {"type": "string", "description": "Opcional: solo las de este responsable"},
        }),
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_upcoming_meetings",
        "title": "Próximas reuniones",
        "description": "Reuniones futuras recibidas por invitación de calendario y bots programados para grabarlas.",
        "inputSchema": _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}}),
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_phone_calls",
        "title": "Llamadas grabadas",
        "description": (
            "Llamadas hechas desde Apex Vox con el número enmascarado: contacto, estado, duración, apuntes "
            "y el meeting_id de su transcripción cuando ya está lista."
        ),
        "inputSchema": _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}}),
        "annotations": _READ_ONLY,
    },
]


class ToolError(Exception):
    """Error que se muestra al modelo como resultado de la herramienta (isError)."""


# ---------------------------------------------------------------------------
# Texto, fechas y zona horaria
# ---------------------------------------------------------------------------

def _tz() -> dt.tzinfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE or "America/Bogota")
    except Exception:  # noqa: BLE001
        return dt.timezone(dt.timedelta(hours=-5))


def _today() -> dt.date:
    return dt.datetime.now(_tz()).date()


def _local(iso: Optional[str]) -> Optional[dt.datetime]:
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(_tz())


def _fmt_local(iso: Optional[str]) -> str:
    d = _local(iso)
    return d.strftime("%Y-%m-%d %H:%M") if d else ""


def _norm(text: Any) -> str:
    """Minúsculas y sin tildes, para comparar «reunión» con «reunion»."""
    s = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


_STOP = set(_norm(w) for w in (
    "el la los las un una unos unas de del al a en y o que con por para sobre se su sus mi mis me lo le "
    "reunion reuniones llamada llamadas meeting meetings call calls the of and or with on in at about my "
    "esa ese esta este eso hicimos tuve tuvimos hablamos hable donde cuando cual quiero ver buscar busca "
    "encuentra find show from to for was we i").split())

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
DateRange = Tuple[dt.date, dt.date]


def parse_when(text: str, today: Optional[dt.date] = None) -> Tuple[Optional[DateRange], List[str]]:
    """Primer rango de fechas mencionado en el texto y las palabras que lo formaban."""
    t = _norm(text)
    today = today or _today()
    used: List[str] = []

    def found(rng: DateRange, *words: str) -> Tuple[Optional[DateRange], List[str]]:
        used.extend(w for phrase in words for w in phrase.split())
        return rng, used

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        try:
            d = dt.date(int(m[1]), int(m[2]), int(m[3]))
            return found((d, d), m[0])
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        year = int(m[3]) if m[3] else today.year
        year = year + 2000 if year < 100 else year
        try:
            d = dt.date(year, int(m[2]), int(m[1]))
            if not m[3] and d > today:
                d = d.replace(year=d.year - 1)
            return found((d, d), m[0])
        except ValueError:
            pass
    month_names = "|".join(_MONTHS)
    m = (re.search(rf"\b(\d{{1,2}})\s+de\s+({month_names})(?:\s+(?:de\s+)?(\d{{4}}))?\b", t)
         or re.search(rf"\b({month_names})\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?\b", t))
    if m:
        day, month = (m[1], m[2]) if m[1].isdigit() else (m[2], m[1])
        try:
            d = dt.date(int(m[3]) if m[3] else today.year, _MONTHS[month], int(day))
            if not m[3] and d > today:
                d = d.replace(year=d.year - 1)
            return found((d, d), m[0])
        except ValueError:
            pass
    m = re.search(r"\b(?:ultimos|last|past)\s+(\d{1,3})\s+(?:dias|days)\b", t)
    if m:
        return found((today - dt.timedelta(days=int(m[1])), today), m[0])
    simple = [
        (r"\bantier\b|\banteayer\b|\bday before yesterday\b", lambda: (today - dt.timedelta(days=2),) * 2),
        (r"\bayer\b|\byesterday\b", lambda: (today - dt.timedelta(days=1),) * 2),
        (r"\bhoy\b|\btoday\b", lambda: (today, today)),
        (r"\b(?:semana pasada|ultima semana|last week)\b", lambda: (
            today - dt.timedelta(days=today.weekday() + 7), today - dt.timedelta(days=today.weekday() + 1))),
        (r"\b(?:esta semana|this week)\b", lambda: (today - dt.timedelta(days=today.weekday()), today)),
        (r"\b(?:mes pasado|last month)\b", lambda: (
            (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1), today.replace(day=1) - dt.timedelta(days=1))),
        (r"\b(?:este mes|this month)\b", lambda: (today.replace(day=1), today)),
    ]
    for pattern, rng in simple:
        m = re.search(pattern, t)
        if m:
            return found(rng(), m[0])
    m = re.search(r"\b(" + "|".join(_WEEKDAYS) + r")(?:\s+pasado)?\b", t)
    if m:
        back = (today.weekday() - _WEEKDAYS[m[1]]) % 7 or (7 if "pasado" in m[0] else 0)
        d = today - dt.timedelta(days=back)
        return found((d, d), m[0])
    return None, used


def _parse_date(value: Any, field: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ToolError(f"{field} debe tener formato AAAA-MM-DD.") from exc


def _parse_hms(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    parts = str(value).strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:
        raise ToolError("Usa el formato HH:MM:SS para start y end.") from exc
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def _hms(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


# ---------------------------------------------------------------------------
# Datos del usuario
# ---------------------------------------------------------------------------

def _is_paid(user: Dict[str, Any]) -> bool:
    return str(user.get("plan", "free")).lower() in ("pro", "trial")


def _records(user_id: str) -> List[Dict[str, Any]]:
    recs = supabase_service.list_user_transcriptions(user_id)
    return sorted(recs, key=lambda r: str(r.get("created_at", "")), reverse=True)


def _links(user_id: str) -> Dict[str, Dict[str, Any]]:
    """job_id → llamada o bot que lo originó (para registros antiguos sin «source»)."""
    with supabase_service._lock:
        db = supabase_service._load_db()
        calls = [dict(c) for c in (db.get("phone_calls") or {}).values() if c.get("user_id") == user_id]
        bots = [dict(b) for b in (db.get("meeting_bots") or {}).values() if b.get("user_id") == user_id]
    out: Dict[str, Dict[str, Any]] = {}
    for b in bots:
        if b.get("job_id"):
            out[b["job_id"]] = {"source": "meeting_bot", "platform": b.get("platform"), "meeting_url": b.get("meeting_url")}
    for c in calls:
        if c.get("job_id"):
            out[c["job_id"]] = {"source": "phone_call", "contact_name": c.get("contact_name"),
                                "contact_number": c.get("to"), "call_id": c.get("call_id")}
    return out


def _enrich(rec: Dict[str, Any], links: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    extra = links.get(rec.get("job_id", ""), {})
    out = {**extra, **{k: v for k, v in rec.items() if v not in (None, "")}}
    out.setdefault("source", "upload")
    return out


def _title(rec: Dict[str, Any]) -> str:
    if rec.get("title"):
        return str(rec["title"])
    files = rec.get("file_order") or []
    return str(files[0]) if files else "Reunión sin título"


def _people(rec: Dict[str, Any], deep: bool = False) -> List[str]:
    """Oradores y contacto. Con deep=True, los registros antiguos (sin «speakers») se leen de la transcripción."""
    speakers = rec.get("speakers")
    if not speakers and deep:
        result = job_manager.get_job_result(rec.get("job_id", ""))
        speakers = list(dict.fromkeys(s.speaker for s in result.segments)) if result else []
        rec["speakers"] = speakers
    names = [str(s) for s in speakers or []]
    for key in ("contact_name", "contact_number", "dominant_speaker"):
        if rec.get(key) and str(rec[key]) not in names:
            names.append(str(rec[key]))
    return names


def _summary_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "meeting_id": rec["job_id"],
        "title": _title(rec),
        "date": _fmt_local(rec.get("created_at")),
        "duration": rec.get("total_duration_formatted", ""),
        "source": rec.get("source", "upload"),
        "source_label": SOURCES.get(rec.get("source", "upload"), rec.get("source")),
        "participants": _people(rec),
        "contact": rec.get("contact_name") or rec.get("contact_number") or None,
        "notes_count": rec.get("notes_count"),
        "url": _meeting_url(rec["job_id"]),
    }


def _row_line(m: Dict[str, Any]) -> str:
    who = f" · con {', '.join(m['participants'][:4])}" if m["participants"] else ""
    return f"- {m['title']} · {m['date']} · {m['duration']} · {m['source_label']}{who} · id: {m['meeting_id']}"


def _enriched_records(user_id: str) -> List[Dict[str, Any]]:
    links = _links(user_id)
    return [_enrich(r, links) for r in _records(user_id)]


def _resolve_id(user: Dict[str, Any], meeting_id: str) -> str:
    meeting_id = (meeting_id or "").strip()
    if _norm(meeting_id) in ("latest", "last", "ultima", "ultimo", "reciente", "mas reciente"):
        recs = _records(user["user_id"])
        if not recs:
            raise ToolError("No tienes reuniones transcritas todavía.")
        return recs[0]["job_id"]
    if not re.fullmatch(r"[\w-]{1,64}", meeting_id):
        raise ToolError("meeting_id inválido.")
    return meeting_id


def _record_for(user: Dict[str, Any], meeting_id: str) -> Dict[str, Any]:
    meeting_id = _resolve_id(user, meeting_id)
    for rec in _enriched_records(user["user_id"]):
        if rec.get("job_id") == meeting_id:
            return rec
    raise ToolError("No encontré esa reunión en tu cuenta. Usa find_meeting o list_meetings para ver los ids.")


def _result_for(user: Dict[str, Any], meeting_id: str):
    rec = _record_for(user, meeting_id)
    result = job_manager.get_job_result(rec["job_id"])
    if not result:
        raise ToolError("La transcripción ya no está disponible (pudo vencer su periodo de almacenamiento).")
    return result


def _meeting_url(meeting_id: str) -> str:
    return f"{settings.PUBLIC_BASE_URL or 'https://apex-vox.ialabs.app'}/?job={meeting_id}"


def _in_range(rec: Dict[str, Any], rng: Optional[DateRange]) -> bool:
    if not rng:
        return True
    d = _local(rec.get("created_at"))
    return bool(d) and rng[0] <= d.date() <= rng[1]


def _speaker_match(rec: Dict[str, Any], name: str) -> bool:
    needle = _norm(name)
    return any(needle in _norm(p) for p in _people(rec, deep=True))


def _notes_of(result) -> List[Dict[str, Any]]:
    return sorted((dict(n) for n in (result.live_notes or [])), key=lambda n: float(n.get("timestamp_sec") or 0))


# ---------------------------------------------------------------------------
# Identificar reuniones
# ---------------------------------------------------------------------------

_SOURCE_WORDS = {
    "phone_call": ("llamada", "llame", "llamamos", "llamo", "telefono", "celular", "call", "called", "phone"),
    "meeting_bot": ("bot", "zoom", "meet", "teams", "webex", "videollamada", "virtual"),
    "box": ("grabacion", "grabe", "presencial", "box", "en vivo", "recorded", "in person"),
    "upload": ("audio", "archivo", "subi", "upload", "uploaded", "nota de voz"),
}


def tool_find_meeting(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    description = str(args.get("description") or "").strip()
    if len(description) < 2:
        raise ToolError("Describe la reunión con al menos 2 caracteres.")
    limit = max(1, min(int(args.get("limit") or 5), 10))
    recs = _enriched_records(user["user_id"])
    if not recs:
        return "No tienes reuniones transcritas todavía.", {"candidates": []}

    rng, date_words = parse_when(description)
    text = _norm(description)
    wanted_sources = {src for src, words in _SOURCE_WORDS.items() if any(re.search(rf"\b{w}\b", text) for w in words)}
    source_words = {w for words in _SOURCE_WORDS.values() for w in words}
    tokens = [w for w in re.findall(r"[\w+]{3,}", text)
              if w not in _STOP and w not in date_words and w not in source_words and w not in _MONTHS]

    scored = []
    for idx, rec in enumerate(recs):
        score, why = 0.0, []
        if rng:
            if _in_range(rec, rng):
                score += 4
                why.append("fecha")
            else:
                score -= 3
        if wanted_sources:
            if rec.get("source") in wanted_sources:
                score += 2.5
                why.append(SOURCES.get(rec["source"], rec["source"]).lower())
            else:
                score -= 1
        title, people = _norm(_title(rec)), [_norm(p) for p in _people(rec, deep=idx < CONTENT_SCAN_LIMIT)]
        digits = re.sub(r"\D", "", description)
        if len(digits) >= 4 and rec.get("contact_number") and digits[-4:] in str(rec["contact_number"]):
            score += 4
            why.append("número del contacto")
        for tok in tokens:
            if tok in title:
                score += 2
                why.append(f"título «{tok}»")
            if any(tok in p for p in people):
                score += 3
                why.append(f"participante «{tok}»")
        scored.append([score, -idx, rec, why])

    # Buscar en el contenido (resumen, temas, apuntes, transcripción) de las más recientes
    if tokens:
        for item in scored[:CONTENT_SCAN_LIMIT]:
            result = job_manager.get_job_result(item[2]["job_id"])
            if not result:
                continue
            report = result.summa_report
            summary = _norm(" ".join([report.executive_summary] + [t.title for t in report.topics])) if report else ""
            notes = _norm(" ".join(str(n.get("text", "")) for n in result.live_notes or []))
            body = _norm(result.full_text[:200_000])
            hits = 0
            for tok in tokens:
                if tok in summary or tok in notes:
                    hits += 1.5
                    item[3].append(f"tema «{tok}»")
                elif tok in body:
                    hits += 1
                    item[3].append(f"se habló de «{tok}»")
            item[0] += min(hits, 6)

    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    best = [s for s in scored if s[0] > 0][:limit] or scored[: min(limit, 3)]
    candidates = []
    for score, _, rec, why in best:
        row = _summary_row(rec)
        row["score"] = round(score, 1)
        row["matched"] = list(dict.fromkeys(why)) or ["más reciente"]
        candidates.append(row)
    header = f"Candidatas para «{description}»"
    if rng:
        header += f" (fechas {rng[0].isoformat()} a {rng[1].isoformat()})"
    lines = [_row_line(c) + f" · coincide en: {', '.join(c['matched'])}" for c in candidates]
    if candidates and all(c["score"] <= 0 for c in candidates):
        header += ". Ninguna coincide bien; estas son las más recientes"
    return header + ":\n" + "\n".join(lines), {"candidates": candidates,
                                               "date_range": [rng[0].isoformat(), rng[1].isoformat()] if rng else None}


def tool_list_meetings(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    limit = max(1, min(int(args.get("limit") or 20), 50))
    rng: Optional[DateRange] = None
    if args.get("when"):
        rng, _ = parse_when(str(args["when"]))
        if not rng:
            raise ToolError("No entendí la fecha de «when». Usa por ejemplo: hoy, ayer, esta semana o 2026-10-30.")
    d_from, d_to = _parse_date(args.get("date_from"), "date_from"), _parse_date(args.get("date_to"), "date_to")
    if d_from or d_to:
        rng = (d_from or dt.date.min, d_to or dt.date.max)
    source, speaker, query = args.get("source"), args.get("speaker"), _norm(args.get("query"))
    if source and source not in SOURCES:
        raise ToolError("source debe ser uno de: " + ", ".join(SOURCES))
    items = []
    for rec in _enriched_records(user["user_id"]):
        if not _in_range(rec, rng) or (source and rec.get("source") != source):
            continue
        if speaker and not _speaker_match(rec, speaker):
            continue
        if query and query not in _norm(_title(rec)):
            continue
        items.append(_summary_row(rec))
        if len(items) >= limit:
            break
    if not items:
        return "No encontré reuniones con esos filtros.", {"meetings": []}
    return f"{len(items)} reuniones:\n" + "\n".join(_row_line(m) for m in items), {"meetings": items}


# ---------------------------------------------------------------------------
# Revisar una reunión
# ---------------------------------------------------------------------------

def _talk_time(result) -> List[Dict[str, Any]]:
    if result.summa_report and result.summa_report.speaker_stats:
        return [{"speaker": s.speaker, "talk_time": s.duration_formatted, "talk_pct": round(s.talk_percentage, 1),
                 "turns": s.turn_count} for s in result.summa_report.speaker_stats]
    totals: Dict[str, float] = {}
    turns: Dict[str, int] = {}
    for s in result.segments:
        totals[s.speaker] = totals.get(s.speaker, 0.0) + max(0.0, s.end - s.start)
        turns[s.speaker] = turns.get(s.speaker, 0) + 1
    whole = sum(totals.values()) or 1.0
    return [{"speaker": k, "talk_time": _hms(v), "talk_pct": round(100 * v / whole, 1), "turns": turns[k]}
            for k, v in sorted(totals.items(), key=lambda kv: -kv[1])]


def tool_get_meeting_details(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    rec = _record_for(user, str(args.get("meeting_id", "")))
    result = job_manager.get_job_result(rec["job_id"])
    row = _summary_row(rec)
    details: Dict[str, Any] = {**row, "expires_at": rec.get("expires_at"), "engine": rec.get("engine_brand")}
    lines = [f"{row['title']} ({row['meeting_id']})", f"Fecha: {row['date']} · Duración: {row['duration']}",
             f"Origen: {row['source_label']}"]
    if rec.get("source") == "phone_call":
        details["contact"] = {"name": rec.get("contact_name") or None, "number": rec.get("contact_number"),
                              "shown_caller_id": rec.get("caller_id")}
        lines.append(f"Contacto: {rec.get('contact_name') or ''} {rec.get('contact_number') or ''}".rstrip()
                     + (f" · llamaste desde el número enmascarado {rec['caller_id']}" if rec.get("caller_id") else ""))
    if rec.get("source") == "meeting_bot" and rec.get("meeting_url"):
        details["meeting_url"] = rec["meeting_url"]
        lines.append(f"Reunión virtual: {rec['meeting_url']}")
    if result:
        talk = _talk_time(result)
        notes = _notes_of(result)
        report = result.summa_report
        details.update({
            "participants": talk, "notes_count": len(notes),
            "notes_by_tag": {tag: sum(1 for n in notes if n.get("tag") == tag) for tag in {n.get("tag") for n in notes}},
            "has_summary": bool(report and not report.is_locked),
            "topics": [t.title for t in report.topics] if report and not report.is_locked else [],
            "tasks_count": len(report.calendar_tasks) if report and not report.is_locked else 0,
            "language": result.language,
        })
        lines.append("Participantes: " + "; ".join(f"{p['speaker']} {p['talk_time']} ({p['talk_pct']}%)" for p in talk))
        lines.append(f"Apuntes en vivo: {len(notes)}"
                     + (f" ({', '.join(f'{v} {k}' for k, v in details['notes_by_tag'].items())})" if notes else ""))
        if details["topics"]:
            lines.append("Temas: " + "; ".join(details["topics"]))
        if details["tasks_count"]:
            lines.append(f"Tareas: {details['tasks_count']} (usa get_action_items)")
        if report and report.is_locked:
            lines.append("El resumen completo está incluido en Apex Pro.")
    else:
        lines.append("La transcripción ya no está disponible (pudo vencer su periodo de almacenamiento).")
    lines.append(f"Enlace: {row['url']}")
    return "\n".join(lines), details


def tool_get_meeting_notes(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    result = _result_for(user, str(args.get("meeting_id", "")))
    tag = args.get("tag")
    with_context = args.get("with_context", True) is not False
    notes = [n for n in _notes_of(result) if not tag or n.get("tag") == tag]
    if not notes:
        msg = "Esta reunión no tiene apuntes" + (f" con la etiqueta «{tag}»." if tag else " tomados en vivo.")
        return msg, {"meeting_id": result.job_id, "notes": []}
    out, lines = [], []
    for n in notes:
        ts = float(n.get("timestamp_sec") or 0)
        item = {"timestamp": n.get("timestamp_formatted") or _hms(ts), "tag": n.get("tag", "nota"),
                "author": n.get("author") or n.get("speaker") or "", "text": n.get("text", "")}
        lines.append(f"- [{item['timestamp']}] {item['tag'].upper()}"
                     + (f" ({item['author']})" if item["author"] else "") + f": {item['text']}")
        if with_context:
            ctx = [s for s in result.segments if s.end >= ts - 25 and s.start <= ts + 10][:6]
            item["context"] = [{"timestamp": s.start_formatted, "speaker": s.speaker, "text": s.text} for s in ctx]
            lines.extend(f"    · [{s.start_formatted}] {s.speaker}: {s.text}" for s in ctx)
        out.append(item)
    return f"{len(out)} apuntes de la reunión {result.job_id}:\n" + "\n".join(lines), {
        "meeting_id": result.job_id, "notes": out}


def tool_search_meetings(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    query = str(args.get("query") or "").strip()
    if len(query) < 2:
        raise ToolError("La búsqueda necesita al menos 2 caracteres.")
    limit = max(1, min(int(args.get("limit") or 15), 50))
    phrase = _norm(query).strip('"')
    terms = [t for t in re.findall(r"\w+", phrase) if len(t) > 1] or [phrase]
    rng = None
    d_from, d_to = _parse_date(args.get("date_from"), "date_from"), _parse_date(args.get("date_to"), "date_to")
    if d_from or d_to:
        rng = (d_from or dt.date.min, d_to or dt.date.max)
    only = _resolve_id(user, str(args["meeting_id"])) if args.get("meeting_id") else None
    speaker = _norm(args.get("speaker")) if args.get("speaker") else None

    def matches(text: str) -> bool:
        t = _norm(text)
        return phrase in t or all(term in t for term in terms)

    hits: List[Dict[str, Any]] = []
    for rec in _enriched_records(user["user_id"])[:SEARCH_SCAN_LIMIT] if not only else _enriched_records(user["user_id"]):
        if (only and rec["job_id"] != only) or not _in_range(rec, rng):
            continue
        result = job_manager.get_job_result(rec["job_id"])
        if not result:
            continue
        segs = result.segments
        for i, seg in enumerate(segs):
            if speaker and speaker not in _norm(seg.speaker):
                continue
            if matches(seg.text):
                hits.append({
                    "meeting_id": rec["job_id"], "title": _title(rec), "date": _fmt_local(rec.get("created_at")),
                    "kind": "transcripción", "timestamp": seg.start_formatted, "speaker": seg.speaker, "text": seg.text,
                    "before": segs[i - 1].text if i > 0 else "", "after": segs[i + 1].text if i + 1 < len(segs) else "",
                })
                if len(hits) >= limit:
                    break
        for n in _notes_of(result):
            if len(hits) >= limit:
                break
            if speaker and speaker not in _norm(n.get("author") or n.get("speaker")):
                continue
            if matches(n.get("text", "")):
                hits.append({"meeting_id": rec["job_id"], "title": _title(rec), "date": _fmt_local(rec.get("created_at")),
                             "kind": f"apunte ({n.get('tag', 'nota')})", "timestamp": n.get("timestamp_formatted", ""),
                             "speaker": n.get("author") or "", "text": n.get("text", "")})
        if len(hits) >= limit:
            break
    if not hits:
        return f"No encontré «{query}» en tus reuniones.", {"results": []}
    lines = [f"- [{h['timestamp']}] {h['speaker']} ({h['title']}, {h['date']}, {h['kind']}, id {h['meeting_id']}): {h['text']}"
             for h in hits]
    return f"{len(hits)} coincidencias para «{query}»:\n" + "\n".join(lines), {"results": hits}


def tool_get_meeting_transcript(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    result = _result_for(user, str(args.get("meeting_id", "")))
    start, end = _parse_hms(args.get("start")), _parse_hms(args.get("end"))
    speaker = _norm(args.get("speaker")) if args.get("speaker") else None
    segs = [s for s in result.segments
            if (start is None or s.end >= start) and (end is None or s.start <= end)
            and (not speaker or speaker in _norm(s.speaker))]
    lines = [f"[{s.start_formatted}] {s.speaker}: {s.text}" for s in segs]
    filtered = bool(start is not None or end is not None or speaker)
    text = "\n".join(lines) or ("" if filtered else result.full_text) or "(sin texto en ese tramo)"
    truncated = len(text) > MAX_TRANSCRIPT_CHARS
    if truncated:
        text = text[:MAX_TRANSCRIPT_CHARS] + "\n[… transcripción recortada por longitud: pide un tramo con start/end …]"
    header = (f"Reunión {result.job_id} · duración {result.total_duration_formatted} · "
              f"{result.detected_speakers_count} oradores · {_meeting_url(result.job_id)}\n\n")
    return header + text, {
        "meeting_id": result.job_id, "duration": result.total_duration_formatted,
        "speakers": sorted({s.speaker for s in result.segments}), "truncated": truncated,
        "segments_returned": len(segs), "url": _meeting_url(result.job_id),
    }


def _require_pro(user: Dict[str, Any]) -> None:
    if not _is_paid(user):
        raise ToolError(
            "El resumen de Apex Summa, el acta y las tareas están incluidos en Apex Pro. "
            "Puedes leer la transcripción y los apuntes, o activar Apex Pro en "
            f"{settings.PUBLIC_BASE_URL or 'https://apex-vox.ialabs.app'}/?view=portal."
        )


def tool_get_meeting_summary(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    _require_pro(user)
    result = _result_for(user, str(args.get("meeting_id", "")))
    report = result.summa_report
    if not report:
        raise ToolError("Esta reunión no tiene resumen de Apex Summa.")
    parts = [f"Resumen de la reunión {result.job_id} ({result.total_duration_formatted})", report.executive_summary]
    if report.dominant_speaker:
        parts.append(f"Habló más: {report.dominant_speaker} ({report.dominant_speaker_pct:.0f}%)")
    if report.speaker_stats:
        parts.append("Participación:\n" + "\n".join(
            f"- {s.speaker}: {s.duration_formatted} ({s.talk_percentage:.0f}%), {s.turn_count} intervenciones"
            for s in report.speaker_stats))
    if report.topics:
        parts.append("Temas:\n" + "\n".join(f"- {t.title}: {t.summary}" for t in report.topics))
    if report.objectives:
        parts.append("Objetivos:\n" + "\n".join(f"- {o}" for o in report.objectives))
    if report.callouts:
        parts.append("Alertas:\n" + "\n".join(f"- [{c.timestamp}] {c.title}: {c.description}" for c in report.callouts))
    if report.calendar_tasks:
        parts.append("Tareas:\n" + "\n".join(f"- {t.title} · {t.assignee} · {t.due_date}" for t in report.calendar_tasks))
    structured = report.model_dump(include={
        "executive_summary", "dominant_speaker", "dominant_speaker_pct", "speaker_stats", "topics", "objectives",
        "callouts", "calendar_tasks",
    })
    structured["meeting_id"] = result.job_id
    return "\n\n".join(p for p in parts if p), structured


def tool_get_meeting_minutes(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    from app.models.schemas import MinutesGenerationRequest
    from app.services.apex_summa import generate_meeting_minutes

    _require_pro(user)
    rec = _record_for(user, str(args.get("meeting_id", "")))
    result = job_manager.get_job_result(rec["job_id"])
    if not result:
        raise ToolError("La transcripción ya no está disponible (pudo vencer su periodo de almacenamiento).")
    template = str(args.get("template") or "ejecutiva")
    if template not in ("ejecutiva", "seguimiento", "comite", "consejo", "asamblea"):
        raise ToolError("template debe ser ejecutiva, seguimiento, comite, consejo o asamblea.")
    report = job_manager.get_or_build_summa(result)
    notes = _notes_of(result)
    custom = "\n".join(
        f"- **[{n.get('timestamp_formatted', '')}] [{str(n.get('tag', 'nota')).upper()}]**: {n.get('text', '')}"
        for n in notes) or None
    doc = generate_meeting_minutes(result=result, report=report, req=MinutesGenerationRequest(
        template_type=template, language=result.language or "es", meeting_title=_title(rec), custom_notes=custom))
    return doc.markdown_content, {"meeting_id": result.job_id, "template": doc.template_type,
                                  "template_title": doc.template_title, "notes_included": len(notes)}


def tool_get_action_items(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    _require_pro(user)
    if args.get("meeting_id"):
        ids = [_resolve_id(user, str(args["meeting_id"]))]
    else:
        n = max(1, min(int(args.get("limit_meetings") or 5), 20))
        ids = [r["job_id"] for r in _records(user["user_id"])[:n]]
    assignee = _norm(args.get("assignee")) if args.get("assignee") else None
    tasks: List[Dict[str, Any]] = []
    for mid in ids:
        try:
            result = _result_for(user, mid)
        except ToolError:
            if args.get("meeting_id"):
                raise
            continue
        for t in (result.summa_report.calendar_tasks if result.summa_report else []):
            if assignee and assignee not in _norm(t.assignee):
                continue
            tasks.append({"meeting_id": mid, "title": t.title, "assignee": t.assignee,
                          "due_date": t.due_date, "description": t.description})
    if not tasks:
        return "No encontré tareas en esas reuniones.", {"action_items": []}
    lines = [f"- {t['title']} · responsable: {t['assignee']} · fecha: {t['due_date']} (reunión {t['meeting_id']})" for t in tasks]
    return f"{len(tasks)} tareas:\n" + "\n".join(lines), {"action_items": tasks}


# ---------------------------------------------------------------------------
# Agenda y llamadas
# ---------------------------------------------------------------------------

def tool_list_upcoming_meetings(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    from app.services import calendar_invites, recall_service

    limit = max(1, min(int(args.get("limit") or 20), 50))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    events = calendar_invites.upcoming_events(user["user_id"], limit=limit)
    bots = {b["bot_id"]: b for b in recall_service.list_bots(user["user_id"])}
    items = []
    for e in events:
        bot = bots.get(e.get("bot_id") or "")
        items.append({"title": e.get("title"), "start": _fmt_local(e.get("start")), "end": _fmt_local(e.get("end")),
                      "meeting_url": e.get("meeting_url"), "bot": bot.get("status") if bot else None})
    seen = {e.get("bot_id") for e in events}
    for b in bots.values():
        if b["bot_id"] not in seen and b.get("status") == "scheduled" and (b.get("join_at") or "") >= now:
            items.append({"title": b.get("title"), "start": _fmt_local(b.get("join_at")), "end": "",
                          "meeting_url": b.get("meeting_url"), "bot": "scheduled"})
    items.sort(key=lambda i: i["start"] or "")
    items = items[:limit]
    if not items:
        return ("No tienes reuniones próximas. Invita a " + (settings.INVITES_ADDRESS or "la dirección de agenda")
                + " a tus reuniones para que aparezcan aquí."), {"upcoming": []}
    lines = [f"- {i['start']} · {i['title']}" + (" · bot programado" if i["bot"] else " · sin bot")
             + (f" · {i['meeting_url']}" if i["meeting_url"] else "") for i in items]
    return f"{len(items)} reuniones próximas:\n" + "\n".join(lines), {"upcoming": items}


CALL_STATUS = {
    "initiating": "iniciando", "calling_you": "llamando a tu celular", "connecting": "marcando al contacto",
    "in_call": "en curso", "awaiting_recording": "esperando la grabación", "processing": "procesando",
    "done": "lista", "failed": "falló", "ended": "terminó sin grabación", "no_answer": "no contestaste",
    "busy": "ocupado", "cancelled": "cancelada", "contact_no_answer": "el contacto no contestó",
    "contact_busy": "el contacto estaba ocupado",
}


def tool_list_phone_calls(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    from app.services import twilio_service

    limit = max(1, min(int(args.get("limit") or 20), 50))
    calls = twilio_service.list_calls(user["user_id"], limit=limit)
    if not calls:
        return "No has hecho llamadas grabadas desde Apex Vox.", {"calls": []}
    items = [{
        "call_id": c["call_id"], "title": c.get("title"), "contact_name": c.get("contact_name") or None,
        "contact_number": c.get("to"), "date": _fmt_local(c.get("created_at")), "status": c.get("status"),
        "status_label": CALL_STATUS.get(c.get("status") or "", c.get("status")),
        "duration": _hms(c["duration_sec"]) if c.get("duration_sec") else None,
        "notes_count": len(c.get("notes") or []), "meeting_id": c.get("job_id"),
    } for c in calls]
    lines = [f"- {i['date']} · {i['contact_name'] or i['contact_number']} · {i['status_label']}"
             + (f" · {i['duration']}" if i["duration"] else "") + f" · {i['notes_count']} apuntes"
             + (f" · meeting_id: {i['meeting_id']}" if i["meeting_id"] else "") for i in items]
    return f"{len(items)} llamadas:\n" + "\n".join(lines), {"calls": items}


HANDLERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Tuple[str, Any]]] = {
    "find_meeting": tool_find_meeting,
    "list_meetings": tool_list_meetings,
    "get_meeting_details": tool_get_meeting_details,
    "get_meeting_notes": tool_get_meeting_notes,
    "search_meetings": tool_search_meetings,
    "get_meeting_transcript": tool_get_meeting_transcript,
    "get_meeting_summary": tool_get_meeting_summary,
    "get_meeting_minutes": tool_get_meeting_minutes,
    "get_action_items": tool_get_action_items,
    "list_upcoming_meetings": tool_list_upcoming_meetings,
    "list_phone_calls": tool_list_phone_calls,
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0
# ---------------------------------------------------------------------------

def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_message(message: Any, user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Procesa un mensaje JSON-RPC. Devuelve None para notificaciones."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
    method, req_id, params = message["method"], message.get("id"), message.get("params") or {}
    if "id" not in message:  # notificación (p. ej. notifications/initialized)
        return None

    if method == "initialize":
        requested = str(params.get("protocolVersion") or "")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if not handler:
            return _error(req_id, -32602, f"Herramienta desconocida: {name}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(req_id, -32602, "arguments debe ser un objeto")
        try:
            text, structured = handler(user, args)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
            if structured is not None:
                result["structuredContent"] = structured if isinstance(structured, dict) else {"data": structured}
        except ToolError as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except (TypeError, ValueError) as exc:
            logger.warning("MCP tool %s rejected its arguments: %s", name, type(exc).__name__)
            result = {"content": [{"type": "text", "text": "Argumentos inválidos para esta herramienta."}], "isError": True}
        return {"jsonrpc": "2.0", "id": req_id, "result": json.loads(json.dumps(result, default=str))}
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method == "resources/list" else "prompts"
        return {"jsonrpc": "2.0", "id": req_id, "result": {key: []}}
    return _error(req_id, -32601, f"Método no soportado: {method}")
