"""End-to-end fixtures: a real uvicorn server on a free port and a real Chromium (Playwright).

The server runs in a background thread of the pytest process, so the Groq transcription call
can be replaced with a deterministic fake (no network, no keys). Everything else is the real
stack: HTTP, middleware, CSP, static files, background jobs, FFmpeg and the browser JavaScript.

The suite skips itself when Playwright or its Chromium build is not installed:

    pip install -r requirements-e2e.txt && python -m playwright install chromium
    python -m pytest tests/e2e -q

On failure a screenshot and a Playwright trace are written to ``test-results/e2e/``
(open the trace with ``python -m playwright show-trace <file>``).
"""

from __future__ import annotations

import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator, List

import pytest

os.environ.setdefault("ALLOWED_HOSTS", "*")

try:  # Playwright is an optional, e2e-only dependency (requirements-e2e.txt).
    from playwright.sync_api import Browser, BrowserContext, Error as PlaywrightError, Page, sync_playwright
except ImportError:  # pragma: no cover - depends on the environment
    sync_playwright = None  # type: ignore[assignment]

from tests.fixtures.audio_generator import convert_audio_format, create_synthetic_wav

ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "test-results" / "e2e"

# Deterministic transcript returned by the fake Groq call, per source file name.
FAKE_TRANSCRIPTS: dict[str, List[dict[str, Any]]] = {
    "entrevista": [
        {"id": 0, "start": 0.0, "end": 1.8, "text": "Hola a todos, bienvenidos al programa."},
        {"id": 1, "start": 2.4, "end": 4.0, "text": "Muchas gracias por la invitación."},
    ],
    "cierre": [
        {"id": 0, "start": 0.1, "end": 2.6, "text": "Perfecto, con esto cerramos la sesión de hoy."},
    ],
}
DEFAULT_TRANSCRIPT = [
    {"id": 0, "start": 0.0, "end": 2.0, "text": "Este es un audio de prueba de extremo a extremo."},
]


def fake_transcribe_chunk(chunk: Any, **_: Any) -> List[dict[str, Any]]:
    name = (getattr(chunk, "source_file_name", "") or "").lower()
    for key, segments in FAKE_TRANSCRIPTS.items():
        if key in name:
            return [dict(s) for s in segments]
    return [dict(s) for s in DEFAULT_TRANSCRIPT]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def _offline_llm_diarizer(*_: Any, **__: Any) -> Any:
    # Same path as a Groq outage: diarize_segments falls back to the acoustic labels.
    raise RuntimeError("LLM diarization is offline in the e2e suite")


# Outbound HTTP attempts the app made during the run (anything not to 127.0.0.1/localhost).
OUTBOUND_CALLS: List[str] = []
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _block_outbound(patcher: pytest.MonkeyPatch) -> None:
    """Make the suite hermetic: the server may not reach any external service."""
    import httpx
    import requests

    def guard(url: str) -> None:
        host = httpx.URL(str(url)).host
        if host not in _LOCAL_HOSTS:
            OUTBOUND_CALLS.append(str(url))
            raise httpx.ConnectError(f"outbound network is blocked in the e2e suite: {url}")

    real_send, real_async_send, real_requests_send = httpx.Client.send, httpx.AsyncClient.send, requests.Session.send

    def send(self: httpx.Client, request: httpx.Request, **kw: Any) -> httpx.Response:
        guard(str(request.url))
        return real_send(self, request, **kw)

    async def async_send(self: httpx.AsyncClient, request: httpx.Request, **kw: Any) -> httpx.Response:
        guard(str(request.url))
        return await real_async_send(self, request, **kw)

    def requests_send(self: requests.Session, request: Any, **kw: Any) -> Any:
        try:
            guard(request.url)
        except httpx.ConnectError as exc:
            raise requests.ConnectionError(str(exc)) from exc
        return real_requests_send(self, request, **kw)

    patcher.setattr(httpx.Client, "send", send)
    patcher.setattr(httpx.AsyncClient, "send", async_send)
    patcher.setattr(requests.Session, "send", requests_send)


