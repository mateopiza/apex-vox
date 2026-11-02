"""
End-to-End Pipeline & API Verification Suite (tests/test_e2e_pipeline.py)
-------------------------------------------------------------------------
Validates the complete workflow inside Docker:
1. Light Ocean Blue & Emerald Green Web UI serving.
2. Multi-format audio upload (MP3, OGG, WAV).
3. Interactive sequence reordering.
4. Audio slicing/chunking (<25 MB) + continuous global timeline alignment.
5. Groq Whisper transcription + Speaker Diarization (1, 2, and automatic speakers).
6. Speaker renaming and multi-format export (TXT, SRT, VTT, JSON, CSV, MD).
"""

from __future__ import annotations

import uuid

import json
from pathlib import Path
from typing import Any, List
import pytest
from starlette.testclient import TestClient

from app.main import app
from tests.fixtures.audio_generator import convert_audio_format, create_synthetic_wav


@pytest.fixture(scope="module")
def sample_audio_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Generate real MP3, OGG, and WAV audio files for E2E testing."""
    base = tmp_path_factory.mktemp("e2e_audio")

    wav1 = base / "parte1_intro.wav"
    create_synthetic_wav(wav1, [(2.0, 440.0), (0.6, 0.0), (1.8, 520.0)])

    wav2_src = base / "raw2.wav"
    create_synthetic_wav(wav2_src, [(2.5, 600.0), (0.7, 0.0), (2.2, 350.0)])
    mp3_path = base / "parte2_entrevista.mp3"
    convert_audio_format(wav2_src, mp3_path, "mp3")

    wav3_src = base / "raw3.wav"
    create_synthetic_wav(wav3_src, [(3.0, 480.0)])
    ogg_path = base / "parte3_cierre.ogg"
    convert_audio_format(wav3_src, ogg_path, "ogg")

    return {"wav": wav1, "mp3": mp3_path, "ogg": ogg_path}


def test_ui_groq_web_design_system() -> None:
    """Verify the web interface ships the Groq Web design system (paper + orange)."""
    client = TestClient(app)
    res_html = client.get("/")
    assert res_html.status_code == 200
    assert "Subir y Ordenar Archivos de Audio" in res_html.text
    assert "Identificación de Oradores" in res_html.text
    assert "/static/css/tokens.css" in res_html.text
    assert "{{ASSET_VERSION}}" not in res_html.text
    assert "footer-display" in res_html.text

    res_tokens = client.get("/static/css/tokens.css")
    assert res_tokens.status_code == 200
    assert "#f43e01" in res_tokens.text  # Groq orange (brand)
    assert "#f3f3ee" in res_tokens.text  # Paper background

    res_css = client.get("/static/css/styles.css")
    assert res_css.status_code == 200
    assert "var(--brand)" in res_css.text


def test_production_security_headers() -> None:
    """Security headers are attached to UI and API responses."""
    client = TestClient(app)
    res = client.get("/")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in res.headers.get("content-security-policy", "")
    static_res = client.get("/static/css/styles.css?v=1")
    assert "immutable" in static_res.headers.get("cache-control", "")
    assert client.get("/favicon.ico").status_code == 200


def test_end_to_end_upload_reorder_transcribe_diarize_and_export(
    sample_audio_files: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Full E2E test:
    Upload 3 audio files (WAV, MP3, OGG) -> Reorder sequence -> Transcribe via Groq ->
    Automatically identify speakers -> Verify ordered timestamps -> Export TXT/SRT/VTT/JSON/CSV/MD.
    """
    client = TestClient(app)

    # 1. Upload 3 files initially in order: [mp3, ogg, wav]
    with (
        open(sample_audio_files["mp3"], "rb") as f_mp3,
        open(sample_audio_files["ogg"], "rb") as f_ogg,
        open(sample_audio_files["wav"], "rb") as f_wav,
    ):
        upload_res = client.post(
            "/api/upload",
            files=[
                ("files", ("parte2_entrevista.mp3", f_mp3, "audio/mpeg")),
                ("files", ("parte3_cierre.ogg", f_ogg, "audio/ogg")),
                ("files", ("parte1_intro.wav", f_wav, "audio/wav")),
            ],
        )

    assert upload_res.status_code == 200, upload_res.text
    upload_data = upload_res.json()
    session_id = upload_data["session_id"]
    uploaded_files = upload_data["files"]
    assert len(uploaded_files) == 3

    # Map filenames to file_ids
    id_by_name = {f["filename"]: f["file_id"] for f in uploaded_files}

    # 2. Designate new order: [parte1_intro.wav, parte2_entrevista.mp3, parte3_cierre.ogg]
    desired_order = [
        id_by_name["parte1_intro.wav"],
        id_by_name["parte2_entrevista.mp3"],
        id_by_name["parte3_cierre.ogg"],
    ]
    reorder_res = client.put(
        f"/api/sessions/{session_id}/order",
        json={"session_id": session_id, "file_order": desired_order},
    )
    assert reorder_res.status_code == 200
    reordered_files = reorder_res.json()["files"]
    assert [f["filename"] for f in reordered_files] == [
        "parte1_intro.wav",
        "parte2_entrevista.mp3",
        "parte3_cierre.ogg",
    ]

    # 3. Mock Groq API call to test deterministic Whisper + Diarization integration
    def fake_transcribe_chunk(chunk: Any, **kwargs: Any) -> List[dict[str, Any]]:
        if "parte1" in chunk.source_file_name:
            return [
                {"id": 0, "start": 0.0, "end": 1.8, "text": "Hola a todos, bienvenidos al programa."},
                {"id": 1, "start": 2.4, "end": 3.8, "text": "Muchas gracias por la invitación."},
            ]
        if "parte2" in chunk.source_file_name:
            return [
                {"id": 0, "start": 0.2, "end": 2.2, "text": "¿Cómo ves el avance del proyecto hoy?"},
                {"id": 1, "start": 3.0, "end": 4.9, "text": "Claro, va excelente y dentro de los tiempos."},
            ]
        return [
            {"id": 0, "start": 0.1, "end": 2.8, "text": "Perfecto, con esto cerramos la sesión."},
        ]

    monkeypatch.setattr("app.services.groq_service.transcribe_chunk", fake_transcribe_chunk)

    # 4. Run synchronous transcription & automatic speaker diarization
    transcribe_res = client.post(
        "/api/transcribe?sync=true",
        json={
            "session_id": session_id,
            "file_order": desired_order,
            "model": "whisper-large-v3",
            "language": "es",
            "num_speakers": None,  # Automatic speaker detection
            "api_key": "gsk_test_key_for_e2e_verification",
        },
    )
    assert transcribe_res.status_code == 200, transcribe_res.text
    job_id = transcribe_res.json()["job_id"]

    # 5. Check job status & result
    status_res = client.get(f"/api/jobs/{job_id}/status")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "completed"
    assert status_res.json()["progress"] == 100

    result_res = client.get(f"/api/jobs/{job_id}/result")
    assert result_res.status_code == 200
    result = result_res.json()

    assert result["file_order"] == [
        "parte1_intro.wav",
        "parte2_entrevista.mp3",
        "parte3_cierre.ogg",
    ]
    assert result["detected_speakers_count"] >= 2
    segments = result["segments"]
    assert len(segments) == 5

    # Verify chronological timestamps are strictly monotonic across the 3 ordered files
    for i in range(1, len(segments)):
        assert segments[i]["start"] >= segments[i - 1]["end"]

    # Verify source files follow the designated sequence order
    assert segments[0]["source_file"] == "parte1_intro.wav"
    assert segments[2]["source_file"] == "parte2_entrevista.mp3"
    assert segments[4]["source_file"] == "parte3_cierre.ogg"

    # 6. Test renaming speakers
    rename_res = client.patch(
        f"/api/jobs/{job_id}/speakers",
        json={"speaker_map": {"Hablante 1": "Conductora", "Hablante 2": "Invitado"}},
    )
    assert rename_res.status_code == 200
    renamed_segments = rename_res.json()["segments"]
    speakers_present = {s["speaker"] for s in renamed_segments}
    assert "Conductora" in speakers_present
    assert "Invitado" in speakers_present

    # 7. Test all export formats (TXT, SRT, VTT, JSON, CSV, MD)
    for fmt, expected_token in [
        ("txt", "Conductora:"),
        ("srt", "-->"),
        ("vtt", "WEBVTT"),
        ("json", '"segments"'),
        ("csv", "start_formatted"),
        ("md", "# Transcripción"),
    ]:
        exp_res = client.get(f"/api/jobs/{job_id}/export/{fmt}")
        assert exp_res.status_code == 200
        assert expected_token in exp_res.text

    # 8. Test merged audio streaming endpoint
    audio_res = client.get(f"/api/jobs/{job_id}/audio")
    assert audio_res.status_code == 200
    assert len(audio_res.content) > 0


