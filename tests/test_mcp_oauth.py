"""Conector MCP con OAuth 2.1 (PKCE) para ChatGPT / Claude, y app web instalable."""

import base64
import hashlib
import secrets
import uuid
from urllib.parse import parse_qs, urlparse

from starlette.testclient import TestClient

from app.main import app
from app.models.schemas import ApexSummaReport, CalendarTaskItem, DiarizedSegment, TranscriptionResult
from app.services.job_manager import job_manager
from app.services.supabase_service import supabase_service

REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _user(client: TestClient, pro: bool = False) -> dict:
    res = client.post("/api/auth/register", json={
        "email": f"mcp_{uuid.uuid4().hex[:8]}@apexvox.ai", "password": "longpassword1", "full_name": "MCP"})
    assert res.status_code == 200, res.text
    profile = res.json()
    if pro:
        supabase_service.activate_paid_period(profile["user_id"], f"MCPTEST-{profile['user_id'][:8]}", "USD", "test")
    return profile


def _meeting(user_id: str, text: str) -> str:
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    result = TranscriptionResult(
        job_id=job_id, user_id=user_id, total_duration_formatted="00:10:00", detected_speakers_count=2,
        segments=[
            DiarizedSegment(id=0, start=0, end=5, speaker="Ana", text=text, start_formatted="00:00:00",
                            end_formatted="00:00:05", source_file="a.wav", file_order_index=0),
            DiarizedSegment(id=1, start=5, end=9, speaker="Luis", text="De acuerdo, lo reviso.",
                            start_formatted="00:00:05", end_formatted="00:00:09", source_file="a.wav", file_order_index=0),
        ],
        full_text=text,
        summa_report=ApexSummaReport(
            job_id=job_id, generated_at="2026-11-02T10:00:00+00:00", executive_summary="Se aprobó el presupuesto.",
            calendar_tasks=[CalendarTaskItem(task_id="t1", title="Enviar contrato", assignee="Luis", due_date="2026-11-10")],
        ),
    )
    with job_manager._lock:
        job_manager._results[job_id] = result
    supabase_service.save_transcription_record({
        "job_id": job_id, "user_id": user_id, "title": "Comité de presupuesto",
        "total_duration_formatted": "00:10:00", "detected_speakers_count": 2,
        "created_at": "2026-11-02T10:00:00+00:00", "expires_at": None,
    })
    return job_id


def _connect(client: TestClient, profile: dict) -> dict:
    """Flujo completo: registro dinámico -> autorizar con la sesión web -> token con PKCE."""
    reg = client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT]})
    assert reg.status_code == 201, reg.text
    client_id = reg.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "xyz",
              "code_challenge": challenge, "code_challenge_method": "S256", "resource": "http://testserver/mcp"}
    page = client.get("/oauth/authorize", params=params)
    assert page.status_code == 200 and "Apex Vox" in page.text and "Claude" in page.text
    decision = client.post("/oauth/authorize/decision", json={"params": params, "approve": True},
                           headers={"Authorization": f"Bearer {profile['access_token']}"})
    assert decision.status_code == 200, decision.text
    q = parse_qs(urlparse(decision.json()["redirect_to"]).query)
    assert q["state"] == ["xyz"]
    bad = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                             "client_id": client_id, "redirect_uri": REDIRECT, "code_verifier": "x" * 50})
    assert bad.status_code == 400  # el código ya se consumió con un verifier inválido
    # Nuevo código para el intercambio válido
    decision = client.post("/oauth/authorize/decision", json={"params": params, "approve": True},
                           headers={"Authorization": f"Bearer {profile['access_token']}"})
    code = parse_qs(urlparse(decision.json()["redirect_to"]).query)["code"][0]
    tok = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                             "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    tokens = tok.json()
    tokens["client_id"] = client_id
    return tokens


def _rpc(client: TestClient, token: str, method: str, params=None, rid=1):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                       headers={"Authorization": f"Bearer {token}"})