@pytest.fixture(scope="package")
def live_server() -> Iterator[str]:
    """Start the real ASGI app with uvicorn and yield its base URL."""
    import uvicorn

    from app.main import app

    patcher = pytest.MonkeyPatch()
    patcher.setattr("app.services.groq_service.transcribe_chunk", fake_transcribe_chunk)
    patcher.setattr("app.services.diarization._call_llm_diarizer_batch", _offline_llm_diarizer)
    patcher.setattr("app.services.apex_summa._enrich_with_groq_llm", lambda *a, **k: None)
    _block_outbound(patcher)

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="e2e-uvicorn", daemon=True)
    thread.start()

    deadline = time.monotonic() + 20
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            patcher.undo()
            pytest.fail("The e2e server did not start within 20 s.")
        time.sleep(0.05)

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        patcher.undo()


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def e2e_browser() -> Iterator["Browser"]:
    if sync_playwright is None:
        pytest.skip("Playwright is not installed (pip install -r requirements-e2e.txt).")
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=os.getenv("E2E_HEADED", "") != "1")
    except PlaywrightError as exc:  # pragma: no cover - depends on the environment
        pw.stop()
        pytest.skip(f"Chromium for Playwright is not available ({exc.message.splitlines()[0]}). "
                    "Run: python -m playwright install chromium")
    try:
        yield browser
    finally:
        browser.close()
        pw.stop()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


class BrowserErrors:
    """Console errors, uncaught exceptions and CSP violations seen by one page."""

    # Messages that are not bugs in our code (e.g. Google Fonts blocked in an offline CI runner).
    IGNORED = (
        re.compile(r"fonts\.(googleapis|gstatic)\.com"),
        re.compile(r"Failed to load resource: net::ERR_(INTERNET_DISCONNECTED|NAME_NOT_RESOLVED|CONNECTION_REFUSED)"),
    )

    def __init__(self) -> None:
        self.messages: List[str] = []
        self.expected: List[re.Pattern[str]] = []

    def expect(self, pattern: str) -> None:
        """Allow an error the test provokes on purpose (e.g. a 401 from a wrong password)."""
        self.expected.append(re.compile(pattern))

    def add(self, text: str) -> None:
        if any(p.search(text) for p in self.IGNORED + tuple(self.expected)):
            return
        self.messages.append(text)


def _new_context(browser: "Browser", **overrides: Any) -> "BrowserContext":
    options: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 900},
        "locale": "es-CO",
        "accept_downloads": True,
    }
    options.update(overrides)
    context = browser.new_context(**options)
    context.set_default_timeout(15_000)
    context.tracing.start(screenshots=True, snapshots=True, sources=False)
    return context


def _watch(page: "Page", errors: BrowserErrors) -> None:
    page.on("console", lambda msg: errors.add(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.add(f"pageerror: {exc}"))


@pytest.fixture
def open_page(e2e_browser: "Browser", live_server: str, request: pytest.FixtureRequest) -> Iterator[Callable[..., "Page"]]:
    """Factory: ``open_page(path, **context_options)`` -> Page in a fresh, isolated browser context.

    After the test, any unexpected console error, uncaught exception or CSP violation fails it.
    On failure, a screenshot and trace per page are saved under test-results/e2e/.
    """
    opened: List[tuple["BrowserContext", "Page", BrowserErrors]] = []
    outbound_before = len(OUTBOUND_CALLS)

    def _open(path: str = "/", **context_options: Any) -> "Page":
        context = _new_context(e2e_browser, base_url=live_server, **context_options)
        page = context.new_page()
        errors = BrowserErrors()
        _watch(page, errors)
        page.errors = errors  # type: ignore[attr-defined]
        opened.append((context, page, errors))
        page.goto(path)
        return page

    yield _open

    failed = bool(getattr(request.node, "rep_call", None) and request.node.rep_call.failed)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)[-120:]
    problems: List[str] = []
    for idx, (context, page, errors) in enumerate(opened):
        if failed:
            ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
            try:
                page.screenshot(path=str(ARTIFACTS_DIR / f"{safe_name}-{idx}.png"), full_page=True)
            except PlaywrightError:
                pass
            context.tracing.stop(path=str(ARTIFACTS_DIR / f"{safe_name}-{idx}.zip"))
        else:
            context.tracing.stop()
        problems.extend(errors.messages)
        context.close()
    problems.extend(f"server tried to reach an external service: {url}" for url in OUTBOUND_CALLS[outbound_before:])

    if problems and not failed:
        pytest.fail("Errors in the browser:\n" + "\n".join(f"  - {p}" for p in problems), pytrace=False)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def audio_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Real WAV and MP3 files generated with FFmpeg (two pitches, so there are two voices)."""
    base = tmp_path_factory.mktemp("e2e_audio")
    entrevista = base / "entrevista.wav"
    create_synthetic_wav(entrevista, [(2.0, 140.0), (0.6, 0.0), (1.8, 260.0)])
    cierre_src = base / "cierre_src.wav"
    create_synthetic_wav(cierre_src, [(2.8, 260.0)])
    cierre = base / "cierre.mp3"
    convert_audio_format(cierre_src, cierre, "mp3")
    return {"entrevista": entrevista, "cierre": cierre}