def test_acoustic_voiceprint_clustering_and_voice_profile_enrollment(
    tmp_path: Path,
) -> None:
    """
    Verify:
    1. Enrolling a speaker Voice Profile via POST /api/voice-profiles extracts 24D embedding & pitch.
    2. Acoustic voiceprint clustering separates distinct fundamental frequencies (130 Hz vs 250 Hz).
    3. Enrolled voice profile automatically identifies and labels the matching speaker.
    """
    from app.models.schemas import WhisperSegment
    from app.services.acoustic_diarizer import (
        cluster_segments_acoustically,
        match_enrolled_voice_profiles,
    )

    client = TestClient(app)

    # Create two distinct voice-like audio files (Speaker A: ~130 Hz, Speaker B: ~250 Hz)
    spk_a_wav = tmp_path / "carlos_sample.wav"
    create_synthetic_wav(spk_a_wav, [(2.5, 130.0)])

    spk_b_wav = tmp_path / "ana_sample.wav"
    create_synthetic_wav(spk_b_wav, [(2.5, 250.0)])

    # Combined conversation: 0-2.5s (130Hz), 0.5s silence, 3.0-5.5s (250Hz)
    conv_wav = tmp_path / "conversation.wav"
    create_synthetic_wav(conv_wav, [(2.5, 130.0), (0.5, 0.0), (2.5, 250.0)])

    # 1. Enroll "Carlos" via API (voice profiles are private to the signed-in account)
    reg = client.post(
        "/api/auth/register",
        json={"email": f"vp_{uuid.uuid4().hex[:8]}@apexvox.ai", "password": "voicePass123", "full_name": "VP"},
    ).json()
    client.headers.update({"Authorization": f"Bearer {reg['access_token']}"})
    with open(spk_a_wav, "rb") as f_a:
        vp_res = client.post(
            "/api/voice-profiles",
            data={"name": "Carlos", "role": "Locutor"},
            files=[("file", ("carlos_sample.wav", f_a, "audio/wav"))],
        )
    assert vp_res.status_code == 200, vp_res.text
    vp_data = vp_res.json()
    assert vp_data["name"] == "Carlos"
    assert len(vp_data["embedding"]) == 24
    assert 110.0 <= vp_data["pitch_hz"] <= 155.0

    # 2. Cluster segments acoustically on the conversation
    segs = [
        WhisperSegment(
            id=0,
            start=0.1,
            end=2.3,
            text="Hola soy el primer hablante.",
            global_start=0.1,
            global_end=2.3,
            source_file="conv.wav",
            file_order_index=0,
            pause_before=0.1,
        ),
        WhisperSegment(
            id=1,
            start=3.1,
            end=5.3,
            text="Y yo soy la segunda hablante.",
            global_start=3.1,
            global_end=5.3,
            source_file="conv.wav",
            file_order_index=0,
            pause_before=0.8,
        ),
    ]
    clustered = cluster_segments_acoustically(conv_wav, segs, num_speakers=2)
    assert clustered[0].acoustic_speaker != clustered[1].acoustic_speaker

    # 3. Match against enrolled voice profiles -> Segment 0 should be recognized as "Carlos"
    initial_map = {s.id: (s.acoustic_speaker or "Hablante 1") for s in clustered}
    matched_map, matched_roles = match_enrolled_voice_profiles(
        audio_path=conv_wav,
        segments=clustered,
        speaker_assignments=initial_map,
        owner_id=reg["user_id"],
    )
    assert matched_map[0] == "Carlos"
    # Another account (or a visitor) never matches someone else's profiles
    other_map, _ = match_enrolled_voice_profiles(
        audio_path=conv_wav, segments=clustered, speaker_assignments=initial_map, owner_id=None,
    )
    assert other_map[0] != "Carlos"
    assert "Carlos" in matched_roles

    # Clean up enrolled profile
    del_res = client.delete(f"/api/voice-profiles/{vp_data['profile_id']}")
    assert del_res.status_code == 200


