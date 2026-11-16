"""Read-only share links: only the owner manages them, the page shows what the owner's plan allows,
and the link goes away with the result or the account."""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.config import settings
from app.main import app
from app.models.schemas import ApexSummaReport, DiarizedSegment, SpeakerAnalyticsItem, TopicItem, TranscriptionResult
from app.services import retention, share_links
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service

PAST = "2020-01-01T00:00:00+00:00"
SUMMARY = "Acordamos cerrar el presupuesto el viernes."


def _client(pro: bool = False) -> TestClient:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123", full_name="Ana Pérez")
    if pro:
        db = supabase_service._load_db()
        db["users"][profile.user_id].update(plan="pro", pro_until="2099-01-01T00:00:00+00:00")
        supabase_service._save_db(db)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {profile.access_token}"})
    client.user_id = profile.user_id
    return client


def _report(job_id: str, locked: bool = False) -> ApexSummaReport:
    stats = [SpeakerAnalyticsItem(speaker="Ana", talk_percentage=70.0, word_count=20, turn_count=2),
             SpeakerAnalyticsItem(speaker="Luis", talk_percentage=30.0, word_count=8, turn_count=1)]
    return ApexSummaReport(
        job_id=job_id, generated_at="2026-11-15T10:00:00+00:00", is_locked=locked, speaker_stats=stats,
        dominant_speaker="Ana", dominant_speaker_pct=70.0, executive_summary="" if locked else SUMMARY,
        topics=[] if locked else [TopicItem(title="Presupuesto", summary="Se revisó.")],
        objectives=[] if locked else ["Cerrar el presupuesto"],
    )


def _job(owner: TestClient, plan: str = "free", expires_at: Optional[str] = None, locked: bool = False,
         audio: bool = True) -> str:
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    seg = DiarizedSegment(id=0, start=1.5, end=3, speaker="Ana", text="Hola <b>equipo</b>.", start_formatted="00:00:01",
                          end_formatted="00:00:03", source_file="reunion.mp3", file_order_index=0)
    result = TranscriptionResult(
        job_id=job_id, session_id="s", user_id=owner.user_id, plan=plan, segments=[seg], full_text="Hola equipo.",
        total_duration_formatted="00:00:03", engine_brand="Mc-Lewis", file_order=["reunion.mp3"],
        expires_at=expires_at, summa_report=_report(job_id, locked=locked),
    )
    (settings.OUTPUT_DIR / f"{job_id}_result.json").write_text(result.model_dump_json(), encoding="utf-8")
    if audio:
        (settings.OUTPUT_DIR / f"{job_id}_merged.mp3").write_bytes(b"ID3audio")
    job_manager._job_owners[job_id] = owner.user_id
    return job_id


def _share(owner: TestClient, job_id: str, include_audio: bool = False) -> str:
    res = owner.post(f"/api/jobs/{job_id}/share", json={"include_audio": include_audio})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["active"] and body["url"].startswith("http")
    return body["url"].split("/s/", 1)[1]


def _visit(token: str, lang: str = "es"):
    return TestClient(app).get(f"/s/{token}", params={"lang": lang})


# Managing the link ---------------------------------------------------------------------------------


def test_owner_creates_reads_and_revokes_the_link() -> None:
    owner = _client()
    job_id = _job(owner)
    assert owner.get(f"/api/jobs/{job_id}/share").json() == {
        "active": False, "url": None, "include_audio": False, "created_at": None,
    }

    token = _share(owner, job_id)
    assert job_id not in token
    again = owner.get(f"/api/jobs/{job_id}/share").json()
    assert again["active"] and again["url"].endswith(f"/s/{token}")

    # Changing the audio keeps the same link.
    assert _share(owner, job_id, include_audio=True) == token
    assert owner.get(f"/api/jobs/{job_id}/share").json()["include_audio"] is True

    assert _visit(token).status_code == 200
    revoked = owner.delete(f"/api/jobs/{job_id}/share")
    assert revoked.json()["active"] is False
    assert _visit(token).status_code == 404
    # A new link after revoking is a different one.
    assert _share(owner, job_id) != token


