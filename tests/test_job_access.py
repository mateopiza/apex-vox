"""Cada trabajo solo lo ve su dueño; las descargas usan un token firmado que caduca."""

from __future__ import annotations

import uuid

from starlette.testclient import TestClient

from app.api import deps
from app.main import app
from app.models.schemas import TranscriptionResult
from app.services.job_manager import job_manager


def _account() -> TestClient:
    client = TestClient(app)
    res = client.post(
        "/api/auth/register",
        json={"email": f"t_{uuid.uuid4().hex[:8]}@example.com", "password": "longpassword1", "full_name": "Tester"},
    )
    assert res.status_code == 200, res.text
    client.headers.update({"Authorization": f"Bearer {res.json()['access_token']}"})
    client.user_id = res.json()["user_id"]
    return client


def _job_for(client: TestClient) -> str:
    user_id = client.user_id
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    job_manager._results[job_id] = TranscriptionResult(job_id=job_id, user_id=user_id, full_text="hola")
    return job_id


def test_other_accounts_and_visitors_cannot_read_a_job() -> None:
    owner, stranger, visitor = _account(), _account(), TestClient(app)
    job_id = _job_for(owner)

    mine = owner.get(f"/api/jobs/{job_id}/result")
    assert mine.status_code == 200 and mine.json()["media_token"]

    for client in (stranger, visitor):
        assert client.get(f"/api/jobs/{job_id}/result").status_code == 404
        assert client.get(f"/api/jobs/{job_id}/export/txt").status_code == 404
        assert client.get(f"/api/jobs/{job_id}/summa").status_code == 404
        assert client.patch(f"/api/jobs/{job_id}/speakers", json={"speaker_map": {"A": "B"}}).status_code == 404
        assert client.post(f"/api/jobs/{job_id}/minutes", json={"template_type": "consejo"}).status_code == 404


def test_signed_download_links() -> None:
    owner, visitor = _account(), TestClient(app)
    job_id = _job_for(owner)
    token = owner.get(f"/api/jobs/{job_id}/result").json()["media_token"]

    # El enlace firmado sirve para descargar sin cabecera Authorization...
    assert visitor.get(f"/api/jobs/{job_id}/export/txt", params={"t": token}).status_code == 200
    # ...pero no abre el resultado completo ni sirve para otro trabajo.
    assert visitor.get(f"/api/jobs/{job_id}/result", params={"t": token}).status_code == 404
    other = _job_for(owner)
    assert visitor.get(f"/api/jobs/{other}/export/txt", params={"t": token}).status_code == 404

    # Firma alterada o caducada: rechazado.
    exp, sig = token.split(".", 1)
    assert visitor.get(f"/api/jobs/{job_id}/export/txt", params={"t": f"{exp}.{'0' * len(sig)}"}).status_code == 404
    expired = deps.media_token(f"job:{job_id}", ttl=-10)
    assert visitor.get(f"/api/jobs/{job_id}/export/txt", params={"t": expired}).status_code == 404


def test_unknown_job_is_404() -> None:
    assert _account().get("/api/jobs/job_doesnotexist/status").status_code == 404


def test_recording_upload_session_belongs_to_its_account() -> None:
    """Las pistas de una grabación de Apex Box no se pueden escuchar sin ser el dueño."""
    from app.models.schemas import BoxCreateSessionRequest
    from app.services.apex_box import apex_box_manager

    owner = _account()
    state = apex_box_manager.create_session(BoxCreateSessionRequest(user_id=owner.user_id))
    upload_id = apex_box_manager._sessions[state.box_session_id].upload_session_id
    assert job_manager.session_owned_by(upload_id, owner.user_id)
    assert not job_manager.session_owned_by(upload_id, "otra_cuenta")
    assert TestClient(app).get(f"/api/sessions/{upload_id}").status_code == 404
