"""Apex Summa reads the whole meeting, once, and shows each viewer what their plan includes."""

import datetime as dt
import json
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.schemas import DiarizedSegment, TranscriptionResult
from app.services import apex_summa
from app.services.apex_summa import _pick_blocks, _split_into_blocks, generate_apex_summa_report
from app.services.job_manager import job_manager
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

client = TestClient(app)
FINAL = {
    "executive_summary": "Resumen de toda la reunión.",
    "topics": [{"title": "Presupuesto", "summary": "Hablante 1 lo presentó.", "relevance_pct": 90, "keywords": ["x"]}],
    "objectives": ["Cerrar el presupuesto"],
    "callouts": [{"title": "Riesgo", "description": "Hablante 1 avisó.", "speaker": "Hablante 1", "timestamp": "00:01:00", "severity": "alta"}],
    "calendar_tasks": [{"task_id": "t1", "title": "Enviar acta", "description": "", "assignee": "Hablante 1", "due_date": "2099-01-01", "due_time": "09:00", "priority": "alta", "category": "x"}],
}


class FakeLLM:
    """Answers each prompt with the next reply; records prompts and models."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: List[str] = []
        self.models: List[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, model: str, messages: list, **kwargs: Any) -> SimpleNamespace:
        self.models.append(model)
        self.prompts.append(messages[-1]["content"])
        reply = self.replies.pop(0) if self.replies else FINAL
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch):
    def install(*replies: Any) -> FakeLLM:
        fake = FakeLLM(*replies)
        monkeypatch.setattr(apex_summa, "_llm_client", lambda key: fake)
        monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_real_looking_key")
        return fake

    return install


def _result(text: str = "[00:00:01 - 00:00:02] Hablante 1: Hola.", plan: str = "pro", user_id: Optional[str] = None, **extra) -> TranscriptionResult:
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    segment = DiarizedSegment(id=0, start=1, end=2, speaker="Hablante 1", text="Hola.", start_formatted="00:00:01",
                              end_formatted="00:00:02", source_file="a", file_order_index=0)
    return TranscriptionResult(
        job_id=job_id, session_id="s", user_id=user_id, plan=plan, status="completed", detected_speakers_count=1,
        total_duration_sec=60, total_duration_formatted="00:01:00", model_used="m", diarization_engine_used="e",
        engine_brand="b", language="es", file_order=[], segments=[segment], full_text=text, **extra,
    )


def _long_text(chars: int) -> str:
    lines = []
    i = 0
    while sum(len(line) + 1 for line in lines) < chars:
        lines.append(f"[00:{i // 60:02d}:{i % 60:02d}] Hablante 1: Frase número {i} de la reunión larga.")
        i += 1
    return "\n".join(lines)


def _account(pro: bool = True) -> tuple[str, dict]:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    if pro:
        db = supabase_service._load_db()
        db["users"][profile.user_id].update(plan="pro", pro_until="2099-01-01T00:00:00+00:00")
        supabase_service._save_db(db)
    return profile.user_id, {"Authorization": f"Bearer {profile.access_token}"}


def _stored_job(uid: str, plan: str = "pro", **extra) -> TranscriptionResult:
    result = _result(plan=plan, user_id=uid, **extra)
    job_manager._results[result.job_id] = result
    job_manager._job_owners[result.job_id] = uid
    return result


# Reading the whole meeting -------------------------------------------------


def test_short_transcript_uses_one_call_with_all_of_it(llm) -> None:
    fake = llm(FINAL)
    report = generate_apex_summa_report(_result())
    assert len(fake.prompts) == 1 and "Hablante 1: Hola." in fake.prompts[0]
    assert report.executive_summary == FINAL["executive_summary"]
    assert report.analysis_source == "llm"


def test_long_transcript_reaches_the_llm_complete(llm) -> None:
    """Before, everything after the first 10,000 characters was never read."""
    text = _long_text(60000)
    fake = llm()
    report = generate_apex_summa_report(_result(text))
    sent = "\n".join(fake.prompts)
    for line in text.split("\n"):
        assert line in sent
    assert len(fake.prompts) >= 3  # the parts and the final combination
    assert "Combine" in fake.prompts[-1]
    assert report.analysis_source == "llm"


def test_very_long_meeting_samples_evenly_and_says_so(llm, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUMMA_MAX_MAP_BLOCKS", 2)
    text = _long_text(100000) + "\n--- NOTAS TOMADAS EN VIVO (APEX BOX) ---\nComprar equipos"
    fake = llm()
    report = generate_apex_summa_report(_result(text))
    assert len(fake.prompts) == 3
    assert "Comprar equipos" in fake.prompts[1]  # the end, where the notes are, is always included
    assert report.analysis_source == "llm_partial"


def test_block_split_keeps_lines_whole_and_handles_giant_ones() -> None:
    text = "linea uno\nlinea dos\n" + "x" * 50 + "\nfinal"
    blocks = _split_into_blocks(text, size=20)
    assert all(len(b) <= 20 for b in blocks)
    assert "".join(b.replace("\n", "") for b in blocks) == text.replace("\n", "")
    assert blocks[0] == "linea uno\nlinea dos"


def test_pick_blocks_is_even_and_includes_both_ends() -> None:
    blocks = [str(i) for i in range(10)]
    assert _pick_blocks(blocks, 20) == blocks
    picked = _pick_blocks(blocks, 4)
    assert picked[0] == "0" and picked[-1] == "9" and len(picked) == 4
    assert _pick_blocks(blocks, 1) == ["9"]


# Failures ------------------------------------------------------------------


def test_fallback_model_is_tried_once(llm) -> None:
    fake = llm(RuntimeError("model gone"), FINAL)
    report = generate_apex_summa_report(_result())
    assert fake.models == [settings.DEFAULT_LLM_MODEL, settings.FALLBACK_LLM_MODEL]
    assert report.analysis_source == "llm"


def test_llm_failure_is_logged_and_the_report_says_heuristic(llm, caplog: pytest.LogCaptureFixture) -> None:
    llm(RuntimeError("down"), RuntimeError("down"))
    with caplog.at_level("WARNING", logger="app.services.apex_summa"):
        report = generate_apex_summa_report(_result())
    assert report.analysis_source == "heuristic"
    assert report.executive_summary
    assert "RuntimeError" in caplog.text and "down" not in caplog.text


def test_budget_stops_further_calls_and_uses_what_it_has(llm, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUMMA_LLM_BUDGET_SECONDS", -1)
    fake = llm()
    report = generate_apex_summa_report(_result(_long_text(60000)))
    assert fake.prompts == []
    assert report.analysis_source == "heuristic"


def test_failed_part_makes_the_report_partial(llm) -> None:
    llm(RuntimeError("x"), RuntimeError("x"))
    report = generate_apex_summa_report(_result(_long_text(60000)))
    assert report.analysis_source == "llm_partial"


def test_locked_report_makes_no_llm_call(llm) -> None:
    fake = llm()
    report = generate_apex_summa_report(_result(), is_locked=True)
    assert fake.prompts == []
    assert report.is_locked and report.analysis_source == "locked"
    assert report.executive_summary == "" and report.speaker_stats


# Generated once ------------------------------------------------------------


def test_screen_minutes_and_calendar_share_one_report(llm) -> None:
    fake = llm()
    uid, auth = _account()
    job = _stored_job(uid).job_id
    assert client.get(f"/api/jobs/{job}/summa", headers=auth).status_code == 200
    calls = len(fake.prompts)
    assert calls == 1
    assert client.post(f"/api/jobs/{job}/minutes", json={"template_type": "ejecutiva"}, headers=auth).status_code == 200
    assert client.get(f"/api/jobs/{job}/calendar.ics", headers=auth).status_code == 200
    assert client.get(f"/api/jobs/{job}/summa", headers=auth).status_code == 200
    assert len(fake.prompts) == calls


def test_each_language_is_generated_once_and_saved(llm) -> None:
    fake = llm()
    uid, auth = _account()
    job = _stored_job(uid, plan="pro").job_id
    assert client.get(f"/api/jobs/{job}/summa", params={"lang": "es"}, headers=auth).json()["language"] == "es"
    for _ in range(2):
        assert client.get(f"/api/jobs/{job}/summa", params={"lang": "en"}, headers=auth).json()["language"] == "en"
        assert client.get(f"/api/jobs/{job}/summa", params={"lang": "es"}, headers=auth).json()["language"] == "es"
    assert len(fake.prompts) == 2
    saved = json.loads((settings.OUTPUT_DIR / f"{job}_result.json").read_text(encoding="utf-8"))
    assert saved["summa_report"]["language"] == "es" and "en" in saved["summa_translations"]


def test_simultaneous_requests_generate_one_report(llm, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = llm()
    real_create = fake.create

    def slow(*args, **kwargs):
        time.sleep(0.1)
        return real_create(*args, **kwargs)

    fake.chat.completions.create = slow
    result = _result(plan="pro", user_id="u")
    threads = [threading.Thread(target=job_manager.get_or_build_summa, args=(result,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(fake.prompts) == 1


def test_saving_a_report_does_not_extend_retention(llm) -> None:
    llm()
    uid, _ = _account()
    result = _stored_job(uid, plan="free", expires_at="2099-02-02T00:00:00+00:00")
    job_manager.get_or_build_summa(result)
    meta = mega_s4_storage.get_object_metadata(f"users/{uid}/jobs/{result.job_id}/result.json")
    assert meta["expires_at"] == "2099-02-02T00:00:00+00:00"


# Notes ---------------------------------------------------------------------


NOTES: List[Dict[str, Any]] = [
    {"tag": "tarea", "text": "Comprar equipos", "timestamp_formatted": "00:05:00"},
    {"tag": "alerta", "text": "Riesgo legal", "timestamp_formatted": "00:06:00", "speaker": "Ana"},
    {"tag": "acuerdo", "text": "Se aprueba", "timestamp_formatted": "00:07:00"},
]


def test_live_notes_are_in_every_generated_report(llm) -> None:
    llm()
    result = _result(live_notes=NOTES)
    for lang in ("es", "en"):
        report = job_manager.get_or_build_summa(result, lang)
        assert report.calendar_tasks[0].title == "Comprar equipos"
        assert report.callouts[0].description == "Riesgo legal" and report.callouts[0].speaker == "Ana"
        assert any("Se aprueba" in o for o in report.objectives)
    assert "Live alert" in result.summa_translations["en"].callouts[0].title
    assert "en vivo" in result.summa_report.callouts[0].title


def test_renaming_speakers_keeps_notes_and_makes_no_llm_call(llm) -> None:
    fake = llm()
    uid, auth = _account()
    result = _stored_job(uid, live_notes=NOTES)
    job_manager.get_or_build_summa(result)
    calls = len(fake.prompts)
    res = client.patch(f"/api/jobs/{result.job_id}/speakers", json={"speaker_map": {"Hablante 1": "Marta"}}, headers=auth)
    assert res.status_code == 200
    assert len(fake.prompts) == calls
    report = res.json()["summa_report"]
    assert report["dominant_speaker"] == "Marta"
    assert report["speaker_stats"][0]["speaker"] == "Marta"
    assert report["calendar_tasks"][0]["title"] == "Comprar equipos"
    assert "Marta" in report["topics"][0]["summary"]
    assert any(c["speaker"] == "Marta" for c in report["callouts"])
    assert any(t["assignee"] == "Marta" for t in report["calendar_tasks"])
    saved = json.loads((settings.OUTPUT_DIR / f"{result.job_id}_result.json").read_text(encoding="utf-8"))
    assert saved["segments"][0]["speaker"] == "Marta"


# What each viewer sees -----------------------------------------------------


def test_lapsed_account_sees_the_preview_of_a_saved_report(llm) -> None:
    llm()
    uid, auth = _account(pro=True)
    result = _stored_job(uid)
    assert client.get(f"/api/jobs/{result.job_id}/summa", headers=auth).json()["executive_summary"]

    db = supabase_service._load_db()
    # Lapsed yesterday: still within the grace period, so the result itself is available.
    yesterday = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    db["users"][uid].update(plan="free", pro_until=yesterday.isoformat())
    supabase_service._save_db(db)

    summa = client.get(f"/api/jobs/{result.job_id}/summa", headers=auth).json()
    full = client.get(f"/api/jobs/{result.job_id}/result", headers=auth).json()
    for report in (summa, full["summa_report"]):
        assert report["is_locked"] is True and report["executive_summary"] == "" and report["calendar_tasks"] == []
    assert full["summa_translations"] == {}
    # The saved report is not damaged: paying again brings it back with no new call.
    assert job_manager.get_job_result(result.job_id).summa_report.executive_summary


def test_upgrade_replaces_the_preview(llm) -> None:
    fake = llm()
    uid, auth = _account(pro=True)
    result = _stored_job(uid, plan="free")
    result.summa_report = generate_apex_summa_report(result, is_locked=True)
    assert fake.prompts == []
    report = client.get(f"/api/jobs/{result.job_id}/summa", headers=auth).json()
    assert report["is_locked"] is False and report["executive_summary"]
    assert len(fake.prompts) == 1
    assert job_manager.get_job_result(result.job_id).summa_report.is_locked is False


def test_free_viewer_summa_makes_no_llm_call_and_saves_nothing(llm) -> None:
    fake = llm()
    uid, auth = _account(pro=False)
    result = _stored_job(uid, plan="free")
    report = client.get(f"/api/jobs/{result.job_id}/summa", headers=auth).json()
    assert report["is_locked"] is True
    assert fake.prompts == []
    assert result.summa_report is None
