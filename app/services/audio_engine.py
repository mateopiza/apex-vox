"""
Audio Engine Service (app/services/audio_engine.py)
--------------------------------------------------
Provides audio probing, silence detection, intelligent windowed chunking,
16kHz mono 64kbps MP3 slice extraction, sequence ordering, timeline arithmetic,
and timestamp formatting using system ffmpeg/ffprobe subprocesses.

Guarantees:
- Safe execution on Python 3.11-3.14 without reliance on deprecated 'audioop'.
- Strict compliance with Groq 25 MB payload limits.
- Verbatim preservation of speech boundaries via windowed silence splitting.
- Continuous chronological timeline mapping across multi-chunk sequences.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Import centralized settings from app.config if available
try:
    from app.config import settings
except ImportError:
    settings = None  # type: ignore

logger = logging.getLogger("app.services.audio_engine")

# -----------------------------------------------------------------------------
# Default Constants (Used as fallbacks if app.config is unavailable)
# -----------------------------------------------------------------------------
DEFAULT_GROQ_PAYLOAD_LIMIT_BYTES = 25 * 1024 * 1024
DEFAULT_CHUNK_TARGET_DURATION_SEC = 600.0
DEFAULT_CHUNK_SEARCH_WINDOW_SEC = 45.0
DEFAULT_CHUNK_MAX_SEARCH_WINDOW_SEC = 90.0
DEFAULT_SILENCE_NOISE_THRESHOLD_DB = -30.0
DEFAULT_SILENCE_MIN_DURATION_SEC = 0.5
DEFAULT_AUDIO_SAMPLE_RATE = 16000
DEFAULT_AUDIO_CHANNELS = 1
DEFAULT_AUDIO_BITRATE = "64k"


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------

class AudioEngineError(RuntimeError):
    """Base exception for all audio engine operations."""
    pass


class AudioProbeError(AudioEngineError):
    """Raised when ffprobe fails to parse or read an audio file."""
    pass


class SilenceDetectionError(AudioEngineError):
    """Raised when ffmpeg silencedetect fails or produces invalid output."""
    pass


class AudioChunkError(AudioEngineError):
    """Raised when chunk extraction or audio slicing fails."""
    pass


class AudioDependencyError(AudioEngineError):
    """Raised when ffmpeg or ffprobe executable is missing from system PATH."""
    pass


# -----------------------------------------------------------------------------
# Data Models (PROJECT.md Interface Contracts)
# -----------------------------------------------------------------------------

class AudioChunkInfo(BaseModel):
    """Metadata describing an extracted audio slice."""
    chunk_index: int
    file_path: Path
    local_start_sec: float
    local_end_sec: float
    global_start_sec: float
    global_end_sec: float
    source_file_name: str
    file_sequence_index: int


class ProbedAudio(BaseModel):
    """High-level audio file metadata returned to API and client."""
    file_id: str
    filename: str
    format: str
    duration_sec: float
    size_bytes: int
    is_over_25mb: bool
    chunks: list[AudioChunkInfo] = Field(default_factory=list)


class AudioMetadata(BaseModel):
    """Internal low-level metadata probed from audio container and streams."""
    file_path: Path
    filename: str
    format: str
    duration_sec: float
    size_bytes: int
    sample_rate: int
    channels: int
    bitrate: int | None = None
    codec_name: str = ""

    @property
    def format_name(self) -> str:
        """Alias for format to support format_name lookups."""
        return self.format

    @property
    def is_over_25mb(self) -> bool:
        """True if file size strictly exceeds Groq 25MB payload limit."""
        limit_bytes = (
            getattr(settings, "GROQ_PAYLOAD_LIMIT_BYTES", DEFAULT_GROQ_PAYLOAD_LIMIT_BYTES)
            if settings
            else DEFAULT_GROQ_PAYLOAD_LIMIT_BYTES
        )
        return self.size_bytes > limit_bytes

    def to_probed_audio(
        self,
        file_id: str,
        chunks: list[AudioChunkInfo] | None = None,
    ) -> ProbedAudio:
        """Convert internal metadata to the standardized ProbedAudio schema."""
        return ProbedAudio(
            file_id=file_id,
            filename=self.filename,
            format=self.format,
            duration_sec=round(self.duration_sec, 3),
            size_bytes=self.size_bytes,
            is_over_25mb=self.is_over_25mb,
            chunks=chunks or [],
        )


# -----------------------------------------------------------------------------
# Dependency Checks
# -----------------------------------------------------------------------------

def check_ffmpeg_installed() -> bool:
    """Return True if both ffmpeg and ffprobe are available in system PATH."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def require_ffmpeg() -> None:
    """Raise AudioDependencyError if ffmpeg or ffprobe is not installed."""
    if shutil.which("ffmpeg") is None:
        raise AudioDependencyError("ffmpeg executable not found in system PATH")
    if shutil.which("ffprobe") is None:
        raise AudioDependencyError("ffprobe executable not found in system PATH")


