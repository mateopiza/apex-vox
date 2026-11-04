"""Deleting an account reaches everything, retries what fails and ignores the retention simulation."""

import json
import uuid
from typing import List

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.errors import UserFacingError
from app.models.schemas import BoxCreateSessionRequest, TranscribeRequest, TranscriptionResult, VoiceProfile
from app.services import acoustic_diarizer, retention, supabase_service as supabase_module
from app.services.apex_box import apex_box_manager
from app.services.job_manager import job_manager
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

client = TestClient(app)


def _account(**fields) -> tuple[str, str, dict]:
    email = f"{uuid.uuid4().hex}@example.com"
    profile = supabase_service.register_user(email, "password123")
    if fields:
        db = supabase_service._load_db()
        db["users"][profile.user_id].update(fields)
        supabase_service._save_db(db)
    return profile.user_id, email, {"Authorization": f"Bearer {profile.access_token}"}


def _job(uid: str) -> tuple[str, str]:
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    key = f"users/{uid}/jobs/{job_id}/result.json"
    result = TranscriptionResult(
        job_id=job_id, session_id="s", user_id=uid, plan="pro", status="completed", detected_speakers_count=1,
        total_duration_sec=1, total_duration_formatted="00:00:01", model_used="m", diarization_engine_used="e",
        engine_brand="b", file_order=[], segments=[], full_text="private",
    )
    (settings.OUTPUT_DIR / f"{job_id}_result.json").write_text(result.model_dump_json(), encoding="utf-8")
    (settings.OUTPUT_DIR / f"{job_id}_merged.mp3").write_bytes(b"audio")
    mega_s4_storage.upload_object(key, b"{}", plan="pro", user_id=uid, job_id=job_id)
    supabase_service.save_transcription_record({"job_id": job_id, "user_id": uid, "s4_result_key": key})
    return job_id, key


def test_deleting_an_account_reaches_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings.RETENTION_DRY_RUN is True  # erasure does not depend on the simulation
    uid, email, auth = _account()
    job_id, key = _job(uid)
    other_uid, _, _ = _account()
    other_job, other_key = _job(other_uid)
    expires = "2099-01-01T00:00:00+00:00"
    db = supabase_service._load_db()
    db.setdefault("oauth_tokens", {})["t"] = {"user_id": uid, "kind": "access", "expires_at": expires}
    db.setdefault("oauth_codes", {})["c"] = {"user_id": uid, "expires_at": expires}
    db.setdefault("telegram_codes", {})["k"] = {"user_id": uid, "expires_at": expires}
    db.setdefault("password_resets", {})["r"] = {"user_id": uid, "expires_at": expires}
    db["handoffs"]["h"] = {"user_id": uid, "expires_at": expires}
    db.setdefault("newsletter", {})[email] = {"status": "confirmed"}
    db["subscriptions"]["ref"] = {"user_id": uid, "amount": 10}
    db["promo_ips"]["ip"] = {"used_at": expires, "user_id": uid}
    supabase_service._save_db(db)
    session = job_manager.create_or_get_session(owner=uid)
    (session.session_dir / "a.wav").write_bytes(b"x")
    box = apex_box_manager.create_session(BoxCreateSessionRequest(title="t", user_id=uid))

    assert client.delete("/api/auth/account", headers=auth).status_code == 200

    after = supabase_service._load_db()
    raw = json.dumps(after)
    assert uid not in after["users"] and job_id not in after["transcriptions"]
    for coll in ("oauth_tokens", "oauth_codes", "telegram_codes", "password_resets", "handoffs"):
        assert not any(v.get("user_id") == uid for v in after.get(coll, {}).values()), coll
    assert email not in raw
    assert uid not in raw  # subscriptions and promo records stay, with no personal link
    assert after["subscriptions"]["ref"]["amount"] == 10
    assert not after.get("pending_erasures")
    assert not list(settings.OUTPUT_DIR.glob(f"{job_id}*"))
    assert mega_s4_storage.get_object_metadata(key) is None
    assert not session.session_dir.exists()
    assert job_manager.get_session(session.session_id) is None
    with pytest.raises(KeyError):
        apex_box_manager.get_session(box.box_session_id)

    # Nobody else is touched.
    assert other_uid in after["users"] and other_job in after["transcriptions"]
    assert mega_s4_storage.get_object_metadata(other_key) is not None
    assert list(settings.OUTPUT_DIR.glob(f"{other_job}*"))