def test_metadata_and_unauthorized_challenge() -> None:
    client = TestClient(app)
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"].endswith("/mcp") and prm["authorization_servers"]
    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["registration_endpoint"].endswith("/oauth/register")
    res = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert res.status_code == 401
    assert "resource_metadata=" in res.headers["www-authenticate"]
    assert client.post("/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]}).status_code == 400


def test_full_oauth_flow_and_tools_for_pro_user() -> None:
    client = TestClient(app)
    owner = _user(client, pro=True)
    job_id = _meeting(owner["user_id"], "Aprobamos el presupuesto de marketing.")
    tokens = _connect(client, owner)
    at = tokens["access_token"]

    init = _rpc(client, at, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}).json()
    assert init["result"]["serverInfo"]["name"] == "apex-vox"
    assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                       headers={"Authorization": f"Bearer {at}"}).status_code == 202
    names = {t["name"] for t in _rpc(client, at, "tools/list").json()["result"]["tools"]}
    assert names == {"list_meetings", "search_meetings", "get_meeting_transcript", "get_meeting_summary", "get_action_items"}

    listed = _rpc(client, at, "tools/call", {"name": "list_meetings", "arguments": {}}).json()["result"]
    assert "Comité de presupuesto" in listed["content"][0]["text"]
    found = _rpc(client, at, "tools/call", {"name": "search_meetings", "arguments": {"query": "presupuesto"}}).json()["result"]
    assert "[00:00:00] Ana" in found["content"][0]["text"]
    transcript = _rpc(client, at, "tools/call", {"name": "get_meeting_transcript", "arguments": {"meeting_id": job_id}}).json()["result"]
    assert "Luis: De acuerdo" in transcript["content"][0]["text"] and transcript["isError"] is False
    summary = _rpc(client, at, "tools/call", {"name": "get_meeting_summary", "arguments": {"meeting_id": job_id}}).json()["result"]
    assert "Se aprobó el presupuesto" in summary["content"][0]["text"]
    tasks = _rpc(client, at, "tools/call", {"name": "get_action_items", "arguments": {}}).json()["result"]
    assert "Enviar contrato" in tasks["content"][0]["text"]

    # Renovación con rotación: el token de renovación viejo deja de servir
    ref = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                             "client_id": tokens["client_id"]})
    assert ref.status_code == 200
    again = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                               "client_id": tokens["client_id"]})
    assert again.status_code == 400

    conns = client.get("/api/mcp/connections", headers={"Authorization": f"Bearer {owner['access_token']}"}).json()
    assert [c["client_name"] for c in conns["connections"]] == ["Claude"]
    client.delete("/api/mcp/connections", headers={"Authorization": f"Bearer {owner['access_token']}"})
    assert _rpc(client, ref.json()["access_token"], "tools/list").status_code == 401


def test_users_only_see_their_meetings_and_free_plan_has_no_summary() -> None:
    client = TestClient(app)
    owner = _user(client, pro=True)
    private_job = _meeting(owner["user_id"], "Dato confidencial del dueño.")
    other = _user(client)  # plan gratis
    at = _connect(client, other)["access_token"]

    leak = _rpc(client, at, "tools/call", {"name": "get_meeting_transcript", "arguments": {"meeting_id": private_job}}).json()["result"]
    assert leak["isError"] is True and "confidencial" not in leak["content"][0]["text"]
    search = _rpc(client, at, "tools/call", {"name": "search_meetings", "arguments": {"query": "confidencial"}}).json()["result"]
    assert "confidencial" not in search["content"][0]["text"].replace("«confidencial»", "")

    own_job = _meeting(other["user_id"], "Reunión del plan gratis.")
    summary = _rpc(client, at, "tools/call", {"name": "get_meeting_summary", "arguments": {"meeting_id": own_job}}).json()["result"]
    assert summary["isError"] is True and "Apex Pro" in summary["content"][0]["text"]


def test_pwa_manifest_icons_and_service_worker() -> None:
    client = TestClient(app)
    m = client.get("/manifest.webmanifest").json()
    assert m["name"] == "Apex Vox" and m["short_name"] == "Apex Vox"
    assert m["start_url"].startswith("/") and m["scope"] == "/" and m["id"] == "/"
    sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert ("192x192", "any") in sizes and ("512x512", "any") in sizes and ("512x512", "maskable") in sizes
    for icon in m["icons"]:
        assert client.get(icon["src"]).status_code == 200
    html = client.get("/").text
    assert 'rel="apple-touch-icon"' in html and 'apple-mobile-web-app-title" content="Apex Vox"' in html
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "fetch" in sw.text