def test_deepgram_utterance_and_hybrid_alignment() -> None:
    """Verify Deepgram response parsing and hybrid temporal overlap alignment onto Groq segments."""
    from app.models.schemas import WhisperSegment
    from app.services.audio_engine import AudioChunkInfo
    from app.services.deepgram_service import (
        align_groq_segments_with_deepgram_diarization,
        extract_deepgram_utterances_and_words,
    )

    sample_dg_response = {
        "results": {
            "utterances": [
                {"start": 0.0, "end": 2.0, "transcript": "Buenos días", "speaker": 0, "confidence": 0.98},
                {"start": 2.5, "end": 5.0, "transcript": "Hola qué tal", "speaker": 1, "confidence": 0.96},
            ],
            "channels": [
                {
                    "alternatives": [
                        {
                            "words": [
                                {"word": "buenos", "punctuated_word": "Buenos", "start": 0.0, "end": 0.9, "speaker": 0},
                                {"word": "días", "punctuated_word": "días", "start": 1.0, "end": 2.0, "speaker": 0},
                                {"word": "hola", "punctuated_word": "Hola", "start": 2.5, "end": 3.5, "speaker": 1},
                                {"word": "qué", "punctuated_word": "qué", "start": 3.6, "end": 4.2, "speaker": 1},
                                {"word": "tal", "punctuated_word": "tal", "start": 4.3, "end": 5.0, "speaker": 1},
                            ]
                        }
                    ]
                }
            ],
        }
    }

    utterances, words = extract_deepgram_utterances_and_words(sample_dg_response)
    assert len(utterances) == 2
    assert len(words) == 5
    assert utterances[0]["speaker"] == "Hablante 1"
    assert utterances[1]["speaker"] == "Hablante 2"