def test_failed_bucket_delete_is_retried_by_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    uid, _, auth = _account()
    job_id, key = _job(uid)
    with monkeypatch.context() as patch:
        patch.setattr(mega_s4_storage, "delete_object", lambda key: False)
        assert client.delete("/api/auth/account", headers=auth).status_code == 200
        pending = supabase_service._load_db()["pending_erasures"][uid]
        assert job_id in pending["jobs"]
        assert uid not in supabase_service._load_db()["users"]  # the account itself is gone already

    retention.sweep()  # a dry run for retention still finishes account deletions
    assert uid not in supabase_service._load_db().get("pending_erasures", {})
    assert mega_s4_storage.get_object_metadata(key) is None
    assert not list(settings.OUTPUT_DIR.glob(f"{job_id}*"))


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "service")
    calls: List[httpx.Request] = []
    state = {"status": 204}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(state["status"] if request.method == "DELETE" else 201, json=[])

    real = httpx.Client
    monkeypatch.setattr(supabase_module.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return calls, state


def test_supabase_rows_and_auth_user_are_deleted(fake_supabase) -> None:
    calls, _ = fake_supabase
    uid, _, _ = _account(supabase_id="auth-user-1")
    supabase_service.delete_account(uid)
    deletes = [str(r.url) for r in calls if r.method == "DELETE"]
    assert any("/rest/v1/transcriptions" in u and f"user_id=eq.{uid}" in u for u in deletes)
    assert any("/rest/v1/profiles" in u and f"id=eq.{uid}" in u for u in deletes)
    assert any(u.endswith("/auth/v1/admin/users/auth-user-1") for u in deletes)
    assert uid not in supabase_service._load_db().get("pending_erasures", {})


def test_supabase_failure_stays_pending(fake_supabase) -> None:
    _, state = fake_supabase
    uid, _, _ = _account(supabase_id="auth-user-2")
    state["status"] = 500
    supabase_service.delete_account(uid)
    assert uid in supabase_service._load_db()["pending_erasures"]
    state["status"] = 204
    assert retention.process_pending_erasures(only_user=uid) == 0
    assert uid not in supabase_service._load_db().get("pending_erasures", {})


def test_auth_user_already_gone_counts_as_done(fake_supabase, monkeypatch: pytest.MonkeyPatch) -> None:
    _, state = fake_supabase
    state["status"] = 404
    assert supabase_service._delete_auth_user("auth-user-3") is True


def test_voiceprints_of_deleted_accounts_are_removed() -> None:
    uid, _, _ = _account()
    other, _, _ = _account()

    def profile(owner: str) -> VoiceProfile:
        return VoiceProfile(profile_id=f"vp_{uuid.uuid4().hex[:8]}", name="Ana", role="", sample_duration_sec=5.0,
                            pitch_hz=120.0, embedding=[0.1], created_at="2026-01-01T00:00:00+00:00", owner_id=owner)

    acoustic_diarizer.update_voice_profiles(lambda ps: ps + [profile(uid), profile(other), profile("deleted-long-ago")])
    supabase_service.delete_account(uid)
    owners = {p.owner_id for p in acoustic_diarizer._load_all_profiles()}
    assert uid not in owners and "deleted-long-ago" not in owners
    assert other in owners


def test_job_running_when_the_account_is_deleted_saves_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.services import job_manager as job_module
    from tests.fixtures.audio_generator import create_synthetic_wav

    uid, _, _ = _account()
    wav = tmp_path / "a.wav"
    create_synthetic_wav(wav, [(1.0, 440.0)])
    session = job_manager.create_or_get_session(owner=uid)
    job_manager.add_file_to_session(session.session_id, "a.wav", wav.read_bytes(), owner=uid)
    req = TranscribeRequest(session_id=session.session_id, user_id=uid, diarization_engine="Mc-Norris")
    status = job_manager.create_job(req)

    def delete_during_transcription(**kwargs):
        supabase_service.delete_account(uid)
        return []

    monkeypatch.setattr(job_module, "transcribe_chunks_sequence", delete_during_transcription)
    with pytest.raises(Exception):
        job_manager.execute_job(status.job_id, req)
    assert not (settings.OUTPUT_DIR / f"{status.job_id}_result.json").exists()
    assert status.job_id not in supabase_service._load_db()["transcriptions"]
    assert uid not in supabase_service._load_db()["users"]


def test_job_of_a_deleted_account_does_not_run(tmp_path) -> None:
    from tests.fixtures.audio_generator import create_synthetic_wav

    wav = tmp_path / "a.wav"
    create_synthetic_wav(wav, [(1.0, 440.0)])
    session = job_manager.create_or_get_session(owner="gone")
    job_manager.add_file_to_session(session.session_id, "a.wav", wav.read_bytes(), owner="gone")
    req = TranscribeRequest(session_id=session.session_id, user_id="gone")
    status = job_manager.create_job(req)
    with pytest.raises(UserFacingError, match="no longer exists"):
        job_manager.execute_job(status.job_id, req)
    assert "gone" not in supabase_service._load_db()["users"]  # it is not recreated either


def test_recording_finalized_after_the_account_is_deleted_saves_nothing() -> None:
    uid, _, _ = _account()
    box = apex_box_manager.create_session(BoxCreateSessionRequest(title="t", user_id=uid)).box_session_id
    session = apex_box_manager.get_session(box)
    db = supabase_service._load_db()
    del db["users"][uid]
    supabase_service._save_db(db)
    with pytest.raises(Exception, match="no longer exists"):
        apex_box_manager.finalize_session(box)
    assert session.final_response is None