# -----------------------------------------------------------------------------
# 1. Audio Probing
# -----------------------------------------------------------------------------

def probe_audio(file_path: Path | str) -> AudioMetadata:
    """
    Probe audio container and stream properties using ffprobe JSON output.

    Extracts duration, format, sample rate, channels, size, and codec.
    Handles multi-stream files (ignoring video/album art streams).
    """
    if shutil.which("ffprobe") is None:
        raise AudioDependencyError("ffprobe executable not found in system PATH")

    path = Path(file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {path}")
    if not path.is_file():
        raise AudioProbeError(f"Audio path is not a regular file: {path}")

    size_bytes = path.stat().st_size
    if size_bytes == 0:
        raise AudioProbeError(f"Audio file is empty (0 bytes): {path}")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30.0,
        )
    except subprocess.CalledProcessError as e:
        err_msg = (
            e.stderr.decode("utf-8", errors="ignore")
            if isinstance(e.stderr, bytes)
            else str(e.stderr or e)
        )
        raise AudioProbeError(f"ffprobe execution failed on '{path.name}': {err_msg}") from e
    except subprocess.TimeoutExpired as e:
        raise AudioProbeError(f"ffprobe timed out probing '{path}': {e}") from e
    except AudioEngineError:
        raise
    except Exception as e:
        raise AudioProbeError(f"ffprobe execution failed on '{path}': {e}") from e

    if res.returncode != 0:
        err_msg = res.stderr.strip() or f"exit code {res.returncode}"
        raise AudioProbeError(f"Failed to probe audio file '{path.name}': {err_msg}")

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise AudioProbeError(f"Invalid JSON returned by ffprobe for '{path.name}': {e}") from e

    format_info: dict[str, Any] = data.get("format", {})
    streams: list[dict[str, Any]] = data.get("streams", [])

    # Filter for audio streams
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not audio_stream:
        raise AudioProbeError(f"No audio stream found in file '{path.name}'.")

    # Extract format name
    raw_fmt = format_info.get("format_name", "")
    fmt = raw_fmt.split(",")[0].strip().lower() if raw_fmt else path.suffix.lstrip(".").lower()

    # Extract duration (format preferred, audio stream fallback, tags fallback, ffmpeg scan fallback)
    format_tags = format_info.get("tags") or {}
    stream_tags = audio_stream.get("tags") or {}
    duration_str = (
        format_info.get("duration")
        or audio_stream.get("duration")
        or format_tags.get("DURATION")
        or stream_tags.get("DURATION")
        or "0.0"
    )
    duration_sec = 0.0
    try:
        if isinstance(duration_str, str) and ":" in duration_str:
            parts = duration_str.split(":")
            if len(parts) == 3:
                duration_sec = float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        else:
            duration_sec = float(duration_str)
    except (ValueError, TypeError):
        duration_sec = 0.0

    # Browser MediaRecorder WebM/Opus streams often omit container duration ("N/A").
    # Probe actual packet timestamps via fast remux to null when header duration is missing.
    if duration_sec <= 0.0 and shutil.which("ffmpeg") is not None:
        try:
            scan_res = subprocess.run(
                ["ffmpeg", "-v", "info", "-i", str(path), "-c", "copy", "-f", "null", "-"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15.0,
            )
            time_matches = re.findall(r"time=(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", scan_res.stderr or "")
            if time_matches:
                hh, mm, ss = time_matches[-1]
                duration_sec = int(hh) * 3600.0 + int(mm) * 60.0 + float(ss)
        except Exception:  # noqa: BLE001
            logger.debug("Fallback duration parse failed for %s", path.name)  # se queda la duración de ffprobe

    if duration_sec <= 0.0 and size_bytes > 0:
        # Safe fallback estimate (~48 kbps = 6000 bytes/sec) so valid blocks never fail with 0.0s
        duration_sec = round(max(0.5, size_bytes / 6000.0), 3)

    # Extract sample rate
    try:
        sample_rate = int(audio_stream.get("sample_rate", DEFAULT_AUDIO_SAMPLE_RATE))
    except (ValueError, TypeError):
        sample_rate = DEFAULT_AUDIO_SAMPLE_RATE

    # Extract channels
    try:
        channels = int(audio_stream.get("channels", DEFAULT_AUDIO_CHANNELS))
    except (ValueError, TypeError):
        channels = DEFAULT_AUDIO_CHANNELS

    # Extract bitrate
    bitrate_str = format_info.get("bit_rate") or audio_stream.get("bit_rate")
    bitrate = int(bitrate_str) if bitrate_str and str(bitrate_str).isdigit() else None
    codec_name = audio_stream.get("codec_name", "")

    return AudioMetadata(
        file_path=path,
        filename=path.name,
        format=fmt,
        duration_sec=duration_sec,
        size_bytes=size_bytes,
        sample_rate=sample_rate,
        channels=channels,
        bitrate=bitrate,
        codec_name=codec_name,
    )


# -----------------------------------------------------------------------------
# 2. Silence Detection
# -----------------------------------------------------------------------------

RE_SILENCE_START = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
RE_SILENCE_END = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")


def detect_silences(
    file_path: Path | str,
    noise_threshold_db: float | None = None,
    min_silence_sec: float | None = None,
    total_duration: float | None = None,
) -> list[tuple[float, float]]:
    """
    Detect acoustic silence intervals in an audio file using ffmpeg -af silencedetect.

    Runs at >2000x real-time without decoding PCM data into Python memory.
    Returns a sorted list of (start_sec, end_sec) tuples.
    """
    if shutil.which("ffmpeg") is None:
        raise AudioDependencyError("ffmpeg executable not found in system PATH")

    path = Path(file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {path}")

    # Fallback to configuration defaults if not provided
    if noise_threshold_db is None:
        noise_threshold_db = (
            getattr(settings, "SILENCE_NOISE_THRESHOLD_DB", DEFAULT_SILENCE_NOISE_THRESHOLD_DB)
            if settings
            else DEFAULT_SILENCE_NOISE_THRESHOLD_DB
        )
    if min_silence_sec is None:
        min_silence_sec = (
            getattr(settings, "SILENCE_MIN_DURATION_SEC", DEFAULT_SILENCE_MIN_DURATION_SEC)
            if settings
            else DEFAULT_SILENCE_MIN_DURATION_SEC
        )

    # Ensure dB unit suffix is strictly present (required by FFmpeg silencedetect)
    noise_str = (
        f"{noise_threshold_db}dB"
        if not str(noise_threshold_db).endswith("dB")
        else str(noise_threshold_db)
    )

    # Note: -v info is strictly mandatory because silencedetect outputs at info level
    cmd = [
        "ffmpeg",
        "-v", "info",
        "-i", str(path),
        "-af", f"silencedetect=noise={noise_str}:d={min_silence_sec}",
        "-f", "null",
        "-",
    ]

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=300.0,
        )
    except subprocess.CalledProcessError as e:
        err_msg = (
            e.stderr.decode("utf-8", errors="ignore")
            if isinstance(e.stderr, bytes)
            else str(e.stderr or e)
        )
        raise SilenceDetectionError(f"silencedetect failed on '{path.name}': {err_msg}") from e
    except subprocess.TimeoutExpired as e:
        raise SilenceDetectionError(f"silencedetect timed out on '{path}': {e}") from e
    except AudioEngineError:
        raise
    except Exception as e:
        raise SilenceDetectionError(f"silencedetect execution failed on '{path}': {e}") from e

    if res.returncode != 0:
        err_msg = res.stderr.strip() or f"exit code {res.returncode}"
        raise SilenceDetectionError(f"silencedetect failed on '{path.name}': {err_msg}")

    silences: list[tuple[float, float]] = []
    current_start: float | None = None

    for line in res.stderr.splitlines():
        sm = RE_SILENCE_START.search(line)
        if sm:
            try:
                current_start = float(sm.group(1))
            except ValueError:
                continue

        em = RE_SILENCE_END.search(line)
        if em:
            try:
                end_val = float(em.group(1))
                start_val = current_start if current_start is not None else 0.0
                if end_val > start_val:
                    silences.append((round(start_val, 3), round(end_val, 3)))
                current_start = None
            except ValueError:
                continue

    # Seal any trailing unclosed silence reaching EOF
    if current_start is not None:
        if total_duration is None:
            try:
                meta = probe_audio(path)
                total_duration = meta.duration_sec
            except Exception:
                total_duration = None

        if total_duration is not None and total_duration > current_start:
            silences.append((round(current_start, 3), round(total_duration, 3)))
        else:
            silences.append((round(current_start, 3), round(current_start + min_silence_sec, 3)))

    return silences


# -----------------------------------------------------------------------------
# 3. Windowed Split Point Calculation
# -----------------------------------------------------------------------------

def find_split_point(
    current_start: float,
    target_duration: float,
    silences: list[tuple[float, float]],
    window_sec: float = DEFAULT_CHUNK_SEARCH_WINDOW_SEC,
    max_window_sec: float = DEFAULT_CHUNK_MAX_SEARCH_WINDOW_SEC,
    min_chunk_duration: float = 1.0,
) -> float:
    """
    Find the optimal split point starting from current_start targeting current_start + target_duration.

    Tiers:
    - Tier 1: Search silence midpoints in [target_abs - window_sec, target_abs + window_sec].
    - Tier 2: Search silence midpoints in [target_abs - max_window_sec, target_abs + max_window_sec].
    - Tier 3: Hard split at target_abs if no silence exists.
    """
    target_abs = current_start + target_duration
    silence_midpoints = [(s + e) / 2.0 for (s, e) in silences if e > s]

    # Filter midpoints that advance beyond current_start by at least min_chunk_duration
    valid_midpoints = [m for m in silence_midpoints if m > (current_start + min_chunk_duration)]

    # Tier 1: Primary search window
    w1_min = target_abs - window_sec
    w1_max = target_abs + window_sec
    candidates_w1 = [m for m in valid_midpoints if w1_min <= m <= w1_max]
    if candidates_w1:
        return min(candidates_w1, key=lambda m: abs(m - target_abs))

    # Tier 2: Secondary expanded search window
    w2_min = target_abs - max_window_sec
    w2_max = target_abs + max_window_sec
    candidates_w2 = [m for m in valid_midpoints if w2_min <= m <= w2_max]
    if candidates_w2:
        return min(candidates_w2, key=lambda m: abs(m - target_abs))

    # Tier 3: Hard fallback
    return target_abs


def calculate_split_points(
    duration_sec: float,
    silences: list[tuple[float, float]],
    target_sec: float = DEFAULT_CHUNK_TARGET_DURATION_SEC,
    search_window_sec: float = DEFAULT_CHUNK_SEARCH_WINDOW_SEC,
    max_search_window_sec: float = DEFAULT_CHUNK_MAX_SEARCH_WINDOW_SEC,
    tail_threshold_ratio: float = 1.25,
) -> list[tuple[float, float]]:
    """
    Compute split intervals [(start_sec, end_sec), ...] using windowed silence detection.

    Algorithm:
    - Target: ~600s chunks.
    - Tail rule: If remaining duration <= target_sec * 1.25, merge into final chunk.
    - Tier 1: Search silence midpoints in [target_abs - 45s, target_abs + 45s].
    - Tier 2: Search silence midpoints in [target_abs - 90s, target_abs + 90s].
    - Tier 3: Hard split at target_abs if no silence exists.
    - Midpoint split: cuts at (s + e) / 2 to keep symmetric silence padding on both sides.
    """
    if duration_sec <= 0:
        return []

    max_single_chunk = target_sec * tail_threshold_ratio
    if duration_sec <= max_single_chunk:
        return [(0.0, round(duration_sec, 3))]

    chunks: list[tuple[float, float]] = []
    cursor = 0.0

    while cursor < duration_sec:
        remaining = duration_sec - cursor
        if remaining <= max_single_chunk:
            chunks.append((round(cursor, 3), round(duration_sec, 3)))
            break

        split = find_split_point(
            current_start=cursor,
            target_duration=target_sec,
            silences=silences,
            window_sec=search_window_sec,
            max_window_sec=max_search_window_sec,
            min_chunk_duration=min(30.0, target_sec * 0.2),
        )

        # Clamp split within valid bounds
        split = max(cursor + 1.0, min(split, duration_sec))
        chunks.append((round(cursor, 3), round(split, 3)))
        cursor = split

    return chunks


# -----------------------------------------------------------------------------
# 4. Chunk Extraction
# -----------------------------------------------------------------------------

def extract_chunk(
    input_path: Path | str,
    output_path: Path | str,
    start_sec: float,
    end_sec: float,
    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE,
    channels: int = DEFAULT_AUDIO_CHANNELS,
    bitrate: str = DEFAULT_AUDIO_BITRATE,
) -> Path:
    """
    Extract a slice of audio from input_path and encode as 16kHz mono 64kbps MP3.

    Uses fast input demuxer seeking (-ss and -to before -i).
    """
    if shutil.which("ffmpeg") is None:
        raise AudioDependencyError("ffmpeg executable not found in system PATH")

    src = Path(input_path).resolve()
    dst = Path(output_path).resolve()

    if not src.exists():
        raise FileNotFoundError(f"Input audio file does not exist: {src}")
    if end_sec <= start_sec:
        raise ValueError(
            f"end_sec ({end_sec}) must be strictly greater than start_sec ({start_sec})"
        )

    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-ss", f"{start_sec:.3f}",
        "-to", f"{end_sec:.3f}",
        "-i", str(src),
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        str(dst),
    ]

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=180.0,
        )
    except subprocess.CalledProcessError as e:
        err_msg = (
            e.stderr.decode("utf-8", errors="ignore")
            if isinstance(e.stderr, bytes)
            else str(e.stderr or e)
        )
        raise AudioChunkError(f"FFmpeg chunk extraction failed for '{dst.name}': {err_msg}") from e
    except subprocess.TimeoutExpired as e:
        raise AudioChunkError(f"FFmpeg chunk extraction timed out for '{dst.name}': {e}") from e
    except AudioEngineError:
        raise
    except Exception as e:
        raise AudioChunkError(f"FFmpeg chunk extraction failed for '{dst.name}': {e}") from e

    if res.returncode != 0:
        err_msg = res.stderr.strip() or f"exit code {res.returncode}"
        raise AudioChunkError(f"FFmpeg chunk extraction failed for '{dst.name}': {err_msg}")

    if not dst.exists() or dst.stat().st_size == 0:
        raise AudioChunkError(f"Chunk extraction produced an empty or missing file: '{dst.name}'")

    return dst


