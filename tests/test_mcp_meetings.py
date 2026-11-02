"""Conector MCP: identificar reuniones por descripción, apuntes, detalles, filtros y llamadas."""

import datetime as dt
import uuid

from starlette.testclient import TestClient

from app.main import app
from app.models.schemas import ApexSummaReport, DiarizedSegment, TopicItem, TranscriptionResult
from app.services import mcp_server
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service
from tests.test_mcp_oauth import _connect, _rpc, _user


def _seg(i, start, speaker, text):
    return DiarizedSegment(id=i, start=start, end=start + 4, speaker=speaker, text=text,
                           start_formatted=mcp_server._hms(start), end_formatted=mcp_server._hms(start + 4),
                           source_file="a.mp3", file_order_index=0)


def _store(user_id, title, created, segments, notes=(), topics=(), **extra) -> str:
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    result = TranscriptionResult(
        job_id=job_id, user_id=user_id, total_duration_formatted="00:05:00", segments=list(segments),
        full_text="\n".join(s.text for s in segments), live_notes=list(notes), language="es",
        summa_report=ApexSummaReport(job_id=job_id, generated_at=created.isoformat(), executive_summary="Resumen.",
                                     topics=[TopicItem(title=t, summary=t) for t in topics]),
    )
    with job_manager._lock:
        job_manager._results[job_id] = result
    supabase_service.save_transcription_record({
        "job_id": job_id, "user_id": user_id, "title": title, "total_duration_formatted": "00:05:00",
        "created_at": created.isoformat(), "expires_at": None,
        "speakers": sorted({s.speaker for s in segments}), **extra,
    })
    return job_id


def _call(client, at, name, args):
    return _rpc(client, at, "tools/call", {"name": name, "arguments": args}).json()["result"]


def _at_local(days_ago: int, hour: int = 10) -> dt.datetime:
    today = mcp_server._today()
    d = today - dt.timedelta(days=days_ago)
    return dt.datetime(d.year, d.month, d.day, hour, tzinfo=mcp_server._tz()).astimezone(dt.timezone.utc)


