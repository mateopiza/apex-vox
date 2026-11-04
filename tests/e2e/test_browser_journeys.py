"""Browser end-to-end journeys (tests/e2e/test_browser_journeys.py).

Each test drives the real web UI in Chromium against a real uvicorn server, the way a person
would: click, type, pick files, wait for the job, read the result, download exports. Only the
Groq transcription call is faked (see conftest.py). Unexpected console errors, uncaught
exceptions and CSP violations fail the test.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Callable

import httpx
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Route, Page, expect  # noqa: E402

pytestmark = pytest.mark.e2e

JOB_TIMEOUT_MS = 60_000
PASSWORD = "E2e-pass-1234"


def _email(tag: str) -> str:
    return f"e2e_{tag}_{uuid.uuid4().hex[:8]}@example.com"


def _go_studio(page: Page) -> None:
    page.locator("#nav-playground-btn").click()
    expect(page.locator("#view-playground")).to_be_visible()


def _upload(page: Page, *paths: Path) -> None:
    page.locator("#file-input").set_input_files([str(p) for p in paths])
    expect(page.locator("#track-list .track-item")).to_have_count(len(paths), timeout=30_000)
    expect(page.locator("#transcribe-btn")).to_be_enabled()


def _transcribe_and_wait(page: Page) -> None:
    page.locator("#transcribe-btn").click()
    expect(page.locator("#result-container")).to_be_visible(timeout=JOB_TIMEOUT_MS)
    expect(page.locator("#empty-result-state")).to_be_hidden()


def _register_in_ui(page: Page, email: str, name: str = "Persona E2E") -> None:
    page.locator("#open-auth-btn").click()
    dialog = page.locator("#auth-dialog")
    expect(dialog).to_be_visible()
    page.locator("#switch-to-register-btn").click()  # the dialog opens on "sign in"
    page.locator("#auth-name-input").fill(name)
    page.locator("#auth-email-input").fill(email)
    page.locator("#auth-password-input").fill(PASSWORD)
    page.locator("#submit-register-btn").click()
    expect(dialog).to_be_hidden()
    expect(page.locator("#user-initials")).to_be_visible()


def _token(page: Page) -> str:
    token = page.evaluate("() => localStorage.getItem('apex_vox_token')")
    assert token, "the session token was not stored after signing in"
    return token


def _api_status(page: Page, path: str, token: str | None) -> int:
    """Status of a GET made from inside the page (same origin, real browser fetch)."""
    return page.evaluate(
        """async ([path, token]) => {
            const headers = token ? { Authorization: `Bearer ${token}` } : {};
            const res = await fetch(path, { headers });
            return res.status;
        }""",
        [path, token],
    )


# ---------------------------------------------------------------------------
# Landing, language, layout
# ---------------------------------------------------------------------------


def test_landing_loads_over_http_with_security_headers(open_page: Callable[..., Page], live_server: str) -> None:
    page = open_page("/?lang=es")
    expect(page).to_have_title(re.compile("Apex Vox"))
    assert page.evaluate("() => document.documentElement.lang") == "es"
    expect(page.locator("#health-text")).to_have_text(re.compile("Activo"))

    res = httpx.get(f"{live_server}/?lang=es")
    assert res.status_code == 200
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"

    # Every same-origin script and stylesheet the page references is served.
    assets = page.evaluate(
        """() => [...document.querySelectorAll('script[src], link[rel=stylesheet]')]
                 .map(el => el.src || el.href)
                 .filter(u => u.startsWith(location.origin))"""
    )
    assert assets, "the page references no local assets"
    for url in assets:
        assert httpx.get(url).status_code == 200, url


def test_english_page_is_translated(open_page: Callable[..., Page]) -> None:
    page = open_page("/?lang=en")
    assert page.evaluate("() => document.documentElement.lang") == "en"
    expect(page.locator("#health-text")).to_have_text(re.compile("Active"))
    expect(page.locator("#nav-landing-btn")).to_have_text("Home")


@pytest.mark.parametrize("width,height", [(390, 844), (768, 1024), (1440, 900)])
def test_no_horizontal_scroll_at_common_widths(open_page: Callable[..., Page], width: int, height: int) -> None:
    page = open_page("/?lang=es", viewport={"width": width, "height": height})
    for view in ("landing", "playground", "portal"):
        page.evaluate(
            "(v) => document.querySelector(`[data-goto-view='${v}'], [data-view='${v}']`)?.click()", view
        )
        overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"{width}px wide: view '{view}' scrolls sideways by {overflow}px"


def test_mobile_bottom_navigation_switches_views(open_page: Callable[..., Page]) -> None:
    page = open_page("/?lang=es", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    nav = page.locator("#mob-nav-playground")
    expect(nav).to_be_visible()
    nav.click()
    expect(page.locator("#view-playground")).to_be_visible()
    page.locator("#mob-nav-landing").click()
    expect(page.locator("#view-landing")).to_be_visible()
    expect(page.locator("#view-playground")).to_be_hidden()


# ---------------------------------------------------------------------------
# Guest: transcribe without an account
# ---------------------------------------------------------------------------


def test_guest_uploads_transcribes_and_downloads_txt(
    open_page: Callable[..., Page], audio_files: dict[str, Path]
) -> None:
    page = open_page("/?lang=es")
    _go_studio(page)
    expect(page.locator("#guest-notice")).to_be_visible()

    _upload(page, audio_files["entrevista"])
    _transcribe_and_wait(page)

    segments = page.locator("#segments-list")
    expect(segments).to_contain_text("bienvenidos al programa")
    expect(segments).to_contain_text("gracias por la invitación")
    # Guests get the transcript only: no saved analysis, and an invitation to sign up.
    expect(page.locator("#guest-result-cta")).to_be_visible()
    expect(page.locator("#apex-summa-container")).to_be_hidden()

    href = page.locator("#export-txt").get_attribute("href")
    assert href and href.startswith("/api/jobs/"), href
    res = page.request.get(href)
    assert res.ok, res.status
    assert "bienvenidos al programa" in res.text()


# ---------------------------------------------------------------------------
# Account: register, transcribe, rename, export, history, logout
# ---------------------------------------------------------------------------


def test_signed_in_user_full_journey(open_page: Callable[..., Page], audio_files: dict[str, Path]) -> None:
    email = _email("full")
    page = open_page("/?lang=es")
    _register_in_ui(page, email)
    token = _token(page)

    # Studio: two files in different formats, two speakers.
    _go_studio(page)
    expect(page.locator("#guest-notice")).to_be_hidden()
    _upload(page, audio_files["entrevista"], audio_files["cierre"])
    page.locator("#speakers-select").select_option("2")
    _transcribe_and_wait(page)

    expect(page.locator("#kpi-speakers")).to_have_text("2")
    expect(page.locator("#guest-result-cta")).to_be_hidden()
    expect(page.locator("#apex-summa-container")).to_be_visible()
    segments = page.locator("#segments-list")
    expect(segments).to_contain_text("bienvenidos al programa")
    expect(segments).to_contain_text("cerramos la sesión de hoy")
    # The two files are stitched in upload order on one timeline.
    text = segments.inner_text()
    assert text.index("bienvenidos al programa") < text.index("cerramos la sesión")

    # Rename the first speaker and see it everywhere.
    page.locator("#rename-speakers-btn").click()
    expect(page.locator("#rename-panel")).to_be_visible()
    page.locator(".speaker-rename-input").first.fill("Conductora")
    page.locator("#apply-rename-btn").click()
    expect(page.locator("#rename-panel")).to_be_hidden()
    expect(segments).to_contain_text("Conductora")

    # Every export link works with its signed media token and carries the new name.
    expected = {"txt": "Conductora", "srt": "-->", "vtt": "WEBVTT", "json": '"segments"', "csv": "start_formatted", "md": "#"}
    for fmt, token_text in expected.items():
        href = page.locator(f"#export-{fmt}").get_attribute("href")
        assert href and "?t=" in href, f"{fmt}: {href}"
        res = page.request.get(href)
        assert res.ok, f"{fmt}: HTTP {res.status}"
        assert token_text in res.text(), fmt
    audio = page.request.get(page.locator("#merged-audio-player").get_attribute("src"))
    assert audio.ok and len(audio.body()) > 1000

    # My account: identity and history.
    page.locator("#open-auth-btn").click()
    expect(page.locator("#view-portal")).to_be_visible()
    expect(page.locator("#portal-user-email")).to_have_text(email)
    expect(page.locator("#portal-kpi-jobs-count")).to_have_text("1")
    expect(page.locator("#portal-history-list .track-item")).to_have_count(1)

    # Log out: the token is gone from the browser and revoked on the server.
    page.errors.expect(r"401")  # type: ignore[attr-defined]  # the revoked token below is refused on purpose
    page.locator("#portal-logout-btn").click()
    expect(page.locator("#portal-logout-btn")).to_be_hidden()
    assert page.evaluate("() => localStorage.getItem('apex_vox_token')") is None
    assert _api_status(page, "/api/auth/me", token) == 401


def test_login_rejects_wrong_password_then_keeps_session_after_reload(
    open_page: Callable[..., Page], live_server: str
) -> None:
    email = _email("login")
    reg = httpx.post(f"{live_server}/api/auth/register", json={"email": email, "password": PASSWORD, "full_name": "Login E2E"})
    assert reg.status_code == 200, reg.text

    page = open_page("/?lang=es")
    page.errors.expect(r"401")  # type: ignore[attr-defined]  # the wrong password is a 401 on purpose
    page.locator("#open-auth-btn").click()
    page.locator("#auth-email-input").fill(email)
    page.locator("#auth-password-input").fill("not-the-password")
    page.locator("#submit-login-btn").click()
    feedback = page.locator("#auth-feedback-box")
    expect(feedback).to_be_visible()
    expect(feedback).to_have_class(re.compile("alert-error"))
    assert page.evaluate("() => localStorage.getItem('apex_vox_token')") is None

    page.locator("#auth-password-input").fill(PASSWORD)
    page.locator("#submit-login-btn").click()
    expect(page.locator("#auth-dialog")).to_be_hidden()
    expect(page.locator("#user-initials")).to_be_visible()

    page.reload()
    expect(page.locator("#user-initials")).to_be_visible()
    page.locator("#open-auth-btn").click()
    expect(page.locator("#view-portal")).to_be_visible()
    expect(page.locator("#portal-user-email")).to_have_text(email)


# ---------------------------------------------------------------------------
# Privacy: one account never sees another account's work
# ---------------------------------------------------------------------------


def test_accounts_cannot_open_each_others_jobs(
    open_page: Callable[..., Page], live_server: str, audio_files: dict[str, Path]
) -> None:
    # Owner A creates a finished job straight through the HTTP API.
    reg_a = httpx.post(
        f"{live_server}/api/auth/register",
        json={"email": _email("owner"), "password": PASSWORD, "full_name": "Owner"},
    ).json()
    auth_a = {"Authorization": f"Bearer {reg_a['access_token']}"}
    with open(audio_files["entrevista"], "rb") as fh:
        up = httpx.post(
            f"{live_server}/api/upload", headers=auth_a,
            files=[("files", ("entrevista.wav", fh, "audio/wav"))], timeout=30,
        )
    assert up.status_code == 200, up.text
    session_id = up.json()["session_id"]
    job = httpx.post(
        f"{live_server}/api/transcribe?sync=true", headers=auth_a, timeout=60,
        json={"session_id": session_id, "file_order": [f["file_id"] for f in up.json()["files"]], "language": "es"},
    )
    assert job.status_code == 200, job.text
    job_id = job.json()["job_id"]
    assert httpx.get(f"{live_server}/api/jobs/{job_id}/result", headers=auth_a).status_code == 200

    # Intruder B signs up in the browser and tries every door to A's job and upload session.
    page = open_page("/?lang=es")
    page.errors.expect(r"40[134]")  # type: ignore[attr-defined]  # the refusals below are expected
    _register_in_ui(page, _email("intruder"), name="Intruder")
    token_b = _token(page)
    for path in (
        f"/api/jobs/{job_id}/status",
        f"/api/jobs/{job_id}/result",
        f"/api/jobs/{job_id}/export/txt",
        f"/api/jobs/{job_id}/audio",
        f"/api/sessions/{session_id}",
    ):
        assert _api_status(page, path, token_b) in (401, 403, 404), f"B could open {path}"
        assert _api_status(page, path, None) in (401, 403, 404), f"a visitor could open {path}"

    # B's own account history stays empty.
    page.locator("#open-auth-btn").click()
    expect(page.locator("#portal-kpi-jobs-count")).to_have_text("0")


def test_progress_survives_a_dropped_connection_and_server_errors(
    open_page: Callable[..., Page], audio_files: dict
) -> None:
    """Before, a single failed status check stopped the progress for good, with the job still running."""
    page = open_page("/?lang=es")
    page.errors.expect(r"503|ERR_FAILED|Failed to load resource")  # type: ignore[attr-defined]
    failures = {"left": 3}

    def flaky(route: Route) -> None:
        if failures["left"] == 0:
            route.continue_()
            return
        failures["left"] -= 1
        if failures["left"] == 2:
            route.abort("failed")
        else:
            route.fulfill(status=503, content_type="text/html", body="<html>Bad gateway</html>")

    page.route("**/api/jobs/*/status", flaky)
    _go_studio(page)
    _upload(page, audio_files["entrevista"])
    _transcribe_and_wait(page)
    assert failures["left"] == 0
    expect(page.locator("#alert-box")).not_to_contain_text("JSON")
    expect(page.locator("#progress-box")).to_be_visible()


def test_status_gone_after_a_restart_still_shows_the_result(open_page: Callable[..., Page], audio_files: dict) -> None:
    page = open_page("/?lang=es")
    page.errors.expect(r"404")  # type: ignore[attr-defined]
    page.route("**/api/jobs/*/status", lambda route: route.fulfill(status=404, json={"detail": "Trabajo no encontrado."}))
    results = {"calls": 0}

    def wait_for_result(route: Route) -> None:
        results["calls"] += 1
        route.continue_()

    page.route("**/api/jobs/*/result", wait_for_result)
    _go_studio(page)
    _upload(page, audio_files["entrevista"])
    page.locator("#transcribe-btn").click()
    expect(page.locator("#progress-box")).to_be_hidden(timeout=JOB_TIMEOUT_MS)
    expect(page.locator("#transcribe-btn")).to_be_enabled()
    assert results["calls"] == 1


def test_expired_link_says_so(open_page: Callable[..., Page], live_server: str, audio_files: dict) -> None:
    from app.services.job_manager import job_manager

    email = _email("expired")
    reg = httpx.post(
        f"{live_server}/api/auth/register", json={"email": email, "password": PASSWORD, "full_name": "Owner"}
    ).json()
    auth = {"Authorization": f"Bearer {reg['access_token']}"}
    with open(audio_files["entrevista"], "rb") as fh:
        up = httpx.post(
            f"{live_server}/api/upload", headers=auth, files=[("files", ("a.wav", fh, "audio/wav"))], timeout=30
        )
    job = httpx.post(
        f"{live_server}/api/transcribe?sync=true", headers=auth, timeout=60,
        json={"session_id": up.json()["session_id"], "file_order": [f["file_id"] for f in up.json()["files"]]},
    ).json()["job_id"]
    job_manager.get_job_result(job).expires_at = "2020-01-01T00:00:00+00:00"

    page = open_page("/?lang=es")
    page.errors.expect(r"410")  # type: ignore[attr-defined]
    page.evaluate("(token) => localStorage.setItem('apex_vox_token', token)", reg["access_token"])
    page.goto(f"/?lang=es&job={job}")
    expect(page.locator("#alert-box")).to_contain_text("venció")
    expect(page.locator("#result-container")).to_be_hidden()
    page.goto(f"/?lang=en&job={job}")
    expect(page.locator("#alert-box")).to_contain_text("expired")


def test_link_to_a_job_still_running_follows_it(open_page: Callable[..., Page], audio_files: dict, live_server: str) -> None:
    page = open_page("/?lang=es")
    answers = {"result": 0}

    def still_running_once(route: Route) -> None:
        answers["result"] += 1
        if answers["result"] == 1:
            route.fulfill(status=202, json={"detail": "El trabajo aún está en estado 'processing' (40%)."})
        else:
            route.continue_()

    _go_studio(page)
    _upload(page, audio_files["entrevista"])
    page.route("**/api/jobs/*/result", still_running_once)
    _transcribe_and_wait(page)
    assert answers["result"] >= 2