# -----------------------------------------------------------------------------
# 5. File Chunking Pipeline
# -----------------------------------------------------------------------------

def chunk_audio_file(
    file_path: Path | str,
    output_dir: Path | str,
    file_sequence_index: int = 0,
    file_offset_sec: float = 0.0,
    target_duration_sec: float | None = None,
    target_sec: float | None = None,
    window_sec: float | None = None,
    search_window_sec: float | None = None,
    max_window_sec: float | None = None,
    max_search_window_sec: float | None = None,
    noise_threshold_db: float | None = None,
    min_silence_sec: float | None = None,
    force_reencode: bool = True,
) -> list[AudioChunkInfo]:
    """
    Decompose an audio file into 16kHz mono 64kbps MP3 chunks.

    Calculates silence-based split points, extracts slices, and records
    continuous local and global timestamps in AudioChunkInfo structures.
    """
    src = Path(file_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    metadata = probe_audio(src)

    # Resolve target and window parameters with fallbacks
    eff_target_sec = (
        target_duration_sec
        if target_duration_sec is not None
        else (
            target_sec
            if target_sec is not None
            else (
                getattr(settings, "CHUNK_TARGET_DURATION_SEC", DEFAULT_CHUNK_TARGET_DURATION_SEC)
                if settings
                else DEFAULT_CHUNK_TARGET_DURATION_SEC
            )
        )
    )

    eff_window_sec = (
        window_sec
        if window_sec is not None
        else (
            search_window_sec
            if search_window_sec is not None
            else (
                getattr(settings, "CHUNK_SEARCH_WINDOW_SEC", DEFAULT_CHUNK_SEARCH_WINDOW_SEC)
                if settings
                else DEFAULT_CHUNK_SEARCH_WINDOW_SEC
            )
        )
    )

    eff_max_window_sec = (
        max_window_sec
        if max_window_sec is not None
        else (
            max_search_window_sec
            if max_search_window_sec is not None
            else (
                getattr(settings, "CHUNK_MAX_SEARCH_WINDOW_SEC", DEFAULT_CHUNK_MAX_SEARCH_WINDOW_SEC)
                if settings
                else DEFAULT_CHUNK_MAX_SEARCH_WINDOW_SEC
            )
        )
    )

    eff_noise_db = (
        noise_threshold_db
        if noise_threshold_db is not None
        else (
            getattr(settings, "SILENCE_NOISE_THRESHOLD_DB", DEFAULT_SILENCE_NOISE_THRESHOLD_DB)
            if settings
            else DEFAULT_SILENCE_NOISE_THRESHOLD_DB
        )
    )

    eff_min_silence = (
        min_silence_sec
        if min_silence_sec is not None
        else (
            getattr(settings, "SILENCE_MIN_DURATION_SEC", DEFAULT_SILENCE_MIN_DURATION_SEC)
            if settings
            else DEFAULT_SILENCE_MIN_DURATION_SEC
        )
    )

    # Determine if file needs splitting
    needs_splitting = (
        metadata.duration_sec > (eff_target_sec * 1.25)
        or metadata.is_over_25mb
    )

    if needs_splitting:
        silences = detect_silences(
            src,
            noise_threshold_db=eff_noise_db,
            min_silence_sec=eff_min_silence,
            total_duration=metadata.duration_sec,
        )
        splits = calculate_split_points(
            duration_sec=metadata.duration_sec,
            silences=silences,
            target_sec=eff_target_sec,
            search_window_sec=eff_window_sec,
            max_search_window_sec=eff_max_window_sec,
        )
    else:
        splits = [(0.0, metadata.duration_sec)]

    sample_rate = (
        getattr(settings, "AUDIO_SAMPLE_RATE", DEFAULT_AUDIO_SAMPLE_RATE)
        if settings
        else DEFAULT_AUDIO_SAMPLE_RATE
    )
    channels = (
        getattr(settings, "AUDIO_CHANNELS", DEFAULT_AUDIO_CHANNELS)
        if settings
        else DEFAULT_AUDIO_CHANNELS
    )
    bitrate = (
        getattr(settings, "AUDIO_BITRATE", DEFAULT_AUDIO_BITRATE)
        if settings
        else DEFAULT_AUDIO_BITRATE
    )

    chunks: list[AudioChunkInfo] = []
    base_stem = src.stem

    for idx, (local_start, local_end) in enumerate(splits):
        chunk_filename = f"{base_stem}_chunk_{idx:03d}.mp3"
        chunk_path = out_dir / chunk_filename
        if chunk_path.exists() and file_sequence_index > 0:
            chunk_filename = f"{base_stem}_seq{file_sequence_index:03d}_chunk_{idx:03d}.mp3"
            chunk_path = out_dir / chunk_filename

        extract_chunk(
            input_path=src,
            output_path=chunk_path,
            start_sec=local_start,
            end_sec=local_end,
            sample_rate=sample_rate,
            channels=channels,
            bitrate=bitrate,
        )

        chunk_info = AudioChunkInfo(
            chunk_index=idx,
            file_path=chunk_path,
            local_start_sec=local_start,
            local_end_sec=local_end,
            global_start_sec=round(file_offset_sec + local_start, 3),
            global_end_sec=round(file_offset_sec + local_end, 3),
            source_file_name=metadata.filename,
            file_sequence_index=file_sequence_index,
        )
        chunks.append(chunk_info)

    return chunks


# -----------------------------------------------------------------------------
# 6. Sequence Ordering & Timeline Math
# -----------------------------------------------------------------------------

def calculate_timeline_offsets(durations: list[float]) -> list[float]:
    """
    Compute cumulative global start timestamps for a sequence of audio durations.

    Example: [10.0, 25.5, 12.0] -> [0.0, 10.0, 35.5]
    """
    offsets: list[float] = []
    accum = 0.0
    for d in durations:
        offsets.append(round(accum, 3))
        accum += d
    return offsets


def process_audio_sequence(
    file_paths: list[Path | str],
    output_dir: Path | str,
    target_duration_sec: float | None = None,
    **kwargs: Any,
) -> tuple[list[ProbedAudio], list[AudioChunkInfo]]:
    """
    Process multiple audio files in user sequence, computing cumulative duration offsets,
    slicing each file into chunks <= 25MB, and re-indexing chunk indices globally.

    Returns:
        (probed_audio_list, all_chunks_list)
    """
    if not file_paths:
        return [], []

    resolved_paths = [Path(p).resolve() for p in file_paths]
    metas = [probe_audio(p) for p in resolved_paths]
    durations = [m.duration_sec for m in metas]
    offsets = calculate_timeline_offsets(durations)

    all_probed: list[ProbedAudio] = []
    all_chunks: list[AudioChunkInfo] = []
    global_chunk_idx = 0

    for idx, (meta, offset) in enumerate(zip(metas, offsets)):
        file_chunks = chunk_audio_file(
            file_path=meta.file_path,
            output_dir=output_dir,
            file_sequence_index=idx,
            file_offset_sec=offset,
            target_duration_sec=target_duration_sec,
            **kwargs,
        )

        updated_file_chunks: list[AudioChunkInfo] = []
        for c in file_chunks:
            c_updated = c.model_copy(update={"chunk_index": global_chunk_idx})
            global_chunk_idx += 1
            updated_file_chunks.append(c_updated)
            all_chunks.append(c_updated)

        probed_audio = meta.to_probed_audio(
            file_id=str(idx),
            chunks=updated_file_chunks,
        )
        all_probed.append(probed_audio)

    return all_probed, all_chunks


def prepare_audio_sequence(
    file_paths: list[Path | str],
    output_dir: Path | str,
    target_duration_sec: float | None = None,
    **kwargs: Any,
) -> list[AudioChunkInfo]:
    """
    Helper pipeline that joins multiple audio files in sequence and returns the chunk list.
    """
    _probed, chunks = process_audio_sequence(
        file_paths=file_paths,
        output_dir=output_dir,
        target_duration_sec=target_duration_sec,
        **kwargs,
    )
    return chunks


# -----------------------------------------------------------------------------
# 7. Timestamp Alignment & Formatting Helpers
# -----------------------------------------------------------------------------

def align_whisper_segments(
    raw_segments: list[dict[str, Any]],
    chunk: AudioChunkInfo,
) -> list[dict[str, Any]]:
    """
    Map local Whisper chunk timestamps into continuous global timeline timestamps.

    Calculates acoustic pause_before relative to chunk or previous segment.
    """
    aligned: list[dict[str, Any]] = []
    prev_end = 0.0

    for seg in raw_segments:
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", 0.0))
        pause_before = max(0.0, round(seg_start - prev_end, 3))

        aligned_seg = {
            **seg,
            "global_start": round(chunk.global_start_sec + seg_start, 3),
            "global_end": round(chunk.global_start_sec + seg_end, 3),
            "source_file": chunk.source_file_name,
            "file_order_index": chunk.file_sequence_index,
            "pause_before": pause_before,
        }
        aligned.append(aligned_seg)
        prev_end = seg_end

    return aligned


def format_timestamp_hhmmss(seconds: float) -> str:
    """
    Format a floating-point timestamp in seconds to 'HH:MM:SS'.

    Negative seconds clamp to '00:00:00'.
    """
    if seconds <= 0.0:
        return "00:00:00"
    total_secs = int(seconds)
    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    secs = total_secs % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


format_timestamp = format_timestamp_hhmmss


def format_timestamp_srt(seconds: float) -> str:
    """
    Format a timestamp to SRT subtitle syntax 'HH:MM:SS,mmm'.

    Uses total millisecond arithmetic to prevent millisecond rollover bugs
    (e.g., 65.9999s rolls over cleanly to 00:01:06,000 without producing ,1000).
    """
    if seconds <= 0.0:
        return "00:00:00,000"
    total_ms = int(round(seconds * 1000.0))
    hours = total_ms // 3600000
    rem = total_ms % 3600000
    minutes = rem // 60000
    rem = rem % 60000
    secs = rem // 1000
    millis = rem % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


format_srt_timestamp = format_timestamp_srt


def format_timestamp_vtt(seconds: float) -> str:
    """
    Format a timestamp to WebVTT subtitle syntax 'HH:MM:SS.mmm'.
    """
    if seconds <= 0.0:
        return "00:00:00.000"
    total_ms = int(round(seconds * 1000.0))
    hours = total_ms // 3600000
    rem = total_ms % 3600000
    minutes = rem // 60000
    rem = rem % 60000
    secs = rem // 1000
    millis = rem % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


format_vtt_timestamp = format_timestamp_vtt
