"""Oversized requests get 413 before they are stored, and uploads never go through memory."""

import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.job_manager import UploadTooLargeError, _store_upload, job_manager
from app.services.supabase_service import supabase_service
from tests.fixtures.audio_generator import create_synthetic_wav

client = TestClient(app)


@pytest.fixture
def wav(tmp_path: Path) -> bytes:
    path = tmp_path / "a.wav"
    create_synthetic_wav(path, [(1.0, 440.0)])
    return path.read_bytes()


def _files(*items):
    return [("files", (name, io.BytesIO(data), "audio/wav")) for name, data in items]


def _auth() -> dict:
    token = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123").access_token
    return {"Authorization": f"Bearer {token}"}


def _files_in_uploads() -> set:
    return {p for p in settings.UPLOAD_DIR.rglob("*") if p.is_file()}


def test_file_over_the_limit_is_refused_and_not_stored(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    before = _files_in_uploads()
    res = client.post("/api/upload", files=_files(("big.wav", b"0" * (2 * 1024 * 1024))), headers=_auth())
    assert res.status_code == 413
    assert " / " in res.json()["detail"]
    assert _files_in_uploads() == before


def test_too_many_files_are_refused(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    monkeypatch.setattr(settings, "MAX_FILES_PER_UPLOAD", 1)
    res = client.post("/api/upload", files=_files(("a.wav", wav), ("b.wav", wav)), headers=_auth())
    assert res.status_code == 413


def test_upload_session_total_is_limited(monkeypatch: pytest.MonkeyPatch, wav: bytes) -> None:
    auth = _auth()
    first = client.post("/api/upload", files=_files(("a.wav", wav)), headers=auth)
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    monkeypatch.setattr(settings, "MAX_TOTAL_UPLOAD_SIZE_MB", 0)
    monkeypatch.setattr(job_manager, "session_size_bytes", lambda _: 1)
    res = client.post("/api/upload", files=_files(("b.wav", wav)), data={"session_id": session_id}, headers=auth)
    assert res.status_code == 413


def test_declared_body_over_the_limit_is_refused_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_MB", 1)
    res = client.post("/api/auth/login", content=b"0" * (2 * 1024 * 1024), headers={"Content-Type": "application/json"})
    assert res.status_code == 413
    assert " / " in res.json()["detail"]


def test_chunked_body_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_VOICE_SAMPLE_MB", 0)
    monkeypatch.setattr("app.api.body_limit._MULTIPART_OVERHEAD", 1024)

    def body():
        yield b"--x\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\nAna\r\n"
        for _ in range(20):
            yield b"0" * 1024

    res = client.post(
        "/api/voice-profiles",
        content=body(),
        headers={"Content-Type": "multipart/form-data; boundary=x", **_auth()},
    )
    assert res.status_code == 413


def test_box_block_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = _auth()
    box = client.post("/api/box/sessions", json={"title": "t"}, headers=auth).json()["box_session_id"]
    monkeypatch.setattr(settings, "MAX_BOX_BLOCK_MB", 1)
    res = client.post(
        f"/api/box/sessions/{box}/blocks",
        files={"file": ("b.webm", io.BytesIO(b"0" * (2 * 1024 * 1024)), "audio/webm")},
        headers=auth,
    )
    assert res.status_code == 413


def test_voice_sample_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_VOICE_SAMPLE_MB", 1)
    res = client.post(
        "/api/voice-profiles",
        data={"name": "Ana"},
        files={"file": ("a.wav", io.BytesIO(b"0" * (2 * 1024 * 1024)), "audio/wav")},
        headers=_auth(),
    )
    assert res.status_code == 413
    assert " / " in res.json()["detail"]


def test_store_upload_streams_and_leaves_nothing_when_over_limit(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    assert _store_upload(io.BytesIO(b"12345"), dest, max_bytes=5) == 5
    assert dest.read_bytes() == b"12345"

    with pytest.raises(UploadTooLargeError):
        _store_upload(io.BytesIO(b"123456"), tmp_path / "too-big", max_bytes=5)
    assert not (tmp_path / "too-big").exists()


def test_empty_upload_is_refused_and_not_stored() -> None:
    res = client.post("/api/upload", files=_files(("a.wav", b"")), headers=_auth())
    assert res.status_code == 400
    assert "0 bytes" in res.json()["detail"]


def test_normal_upload_still_works(wav: bytes) -> None:
    res = client.post("/api/upload", files=_files(("a.wav", wav)), headers=_auth())
    assert res.status_code == 200
    assert res.json()["files"][0]["size_bytes"] == len(wav)
