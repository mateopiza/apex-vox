"""
Empirical Verification & Stress Test Suite: Challenger M2.2
============================================================
Adversarial testing of:
1. Heterogeneous multi-audio sequences (MP3, OGG, WAV in arbitrary permutations sigma).
2. Cumulative file timeline offset arithmetic: T_offset(F_i) = sum_{j=1}^{i-1} D_j.
3. Chunk global base calculation and segment alignment to continuous global timeline.
4. Acoustic pause calculation: pause_before = max(0.0, current_start - prev_end).
5. Timestamp formatters (HH:MM:SS, SRT with millisecond rollover, VTT).
6. File stem collision vulnerability analysis across multi-file sequences.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path
import pytest

from app.services.audio_engine import (
    AudioChunkInfo,
    AudioMetadata,
    ProbedAudio,
    align_whisper_segments,
    calculate_split_points,
    calculate_timeline_offsets,
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
)
from tests.fixtures.audio_generator import (
    convert_audio_format,
    create_synthetic_wav,
)


@pytest.fixture(scope="module")
def challenger_audio_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("challenger_audio")
    return out


@pytest.fixture(scope="module")
def heterogeneous_audio_files(challenger_audio_dir: Path) -> dict[str, Path]:
    """Generate 3 distinct audio files in WAV, MP3, and OGG formats with known durations."""
    wav_path = challenger_audio_dir / "track_alpha.wav"
    create_synthetic_wav(wav_path, [(3.2, 440.0)])  # 3.2s tone

    mp3_source = challenger_audio_dir / "temp_beta.wav"
    create_synthetic_wav(mp3_source, [(2.5, 660.0)])  # 2.5s tone
    mp3_path = challenger_audio_dir / "track_beta.mp3"
    convert_audio_format(mp3_source, mp3_path, "mp3")

    ogg_source = challenger_audio_dir / "temp_gamma.wav"
    create_synthetic_wav(ogg_source, [(4.1, 880.0)])  # 4.1s tone
    ogg_path = challenger_audio_dir / "track_gamma.ogg"
    convert_audio_format(ogg_source, ogg_path, "ogg")

    return {"wav": wav_path, "mp3": mp3_path, "ogg": ogg_path}


# =============================================================================
# 1. Heterogeneous Multi-Audio Sequences & Arbitrary Permutations (sigma in S_3)
# =============================================================================
class TestHeterogeneousMultiAudioPermutations:
    """Stress test all 6 permutations of [WAV, MP3, OGG] to verify timeline math."""

    @pytest.mark.parametrize("order_keys", list(itertools.permutations(["wav", "mp3", "ogg"])))
    def test_arbitrary_permutation_sequence_order(
        self,
        heterogeneous_audio_files: dict[str, Path],
        order_keys: tuple[str, ...],
        tmp_path: Path,
    ) -> None:
        sequence_files = [heterogeneous_audio_files[k] for k in order_keys]
        out_dir = tmp_path / f"out_{'_'.join(order_keys)}"
        out_dir.mkdir(parents=True, exist_ok=True)

        probed, chunks = process_audio_sequence(
            file_paths=sequence_files,
            output_dir=out_dir,
            target_duration_sec=10.0,  # Each file fits into 1 chunk
        )

        assert len(probed) == 3
        assert len(chunks) == 3

        # 1. Verify sequence order fidelity
        for i, (key, p, c) in enumerate(zip(order_keys, probed, chunks)):
            assert p.file_id == str(i)
            assert p.filename == sequence_files[i].name
            assert c.file_sequence_index == i
            assert c.source_file_name == sequence_files[i].name
            assert c.chunk_index == i

        # 2. Verify cumulative timeline offsets: T_offset(F_i) = sum_{j=0}^{i-1} D_j
        expected_offset = 0.0
        for i, (p, c) in enumerate(zip(probed, chunks)):
            assert c.global_start_sec == pytest.approx(expected_offset, abs=0.05)
            assert c.global_end_sec == pytest.approx(expected_offset + p.duration_sec, abs=0.1)
            expected_offset += p.duration_sec

        # 3. Verify total global duration equals sum of individual durations
        total_probed_duration = sum(p.duration_sec for p in probed)
        assert chunks[-1].global_end_sec == pytest.approx(total_probed_duration, abs=0.1)

        # 4. Verify all extracted chunks exist, are valid files, and are non-empty
        for c in chunks:
            assert c.file_path.exists()
            assert c.file_path.stat().st_size > 0


# =============================================================================
# 2. Cumulative File Timeline Offset Arithmetic: T_file_offset(F_i) = sum_{j=1}^{i-1} D_j
# =============================================================================
class TestCumulativeTimelineOffsetsArithmetic:
    """Rigorous mathematical oracle tests for timeline offset calculation."""

    def test_empty_durations_returns_empty(self) -> None:
        assert calculate_timeline_offsets([]) == []

    def test_single_file_offset_is_identically_zero(self) -> None:
        assert calculate_timeline_offsets([42.123]) == [0.0]

    def test_two_files_offset_matches_oracle(self) -> None:
        offsets = calculate_timeline_offsets([12.345, 67.890])
        assert offsets == [0.0, 12.345]

    def test_oracle_mathematical_definition(self) -> None:
        durations = [1.234, 5.678, 9.101, 11.121, 3.141]
        oracle_offsets = [round(sum(durations[:i]), 3) for i in range(len(durations))]
        actual_offsets = calculate_timeline_offsets(durations)
        assert actual_offsets == oracle_offsets

    def test_drift_resilience_1000_files(self) -> None:
        """1000 files with fractional durations: test numerical stability."""
        durations = [0.1] * 1000
        offsets = calculate_timeline_offsets(durations)
        assert len(offsets) == 1000
        assert offsets[0] == 0.0
        # 100th element should be offset 99 * 0.1 = 9.9
        assert offsets[99] == pytest.approx(9.9, abs=1e-5)
        # 1000th element should be offset 999 * 0.1 = 99.9
        assert offsets[999] == pytest.approx(99.9, abs=1e-5)

    def test_zero_duration_files_preserve_monotonicity(self) -> None:
        durations = [0.0, 10.0, 0.0, 5.0, 0.0]
        offsets = calculate_timeline_offsets(durations)
        assert offsets == [0.0, 0.0, 10.0, 10.0, 15.0]
        # Must be strictly monotonic non-decreasing
        for i in range(1, len(offsets)):
            assert offsets[i] >= offsets[i - 1]


# =============================================================================
# 3. Chunk Global Base Calculation & Continuous Global Timeline Alignment
# =============================================================================
class TestChunkGlobalBaseAndAlignment:
    """Stress test chunk slicing and Whisper segment alignment to global timeline."""

    def test_multi_chunk_continuous_alignment(self) -> None:
        """Verify T_global = T_file_offset + T_chunk_start + t_segment across multiple chunks."""
        file_offset = 3600.0  # 1 hour file offset

        chunk0 = AudioChunkInfo(
            chunk_index=0,
            file_path=Path("/tmp/chunk_000.mp3"),
            local_start_sec=0.0,
            local_end_sec=600.0,
            global_start_sec=3600.0,
            global_end_sec=4200.0,
            source_file_name="track1.wav",
            file_sequence_index=1,
        )

        chunk1 = AudioChunkInfo(
            chunk_index=1,
            file_path=Path("/tmp/chunk_001.mp3"),
            local_start_sec=600.0,
            local_end_sec=1200.0,
            global_start_sec=4200.0,
            global_end_sec=4800.0,
            source_file_name="track1.wav",
            file_sequence_index=1,
        )

        whisper_segs_chunk0 = [
            {"id": 0, "start": 0.5, "end": 4.0, "text": "Segment A"},
            {"id": 1, "start": 5.0, "end": 10.0, "text": "Segment B"},
            {"id": 2, "start": 590.0, "end": 598.0, "text": "Segment C (end of chunk 0)"},
        ]

        whisper_segs_chunk1 = [
            {"id": 0, "start": 2.0, "end": 6.0, "text": "Segment D (start of chunk 1)"},
            {"id": 1, "start": 8.0, "end": 15.0, "text": "Segment E"},
        ]

        aligned0 = align_whisper_segments(whisper_segs_chunk0, chunk0)
        aligned1 = align_whisper_segments(whisper_segs_chunk1, chunk1)

        # Chunk 0 alignment
        assert aligned0[0]["global_start"] == 3600.5
        assert aligned0[0]["global_end"] == 3604.0
        assert aligned0[1]["global_start"] == 3605.0
        assert aligned0[1]["global_end"] == 3610.0
        assert aligned0[2]["global_start"] == 4190.0
        assert aligned0[2]["global_end"] == 4198.0

        # Chunk 1 alignment: global_start = chunk.global_start_sec + seg_start = 4200.0 + 2.0 = 4202.0
        assert aligned1[0]["global_start"] == 4202.0
        assert aligned1[0]["global_end"] == 4206.0
        assert aligned1[1]["global_start"] == 4208.0
        assert aligned1[1]["global_end"] == 4215.0

        # Verify global monotonicity across the joint sequence
        all_aligned = aligned0 + aligned1
        for i in range(1, len(all_aligned)):
            assert all_aligned[i]["global_start"] >= all_aligned[i - 1]["global_end"]


# =============================================================================
# 4. Acoustic Pause Calculation: pause_before = max(0.0, current_start - prev_end)
# =============================================================================
class TestAcousticPauseCalculation:
    """Stress test pause calculations across diverse acoustic conditions."""

    @pytest.fixture
    def dummy_chunk(self) -> AudioChunkInfo:
        return AudioChunkInfo(
            chunk_index=0,
            file_path=Path("/tmp/c.mp3"),
            local_start_sec=0.0,
            local_end_sec=100.0,
            global_start_sec=500.0,
            global_end_sec=600.0,
            source_file_name="test.mp3",
            file_sequence_index=0,
        )

    def test_standard_positive_pause(self, dummy_chunk: AudioChunkInfo) -> None:
        raw = [
            {"start": 1.0, "end": 3.0, "text": "Hello"},
            {"start": 4.5, "end": 6.0, "text": "World"},  # Pause: 4.5 - 3.0 = 1.5s
        ]
        aligned = align_whisper_segments(raw, dummy_chunk)
        assert aligned[0]["pause_before"] == 1.0  # From chunk start 0.0 to 1.0
        assert aligned[1]["pause_before"] == 1.5

    def test_zero_pause_continuous_speech(self, dummy_chunk: AudioChunkInfo) -> None:
        raw = [
            {"start": 1.0, "end": 3.0, "text": "Continuous"},
            {"start": 3.0, "end": 5.0, "text": "Speech"},  # Exact zero pause
        ]
        aligned = align_whisper_segments(raw, dummy_chunk)
        assert aligned[1]["pause_before"] == 0.0

    def test_overlapping_speech_clamped_to_zero(self, dummy_chunk: AudioChunkInfo) -> None:
        """Whisper sometimes returns overlapping timestamps (turn overlaps)."""
        raw = [
            {"start": 2.0, "end": 5.0, "text": "Speaker 1"},
            {"start": 4.2, "end": 7.0, "text": "Speaker 2 cuts in"},  # 4.2 - 5.0 = -0.8s
        ]
        aligned = align_whisper_segments(raw, dummy_chunk)
        assert aligned[1]["pause_before"] == 0.0  # Clamped by max(0.0, ...)

    def test_first_segment_starts_at_zero(self, dummy_chunk: AudioChunkInfo) -> None:
        raw = [{"start": 0.0, "end": 2.5, "text": "Immediate start"}]
        aligned = align_whisper_segments(raw, dummy_chunk)
        assert aligned[0]["pause_before"] == 0.0

    def test_whisper_hallucinated_negative_start_clamped(self, dummy_chunk: AudioChunkInfo) -> None:
        """Adversarial case: Whisper outputs negative start timestamp."""
        raw = [{"start": -0.5, "end": 2.0, "text": "Negative start"}]
        aligned = align_whisper_segments(raw, dummy_chunk)
        assert aligned[0]["pause_before"] == 0.0  # max(0.0, -0.5 - 0.0) = 0.0

    def test_cross_chunk_pause_loss_observation(self) -> None:
        """
        Empirically document that align_whisper_segments initializes prev_end = 0.0,
        causing trailing silence at the end of chunk N to be omitted from the pause
        reported before the first segment of chunk N+1.
        """
        c0 = AudioChunkInfo(
            chunk_index=0,
            file_path=Path("c0.mp3"),
            local_start_sec=0.0,
            local_end_sec=600.0,
            global_start_sec=0.0,
            global_end_sec=600.0,
            source_file_name="track.wav",
            file_sequence_index=0,
        )
        c1 = AudioChunkInfo(
            chunk_index=1,
            file_path=Path("c1.mp3"),
            local_start_sec=600.0,
            local_end_sec=1200.0,
            global_start_sec=600.0,
            global_end_sec=1200.0,
            source_file_name="track.wav",
            file_sequence_index=0,
        )
        # Last segment of chunk 0 ends at 590.0s (10s of trailing silence in chunk 0)
        raw0 = [{"start": 580.0, "end": 590.0, "text": "Chunk 0 speech"}]
        # First segment of chunk 1 starts at local 5.0s (global 605.0s)
        raw1 = [{"start": 5.0, "end": 10.0, "text": "Chunk 1 speech"}]

        a0 = align_whisper_segments(raw0, c0)
        a1 = align_whisper_segments(raw1, c1)

        real_pause = a1[0]["global_start"] - a0[-1]["global_end"]  # 605.0 - 590.0 = 15.0s
        # Reported pause_before in chunk 1 is only 5.0s because prev_end starts at 0.0
        assert a1[0]["pause_before"] == 5.0
        assert real_pause == 15.0
        # The 10.0s silence at the end of chunk 0 is unrepresented in pause_before



# =============================================================================
# 5. Timestamp Formatters & Subtitle Millisecond Rollover Protection
# =============================================================================
class TestTimestampFormattersAndRollover:
    """Adversarial stress testing of timestamp formatting functions."""

    @pytest.mark.parametrize(
        "seconds, expected_hhmmss, expected_srt, expected_vtt",
        [
            (0.0, "00:00:00", "00:00:00,000", "00:00:00.000"),
            (0.0001, "00:00:00", "00:00:00,000", "00:00:00.000"),
            (0.0006, "00:00:00", "00:00:00,001", "00:00:00.001"),
            (0.9994, "00:00:00", "00:00:00,999", "00:00:00.999"),
            # Critical Rollover 1: 999.5ms rolls over into next second
            (0.9995, "00:00:00", "00:00:01,000", "00:00:01.000"),
            # Critical Rollover 2: 59.9995s rolls over into next minute
            (59.9995, "00:00:59", "00:01:00,000", "00:01:00.000"),
            # Critical Rollover 3: 3599.9995s rolls over into next hour
            (3599.9995, "00:59:59", "01:00:00,000", "01:00:00.000"),
            # Multi-hour formatting
            (3665.421, "01:01:05", "01:01:05,421", "01:01:05.421"),
            # Rollover 4: 86399.9995s rolls over into 24:00:00
            (86399.9995, "23:59:59", "24:00:00,000", "24:00:00.000"),
            # 100 hours
            (360000.0, "100:00:00", "100:00:00,000", "100:00:00.000"),
            # Negative clamping
            (-1.5, "00:00:00", "00:00:00,000", "00:00:00.000"),
            (-0.00001, "00:00:00", "00:00:00,000", "00:00:00.000"),
        ],
    )
    def test_formatter_matrix(
        self,
        seconds: float,
        expected_hhmmss: str,
        expected_srt: str,
        expected_vtt: str,
    ) -> None:
        assert format_timestamp_hhmmss(seconds) == expected_hhmmss
        assert format_timestamp_srt(seconds) == expected_srt
        assert format_timestamp_vtt(seconds) == expected_vtt
        # Verify SRT vs VTT invariant: identical except comma vs dot
        assert format_timestamp_srt(seconds).replace(",", ".") == format_timestamp_vtt(seconds)

    def test_no_literal_1000_milliseconds_ever_emitted(self) -> None:
        """Exhaustively check that ',1000' or '.1000' is never produced for sub-millisecond values."""
        for frac in [0.9995, 0.9996, 0.9997, 0.9998, 0.9999, 0.999999]:
            srt = format_timestamp_srt(frac)
            vtt = format_timestamp_vtt(frac)
            assert "1000" not in srt
            assert "1000" not in vtt
            assert srt == "00:00:01,000"
            assert vtt == "00:00:01.000"


# =============================================================================
# 6. Stress Test: Filename & Base Stem Collisions in Multi-Audio Sequences
# =============================================================================
class TestMultiAudioCollisionStress:
    """
    Stress-test how chunk extraction behaves when files in the sequence share
    the same base stem (e.g., track.wav and track.mp3, or track.mp3 in different folders).
    """

    def test_same_base_stem_multi_audio_sequence(self, tmp_path: Path) -> None:
        """
        Adversarial test: Two audio files with the same stem:
        dir1/audio.wav (2.0s) and dir2/audio.mp3 (3.0s).
        Verifies if chunk output paths collide or cause silent data loss.
        """
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir(parents=True, exist_ok=True)
        dir2.mkdir(parents=True, exist_ok=True)

        f1 = dir1 / "audio.wav"
        create_synthetic_wav(f1, [(2.0, 440.0)])

        f2_wav = dir2 / "audio_src.wav"
        create_synthetic_wav(f2_wav, [(3.0, 880.0)])
        f2 = dir2 / "audio.mp3"  # Same stem "audio" as f1!
        convert_audio_format(f2_wav, f2, "mp3")

        out_dir = tmp_path / "chunk_output"
        out_dir.mkdir(parents=True, exist_ok=True)

        probed, chunks = process_audio_sequence(
            file_paths=[f1, f2],
            output_dir=out_dir,
            target_duration_sec=10.0,
        )

        assert len(probed) == 2
        assert len(chunks) == 2

        # Check chunk paths
        c0_path = chunks[0].file_path
        c1_path = chunks[1].file_path

        # If chunk paths are identical, chunk 1 overwrote chunk 0!
        assert c0_path != c1_path, (
            f"VULNERABILITY DETECTED: Chunk 0 path ({c0_path}) and Chunk 1 path ({c1_path}) "
            f"collided because they share the same stem '{f1.stem}'. "
            f"Chunk 1 overwrote Chunk 0 on disk!"
        )
