"""Long audio is decoded once, to disk, and a slow decode does not fail the job."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.config import settings
from app.models.schemas import WhisperSegment
from app.services import acoustic_diarizer
from app.services.acoustic_diarizer import (
    SAMPLE_RATE,
    clear_decoded_audio,
    cluster_segments_acoustically,
    load_pcm_float32,
    release_pcm,
)
from app.services.transcript_cleaner import filter_hallucinated_segments
from tests.fixtures.audio_generator import create_synthetic_wav


@pytest.fixture
def wav(tmp_path: Path) -> Path:
    path = tmp_path / "meeting.wav"
    create_synthetic_wav(path, [(1.0, 220.0), (1.0, 0.0), (1.0, 660.0)])
    yield path
    release_pcm(path)


@pytest.fixture
def ffmpeg_runs(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []
    real = subprocess.run

    def spy(cmd, *args, **kwargs):
        calls.append(cmd)
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(acoustic_diarizer.subprocess, "run", spy)
    return calls


def _segments() -> list:
    return [
        WhisperSegment(id=i, start=s, end=s + 0.8, text=f"Texto número {i} de la reunión.", global_start=s,
                       global_end=s + 0.8, source_file="a", file_order_index=0, pause_before=0.0)
        for i, s in enumerate([0.1, 2.1])
    ]


def test_whole_file_is_decoded_once_however_many_steps_ask(wav: Path, ffmpeg_runs: list) -> None:
    first = load_pcm_float32(wav)
    second = load_pcm_float32(wav)
    assert len(ffmpeg_runs) == 1
    assert first.size == second.size == 3 * SAMPLE_RATE


def test_pipeline_steps_share_one_decode(wav: Path, ffmpeg_runs: list) -> None:
    segments = cluster_segments_acoustically(audio_path=wav, segments=_segments(), num_speakers=None)
    filter_hallucinated_segments(segments, audio_path=wav)
    filter_hallucinated_segments(segments, audio_path=wav)
    assert len(ffmpeg_runs) <= 1


def test_array_lives_on_disk_and_is_read_only(wav: Path) -> None:
    pcm = load_pcm_float32(wav)
    assert isinstance(pcm, np.memmap)
    assert not pcm.flags.writeable
    assert Path(pcm.filename).is_relative_to(settings.TEMP_DIR)


def test_slices_still_use_a_pipe(wav: Path, ffmpeg_runs: list) -> None:
    assert load_pcm_float32(wav, start_sec=1.0, end_sec=2.0).size == pytest.approx(SAMPLE_RATE, abs=800)
    assert ffmpeg_runs[0][-1] == "pipe:1"


def test_release_deletes_the_decoded_copy_and_arrays_keep_working(wav: Path) -> None:
    pcm = load_pcm_float32(wav)
    decoded = Path(pcm.filename)
    assert decoded.exists()
    release_pcm(wav)
    assert not decoded.exists()
    assert float(np.abs(pcm[:100]).sum()) >= 0.0


def test_changed_file_is_decoded_again(wav: Path, ffmpeg_runs: list) -> None:
    load_pcm_float32(wav)
    create_synthetic_wav(wav, [(2.0, 440.0)])
    assert load_pcm_float32(wav).size == 2 * SAMPLE_RATE
    assert len(ffmpeg_runs) == 2


def test_cache_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acoustic_diarizer, "_PCM_CACHE_ENTRIES", 2)
    clear_decoded_audio()
    paths = [tmp_path / f"{i}.wav" for i in range(4)]
    for path in paths:
        create_synthetic_wav(path, [(0.5, 440.0)])
        load_pcm_float32(path)
    assert len(list(acoustic_diarizer._pcm_dir().glob("*.f32"))) == 2
    clear_decoded_audio()
    assert not acoustic_diarizer._pcm_dir().exists()


def test_timeout_gives_empty_audio_instead_of_failing(wav: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def too_slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(acoustic_diarizer.subprocess, "run", too_slow)
    assert load_pcm_float32(wav).size == 0
    assert load_pcm_float32(wav, start_sec=0.0, end_sec=1.0).size == 0
    segments = _segments()
    assert cluster_segments_acoustically(audio_path=wav, segments=segments, num_speakers=None) == segments


def test_undecodable_or_missing_file_gives_empty_audio(tmp_path: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    assert load_pcm_float32(bad).size == 0
    assert load_pcm_float32(tmp_path / "missing.wav").size == 0


def test_speaker_estimate_does_not_grow_with_the_square_of_segments(
    wav: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(acoustic_diarizer, "_MAX_SEGMENTS_FOR_SIMILARITY", 4)
    segments = [
        WhisperSegment(id=i, start=i * 0.1, end=i * 0.1 + 0.05, text="Hola.", global_start=i * 0.1,
                       global_end=i * 0.1 + 0.05, source_file="a", file_order_index=0, pause_before=0.0)
        for i in range(20)
    ]
    labelled = cluster_segments_acoustically(audio_path=wav, segments=segments, num_speakers=None)
    assert len(labelled) == 20
    assert all(s.acoustic_speaker for s in labelled)