def test_only_the_owner_manages_the_link() -> None:
    owner, stranger = _client(), _client()
    job_id = _job(owner)
    token = _share(owner, job_id)
    for method in ("get", "post", "delete"):
        kwargs = {"json": {"include_audio": True}} if method == "post" else {}
        assert getattr(stranger, method)(f"/api/jobs/{job_id}/share", **kwargs).status_code == 404
        assert getattr(TestClient(app), method)(f"/api/jobs/{job_id}/share", **kwargs).status_code == 401
    assert _visit(token).status_code == 200  # la revocación ajena no tuvo efecto


def test_guest_results_cannot_be_shared() -> None:
    guest = TestClient(app)
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    job_manager._results[job_id] = TranscriptionResult(job_id=job_id, plan="guest", full_text="x")
    job_manager._job_owners[job_id] = supabase_service.guest_key("testclient")
    assert guest.post(f"/api/jobs/{job_id}/share", json={}).status_code == 401
    assert guest.get(f"/api/jobs/{job_id}/share").status_code == 401


def test_expired_or_missing_result_cannot_be_shared() -> None:
    owner = _client()
    expired = _job(owner, expires_at=PAST)
    assert owner.post(f"/api/jobs/{expired}/share", json={}).status_code == 410
    assert owner.post("/api/jobs/job_doesnotexist00/share", json={}).status_code == 404


def test_creating_links_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client()
    job_id = _job(owner)
    calls = []
    real = deps.throttle

    def limited(key: str, limit: int, window_seconds: int) -> None:
        calls.append((key, limit, window_seconds))
        real(key, 1, window_seconds)

    from app.api import routes_share

    monkeypatch.setattr(routes_share, "throttle", limited)
    assert owner.post(f"/api/jobs/{job_id}/share", json={}).status_code == 200
    assert owner.post(f"/api/jobs/{job_id}/share", json={}).status_code == 429
    assert calls[0][0] == f"share-create:{owner.user_id}"


# The public page -----------------------------------------------------------------------------------


def test_page_is_private_read_only_and_escaped() -> None:
    owner = _client()
    job_id = _job(owner)
    res = _visit(_share(owner, job_id))
    assert res.status_code == 200
    assert res.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in res.headers["x-robots-tag"]
    assert "no-store" in res.headers["cache-control"]
    assert '<meta name="robots" content="noindex' in res.text
    assert "Hola &lt;b&gt;equipo&lt;/b&gt;." in res.text and "<b>equipo</b>" not in res.text
    # Sin la configuración ni la cola del estudio, y sin botones que cambien nada.
    for absent in ("dropzone", "track-list", "rename-speakers-btn", "generate-minutes-btn", "app.js"):
        assert absent not in res.text
    assert "Compartido por Ana desde Apex Vox" in res.text
    assert "Disallow: /s/" in TestClient(app).get("/robots.txt").text


def test_page_language_follows_the_visitor() -> None:
    owner = _client()
    token = _share(owner, _job(owner))
    english = _visit(token, lang="en")
    assert '<html lang="en">' in english.text and "Transcript" in english.text


def test_audio_only_when_the_owner_includes_it() -> None:
    owner = _client()
    job_id = _job(owner)
    token = _share(owner, job_id)
    page = _visit(token).text
    assert "<audio" not in page and job_id not in page and "share.js" not in page

    _share(owner, job_id, include_audio=True)
    page = _visit(token).text
    assert "<audio" in page and "share.js" in page
    audio_src = page.split('id="share-audio" controls preload="metadata" src="', 1)[1].split('"', 1)[0]
    listen = TestClient(app).get(audio_src.replace("&amp;", "&"))
    assert listen.status_code == 200 and listen.content == b"ID3audio"


