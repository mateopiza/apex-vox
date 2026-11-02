"""
Empirical Stress Test Suite for Audio Processing Engine (Milestone 2.1)
-----------------------------------------------------------------------
Adversarial and empirical verification covering:
1. Multi-minute windowed silence splitting (alignment with silence intervals).
2. Pure unbroken continuous loud audio (Tier 3 deterministic hard split fallback).
3. Payload constraints (< 25MB Groq API limit, 16kHz mono MP3 format validation).
4. High-density silence torture test (250+ silence intervals).
5. Fractional sub-second duration and timeline continuity.
6. Multi-file sequence ordering and reverse reordering.
7. Special characters, brackets, and spaces in filenames.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from app.services.audio_engine import (
    chunk_audio_file,
    detect_silences,
    probe_audio,
    process_audio_sequence,
)
from tests.fixtures.audio_generator import (
    create_synthetic_wav,
)

GROQ_LIMIT_BYTES = 25 * 1024 * 1024  # 26,214,400 bytes


class TestEmpiricalAudioStress:
    """Empirical adversarial challenge suite for Milestone 2."""

    def test_stress_windowed_silence_splitting_multi_minute(self, tmp_path: Path) -> None:
        """
        Synthesize a 30-minute (1800s, ~57.6MB) audio file with calibrated silence pauses.
        Verify that chunk_audio_file splits precisely at silence intervals, maintaining
        full continuity, MP3 16kHz mono format, and size strictly < 25MB.
        """
        wav_path = tmp_path / "multi_minute_speech_sim.wav"
        # Layout:
        # Segment 1: Sound 0.0s -> 595.0s (595s)
        # Silence 1: Silence 595.0s -> 605.0s (10s, midpoint 600.0s)
        # Segment 2: Sound 605.0s -> 1180.0s (575s)
        # Silence 2: Silence 1180.0s -> 1184.0s (4s, midpoint 1182.0s)
        # Segment 3: Sound 1184.0s -> 1800.0s (616s)
        create_synthetic_wav(
            wav_path,
            [
                (595.0, 440.0),
                (10.0, 0.0),    # Pause 1: midpoint = 600.0s
                (575.0, 880.0),
                (4.0, 0.0),     # Pause 2: midpoint = 1182.0s
                (616.0, 440.0),
            ],
            sample_rate=16000,
            channels=1,
        )

        meta = probe_audio(wav_path)
        assert meta.duration_sec == pytest.approx(1800.0, abs=0.1)
        assert meta.size_bytes > GROQ_LIMIT_BYTES  # ~57.6MB, verifies >25MB input
        assert meta.is_over_25mb is True

        out_dir = tmp_path / "chunks_silence"
        chunks = chunk_audio_file(wav_path, out_dir, target_duration_sec=600.0)

        # Expected: 3 chunks
        # Chunk 0: 0.0 -> 600.0 (Silence 1 midpoint)
        # Chunk 1: 600.0 -> 1182.0 (Silence 2 midpoint)
        # Chunk 2: 1182.0 -> 1800.0 (Remaining 618s <= 600*1.25 merged tail)
        assert len(chunks) == 3

        # Verify alignment with silence intervals
        assert chunks[0].local_start_sec == 0.0
        assert chunks[0].local_end_sec == pytest.approx(600.0, abs=0.1)
        assert 595.0 <= chunks[0].local_end_sec <= 605.0  # Inside Silence 1

        assert chunks[1].local_start_sec == chunks[0].local_end_sec
        assert chunks[1].local_end_sec == pytest.approx(1182.0, abs=0.1)
        assert 1180.0 <= chunks[1].local_end_sec <= 1184.0  # Inside Silence 2

        assert chunks[2].local_start_sec == chunks[1].local_end_sec
        assert chunks[2].local_end_sec == pytest.approx(1800.0, abs=0.1)

        # Verify global timeline continuity
        for i in range(1, len(chunks)):
            assert chunks[i].global_start_sec == chunks[i - 1].global_end_sec

        # Verify format and payload constraints on all extracted chunks
        for idx, chunk in enumerate(chunks):
            assert chunk.file_path.exists()
            size = chunk.file_path.stat().st_size
            assert 0 < size < GROQ_LIMIT_BYTES, f"Chunk {idx} size {size} violates <25MB limit"

            chunk_meta = probe_audio(chunk.file_path)
            assert chunk_meta.format == "mp3", f"Chunk {idx} format is not mp3"
            assert chunk_meta.sample_rate == 16000, f"Chunk {idx} sample rate is not 16kHz"
            assert chunk_meta.channels == 1, f"Chunk {idx} is not mono"

    def test_stress_continuous_loud_audio_tier3_hard_split(self, tmp_path: Path) -> None:
        """
        Synthesize a 30-minute (1800s) continuous unbroken 440Hz sine wave (zero silences).
        Verify Tier 3 hard split executes cleanly without crash, hang, or infinite loop,
        splitting into deterministic 600s chunks under 25MB.
        """
        wav_path = tmp_path / "continuous_tone_1800s.wav"
        create_synthetic_wav(wav_path, [(1800.0, 440.0)], sample_rate=16000, channels=1)

        meta = probe_audio(wav_path)
        assert meta.duration_sec == pytest.approx(1800.0, abs=0.1)

        # Silence detector must confirm 0 silences
        silences = detect_silences(wav_path)
        assert silences == []

        out_dir = tmp_path / "chunks_continuous"
        chunks = chunk_audio_file(wav_path, out_dir, target_duration_sec=600.0)

        # Tier 3 hard splits at exactly 600.0s intervals
        assert len(chunks) == 3
        assert chunks[0].local_start_sec == 0.0
        assert chunks[0].local_end_sec == pytest.approx(600.0, abs=0.1)

        assert chunks[1].local_start_sec == pytest.approx(600.0, abs=0.1)
        assert chunks[1].local_end_sec == pytest.approx(1200.0, abs=0.1)

        assert chunks[2].local_start_sec == pytest.approx(1200.0, abs=0.1)
        assert chunks[2].local_end_sec == pytest.approx(1800.0, abs=0.1)

        for chunk in chunks:
            assert chunk.file_path.exists()
            assert 0 < chunk.file_path.stat().st_size < GROQ_LIMIT_BYTES
            cm = probe_audio(chunk.file_path)
            assert cm.format == "mp3"
            assert cm.sample_rate == 16000
            assert cm.channels == 1

    def test_stress_large_payload_short_duration_under_25mb(self, tmp_path: Path) -> None:
        """
        Synthesize a 48kHz stereo WAV file exceeding 30MB but with short duration (160s).
        Verify that chunk_audio_file encodes to 16kHz mono MP3 strictly < 25MB (~1.3MB).
        """
        wav_path = tmp_path / "large_payload_short.wav"
        # 160s * 48000 samples/s * 2 channels * 2 bytes/sample = 30,720,000 bytes (~30.7MB)
        create_synthetic_wav(
            wav_path, [(160.0, 440.0)], sample_rate=48000, channels=2
        )

        meta = probe_audio(wav_path)
        assert meta.size_bytes > GROQ_LIMIT_BYTES
        assert meta.is_over_25mb is True

        out_dir = tmp_path / "chunks_large_short"
        chunks = chunk_audio_file(wav_path, out_dir, target_duration_sec=600.0)

        assert len(chunks) == 1
        c = chunks[0]
        assert c.file_path.exists()
        size = c.file_path.stat().st_size
        # Sliced MP3 at 16kHz mono 64k is ~1.3MB
        assert 0 < size < GROQ_LIMIT_BYTES
        assert size < 2 * 1024 * 1024  # Well below 2MB

        cm = probe_audio(c.file_path)
        assert cm.format == "mp3"
        assert cm.sample_rate == 16000
        assert cm.channels == 1

    def test_stress_high_density_silences_torture(self, tmp_path: Path) -> None:
        """
        Synthesize a 1000s track with 250 alternating sound and silence segments (every 2s).
        Verify silence detection and chunking handle dense intervals without degradation,
        snapping to the closest silence midpoint near 600s.
        """
        wav_path = tmp_path / "torture_density.wav"
        # 250 repetitions of (2.0s tone, 2.0s silence) = 1000.0s
        segs = [(2.0, 440.0), (2.0, 0.0)] * 250
        create_synthetic_wav(wav_path, segs, sample_rate=16000, channels=1)

        silences = detect_silences(wav_path)
        assert len(silences) == 250

        out_dir = tmp_path / "chunks_torture"
        chunks = chunk_audio_file(wav_path, out_dir, target_duration_sec=600.0)

        # 1000s with target 600s:
        # Near 600s, silence is at [598.0, 600.0], midpoint = 599.0s.
        # Remaining: 1000 - 599 = 401s <= 600 * 1.25 (750s) -> merged into Chunk 1.
        assert len(chunks) == 2
        assert chunks[0].local_end_sec == pytest.approx(599.0, abs=0.1)
        assert chunks[1].local_start_sec == chunks[0].local_end_sec
        assert chunks[1].local_end_sec == pytest.approx(1000.0, abs=0.1)

        for c in chunks:
            assert 0 < c.file_path.stat().st_size < GROQ_LIMIT_BYTES
            cm = probe_audio(c.file_path)
            assert cm.format == "mp3"
            assert cm.sample_rate == 16000
            assert cm.channels == 1

    def test_stress_fractional_subsecond_durations(self, tmp_path: Path) -> None:
        """
        Synthesize an audio file with irregular fractional sub-second durations.
        Verify that exact timestamps are preserved with zero floating-point drift.
        """
        wav_path = tmp_path / "fractional.wav"
        create_synthetic_wav(
            wav_path,
            [
                (580.123, 440.0),
                (2.456, 0.0),   # Silence 1: 580.123 -> 582.579, midpoint = 581.351
                (590.789, 880.0),
                (1.500, 0.0),   # Silence 2: 1173.368 -> 1174.868, midpoint = 1174.118
                (198.588, 440.0),
            ],
        )
        meta = probe_audio(wav_path)
        assert meta.duration_sec == pytest.approx(1373.456, abs=0.005)

        out_dir = tmp_path / "chunks_fractional"
        chunks = chunk_audio_file(wav_path, out_dir, target_duration_sec=600.0)

        assert len(chunks) == 3
        assert chunks[0].local_start_sec == 0.0
        assert chunks[0].local_end_sec == pytest.approx(581.351, abs=0.01)

        assert chunks[1].local_start_sec == chunks[0].local_end_sec
        assert chunks[1].local_end_sec == pytest.approx(1174.118, abs=0.01)

        assert chunks[2].local_start_sec == chunks[1].local_end_sec
        assert chunks[2].local_end_sec == pytest.approx(1373.456, abs=0.01)

        # Global timeline continuity
        for i in range(1, len(chunks)):
            assert chunks[i].global_start_sec == chunks[i - 1].global_end_sec
        assert chunks[-1].global_end_sec == pytest.approx(1373.456, abs=0.01)

    def test_stress_multi_file_sequence_ordering_and_reordering(self, tmp_path: Path) -> None:
        """
        Process multiple multi-chunk audio files in user sequence.
        Verify forward and reverse sequence timeline arithmetic, cumulative offsets,
        and monotonic global chunk indexing.
        """
        a = create_synthetic_wav(tmp_path / "track_A.wav", [(35.0, 440.0)])
        b = create_synthetic_wav(tmp_path / "track_B.wav", [(25.0, 880.0)])
        c = create_synthetic_wav(tmp_path / "track_C.wav", [(15.0, 660.0)])

        # Forward sequence: [A (35s), B (25s), C (15s)] -> total 75s
        _probed_fwd, chunks_fwd = process_audio_sequence(
            [a, b, c], tmp_path / "seq_fwd", target_duration_sec=15.0
        )
        assert len(chunks_fwd) == 6
        for idx, chunk in enumerate(chunks_fwd):
            assert chunk.chunk_index == idx
            assert 0 < chunk.file_path.stat().st_size < GROQ_LIMIT_BYTES
        for i in range(1, len(chunks_fwd)):
            assert chunks_fwd[i].global_start_sec == chunks_fwd[i - 1].global_end_sec
        assert chunks_fwd[-1].global_end_sec == pytest.approx(75.0, abs=0.1)

        # Reverse sequence: [C (15s), B (25s), A (35s)] -> total 75s
        _probed_rev, chunks_rev = process_audio_sequence(
            [c, b, a], tmp_path / "seq_rev", target_duration_sec=15.0
        )
        assert len(chunks_rev) == 6
        for idx, chunk in enumerate(chunks_rev):
            assert chunk.chunk_index == idx
            assert 0 < chunk.file_path.stat().st_size < GROQ_LIMIT_BYTES
        for i in range(1, len(chunks_rev)):
            assert chunks_rev[i].global_start_sec == chunks_rev[i - 1].global_end_sec
        assert chunks_rev[-1].global_end_sec == pytest.approx(75.0, abs=0.1)

        # Check track C chunks
        assert chunks_rev[0].source_file_name == "track_C.wav"
        assert chunks_rev[0].file_sequence_index == 0
        assert chunks_rev[0].global_start_sec == 0.0
        assert chunks_rev[0].global_end_sec == pytest.approx(15.0, abs=0.1)

    def test_stress_special_characters_and_spaces_in_filepath(self, tmp_path: Path) -> None:
        """
        Verify robust subprocess handling with filenames containing spaces, parentheses,
        brackets, and hashes.
        """
        complex_name = "audio track (special) [2026] #1 & test.wav"
        wav_path = create_synthetic_wav(tmp_path / complex_name, [(12.0, 440.0)])

        meta = probe_audio(wav_path)
        assert meta.filename == complex_name

        out_dir = tmp_path / "special_chunks"
        chunks = chunk_audio_file(wav_path, out_dir, target_duration_sec=5.0)

        assert len(chunks) == 3
        assert chunks[0].local_end_sec == pytest.approx(5.0, abs=0.1)
        assert chunks[1].local_end_sec == pytest.approx(10.0, abs=0.1)
        assert chunks[2].local_end_sec == pytest.approx(12.0, abs=0.1)
        for chunk in chunks:
            assert chunk.file_path.exists()
            assert 0 < chunk.file_path.stat().st_size < GROQ_LIMIT_BYTES
            cm = probe_audio(chunk.file_path)
            assert cm.format == "mp3"
            assert cm.sample_rate == 16000
            assert cm.channels == 1
