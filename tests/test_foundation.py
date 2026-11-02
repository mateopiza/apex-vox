"""
Foundation & Milestone 1 Verification Tests
-------------------------------------------
Tests application configuration, environment parsing, healthcheck endpoint,
system tool dependencies, and storage directory permissions under normal,
fallback, and degraded failure scenarios.
"""

from __future__ import annotations

import shutil
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings, settings
from app.main import app


# =============================================================================
# 1. Configuration & Environment Variable Tests
# =============================================================================

def test_config_defaults() -> None:
    """Verify default configuration parameters match specification."""
    cfg = get_settings()
    assert cfg.PORT == 8000
    assert cfg.HOST == "0.0.0.0"
    assert cfg.DEFAULT_MODEL == "whisper-large-v3"
    assert cfg.DEFAULT_LLM_MODEL == "llama-3.3-70b-versatile"
    assert cfg.GROQ_PAYLOAD_LIMIT_MB == 25.0
    assert cfg.CHUNK_TARGET_DURATION_SEC == 600.0
    assert cfg.SILENCE_NOISE_THRESHOLD_DB == -30.0
    assert cfg.SILENCE_MIN_DURATION_SEC == 0.5
    assert cfg.AUDIO_SAMPLE_RATE == 16000
    assert cfg.AUDIO_CHANNELS == 1
    assert cfg.UPLOAD_DIR.name == "uploads"
    assert cfg.OUTPUT_DIR.name == "outputs"


def test_config_env_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify fallback environment variables from docker-compose.yml and .env.example
    (CHUNK_DURATION_MINUTES, SILENCE_THRESHOLD_DB, CHUNK_MAX_BYTES) are recognized
    when the primary internal setting names are not explicitly defined.
    """
    monkeypatch.delenv("CHUNK_TARGET_DURATION_SEC", raising=False)
    monkeypatch.delenv("SILENCE_NOISE_THRESHOLD_DB", raising=False)
    monkeypatch.delenv("GROQ_PAYLOAD_LIMIT_BYTES", raising=False)

    monkeypatch.setenv("CHUNK_DURATION_MINUTES", "5")
    monkeypatch.setenv("SILENCE_THRESHOLD_DB", "-40")
    monkeypatch.setenv("CHUNK_MAX_BYTES", "20000000")

    cfg = Settings()
    # 5 minutes -> 300.0 seconds
    assert cfg.CHUNK_TARGET_DURATION_SEC == 300.0
    # -40 dB
    assert cfg.SILENCE_NOISE_THRESHOLD_DB == -40.0
    # 20,000,000 bytes
    assert cfg.GROQ_PAYLOAD_LIMIT_BYTES == 20000000

    # Test backward compatibility aliases if available
    if hasattr(cfg, "CHUNK_DURATION_MINUTES"):
        assert cfg.CHUNK_DURATION_MINUTES == 5.0
    if hasattr(cfg, "CHUNK_MAX_BYTES"):
        assert cfg.CHUNK_MAX_BYTES == 20000000
    if hasattr(cfg, "SILENCE_THRESHOLD_DB"):
        assert cfg.SILENCE_THRESHOLD_DB == -40.0


def test_config_primary_env_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify primary environment variables take precedence over legacy/compose
    fallback variables when both are specified.
    """
    monkeypatch.setenv("CHUNK_TARGET_DURATION_SEC", "450.0")
    monkeypatch.setenv("CHUNK_DURATION_MINUTES", "15")

    monkeypatch.setenv("SILENCE_NOISE_THRESHOLD_DB", "-25.0")
    monkeypatch.setenv("SILENCE_THRESHOLD_DB", "-35.0")

    monkeypatch.setenv("GROQ_PAYLOAD_LIMIT_BYTES", "24000000")
    monkeypatch.setenv("CHUNK_MAX_BYTES", "22000000")

    cfg = Settings()
    assert cfg.CHUNK_TARGET_DURATION_SEC == 450.0
    assert cfg.SILENCE_NOISE_THRESHOLD_DB == -25.0
    assert cfg.GROQ_PAYLOAD_LIMIT_BYTES == 24000000


def test_groq_key_validation_behavior() -> None:
    """Verify behavior of Groq API key checking and validation."""
    custom_cfg = Settings(GROQ_API_KEY="")
    assert custom_cfg.is_groq_configured is False

    with pytest.raises(RuntimeError) as exc_info:
        custom_cfg.validate_for_transcription()
    assert "GROQ_API_KEY is not set" in str(exc_info.value)

    configured_cfg = Settings(GROQ_API_KEY="gsk_valid_key_test_123")
    assert configured_cfg.is_groq_configured is True
    # Should not raise exception
    configured_cfg.validate_for_transcription()