def test_parse_when_spanish_and_english() -> None:
    monday = dt.date(2026, 11, 2)
    assert mcp_server.parse_when("la de ayer", monday)[0] == (dt.date(2026, 11, 1),) * 2
    assert mcp_server.parse_when("anteayer", monday)[0] == (dt.date(2026, 10, 31),) * 2
    assert mcp_server.parse_when("el viernes", monday)[0] == (dt.date(2026, 10, 30),) * 2
    assert mcp_server.parse_when("el lunes pasado", monday)[0] == (dt.date(2026, 10, 26),) * 2
    assert mcp_server.parse_when("30 de octubre", monday)[0] == (dt.date(2026, 10, 30),) * 2
    assert mcp_server.parse_when("october 30, 2025", monday)[0] == (dt.date(2025, 10, 30),) * 2
    assert mcp_server.parse_when("15/10", monday)[0] == (dt.date(2026, 10, 15),) * 2
    assert mcp_server.parse_when("2026-09-01", monday)[0] == (dt.date(2026, 9, 1),) * 2
    assert mcp_server.parse_when("la semana pasada", monday)[0] == (dt.date(2026, 10, 26), dt.date(2026, 11, 1))
    assert mcp_server.parse_when("últimos 7 días", monday)[0] == (dt.date(2026, 10, 26), monday)
    assert mcp_server.parse_when("last month", monday)[0] == (dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert mcp_server.parse_when("sin fecha aquí", monday)[0] is None


def test_identify_review_and_filter_meetings() -> None:
    client = TestClient(app)
    owner = _user(client, pro=True)
    uid = owner["user_id"]
    call_job = _store(
        uid, "Llamada con Carlos", _at_local(1),
        [_seg(0, 0, "Ana", "Hola Carlos, ¿recibiste la cotización?"), _seg(1, 5, "Carlos", "Sí, la reviso hoy.")],
        notes=[{"note_id": "n1", "timestamp_sec": 6.0, "timestamp_formatted": "00:00:06", "tag": "tarea",
                "author": "Ana", "text": "Llamar de nuevo el jueves"}],
        source="phone_call", contact_name="Carlos", contact_number="+573105556677", caller_id="+15005550006",
    )
    box_job = _store(
        uid, "Comité semanal", _at_local(5),
        [_seg(0, 0, "Luis", "Revisemos el presupuesto de marketing."), _seg(1, 5, "Marta", "Bajamos 10%.")],
        notes=[{"note_id": "n2", "timestamp_sec": 5.0, "timestamp_formatted": "00:00:05", "tag": "acuerdo",
                "author": "Ana", "text": "Presupuesto aprobado con recorte"}],
        topics=["Presupuesto de marketing"], source="box", platform="in_person",
    )
    _store(uid, "audio.m4a", _at_local(20), [_seg(0, 0, "Hablante 1", "Nota suelta.")])
    at = _connect(client, owner)["access_token"]

    found = _call(client, at, "find_meeting", {"description": "la llamada con Carlos de ayer"})
    assert found["isError"] is False
    first = found["structuredContent"]["candidates"][0]
    assert first["meeting_id"] == call_job and "fecha" in first["matched"]

    by_topic = _call(client, at, "find_meeting", {"description": "la reunión donde hablamos del presupuesto"})
    assert by_topic["structuredContent"]["candidates"][0]["meeting_id"] == box_job

    by_number = _call(client, at, "find_meeting", {"description": "llamada al número terminado en 6677"})
    assert by_number["structuredContent"]["candidates"][0]["meeting_id"] == call_job

    calls = _call(client, at, "list_meetings", {"source": "phone_call"})["structuredContent"]["meetings"]
    assert [m["meeting_id"] for m in calls] == [call_job]
    yesterday = _call(client, at, "list_meetings", {"when": "ayer"})["structuredContent"]["meetings"]
    assert [m["meeting_id"] for m in yesterday] == [call_job]
    marta = _call(client, at, "list_meetings", {"speaker": "marta"})["structuredContent"]["meetings"]
    assert [m["meeting_id"] for m in marta] == [box_job]
    assert _call(client, at, "list_meetings", {"when": "cuando sea"})["isError"] is True

    details = _call(client, at, "get_meeting_details", {"meeting_id": "latest"})
    text = details["content"][0]["text"]
    assert details["structuredContent"]["meeting_id"] == call_job
    assert "Carlos" in text and "+15005550006" in text and "Apuntes en vivo: 1" in text
    assert {p["speaker"] for p in details["structuredContent"]["participants"]} == {"Ana", "Carlos"}

    notes = _call(client, at, "get_meeting_notes", {"meeting_id": call_job})
    assert "TAREA (Ana): Llamar de nuevo el jueves" in notes["content"][0]["text"]
    assert notes["structuredContent"]["notes"][0]["context"][0]["speaker"] in ("Ana", "Carlos")
    assert _call(client, at, "get_meeting_notes", {"meeting_id": call_job, "tag": "alerta"})["structuredContent"]["notes"] == []

    # Sin tildes, con varias palabras y también en los apuntes
    hits = _call(client, at, "search_meetings", {"query": "cotizacion recibiste"})["structuredContent"]["results"]
    assert hits and hits[0]["meeting_id"] == call_job and hits[0]["after"] == "Sí, la reviso hoy."
    note_hits = _call(client, at, "search_meetings", {"query": "recorte"})["structuredContent"]["results"]
    assert note_hits and note_hits[0]["kind"].startswith("apunte")
    only_marta = _call(client, at, "search_meetings", {"query": "presupuesto", "speaker": "Marta"})
    assert only_marta["structuredContent"]["results"] == []
    only_luis = _call(client, at, "search_meetings", {"query": "presupuesto", "speaker": "Luis"})
    assert [h["speaker"] for h in only_luis["structuredContent"]["results"]] == ["Luis"]

    part = _call(client, at, "get_meeting_transcript", {"meeting_id": box_job, "speaker": "Marta"})
    assert "Bajamos 10%" in part["content"][0]["text"] and "Revisemos" not in part["content"][0]["text"]
    window = _call(client, at, "get_meeting_transcript", {"meeting_id": box_job, "start": "00:00:05"})
    assert "Revisemos" not in window["content"][0]["text"]

    minutes = _call(client, at, "get_meeting_minutes", {"meeting_id": box_job, "template": "ejecutiva"})
    assert minutes["isError"] is False and "Presupuesto aprobado con recorte" in minutes["content"][0]["text"]


def test_free_plan_reads_notes_but_not_minutes() -> None:
    client = TestClient(app)
    free = _user(client)
    job = _store(free["user_id"], "Gratis", _at_local(0), [_seg(0, 0, "Ana", "Hola")],
                 notes=[{"timestamp_sec": 0, "timestamp_formatted": "00:00:00", "tag": "idea", "text": "Idea libre"}])
    at = _connect(client, free)["access_token"]
    assert "Idea libre" in _call(client, at, "get_meeting_notes", {"meeting_id": job})["content"][0]["text"]
    minutes = _call(client, at, "get_meeting_minutes", {"meeting_id": job})
    assert minutes["isError"] is True and "Apex Pro" in minutes["content"][0]["text"]
    assert _call(client, at, "list_phone_calls", {})["structuredContent"]["calls"] == []
    assert _call(client, at, "list_upcoming_meetings", {})["structuredContent"]["upcoming"] == []


def test_batches_are_capped_and_each_message_counts() -> None:
    client = TestClient(app)
    owner = _user(client)
    at = _connect(client, owner)["access_token"]
    headers = {"Authorization": f"Bearer {at}"}
    batch = [{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(11)]
    big = client.post("/mcp", json=batch, headers=headers)
    assert big.status_code == 400
    ok = client.post("/mcp", json=batch[:10], headers=headers)
    assert ok.status_code == 200 and len(ok.json()) == 10
    statuses = [client.post("/mcp", json=batch[:10], headers=headers).status_code for _ in range(12)]
    assert 429 in statuses  # 120 mensajes por minuto, aunque vengan en lotes


def test_record_extra_cannot_change_owner() -> None:
    from app.services.apex_box import _RESERVED_RECORD_KEYS

    assert {"user_id", "job_id", "plan", "expires_at"} <= _RESERVED_RECORD_KEYS


def test_public_base_url_rejects_injected_host(monkeypatch) -> None:
    from app.api.deps import public_base_url
    from app.config import settings

    class Req:
        def __init__(self, base):
            self.base_url = base

    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    assert public_base_url(Req("https://apex.example:8443/")) == "https://apex.example:8443"
    assert public_base_url(Req('https://x"><script>alert(1)</script>/')) == "https://apex-vox.ialabs.app"
