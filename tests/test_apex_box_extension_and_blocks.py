"""
Apex Box — Unlimited Block Recording (10h+ Constant RAM), Chrome Extension (MV3),
Mobile Web App (PWA), Live Timestamped Notes & Official Groq Badge Verification Suite
(tests/test_apex_box_extension_and_blocks.py)
-------------------------------------------------------------------------------------
Verifies:
1. Mathematical block calculation (`GET /api/box/optimal-config`) for 10+ hours continuous
   recording with constant O(1) RAM (~1.03 MB/block at 180s / 3 min, ~2.06 MB peak RAM,
   99.6% RAM savings vs monolithic recording).
2. Continuous multi-block upload & incremental live transcription (`POST /api/box/sessions`,
   `POST /api/box/sessions/{id}/blocks`) for both:
   - Modo Reunión Presencial / App Web Celular (`mode="presencial"`, `device_type="mobile_pwa"`)
   - Modo Reunión Virtual (`mode="virtual"`, `platform="google_meet" / "zoom" / "ms_teams"`)
3. Live timestamped note-taking (`POST`, `PUT`, `DELETE /api/box/sessions/{id}/notes`)
   during recording (`nota`, `acuerdo`, `tarea`, `alerta`) and finalization
   (`POST /api/box/sessions/{id}/finalize`) weaving notes into `ApexSummaReport`
   (objectives, callouts, calendar tasks) and `MinutesDocumentResponse` (Acta Oficial).
4. Chrome Extension Manifest V3 (`extension/manifest.json`, `/api/box/extension.zip`),
   exact PNG icon dimensions (`16x16`, `48x48`, `128x128`), `CHROMEWEBSTORE.md`,
   and Mobile PWA manifest (`/manifest.webmanifest`).
5. Official Groq Badge (`https://console.groq.com/powered-by-groq-light.svg`) integrated
   across the Web UI and Chrome Extension Side Panel.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
from pathlib import Path
from typing import Any
from starlette.testclient import TestClient

from app.main import app
from tests.fixtures.audio_generator import create_synthetic_wav


def test_optimal_block_math_for_10h_constant_ram() -> None:
    """
    Verify the mathematical calculation for optimal block duration (180s / 3 minutes)
    that prevents speech cuts and keeps browser/mobile RAM constant across 10+ hours.
    """
    client = TestClient(app)
    res = client.get("/api/box/optimal-config?target_hours=10")
    assert res.status_code == 200
    data = res.json()

    assert data["optimal_block_seconds"] == 180
    assert data["optimal_block_minutes"] == 3.0
    assert data["recommended_bitrate_bps"] == 48000
    assert 0.9 <= data["single_block_size_mb"] <= 1.2
    assert data["total_blocks_for_target"] == 200
    assert data["peak_client_ram_mb"] <= 2.5
    assert data["unblocked_ram_10h_mb"] >= 200.0
    assert data["ram_savings_pct"] >= 99.0
    assert data["rotation_strategy"] == "dual_recorder_zero_gap_ebml"
    assert "3.0 min" in data["explanation_es"]


def test_continuous_multi_block_recording_and_live_notes_to_summa_and_minutes(
    tmp_path: Path,
) -> None:
    """
    Simulate a multi-block continuous recording session (both Virtual Zoom/Meet/Teams
    and Presencial/Mobile modes), taking live timestamped notes across blocks, and
    finalizing into a continuous transcript + Apex Summa report + Official Minutes.
    """
    client = TestClient(app)

    # 1. Create a Virtual Meeting session (Google Meet / Zoom / Teams)
    create_res = client.post(
        "/api/box/sessions",
        json={
            "title": "Comité Técnico 10 Horas — Google Meet",
            "mode": "virtual",
            "platform": "google_meet",
            "language": "es",
            "diarization_engine": "Mc-Lewis",
            "block_duration_sec": 180,
            "device_type": "chrome_extension",
            "plan": "pro",
        },
    )
    assert create_res.status_code == 200
    session_data = create_res.json()
    box_session_id = session_data["box_session_id"]
    assert session_data["mode"] == "virtual"
    assert session_data["platform"] == "google_meet"
    assert session_data["block_duration_sec"] == 180

    # 2. Upload 3 consecutive audio blocks simulating continuous block rotation
    for block_idx in range(3):
        wav_path = create_synthetic_wav(
            tmp_path / f"block_{block_idx}.wav",
            segments=[(1.2, 440.0 + block_idx * 80.0), (0.6, 0.0), (1.2, 520.0 + block_idx * 60.0)],
        )
        with wav_path.open("rb") as f:
            blk_res = client.post(
                f"/api/box/sessions/{box_session_id}/blocks",
                files={"file": (f"block_{block_idx:04d}.wav", f, "audio/wav")},
                data={
                    "block_index": str(block_idx),
                    "duration_hint_sec": "180.0",
                    "transcribe_immediately": "true",
                },
            )
        assert blk_res.status_code == 200
        blk_payload = blk_res.json()
        assert blk_payload["total_blocks_received"] == block_idx + 1
        assert len(blk_payload["new_segments"]) >= 1
        assert blk_payload["block"]["transcribed"] is True

    # 3. Take live timestamped notes across categories ('acuerdo', 'tarea', 'alerta', 'nota')
    note_acuerdo = client.post(
        f"/api/box/sessions/{box_session_id}/notes",
        json={
            "text": "Se aprueba rotación de bloques cada 180 segundos para grabaciones de 10 horas.",
            "timestamp_sec": 125.0,
            "category": "acuerdo",
            "author": "Dra. Elena Gómez",
        },
    )
    assert note_acuerdo.status_code == 200
    assert "02:05" in note_acuerdo.json()["timestamp_formatted"]

    note_tarea = client.post(
        f"/api/box/sessions/{box_session_id}/notes",
        json={
            "text": "Publicar extensión Chrome MV3 y PWA móvil antes del viernes.",
            "timestamp_sec": 310.0,
            "category": "tarea",
            "author": "Ing. Carlos Ruiz",
        },
    )
    assert note_tarea.status_code == 200

    note_alerta = client.post(
        f"/api/box/sessions/{box_session_id}/notes",
        json={
            "text": "Revisar permisos de audio compartido en Microsoft Teams.",
            "timestamp_sec": 420.0,
            "category": "alerta",
            "author": "Dra. Elena Gómez",
        },
    )
    assert note_alerta.status_code == 200

    note_temp = client.post(
        f"/api/box/sessions/{box_session_id}/notes",
        json={
            "text": "Nota temporal para probar edición y borrado.",
            "timestamp_sec": 450.0,
            "category": "nota",
            "author": "Participante",
        },
    )
    assert note_temp.status_code == 200
    temp_note_id = note_temp.json()["note_id"]

    # Update and then delete the temporary note
    upd_res = client.put(
        f"/api/box/sessions/{box_session_id}/notes/{temp_note_id}",
        json={
            "text": "Nota actualizada",
            "timestamp_sec": 455.0,
            "category": "idea",
            "author": "Participante",
        },
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["text"] == "Nota actualizada"

    del_res = client.delete(f"/api/box/sessions/{box_session_id}/notes/{temp_note_id}")
    assert del_res.status_code == 200
    assert len(del_res.json()) == 3

    # 4. Finalize the session and verify continuous transcript + Apex Summa + Minutes
    fin_res = client.post(
        f"/api/box/sessions/{box_session_id}/finalize",
        json={
            "generate_minutes": True,
            "minutes_type": "comite",
            "organization_name": "Apex Engineering Board",
        },
    )
    assert fin_res.status_code == 200
    fin_data = fin_res.json()

    assert fin_data["status"] == "completed"
    assert fin_data["total_blocks_processed"] == 3
    result = fin_data["result"]
    assert len(result["segments"]) >= 3
    assert len(result["live_notes"]) == 3

    # Verify timestamps are monotonically non-decreasing across blocks
    starts = [seg["start"] for seg in result["segments"]]
    assert starts == sorted(starts)

    # Verify live notes were woven into Apex Summa (Objectives, Callouts, Calendar Tasks)
    summa = result["summa_report"]
    assert any("180 segundos" in obj for obj in summa["objectives"])
    assert any("Microsoft Teams" in c["description"] for c in summa["callouts"])
    assert any("Publicar extensión Chrome MV3" in t["title"] for t in summa["calendar_tasks"])

    # Verify Official Minutes (Acta) includes the live notes section
    minutes = fin_data["minutes_document"]
    assert minutes is not None
    assert "Se aprueba rotación de bloques cada 180 segundos" in minutes["markdown_content"]


def test_chrome_extension_mv3_package_icons_and_official_groq_badge() -> None:
    """
    Verify:
    - `/api/box/extension.zip` returns a valid MV3 Chrome Extension zip archive.
    - `extension/manifest.json` follows Manifest V3 best practices (`sidePanel`, `offscreen`,
      `tabCapture`, `desktopCapture`, `storage`, `alarms`).
    - Icons (`16x16`, `48x48`, `128x128`) have exact matching pixel dimensions in their PNG IHDR headers.
    - Official Groq badge (`https://console.groq.com/powered-by-groq-light.svg`) is embedded in both
      the Web Application (`index.html`) and the Chrome Extension Side Panel (`sidepanel.html`).
    - Mobile Web App manifest (`/manifest.webmanifest`) is served properly.
    """
    client = TestClient(app)

    # 1. Verify Official Groq Badge in main Web UI
    home_res = client.get("/")
    assert home_res.status_code == 200
    html = home_res.text
    assert 'href="https://groq.com"' in html
    assert 'src="https://console.groq.com/powered-by-groq-light.svg"' in html
    assert 'alt="Powered by Groq for fast inference."' in html
    assert 'id="view-box"' in html
    assert 'id="nav-box-btn"' in html

    # 2. Verify PWA Web App Manifest for Mobile Mode
    pwa_res = client.get("/manifest.webmanifest")
    assert pwa_res.status_code == 200
    pwa_data = pwa_res.json()
    assert "Apex" in pwa_data["name"]
    assert pwa_data["display"] == "standalone"

    # 3. Verify `/api/box/extension.zip` downloadable MV3 extension bundle
    zip_res = client.get("/api/box/extension.zip")
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as zf:
        names = set(zf.namelist())
        expected_files = {
            "manifest.json",
            "service-worker.js",
            "offscreen/offscreen.html",
            "offscreen/offscreen.js",
            "sidepanel/sidepanel.html",
            "sidepanel/sidepanel.css",
            "sidepanel/sidepanel.js",
            "content/meeting-detector.js",
            "content/meeting-detector.css",
            "icons/icon-16.png",
            "icons/icon-48.png",
            "icons/icon-128.png",
        }
        assert expected_files.issubset(names)

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["manifest_version"] == 3
        assert "sidePanel" in manifest["permissions"]
        assert "offscreen" in manifest["permissions"]
        assert "tabCapture" in manifest["permissions"]
        assert "desktopCapture" in manifest["permissions"]
        assert "storage" in manifest["permissions"]

        sidepanel_html = zf.read("sidepanel/sidepanel.html").decode("utf-8")
        assert "https://console.groq.com/powered-by-groq-light.svg" in sidepanel_html
        assert "Powered by Groq for fast inference." in sidepanel_html

        # Verify PNG icon dimensions match declared sizes (16x16, 48x48, 128x128)
        for size in (16, 48, 128):
            png_bytes = zf.read(f"icons/icon-{size}.png")
            assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
            width, height = struct.unpack(">II", png_bytes[16:24])
            assert (width, height) == (size, size)

    # 4. Verify CHROMEWEBSTORE.md exists and documents permission justifications
    cws_path = Path(__file__).resolve().parent.parent / "CHROMEWEBSTORE.md"
    assert cws_path.exists()
    cws_text = cws_path.read_text(encoding="utf-8")
    assert "tabCapture" in cws_text
    assert "offscreen" in cws_text
    assert "Privacy Policy" in cws_text