# =============================================================================
# 2. HTTP Endpoints: Happy Paths
# =============================================================================

def test_root_endpoint() -> None:
    """Verify root endpoint serves the HTML UI and supports JSON format."""
    client = TestClient(app)
    html_res = client.get("/")
    assert html_res.status_code == 200
    assert "Audio Studio" in html_res.text

    response = client.get("/?format=json")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == settings.APP_NAME
    assert data["status"] == "running"
    assert data["health_url"] == "/api/health"


def test_health_endpoint() -> None:
    """Verify healthcheck endpoint returns valid JSON with system and storage status."""
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == settings.APP_VERSION
    assert "system" in data
    assert "storage" in data
    assert "models" in data
    assert data["system"]["ffmpeg"] is True
    assert data["system"]["ffprobe"] is True
    assert data["storage"]["uploads_writable"] is True
    assert data["storage"]["outputs_writable"] is True
    assert data["storage"]["temp_writable"] is True


# =============================================================================
# 3. HTTP Endpoints: Degraded & Failure Mode Paths
# =============================================================================

def test_health_degraded_when_ffmpeg_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify /api/health returns HTTP 503 and status 'degraded' when ffmpeg
    binary is not available on PATH.
    """
    real_which = shutil.which
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd, *args, **kwargs: None if cmd == "ffmpeg" else real_which(cmd, *args, **kwargs),
    )
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["system"]["ffmpeg"] is False
    assert data["system"]["ffprobe"] is True


def test_health_degraded_when_ffprobe_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify /api/health returns HTTP 503 and status 'degraded' when ffprobe
    binary is not available on PATH.
    """
    real_which = shutil.which
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd, *args, **kwargs: None if cmd == "ffprobe" else real_which(cmd, *args, **kwargs),
    )
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["system"]["ffmpeg"] is True
    assert data["system"]["ffprobe"] is False


def test_health_degraded_when_both_media_binaries_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify /api/health returns HTTP 503 and status 'degraded' when both
    ffmpeg and ffprobe binaries are missing.
    """
    real_which = shutil.which
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd, *args, **kwargs: None if cmd in ("ffmpeg", "ffprobe") else real_which(cmd, *args, **kwargs),
    )
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["system"]["ffmpeg"] is False
    assert data["system"]["ffprobe"] is False


def test_health_degraded_when_uploads_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify /api/health returns HTTP 503 and status 'degraded' when upload
    directory is not writable.
    """
    orig_touch = Path.touch

    def fake_touch(self: Path, *args, **kwargs) -> None:
        if str(self).startswith(str(settings.UPLOAD_DIR)):
            raise PermissionError("Simulated read-only uploads directory")
        orig_touch(self, *args, **kwargs)

    monkeypatch.setattr(Path, "touch", fake_touch)
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["storage"]["uploads_writable"] is False
    assert data["storage"]["outputs_writable"] is True
    assert data["storage"]["temp_writable"] is True


def test_health_degraded_when_outputs_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify /api/health returns HTTP 503 and status 'degraded' when outputs
    directory is not writable.
    """
    orig_touch = Path.touch

    def fake_touch(self: Path, *args, **kwargs) -> None:
        if str(self).startswith(str(settings.OUTPUT_DIR)):
            raise PermissionError("Simulated read-only outputs directory")
        orig_touch(self, *args, **kwargs)

    monkeypatch.setattr(Path, "touch", fake_touch)
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["storage"]["uploads_writable"] is True
    assert data["storage"]["outputs_writable"] is False
    assert data["storage"]["temp_writable"] is True


def test_health_degraded_when_temp_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify /api/health returns HTTP 503 and status 'degraded' when temp
    directory is not writable.
    """
    orig_touch = Path.touch

    def fake_touch(self: Path, *args, **kwargs) -> None:
        if str(self).startswith(str(settings.TEMP_DIR)):
            raise PermissionError("Simulated read-only temp directory")
        orig_touch(self, *args, **kwargs)

    monkeypatch.setattr(Path, "touch", fake_touch)
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["storage"]["uploads_writable"] is True
    assert data["storage"]["outputs_writable"] is True
    assert data["storage"]["temp_writable"] is False
