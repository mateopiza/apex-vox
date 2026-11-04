"""With a single worker, nothing slow may run on the event loop."""

import ast
import asyncio
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"
BLOCKING_MODULES = {
    "apex_box_manager", "bold_service", "calendar_invites", "email_service", "httpx", "job_manager", "mcp_oauth",
    "mega_s4_storage", "oauth_service", "recall_service", "requests", "subprocess", "supabase_service",
    "telegram_service", "time", "twilio_service",
}
# Quick and free of I/O: signature checks over bytes already in memory, and starting a thread.
ALLOWED_CALLS = {
    "bold_service.verify_bold_webhook_signature",
    "recall_service.verify_svix",
    "telegram_service.handle_update_async",
    "telegram_service.verify_webhook",
    "twilio_service.twiml_contact_notice",
    "twilio_service.validate_signature",
    "twilio_service.webhook_base",
}


def _blocking_calls(tree: ast.AST) -> list[str]:
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                name = f"{node.func.value.id}.{node.func.attr}"
                if node.func.value.id in BLOCKING_MODULES and name not in ALLOWED_CALLS:
                    found.append(f"{function.name}: {name}")
    return found


@pytest.mark.parametrize("path", sorted(API_DIR.glob("routes_*.py")), ids=lambda p: p.name)
def test_async_routes_do_not_call_blocking_services_directly(path: Path) -> None:
    assert _blocking_calls(ast.parse(path.read_text(encoding="utf-8"))) == []


def test_slow_login_does_not_delay_other_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Before, the wrong password path alone could stop every user for up to 10 s."""
    started, release = threading.Event(), threading.Event()

    def slow_login(email: str, password: str):
        started.set()
        release.wait(5)
        raise ValueError("Credenciales inválidas.")

    monkeypatch.setattr(supabase_service, "login_user", slow_login)

    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = asyncio.create_task(client.post("/api/auth/login", json={"email": "a@b.co", "password": "x" * 8}))
            await asyncio.to_thread(started.wait, 5)
            begin = time.monotonic()
            quick = await client.get("/api/info")
            elapsed = time.monotonic() - begin
            release.set()
            await login
            assert quick.status_code == 200
            return elapsed

    assert asyncio.run(scenario()) < 2


def test_routes_converted_to_threads_still_authenticate() -> None:
    profile = supabase_service.register_user(f"{uuid.uuid4().hex}@example.com", "password123")
    client = TestClient(app)
    assert client.get("/api/auth/me").status_code == 401
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {profile.access_token}"})
    assert me.status_code == 200


def test_renames_of_one_job_do_not_overwrite_each_other(monkeypatch: pytest.MonkeyPatch) -> None:
    running, overlaps = [0], []

    def tracked(job_id, speaker_map):
        running[0] += 1
        overlaps.append(running[0])
        time.sleep(0.05)
        running[0] -= 1
        raise KeyError(job_id)

    monkeypatch.setattr(job_manager, "_rename_speakers", tracked)

    def rename():
        with pytest.raises(KeyError):
            job_manager.rename_speakers("job_same", {"A": "B"})

    threads = [threading.Thread(target=rename) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert max(overlaps) == 1


def test_asset_version_is_computed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    main._asset_version.cache_clear()
    first = main._asset_version()
    monkeypatch.setattr(main, "STATIC_DIR", Path("/nonexistent"))
    assert main._asset_version() == first
    main._asset_version.cache_clear()
