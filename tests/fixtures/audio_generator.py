"""
Synthetic Audio Generator Utility for Unit and Integration Testing
------------------------------------------------------------------
Generates deterministic, sample-accurate WAV, MP3, and OGG test files
using standard library `wave` and cycle-cached waveforms in < 2ms.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path


def create_synthetic_wav(
    output_path: Path | str,
    segments: list[tuple[float, float]],
    sample_rate: int = 16000,
    channels: int = 1,
) -> Path:
    """
    Generate a deterministic WAV file from a sequence of (duration_sec, frequency_hz) segments.

    frequency_hz <= 0 generates calibrated digital silence.
    Uses precomputed single-cycle caching for millisecond generation speeds.
    """
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)

        for duration, freq in segments:
            n_samples = int(sample_rate * duration)
            if n_samples <= 0:
                continue

            if freq <= 0.0:
                # Silence: zeroed 16-bit words
                wf.writeframes(b"\x00\x00" * n_samples * channels)
            else:
                # Precompute one sine cycle
                cycle_len = max(1, int(sample_rate / freq))
                cycle = bytearray()
                for i in range(cycle_len):
                    val = int(16000 * math.sin(2.0 * math.pi * i / cycle_len))
                    cycle.extend(struct.pack("<h", val) * channels)

                bytes_per_sample = 2 * channels
                full_cycles = n_samples // cycle_len
                rem_samples = n_samples % cycle_len

                wf.writeframes(cycle * full_cycles)
                if rem_samples:
                    wf.writeframes(cycle[: rem_samples * bytes_per_sample])

    return path


def convert_audio_format(
    input_wav: Path | str,
    output_path: Path | str,
    format_name: str = "mp3",
    bitrate: str = "64k",
) -> Path:
    """Convert an existing WAV to MP3, OGG, FLAC, or M4A via FFmpeg."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg binary not found in PATH")

    src = Path(input_wav).resolve()
    dst = Path(output_path).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    codec_map = {
        "mp3": ["-c:a", "libmp3lame", "-b:a", bitrate],
        "ogg": ["-c:a", "libvorbis", "-q:a", "2"],
        "flac": ["-c:a", "flac"],
        "m4a": ["-c:a", "aac", "-b:a", bitrate],
    }

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(src),
        *codec_map.get(format_name.lower(), ["-c:a", "copy"]),
        str(dst),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst


def create_corrupt_audio_file(output_path: Path | str, kind: str = "garbage") -> Path:
    """Generate empty, non-audio, or truncated files for adversarial testing."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if kind == "empty":
        path.touch()
    elif kind == "garbage":
        path.write_bytes(b"This is not a valid audio container file format.")
    elif kind == "truncated_wav":
        # Valid 44-byte WAV header specifying 1MB data, but writing only 10 bytes
        header = (
            b"RIFF\x24\x00\x10\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
            b"\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x10\x00"
        )
        path.write_bytes(header + b"\x00" * 10)
    else:
        raise ValueError(f"Unknown corrupt kind: {kind}")

    return path
