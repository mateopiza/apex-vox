"""Background services start and stop with the app, and the health check survives strict hosts."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.testclient import TestClient

from app import main
from app.config import settings


def test_lifespan_starts_and_stops_background_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    started = []
    monkeypatch.setattr(main, "_start_background_services", lambda: started.append(True))
    with TestClient(main.app):
        assert started == [True]
        assert not main._stop_background.is_set()
    assert main._stop_background.is_set()
    main._stop_background.clear()


def test_billing_loop_ends_when_the_app_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.supabase_service import supabase_service

    calls = []

    def stop_after_first_sweep():
        calls.append(True)
        main._stop_background.set()
        return []

    monkeypatch.setattr(supabase_service, "collect_due_billing_emails", stop_after_first_sweep)
    main._stop_background.clear()
    main._billing_email_loop()  # returns instead of sleeping forever
    assert calls == [True]
    main._stop_background.clear()


def test_app_has_no_deprecated_startup_handlers() -> None:
    assert main.app.router.on_startup == []


def _health_app(hosts: list[str]) -> FastAPI:
    app = FastAPI()
    app.get("/api/health")(lambda: {"ok": True})
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*hosts, "localhost", "127.0.0.1"])
    return app


def test_container_health_check_host_is_always_allowed() -> None:
    """Dockerfile and compose call http://localhost:8000/api/health."""
    client = TestClient(_health_app(["apexvox.example.com"]))
    assert client.get("http://localhost:8000/api/health").status_code == 200
    assert client.get("http://127.0.0.1:8000/api/health").status_code == 200
    assert client.get("http://apexvox.example.com/api/health").status_code == 200
    assert client.get("http://evil.example/api/health").status_code == 400


def test_main_module_applies_the_same_allowance() -> None:
    source = (main.APP_DIR / "main.py").read_text(encoding="utf-8")
    assert '[*settings.ALLOWED_HOSTS, "localhost", "127.0.0.1"]' in source


def test_production_warns_about_open_hosts(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["*"])
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://apexvox.example.com"])
    with caplog.at_level(logging.WARNING, logger="app.main"):
        main._warn_about_open_settings()
    assert "ALLOWED_HOSTS" in caplog.text
    assert "CORS_ORIGINS" not in caplog.text