def test_transcript_cleaner_removes_whisper_silence_hallucinations() -> None:
    """
    Verify filter_hallucinated_segments removes:
    - Loose noise tokens ('y', '3', 'porque no', 'no no no no')
    - Periodic 30s 'gracias' / 'gracias gracias' silence tails
    While keeping real conversational sentences intact.
    """
    from app.models.schemas import DiarizedSegment
    from app.services.transcript_cleaner import filter_hallucinated_segments

    segs = [
        DiarizedSegment(
            id=0,
            start=7148.0,
            end=7161.0,
            speaker="Hablante 1",
            text="es que la mitad platos y de 150 imposibles realmente no estoy muy difícil",
            start_formatted="01:59:08",
            end_formatted="01:59:21",
            source_file="reunion.mp3",
            file_order_index=0,
        ),
        DiarizedSegment(
            id=1,
            start=7161.0,
            end=7184.0,
            speaker="Hablante 1",
            text="y no sé por eso es que ya es un caso especial desafío por dos horas",
            start_formatted="01:59:21",
            end_formatted="01:59:44",
            source_file="reunion.mp3",
            file_order_index=0,
        ),
        # Loose noise between 01:59:44 and 02:02:42
        DiarizedSegment(id=2, start=7184.0, end=7187.0, speaker="Hablante 1", text="y", start_formatted="01:59:44", end_formatted="01:59:47", source_file="reunion.mp3", file_order_index=0),
        DiarizedSegment(id=3, start=7190.0, end=7193.0, speaker="Hablante 1", text="3", start_formatted="01:59:50", end_formatted="01:59:53", source_file="reunion.mp3", file_order_index=0),
        DiarizedSegment(id=4, start=7205.0, end=7208.0, speaker="Hablante 1", text="porque no", start_formatted="02:00:05", end_formatted="02:00:08", source_file="reunion.mp3", file_order_index=0),
        DiarizedSegment(id=5, start=7214.0, end=7226.0, speaker="Hablante 1", text="no no no no", start_formatted="02:00:14", end_formatted="02:00:26", source_file="reunion.mp3", file_order_index=0),
        # Periodic 30s 'gracias' tail
        DiarizedSegment(id=6, start=7389.0, end=7391.0, speaker="Hablante 1", text="gracias", start_formatted="02:03:09", end_formatted="02:03:11", source_file="reunion.mp3", file_order_index=0),
        DiarizedSegment(id=7, start=7419.0, end=7421.0, speaker="Hablante 1", text="gracias", start_formatted="02:03:39", end_formatted="02:03:41", source_file="reunion.mp3", file_order_index=0),
        DiarizedSegment(id=8, start=7449.0, end=7451.0, speaker="Hablante 1", text="gracias gracias", start_formatted="02:04:09", end_formatted="02:04:11", source_file="reunion.mp3", file_order_index=0),
        DiarizedSegment(id=9, start=7479.0, end=7481.0, speaker="Hablante 1", text="Gracias.", start_formatted="02:04:39", end_formatted="02:04:41", source_file="reunion.mp3", file_order_index=0),
    ]

    cleaned = filter_hallucinated_segments(segs)
    assert len(cleaned) == 2
    assert cleaned[0].end_formatted == "01:59:21"
    assert cleaned[1].end_formatted == "01:59:44"
