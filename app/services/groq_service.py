"""
Groq Whisper Transcription Service (app/services/groq_service.py)
-----------------------------------------------------------------
Handles communication with the Groq Speech-to-Text API (whisper-large-v3,
whisper-large-v3-turbo, distil-whisper-large-v3), extracts segment-level
timestamps, and maps all segments onto a continuous global timeline across
multiple ordered audio files and chunks.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from groq import Groq

from app.config import settings
from app.models.schemas import WhisperSegment
from app.services.audio_engine import AudioChunkInfo

logger = logging.getLogger("app.services.groq_service")


class GroqTranscriptionError(RuntimeError):
    """Raised when Groq Whisper transcription fails."""
    pass


def get_groq_client(api_key: Optional[str] = None) -> Groq:
    """Create and return an authenticated Groq client."""
    effective_key = (api_key or settings.GROQ_API_KEY or "").strip()
    if not effective_key:
        raise GroqTranscriptionError(
            "GROQ_API_KEY no está configurada. Por favor defínala en el archivo .env "
            "o ingrésela en la interfaz web."
        )
    kwargs: Dict[str, Any] = {
        "api_key": effective_key,
        "timeout": settings.GROQ_TIMEOUT_SECONDS,
        "max_retries": settings.GROQ_MAX_RETRIES,
    }
    if settings.GROQ_BASE_URL:
        kwargs["base_url"] = settings.GROQ_BASE_URL
    return Groq(**kwargs)


def _extract_raw_segments(response: Any, fallback_duration: float = 0.0) -> List[Dict[str, Any]]:
    """
    Normalize Groq verbose_json transcription response into a list of segment dicts.
    Handles SDK Pydantic models, dicts, and single-segment fallbacks.
    """
    raw_segments: List[Any] = []
    full_text = ""

    if isinstance(response, dict):
        raw_segments = response.get("segments") or []
        full_text = response.get("text") or ""
    else:
        raw_segments = getattr(response, "segments", None) or []
        full_text = getattr(response, "text", None) or ""

    normalized: List[Dict[str, Any]] = []
    for idx, seg in enumerate(raw_segments):
        if isinstance(seg, dict):
            s_start = float(seg.get("start", 0.0))
            s_end = float(seg.get("end", s_start))
            s_text = str(seg.get("text", "")).strip()
        else:
            s_start = float(getattr(seg, "start", 0.0))
            s_end = float(getattr(seg, "end", s_start))
            s_text = str(getattr(seg, "text", "")).strip()

        if s_text:
            normalized.append({
                "id": idx,
                "start": max(0.0, s_start),
                "end": max(s_start, s_end),
                "text": s_text,
            })

    # If Whisper returned text but no segments array, synthesize one segment
    if not normalized and full_text and full_text.strip():
        normalized.append({
            "id": 0,
            "start": 0.0,
            "end": max(0.5, fallback_duration),
            "text": full_text.strip(),
        })

    return normalized


def transcribe_chunk(
    chunk: AudioChunkInfo,
    model: Optional[str] = None,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
    api_key: Optional[str] = None,
    client: Optional[Groq] = None,
) -> List[Dict[str, Any]]:
    """
    Send a single audio chunk (< 25 MB) to Groq Whisper API and return raw segments.
    Includes retry handling for transient API/rate-limit errors.
    """
    chunk_path = Path(chunk.file_path)
    if not chunk_path.exists():
        raise FileNotFoundError(f"Audio chunk file not found: {chunk_path}")

    file_size = chunk_path.stat().st_size
    if file_size > settings.GROQ_PAYLOAD_LIMIT_BYTES:
        raise GroqTranscriptionError(
            f"Chunk '{chunk_path.name}' ({file_size} bytes) exceeds Groq 25 MB limit "
            f"({settings.GROQ_PAYLOAD_LIMIT_BYTES} bytes)."
        )

    groq_client = client or get_groq_client(api_key=api_key)
    selected_model = model or settings.DEFAULT_MODEL

    req_kwargs: Dict[str, Any] = {
        "model": selected_model,
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment"],
        "temperature": settings.WHISPER_TEMPERATURE,
    }
    if language and language.strip() and language.strip().lower() != "auto":
        req_kwargs["language"] = language.strip().lower()
    if prompt and prompt.strip():
        req_kwargs["prompt"] = prompt.strip()[:800]

    last_err: Optional[Exception] = None
    max_attempts = max(1, settings.GROQ_MAX_RETRIES)

    for attempt in range(1, max_attempts + 1):
        try:
            with open(chunk_path, "rb") as audio_file:
                response = groq_client.audio.transcriptions.create(
                    file=(chunk_path.name, audio_file),
                    **req_kwargs,
                )
            chunk_duration = max(0.0, chunk.local_end_sec - chunk.local_start_sec)
            return _extract_raw_segments(response, fallback_duration=chunk_duration)
        except Exception as exc:
            last_err = exc
            logger.warning(
                "Groq transcription attempt %d/%d failed for chunk %s: %s",
                attempt,
                max_attempts,
                chunk_path.name,
                exc,
            )
            if attempt < max_attempts:
                time.sleep(min(2.0 ** (attempt - 1), 8.0))

    raise GroqTranscriptionError(
        f"Error al transcribir el fragmento '{chunk_path.name}' en Groq API: {last_err}"
    ) from last_err


def transcribe_chunks_sequence(
    chunks: List[AudioChunkInfo],
    model: Optional[str] = None,
    language: Optional[str] = None,
    prompt_hint: Optional[str] = None,
    api_key: Optional[str] = None,
    client: Optional[Groq] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[WhisperSegment]:
    """
    Transcribe an ordered list of AudioChunkInfo slices sequentially via Groq Whisper
    and map all segments to a continuous global timeline with inter-segment acoustic pauses.
    """
    if not chunks:
        return []

    groq_client = client or get_groq_client(api_key=api_key)
    all_segments: List[WhisperSegment] = []
    global_seg_id = 0
    prev_global_end: Optional[float] = None
    rolling_context = prompt_hint or ""

    total_chunks = len(chunks)
    for idx, chunk in enumerate(chunks):
        if progress_callback:
            progress_callback(
                idx,
                total_chunks,
                f"Transcribiendo fragmento {idx + 1}/{total_chunks} ({chunk.source_file_name})...",
            )

        raw_segs = transcribe_chunk(
            chunk=chunk,
            model=model,
            language=language,
            prompt=rolling_context if rolling_context else None,
            api_key=api_key,
            client=groq_client,
        )

        for seg in raw_segs:
            local_start = float(seg["start"])
            local_end = float(seg["end"])
            text = str(seg["text"]).strip()
            if not text:
                continue

            g_start = round(chunk.global_start_sec + local_start, 3)
            g_end = round(chunk.global_start_sec + local_end, 3)
            if g_end < g_start:
                g_end = g_start

            if prev_global_end is None:
                pause_before = round(max(0.0, local_start), 3)
            else:
                pause_before = round(max(0.0, g_start - prev_global_end), 3)

            whisper_seg = WhisperSegment(
                id=global_seg_id,
                start=round(local_start, 3),
                end=round(local_end, 3),
                text=text,
                global_start=g_start,
                global_end=g_end,
                source_file=chunk.source_file_name,
                file_order_index=chunk.file_sequence_index,
                pause_before=pause_before,
            )
            all_segments.append(whisper_seg)
            global_seg_id += 1
            prev_global_end = g_end

        # Keep last ~200 chars as context prompt for next chunk continuity
        if all_segments:
            recent_text = " ".join(s.text for s in all_segments[-3:])
            if prompt_hint:
                rolling_context = f"{prompt_hint.strip()} {recent_text}"[-400:]
            else:
                rolling_context = recent_text[-300:]

    return all_segments