def test_free_owner_shares_the_preview_and_pro_owner_the_full_report() -> None:
    free = _client(pro=False)
    page = _visit(_share(free, _job(free, plan="free", locked=True))).text
    assert "Ana lideró la conversación" in page and "<svg" in page  # oradores y gráficas
    assert SUMMARY not in page and "7. Acta" not in page
    assert "incluidos en Apex Pro" in page

    pro = _client(pro=True)
    page = _visit(_share(pro, _job(pro, plan="pro"))).text
    assert SUMMARY in page and "7. Acta" in page and "Cerrar el presupuesto" in page
    assert "incluidos en Apex Pro" not in page


def test_lapsed_pro_shows_the_preview_even_for_a_full_report() -> None:
    owner = _client(pro=True)
    job_id = _job(owner, plan="pro")
    token = _share(owner, job_id)
    db = supabase_service._load_db()
    db["users"][owner.user_id].update(plan="free", pro_until=PAST)
    supabase_service._save_db(db)
    assert SUMMARY not in _visit(token).text


def test_expired_result_gives_a_clear_410() -> None:
    owner = _client()
    job_id = _job(owner)
    token = _share(owner, job_id)
    result = job_manager._load_result(job_id)
    result.expires_at = PAST
    res = _visit(token)
    assert res.status_code == 410 and "venció" in res.text
    assert "noindex" in res.headers["x-robots-tag"]


def test_unknown_or_forged_tokens_are_404() -> None:
    owner = _client()
    token = _share(owner, _job(owner))
    nonce, sig = token.split(".")
    for bad in ("nope", f"{nonce}.{'0' * len(sig)}", f"{'A' * len(nonce)}.{sig}", token + "x"):
        assert _visit(bad).status_code == 404


def test_state_alone_cannot_rebuild_a_link() -> None:
    owner = _client()
    token = _share(owner, _job(owner))
    stored = supabase_service._read_snapshot()["share_links"]
    nonce = token.split(".")[0]
    assert nonce in stored and token not in str(stored)


def test_page_views_are_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _client()
    token = _share(owner, _job(owner))
    monkeypatch.setattr(settings, "SHARE_VIEWS_PER_MINUTE", 2)
    deps._throttle_hits.clear()
    visitor = TestClient(app)
    assert [visitor.get(f"/s/{token}").status_code for _ in range(3)] == [200, 200, 429]
    assert "Demasiadas visitas" in visitor.get(f"/s/{token}", params={"lang": "es"}).text
    deps._throttle_hits.clear()


# Clean-up ------------------------------------------------------------------------------------------


def test_forgetting_the_job_removes_its_link() -> None:
    owner = _client()
    job_id = _job(owner)
    token = _share(owner, job_id)
    job_manager.forget_job(job_id)
    assert share_links.resolve(token) is None


def test_retention_sweep_removes_the_link_of_a_deleted_result() -> None:
    owner = _client()
    expired = _job(owner, expires_at=PAST)
    token_expired = share_links.create_or_update(expired, owner.user_id, False)["token"]
    orphan = _job(owner)
    token_orphan = _share(owner, orphan)
    (settings.OUTPUT_DIR / f"{orphan}_result.json").unlink()
    job_manager._results.pop(orphan, None)

    report = retention.sweep(dry_run=True)
    assert orphan in report["share_links"] and share_links.resolve(token_orphan)  # simulación: no borra

    report = retention.sweep(dry_run=False)
    assert expired in report["jobs"]
    assert share_links.resolve(token_expired) is None
    assert share_links.resolve(token_orphan) is None


def test_deleting_the_account_removes_its_links() -> None:
    owner = _client()
    job_id = _job(owner)
    token = _share(owner, job_id)
    supabase_service.delete_account(owner.user_id)
    assert share_links.resolve(token) is None
    assert _visit(token).status_code == 404
