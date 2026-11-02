"""
Servidor MCP de Apex Vox (app/services/mcp_server.py)
----------------------------------------------------
Herramientas de solo lectura para que ChatGPT, Claude u otro cliente MCP respondan
preguntas sobre las reuniones del usuario autenticado. Cada herramienta solo ve las
transcripciones de esa cuenta.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import settings
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "apex-vox", "title": "Apex Vox", "version": "1.0.0"}
INSTRUCTIONS = (
    "Apex Vox guarda las reuniones transcritas del usuario (con oradores y marcas de tiempo) "
    "y, en Apex Pro, su resumen ejecutivo, temas, objetivos, alertas y tareas. "
    "Usa list_meetings o search_meetings para encontrar la reunión y luego get_meeting_transcript "
    "o get_meeting_summary. Cita la marca de tiempo [HH:MM:SS] cuando uses frases de la transcripción."
)
MAX_TRANSCRIPT_CHARS = 60_000

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_meetings",
        "title": "Listar reuniones",
        "description": "Lista las reuniones transcritas del usuario, de la más reciente a la más antigua.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}},
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "search_meetings",
        "title": "Buscar en reuniones",
        "description": "Busca palabras o frases en todas las transcripciones del usuario y devuelve fragmentos con su reunión y marca de tiempo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2, "description": "Texto a buscar"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_meeting_transcript",
        "title": "Transcripción de una reunión",
        "description": "Devuelve la transcripción completa de una reunión con oradores y marcas de tiempo.",
        "inputSchema": {
            "type": "object",
            "properties": {"meeting_id": {"type": "string", "description": "id devuelto por list_meetings"}},
            "required": ["meeting_id"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_meeting_summary",
        "title": "Resumen de una reunión",
        "description": "Resumen ejecutivo de Apex Summa: quién habló más, temas, objetivos, alertas y tareas (Apex Pro).",
        "inputSchema": {
            "type": "object",
            "properties": {"meeting_id": {"type": "string"}},
            "required": ["meeting_id"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_action_items",
        "title": "Tareas y compromisos",
        "description": "Tareas con responsable y fecha extraídas de una reunión o de las últimas reuniones (Apex Pro).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "string", "description": "Opcional: solo esta reunión"},
                "limit_meetings": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
]


class ToolError(Exception):
    """Error que se muestra al modelo como resultado de la herramienta (isError)."""


# ---------------------------------------------------------------------------
# Datos del usuario
# ---------------------------------------------------------------------------

def _is_paid(user: Dict[str, Any]) -> bool:
    return str(user.get("plan", "free")).lower() in ("pro", "trial")


def _records(user_id: str) -> List[Dict[str, Any]]:
    recs = supabase_service.list_user_transcriptions(user_id)
    return sorted(recs, key=lambda r: str(r.get("created_at", "")), reverse=True)


def _title(rec: Dict[str, Any]) -> str:
    if rec.get("title"):
        return str(rec["title"])
    files = rec.get("file_order") or []
    return str(files[0]) if files else "Reunión sin título"


def _result_for(user: Dict[str, Any], meeting_id: str):
    meeting_id = (meeting_id or "").strip()
    if not re.fullmatch(r"[\w-]{1,64}", meeting_id):
        raise ToolError("meeting_id inválido.")
    if not any(r.get("job_id") == meeting_id for r in _records(user["user_id"])):
        raise ToolError("No encontré esa reunión en tu cuenta. Usa list_meetings para ver los ids.")
    result = job_manager.get_job_result(meeting_id)
    if not result:
        raise ToolError("La transcripción ya no está disponible (pudo vencer su periodo de almacenamiento).")
    return result


def _meeting_url(meeting_id: str) -> str:
    return f"{settings.PUBLIC_BASE_URL or 'https://apex-vox.ialabs.app'}/?job={meeting_id}"


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

def tool_list_meetings(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    limit = max(1, min(int(args.get("limit") or 20), 50))
    items = [
        {
            "meeting_id": r["job_id"],
            "title": _title(r),
            "date": str(r.get("created_at", ""))[:16].replace("T", " "),
            "duration": r.get("total_duration_formatted", ""),
            "speakers": r.get("detected_speakers_count"),
            "dominant_speaker": r.get("dominant_speaker", ""),
            "url": _meeting_url(r["job_id"]),
        }
        for r in _records(user["user_id"])[:limit]
    ]
    if not items:
        return "No tienes reuniones transcritas todavía.", {"meetings": []}
    lines = [f"- {m['title']} · {m['date']} · {m['duration']} · id: {m['meeting_id']}" for m in items]
    return f"{len(items)} reuniones:\n" + "\n".join(lines), {"meetings": items}


def tool_search_meetings(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    query = str(args.get("query") or "").strip()
    if len(query) < 2:
        raise ToolError("La búsqueda necesita al menos 2 caracteres.")
    limit = max(1, min(int(args.get("limit") or 15), 50))
    needle = query.lower()
    hits: List[Dict[str, Any]] = []
    for rec in _records(user["user_id"]):
        result = job_manager.get_job_result(rec["job_id"])
        if not result:
            continue
        for seg in result.segments:
            if needle in seg.text.lower():
                hits.append({
                    "meeting_id": rec["job_id"], "title": _title(rec),
                    "timestamp": seg.start_formatted, "speaker": seg.speaker, "text": seg.text,
                })
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break
    if not hits:
        return f"No encontré «{query}» en tus reuniones.", {"results": []}
    lines = [f"- [{h['timestamp']}] {h['speaker']} ({h['title']}, id {h['meeting_id']}): {h['text']}" for h in hits]
    return f"{len(hits)} coincidencias para «{query}»:\n" + "\n".join(lines), {"results": hits}


def tool_get_meeting_transcript(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    result = _result_for(user, str(args.get("meeting_id", "")))
    lines = [f"[{s.start_formatted}] {s.speaker}: {s.text}" for s in result.segments]
    text = "\n".join(lines) or result.full_text
    truncated = len(text) > MAX_TRANSCRIPT_CHARS
    if truncated:
        text = text[:MAX_TRANSCRIPT_CHARS] + "\n[… transcripción recortada por longitud …]"
    header = (f"Reunión {result.job_id} · duración {result.total_duration_formatted} · "
              f"{result.detected_speakers_count} oradores · {_meeting_url(result.job_id)}\n\n")
    return header + text, {
        "meeting_id": result.job_id, "duration": result.total_duration_formatted,
        "speakers": sorted({s.speaker for s in result.segments}), "truncated": truncated,
        "url": _meeting_url(result.job_id),
    }


def _require_pro(user: Dict[str, Any]) -> None:
    if not _is_paid(user):
        raise ToolError(
            "El resumen de Apex Summa y las tareas están incluidos en Apex Pro. "
            "Puedes leer la transcripción con get_meeting_transcript, o activar Apex Pro en "
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
    if report.topics:
        parts.append("Temas:\n" + "\n".join(f"- {t.title}: {t.summary}" for t in report.topics))
    if report.objectives:
        parts.append("Objetivos:\n" + "\n".join(f"- {o}" for o in report.objectives))
    if report.callouts:
        parts.append("Alertas:\n" + "\n".join(f"- [{c.timestamp}] {c.title}: {c.description}" for c in report.callouts))
    if report.calendar_tasks:
        parts.append("Tareas:\n" + "\n".join(f"- {t.title} · {t.assignee} · {t.due_date}" for t in report.calendar_tasks))
    structured = report.model_dump(include={
        "executive_summary", "dominant_speaker", "dominant_speaker_pct", "topics", "objectives", "callouts", "calendar_tasks",
    })
    structured["meeting_id"] = result.job_id
    return "\n\n".join(p for p in parts if p), structured


def tool_get_action_items(user: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, Any]:
    _require_pro(user)
    if args.get("meeting_id"):
        ids = [str(args["meeting_id"])]
    else:
        n = max(1, min(int(args.get("limit_meetings") or 5), 20))
        ids = [r["job_id"] for r in _records(user["user_id"])[:n]]
    tasks: List[Dict[str, Any]] = []
    for mid in ids:
        try:
            result = _result_for(user, mid)
        except ToolError:
            if args.get("meeting_id"):
                raise
            continue
        for t in (result.summa_report.calendar_tasks if result.summa_report else []):
            tasks.append({"meeting_id": mid, "title": t.title, "assignee": t.assignee,
                          "due_date": t.due_date, "description": t.description})
    if not tasks:
        return "No encontré tareas en esas reuniones.", {"action_items": []}
    lines = [f"- {t['title']} · responsable: {t['assignee']} · fecha: {t['due_date']} (reunión {t['meeting_id']})" for t in tasks]
    return f"{len(tasks)} tareas:\n" + "\n".join(lines), {"action_items": tasks}


HANDLERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Tuple[str, Any]]] = {
    "list_meetings": tool_list_meetings,
    "search_meetings": tool_search_meetings,
    "get_meeting_transcript": tool_get_meeting_transcript,
    "get_meeting_summary": tool_get_meeting_summary,
    "get_action_items": tool_get_action_items,
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
            result = {"content": [{"type": "text", "text": f"Argumentos inválidos: {exc}"}], "isError": True}
        return {"jsonrpc": "2.0", "id": req_id, "result": json.loads(json.dumps(result, default=str))}
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method == "resources/list" else "prompts"
        return {"jsonrpc": "2.0", "id": req_id, "result": {key: []}}
    return _error(req_id, -32601, f"Método no soportado: {method}")
