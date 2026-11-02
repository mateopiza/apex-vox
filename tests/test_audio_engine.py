"""
Unit Test Suite for Audio Processing Engine
-------------------------------------------
Covers metadata probing, windowed silence detection, payload slicing (<= 25MB),
fallback splitting, sequence ordering, timeline arithmetic, and timestamp formatting.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
import pytest

from app.config import settings
from app.services.audio_engine import (
    AudioChunkError,
    AudioChunkInfo,
    AudioDependencyError,
    AudioEngineError,
    AudioMetadata,
    AudioProbeError,
    ProbedAudio,
    SilenceDetectionError,
    align_whisper_segments,
    calculate_split_points,
    calculate_timeline_offsets,
    check_ffmpeg_installed,
    chunk_audio_file,
    detect_silences,
    extract_chunk,
    find_split_point,
    format_srt_timestamp,
    format_timestamp,
    format_timestamp_hhmmss,
    format_timestamp_srt,
    format_timestamp_vtt,
    format_vtt_timestamp,
    prepare_audio_sequence,
    probe_audio,
    process_audio_sequence,
    require_ffmpeg,
)
from tests.fixtures.audio_generator import (
    convert_audio_format,
    create_corrupt_audio_file,
    create_synthetic_wav,
)


# =============================================================================
# Pytest Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def session_audio_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("session_audio")


@pytest.fixture(scope="session")
def sample_wav_5s(session_audio_dir: Path) -> Path:
    path = session_audio_dir / "sample_5s.wav"
    return create_synthetic_wav(path, [(5.0, 440.0)])


@pytest.fixture(scope="session")
def sample_wav_with_silence(session_audio_dir: Path) -> Path:
    # 2s tone + 1s silence (midpoint 2.5s) + 2s tone + 1.2s silence (midpoint 5.6s) + 2s tone = 8.2s
    path = session_audio_dir / "calibrated_silences.wav"
    return create_synthetic_wav(
        path,
        [(2.0, 440.0), (1.0, 0.0), (2.0, 880.0), (1.2, 0.0), (2.0, 440.0)],
    )


@pytest.fixture(scope="session")
def sample_mp3_5s(sample_wav_5s: Path, session_audio_dir: Path) -> Path:
    path = session_audio_dir / "sample_5s.mp3"
    return convert_audio_format(sample_wav_5s, path, "mp3")


@pytest.fixture(scope="session")
def sample_ogg_5s(sample_wav_5s: Path, session_audio_dir: Path) -> Path:
    path = session_audio_dir / "sample_5s.ogg"
    return convert_audio_format(sample_wav_5s, path, "ogg")


@pytest.fixture
def temp_audio_dir(tmp_path: Path) -> Path:
    out = tmp_path / "audio_out"
    out.mkdir(parents=True, exist_ok=True)
    return out


# =============================================================================
# 1. Audio Probing Tests
# =============================================================================
class TestAudioProbing:
    def test_probe_valid_wav(self, sample_wav_5s: Path) -> None:
        meta = probe_audio(sample_wav_5s)
        assert meta.format_name == "wav"
        assert meta.duration_sec == pytest.approx(5.0, abs=0.05)
        assert meta.channels == 1
        assert meta.sample_rate == 16000
        assert meta.size_bytes > 0
        assert not meta.is_over_25mb

        probed = meta.to_probed_audio(file_id="wav_1")
        assert probed.file_id == "wav_1"
        assert probed.filename == sample_wav_5s.name
        assert probed.format == "wav"
        assert probed.duration_sec == pytest.approx(5.0, abs=0.05)
        assert not probed.is_over_25mb

    def test_probe_valid_mp3(self, sample_mp3_5s: Path) -> None:
        meta = probe_audio(sample_mp3_5s)
        assert meta.format_name == "mp3"
        assert meta.duration_sec == pytest.approx(5.0, abs=0.15)
        assert meta.sample_rate == 16000

    def test_probe_valid_ogg(self, sample_ogg_5s: Path) -> None:
        meta = probe_audio(sample_ogg_5s)
        assert "ogg" in meta.format_name or "vorbis" in meta.format_name
        assert meta.duration_sec == pytest.approx(5.0, abs=0.05)

    def test_probe_stereo_wav(self, temp_audio_dir: Path) -> None:
        stereo_path = create_synthetic_wav(
            temp_audio_dir / "stereo.wav", [(2.0, 440.0)], channels=2, sample_rate=44100
        )
        meta = probe_audio(stereo_path)
        assert meta.channels == 2
        assert meta.sample_rate == 44100

    def test_probe_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            probe_audio(Path("/nonexistent/audio/track.mp3"))

    def test_probe_empty_file(self, temp_audio_dir: Path) -> None:
        empty_file = create_corrupt_audio_file(temp_audio_dir / "empty.wav", "empty")
        with pytest.raises((ValueError, AudioEngineError)):
            probe_audio(empty_file)

    def test_probe_corrupt_file(self, temp_audio_dir: Path) -> None:
        corrupt_file = create_corrupt_audio_file(temp_audio_dir / "corrupt.wav", "garbage")
        with pytest.raises((ValueError, AudioEngineError)):
            probe_audio(corrupt_file)

    def test_probe_missing_ffprobe_binary(
        self, sample_wav_5s: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_which = shutil.which
        monkeypatch.setattr(
            "shutil.which",
            lambda cmd, *args, **kwargs: None if cmd == "ffprobe" else real_which(cmd, *args, **kwargs),
        )
        with pytest.raises(RuntimeError, match="ffprobe"):
            probe_audio(sample_wav_5s)


# =============================================================================
# 2. Silence Detection Tests
# =============================================================================
class TestSilenceDetection:
    def test_detect_silences_known_intervals(self, sample_wav_with_silence: Path) -> None:
        # File has known silences at [2.0, 3.0] and [5.0, 6.2]
        silences = detect_silences(
            sample_wav_with_silence, noise_threshold_db=-30.0, min_silence_sec=0.5
        )
        assert len(silences) == 2
        # Silence 1
        assert silences[0][0] == pytest.approx(2.0, abs=0.1)
        assert silences[0][1] == pytest.approx(3.0, abs=0.1)
        # Silence 2
        assert silences[1][0] == pytest.approx(5.0, abs=0.1)
        assert silences[1][1] == pytest.approx(6.2, abs=0.1)

    def test_detect_silences_continuous_tone_no_silence(self, sample_wav_5s: Path) -> None:
        silences = detect_silences(sample_wav_5s, noise_threshold_db=-30.0, min_silence_sec=0.5)
        assert silences == []

    def test_detect_silences_all_silence(self, temp_audio_dir: Path) -> None:
        silent_path = create_synthetic_wav(temp_audio_dir / "silent.wav", [(4.0, 0.0)])
        silences = detect_silences(silent_path, noise_threshold_db=-30.0, min_silence_sec=0.5)
        assert len(silences) == 1
        assert silences[0][0] == pytest.approx(0.0, abs=0.1)
        assert silences[0][1] == pytest.approx(4.0, abs=0.1)

    def test_detect_silences_subthreshold_duration_ignored(self, temp_audio_dir: Path) -> None:
        # Pause is 0.3s, threshold is 0.5s -> should not be reported
        short_pause = create_synthetic_wav(
            temp_audio_dir / "short_pause.wav", [(2.0, 440.0), (0.3, 0.0), (2.0, 440.0)]
        )
        silences = detect_silences(short_pause, min_silence_sec=0.5)
        assert silences == []

    def test_detect_silences_leading_and_trailing(self, temp_audio_dir: Path) -> None:
        edge_silence = create_synthetic_wav(
            temp_audio_dir / "edge_silence.wav", [(1.5, 0.0), (2.0, 440.0), (1.5, 0.0)]
        )
        silences = detect_silences(edge_silence, min_silence_sec=0.5)
        assert len(silences) == 2
        assert silences[0][0] == pytest.approx(0.0, abs=0.1)
        assert silences[1][1] == pytest.approx(5.0, abs=0.1)


# =============================================================================
# 3. Windowed Split Point Selection Algorithm Tests
# =============================================================================
class TestWindowedSplitPointSelection:
    def test_split_point_exact_silence_at_target(self) -> None:
        # Target split is 600.0s. Silence interval [598.0, 602.0] midpoint 600.0s
        silences = [(598.0, 602.0)]
        split = find_split_point(
            current_start=0.0, target_duration=600.0, silences=silences, window_sec=45.0
        )
        assert split == pytest.approx(600.0)

    def test_split_point_selects_closest_silence_midpoint(self) -> None:
        # Target 600.0s. Silence 1 midpoint 580.0 (delta 20). Silence 2 midpoint 605.0 (delta 5).
        silences = [(578.0, 582.0), (604.0, 606.0), (620.0, 624.0)]
        split = find_split_point(
            current_start=0.0, target_duration=600.0, silences=silences, window_sec=45.0
        )
        assert split == pytest.approx(605.0)

    def test_split_point_expanded_window_fallback(self) -> None:
        # Target 600.0s. Standard window 45.0s (555..645).
        # Silence at [660, 664] midpoint 662.0 (delta 62.0 > 45.0, but <= 90.0)
        silences = [(660.0, 664.0)]
        split = find_split_point(
            current_start=0.0,
            target_duration=600.0,
            silences=silences,
            window_sec=45.0,
            max_window_sec=90.0,
        )
        assert split == pytest.approx(662.0)

    def test_split_point_hard_fallback_when_no_silence_found(self) -> None:
        # No silences anywhere
        split = find_split_point(
            current_start=0.0, target_duration=600.0, silences=[], window_sec=45.0
        )
        assert split == pytest.approx(600.0)

    def test_split_point_ignores_silences_behind_cursor(self) -> None:
        # Cursor at 1000.0, target 1600.0. Silence at 800.0 must be ignored
        silences = [(795.0, 805.0), (1598.0, 1602.0)]
        split = find_split_point(
            current_start=1000.0, target_duration=600.0, silences=silences, window_sec=45.0
        )
        assert split == pytest.approx(1600.0)


# =============================================================================
# 4. Audio Chunking & Slicing Tests (<= 25MB limit)
# =============================================================================
class TestAudioChunkingAndExtraction:
    def test_chunk_file_under_target_single_chunk(
        self, sample_wav_5s: Path, temp_audio_dir: Path
    ) -> None:
        chunks = chunk_audio_file(
            sample_wav_5s,
            output_dir=temp_audio_dir,
            target_duration_sec=10.0,
        )
        assert len(chunks) == 1
        c = chunks[0]
        assert c.chunk_index == 0
        assert c.local_start_sec == 0.0
        assert c.local_end_sec == pytest.approx(5.0, abs=0.1)
        assert c.global_start_sec == 0.0
        assert c.global_end_sec == pytest.approx(5.0, abs=0.1)
        assert c.file_path.exists()
        limit = (
            getattr(settings, "GROQ_PAYLOAD_LIMIT_BYTES", 25 * 1024 * 1024)
            if settings
            else 25 * 1024 * 1024
        )
        assert c.file_path.stat().st_size <= limit

    def test_chunk_file_multi_chunk_on_silence_midpoints(self, temp_audio_dir: Path) -> None:
        # 18.0s audio with silences at ~5.0s, ~10.0s, ~15.0s
        long_wav = create_synthetic_wav(
            temp_audio_dir / "long_track.wav",
            [
                (4.5, 440.0),
                (1.0, 0.0),  # silence midpoint = 5.0s
                (4.0, 880.0),
                (1.0, 0.0),  # silence midpoint = 10.0s
                (4.0, 440.0),
                (1.0, 0.0),  # silence midpoint = 15.0s
                (2.5, 880.0),
            ],
        )
        chunks = chunk_audio_file(
            long_wav,
            output_dir=temp_audio_dir,
            target_duration_sec=5.0,
            window_sec=1.0,
        )
        assert len(chunks) == 4
        # Verify continuity across chunk boundaries
        for i in range(1, len(chunks)):
            assert chunks[i].local_start_sec == pytest.approx(chunks[i - 1].local_end_sec, abs=0.01)
            assert chunks[i].global_start_sec == pytest.approx(chunks[i - 1].global_end_sec, abs=0.01)

        assert chunks[0].local_start_sec == 0.0
        assert chunks[-1].local_end_sec == pytest.approx(18.0, abs=0.2)

        # Verify all extracted chunk files exist and are valid MP3s
        limit = (
            getattr(settings, "GROQ_PAYLOAD_LIMIT_BYTES", 25 * 1024 * 1024)
            if settings
            else 25 * 1024 * 1024
        )
        for c in chunks:
            assert c.file_path.exists()
            assert c.file_path.stat().st_size <= limit

    def test_chunk_file_fallback_continuous_noise(self, temp_audio_dir: Path) -> None:
        # 12.0s continuous tone with 0 silence
        tone_wav = create_synthetic_wav(temp_audio_dir / "unbroken.wav", [(12.0, 440.0)])
        chunks = chunk_audio_file(
            tone_wav,
            output_dir=temp_audio_dir,
            target_duration_sec=4.0,
        )
        assert len(chunks) == 3
        assert chunks[0].local_end_sec == pytest.approx(4.0, abs=0.1)
        assert chunks[1].local_end_sec == pytest.approx(8.0, abs=0.1)
        assert chunks[2].local_end_sec == pytest.approx(12.0, abs=0.1)

    def test_chunk_payload_size_strictly_under_25mb(
        self, sample_wav_5s: Path, temp_audio_dir: Path
    ) -> None:
        chunks = chunk_audio_file(sample_wav_5s, output_dir=temp_audio_dir, target_duration_sec=5.0)
        assert len(chunks) == 1
        # At 16kHz mono 64kbps MP3, 5s is ~40KB, vastly under 25MB (26,214,400 bytes)
        file_size = chunks[0].file_path.stat().st_size
        assert file_size < 25 * 1024 * 1024
        assert file_size > 0

    def test_calculate_split_points_short_audio(self) -> None:
        splits = calculate_split_points(duration_sec=500.0, silences=[], target_sec=600.0)
        assert splits == [(0.0, 500.0)]

    def test_calculate_split_points_zero_or_negative(self) -> None:
        assert calculate_split_points(duration_sec=0.0, silences=[]) == []
        assert calculate_split_points(duration_sec=-10.0, silences=[]) == []


# =============================================================================
# 5. Sequence Ordering & Continuous Timeline Math Tests
# =============================================================================
class TestSequenceOrderingAndTimelineMath:
    def test_calculate_timeline_offsets_single_file(self) -> None:
        offsets = calculate_timeline_offsets([15.5])
        assert offsets == [0.0]

    def test_calculate_timeline_offsets_multiple_files(self) -> None:
        durations = [10.0, 25.5, 12.0]
        offsets = calculate_timeline_offsets(durations)
        assert offsets == [0.0, 10.0, 35.5]

    def test_sequence_reordering_adjusts_timeline_deterministically(self) -> None:
        durations_orig = [10.0, 30.0]  # Order [A, B]
        durations_rev = [30.0, 10.0]   # Order [B, A]
        assert calculate_timeline_offsets(durations_orig) == [0.0, 10.0]
        assert calculate_timeline_offsets(durations_rev) == [0.0, 30.0]

    def test_process_audio_sequence_continuous_timestamps(self, temp_audio_dir: Path) -> None:
        f1 = create_synthetic_wav(temp_audio_dir / "f1.wav", [(6.0, 440.0)])
        f2 = create_synthetic_wav(temp_audio_dir / "f2.wav", [(4.0, 880.0)])

        probed, chunks = process_audio_sequence(
            [f1, f2],
            output_dir=temp_audio_dir,
            target_duration_sec=3.0,
        )
        assert len(probed) == 2
        assert chunks[0].global_start_sec == pytest.approx(0.0)
        assert chunks[0].file_sequence_index == 0

        # Verify strict monotonicity across entire sequence
        for i in range(1, len(chunks)):
            assert chunks[i].global_start_sec >= chunks[i - 1].global_end_sec
            assert chunks[i].chunk_index == i

        # Total duration equals sum of individual durations
        total_dur = sum(p.duration_sec for p in probed)
        assert chunks[-1].global_end_sec == pytest.approx(total_dur, abs=0.2)

    def test_process_audio_sequence_empty_input(self, temp_audio_dir: Path) -> None:
        probed, chunks = process_audio_sequence([], output_dir=temp_audio_dir)
        assert probed == []
        assert chunks == []

    def test_prepare_audio_sequence_helper(self, temp_audio_dir: Path) -> None:
        f1 = create_synthetic_wav(temp_audio_dir / "prep1.wav", [(3.0, 440.0)])
        chunks = prepare_audio_sequence([f1], output_dir=temp_audio_dir, target_duration_sec=5.0)
        assert len(chunks) == 1
        assert chunks[0].file_path.exists()
        assert chunks[0].local_end_sec == pytest.approx(3.0, abs=0.1)


# =============================================================================
# 6. Timestamp Alignment & Formatting Tests
# =============================================================================
class TestTimestampAlignmentAndFormatting:
    def test_align_whisper_segments_applies_chunk_global_offset(self) -> None:
        chunk = AudioChunkInfo(
            chunk_index=2,
            file_path=Path("/tmp/chunk2.mp3"),
            local_start_sec=0.0,
            local_end_sec=300.0,
            global_start_sec=1200.0,
            global_end_sec=1500.0,
            source_file_name="meeting_part2.mp3",
            file_sequence_index=1,
        )
        raw_segments = [
            {"id": 0, "start": 1.25, "end": 4.50, "text": "Good morning everyone."},
            {"id": 1, "start": 5.20, "end": 9.00, "text": "Let us begin the discussion."},
        ]
        aligned = align_whisper_segments(raw_segments, chunk)
        assert aligned[0]["global_start"] == pytest.approx(1201.25)
        assert aligned[0]["global_end"] == pytest.approx(1204.50)
        assert aligned[0]["source_file"] == "meeting_part2.mp3"
        assert aligned[0]["file_order_index"] == 1
        assert aligned[0]["pause_before"] == pytest.approx(1.25)

        assert aligned[1]["global_start"] == pytest.approx(1205.20)
        assert aligned[1]["global_end"] == pytest.approx(1209.00)
        # Pause between 1204.50 and 1205.20 = 0.70s
        assert aligned[1]["pause_before"] == pytest.approx(0.70)

    def test_format_timestamp_hhmmss(self) -> None:
        assert format_timestamp_hhmmss(0.0) == "00:00:00"
        assert format_timestamp_hhmmss(59.9) == "00:00:59"
        assert format_timestamp_hhmmss(60.0) == "00:01:00"
        assert format_timestamp_hhmmss(3599.0) == "00:59:59"
        assert format_timestamp_hhmmss(3665.4) == "01:01:05"
        assert format_timestamp_hhmmss(86400.0) == "24:00:00"

    def test_format_timestamp_srt(self) -> None:
        assert format_timestamp_srt(0.0) == "00:00:00,000"
        assert format_timestamp_srt(65.523) == "00:01:05,523"
        assert format_timestamp_srt(3665.008) == "01:01:05,008"

    def test_format_timestamp_srt_millisecond_rollover_bug(self) -> None:
        # 65.9999s rounds millis to 1000 -> must roll over to 66s cleanly
        formatted = format_timestamp_srt(65.9999)
        assert formatted == "00:01:06,000"
        assert "1000" not in formatted

    def test_format_timestamp_vtt(self) -> None:
        assert format_timestamp_vtt(65.523) == "00:01:05.523"

    def test_format_timestamp_negative_clamping(self) -> None:
        assert format_timestamp_hhmmss(-10.0) == "00:00:00"
        assert format_timestamp_srt(-5.0) == "00:00:00,000"
        assert format_timestamp_vtt(-5.0) == "00:00:00.000"

    def test_formatting_aliases(self) -> None:
        assert format_timestamp(125.0) == format_timestamp_hhmmss(125.0)
        assert format_srt_timestamp(125.45) == format_timestamp_srt(125.45)
        assert format_vtt_timestamp(125.45) == format_timestamp_vtt(125.45)


# =============================================================================
# 7. Subprocess Resilience & Mocking Tests
# =============================================================================
class TestSubprocessResilienceAndMocking:
    def test_probe_handles_ffprobe_called_process_error(
        self, sample_wav_5s: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffprobe", stderr=b"Simulated demuxer crash")

        monkeypatch.setattr("subprocess.run", fake_run)
        with pytest.raises(AudioEngineError, match="demuxer crash"):
            probe_audio(sample_wav_5s)

    def test_detect_silences_handles_ffmpeg_error(
        self, sample_wav_5s: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"Filter graph error")

        monkeypatch.setattr("subprocess.run", fake_run)
        with pytest.raises(AudioEngineError, match="Filter graph"):
            detect_silences(sample_wav_5s)

    def test_extract_chunk_handles_ffmpeg_error(
        self, sample_wav_5s: Path, temp_audio_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"Encoder error")

        monkeypatch.setattr("subprocess.run", fake_run)
        with pytest.raises(AudioChunkError, match="Encoder error"):
            extract_chunk(sample_wav_5s, temp_audio_dir / "err.mp3", 0.0, 2.0)

    def test_extract_chunk_invalid_range_raises(
        self, sample_wav_5s: Path, temp_audio_dir: Path
    ) -> None:
        with pytest.raises(ValueError, match="strictly greater"):
            extract_chunk(sample_wav_5s, temp_audio_dir / "inv.mp3", 5.0, 2.0)

    def test_dependency_checks(self) -> None:
        # In container, both ffmpeg and ffprobe must be present
        assert check_ffmpeg_installed() is True
        require_ffmpeg()  # Must not raise
