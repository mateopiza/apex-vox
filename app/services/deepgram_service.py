"""
Deepgram Acoustic Diarization & Speech-to-Text Service (app/services/deepgram_service.py)
-----------------------------------------------------------------------------------------
Integrates with Deepgram's Nova-2 API (`https://api.deepgram.com/v1/listen`) with
`diarize=true` and `utterances=true` for true acoustic voice timbre speaker
separation and word-level speaker attribution.

Supports:
1. Direct Deepgram Transcription + Acoustic Speaker Diarization (`deepgram` mode).
2. Hybrid Groq Whisper + Deepgram Acoustic Diarization (`hybrid_deepgram_groq` mode),
   mapping Deepgram's word-level acoustic speaker timeline onto Groq Whisper segments.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from app.config import settings
from app.models.schemas import WhisperSegment
from app.services.groq_service import retry_delay
from app.services.audio_engine import AudioChunkInfo

logger = logging.getLogger("app.services.deepgram_service")

DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"


class DeepgramServiceError(RuntimeError):
    """Raised when Deepgram fails. Carries the HTTP status and headers to decide about retrying."""

    def __init__(self, message: str, status_code: Optional[int] = None, headers: Optional[Any] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = headers


def get_deepgram_api_key(override_key: Optional[str] = None) -> str:
    """Resolve Deepgram API key from override or environment."""
    key = (override_key or settings.DEEPGRAM_API_KEY or "").strip()
    if not key:
        raise DeepgramServiceError(
            "DEEPGRAM_API_KEY no está configurada. Defínala en .env o en la interfaz web."
        )
    return key


def call_deepgram_listen(
    audio_path: Path | str,
    language: Optional[str] = None,
    deepgram_api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call Deepgram /v1/listen endpoint with diarize=true, utterances=true,
    smart_format=true, and punctuate=true.
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio chunk not found for Deepgram: {path}")

    api_key = get_deepgram_api_key(deepgram_api_key)
    dg_model = model or settings.DEEPGRAM_MODEL or "nova-2"

    params: Dict[str, str] = {
        "model": dg_model,
        "diarize": "true",
        "utterances": "true",
        "smart_format": "true",
        "punctuate": "true",
    }

    if language and language.strip() and language.strip().lower() != "auto":
        params["language"] = language.strip().lower()
    else:
        params["detect_language"] = "true"

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "audio/mpeg",
    }

    max_attempts = max(1, settings.GROQ_MAX_RETRIES)
    last_err: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            with open(path, "rb") as f:
                resp = requests.post(
                    DEEPGRAM_LISTEN_URL,
                    params=params,
                    headers=headers,
                    data=f,
                    timeout=settings.GROQ_TIMEOUT_SECONDS,
                )
            if resp.status_code >= 400:
                logger.warning("Deepgram HTTP %s for %s: %s", resp.status_code, path.name, resp.text[:300])
                raise DeepgramServiceError(f"Deepgram HTTP {resp.status_code}", resp.status_code, resp.headers)
            return resp.json()
        except Exception as exc:
            last_err = exc
            logger.warning(
                "Deepgram attempt %d/%d failed for %s: %s",
                attempt,
                max_attempts,
                path.name,
                exc,
            )
            delay = retry_delay(
                attempt, getattr(exc, "status_code", None), getattr(exc, "headers", None), cap=6.0
            )
            if delay is None:
                break
            if attempt < max_attempts:
                time.sleep(delay)

    raise DeepgramServiceError(
        f"Error en Deepgram API para '{path.name}': {type(last_err).__name__}"
    ) from last_err


def extract_deepgram_utterances_and_words(
    dg_json: Dict[str, Any],
    max_speakers: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parse Deepgram response into:
    1. utterances: [{'start': float, 'end': float, 'text': str, 'speaker': 'Hablante N', 'confidence': float}]
    2. words: [{'start': float, 'end': float, 'word': str, 'speaker': 'Hablante N'}]
    """
    results = dg_json.get("results") or {}
    utterances_raw = results.get("utterances") or []
    channels = results.get("channels") or []

    def _spk_label(raw_spk: Any) -> str:
        try:
            idx = int(raw_spk) + 1
        except (ValueError, TypeError):
            idx = 1
        if max_speakers and max_speakers > 0:
            idx = ((idx - 1) % max_speakers) + 1
        return f"Hablante {idx}"

    words_list: List[Dict[str, Any]] = []
    if channels:
        alts = channels[0].get("alternatives") or []
        if alts:
            for w in alts[0].get("words") or []:
                w_text = str(w.get("punctuated_word") or w.get("word") or "").strip()
                if not w_text:
                    continue
                words_list.append({
                    "start": float(w.get("start", 0.0)),
                    "end": float(w.get("end", 0.0)),
                    "word": w_text,
                    "speaker": _spk_label(w.get("speaker", 0)),
                    "confidence": float(w.get("speaker_confidence") or w.get("confidence") or 0.9),
                })

    utterances: List[Dict[str, Any]] = []
    for u in utterances_raw:
        u_text = str(u.get("transcript") or "").strip()
        if not u_text:
            continue
        utterances.append({
            "start": float(u.get("start", 0.0)),
            "end": float(u.get("end", 0.0)),
            "text": u_text,
            "speaker": _spk_label(u.get("speaker", 0)),
            "confidence": float(u.get("confidence", 0.9)),
        })

    # If utterances wasn't populated but words exist, group consecutive words by speaker
    if not utterances and words_list:
        curr_spk = words_list[0]["speaker"]
        curr_start = words_list[0]["start"]
        curr_end = words_list[0]["end"]
        curr_words = [words_list[0]["word"]]

        for w in words_list[1:]:
            pause = w["start"] - curr_end
            if w["speaker"] != curr_spk or pause > 1.2:
                utterances.append({
                    "start": curr_start,
                    "end": curr_end,
                    "text": " ".join(curr_words),
                    "speaker": curr_spk,
                    "confidence": 0.9,
                })
                curr_spk = w["speaker"]
                curr_start = w["start"]
                curr_words = [w["word"]]
            else:
                curr_words.append(w["word"])
            curr_end = w["end"]

        if curr_words:
            utterances.append({
                "start": curr_start,
                "end": curr_end,
                "text": " ".join(curr_words),
                "speaker": curr_spk,
                "confidence": 0.9,
            })

    return utterances, words_list


def transcribe_and_diarize_chunks_deepgram(
    chunks: List[AudioChunkInfo],
    language: Optional[str] = None,
    num_speakers: Optional[int] = None,
    deepgram_api_key: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[WhisperSegment]:
    """
    Transcribe and acoustically diarize an ordered sequence of audio chunks
    directly using Deepgram Nova-2 (`diarize=true`).
    """
    if not chunks:
        return []

    all_segments: List[WhisperSegment] = []
    global_seg_id = 0
    prev_global_end: Optional[float] = None
    total_chunks = len(chunks)

    for idx, chunk in enumerate(chunks):
        if progress_callback:
            progress_callback(
                idx,
                total_chunks,
                f"Analizando voz y transcribiendo fragmento {idx + 1}/{total_chunks} con Deepgram ({chunk.source_file_name})...",
            )

        dg_json = call_deepgram_listen(
            audio_path=chunk.file_path,
            language=language,
            deepgram_api_key=deepgram_api_key,
        )
        utterances, _ = extract_deepgram_utterances_and_words(
            dg_json, max_speakers=num_speakers
        )

        for utt in utterances:
            l_start = float(utt["start"])
            l_end = max(l_start, float(utt["end"]))
            text = str(utt["text"]).strip()
            if not text:
                continue

            g_start = round(chunk.global_start_sec + l_start, 3)
            g_end = round(chunk.global_start_sec + l_end, 3)

            if prev_global_end is None:
                pause_before = round(max(0.0, l_start), 3)
            else:
                pause_before = round(max(0.0, g_start - prev_global_end), 3)

            spk = "Hablante 1" if num_speakers == 1 else utt["speaker"]

            all_segments.append(
                WhisperSegment(
                    id=global_seg_id,
                    start=round(l_start, 3),
                    end=round(l_end, 3),
                    text=text,
                    global_start=g_start,
                    global_end=g_end,
                    source_file=chunk.source_file_name,
                    file_order_index=chunk.file_sequence_index,
                    pause_before=pause_before,
                    acoustic_speaker=spk,
                )
            )
            global_seg_id += 1
            prev_global_end = g_end

    return all_segments


def align_groq_segments_with_deepgram_diarization(
    chunks: List[AudioChunkInfo],
    groq_segments: List[WhisperSegment],
    language: Optional[str] = None,
    num_speakers: Optional[int] = None,
    deepgram_api_key: Optional[str] = None,
) -> List[WhisperSegment]:
    """
    Hybrid pipeline:
    Takes high-accuracy Groq Whisper segments and aligns each segment with
    Deepgram's word-level acoustic speaker timeline using maximum temporal overlap.
    """
    if not groq_segments or not chunks:
        return groq_segments

    if num_speakers == 1:
        return [
            seg.model_copy(update={"acoustic_speaker": "Hablante 1"})
            for seg in groq_segments
        ]

    # Collect global word speaker intervals from Deepgram across all chunks
    global_dg_intervals: List[Tuple[float, float, str]] = []

    for chunk in chunks:
        try:
            dg_json = call_deepgram_listen(
                audio_path=chunk.file_path,
                language=language,
                deepgram_api_key=deepgram_api_key,
            )
            utterances, words = extract_deepgram_utterances_and_words(
                dg_json, max_speakers=num_speakers
            )
            if words:
                for w in words:
                    g_s = chunk.global_start_sec + float(w["start"])
                    g_e = chunk.global_start_sec + float(w["end"])
                    global_dg_intervals.append((g_s, max(g_s + 0.05, g_e), w["speaker"]))
            else:
                for u in utterances:
                    g_s = chunk.global_start_sec + float(u["start"])
                    g_e = chunk.global_start_sec + float(u["end"])
                    global_dg_intervals.append((g_s, max(g_s + 0.05, g_e), u["speaker"]))
        except Exception as exc:
            logger.warning(
                "Hybrid Deepgram acoustic pass failed on chunk %s: %s",
                chunk.file_path.name,
                exc,
            )

    if not global_dg_intervals:
        return groq_segments

    enriched: List[WhisperSegment] = []
    for seg in groq_segments:
        s_start = seg.global_start
        s_end = max(s_start + 0.05, seg.global_end)

        speaker_scores: Dict[str, float] = {}
        for iv_start, iv_end, spk in global_dg_intervals:
            if iv_end < s_start - 0.3:
                continue
            if iv_start > s_end + 0.3:
                break
            overlap = min(s_end, iv_end) - max(s_start, iv_start)
            if overlap > 0:
                speaker_scores[spk] = speaker_scores.get(spk, 0.0) + overlap

        if speaker_scores:
            best_spk = max(speaker_scores.items(), key=lambda kv: kv[1])[0]
        else:
            # Find nearest interval by midpoint distance
            seg_mid = (s_start + s_end) / 2.0
            nearest = min(
                global_dg_intervals,
                key=lambda iv: abs(((iv[0] + iv[1]) / 2.0) - seg_mid),
            )
            best_spk = nearest[2]

        enriched.append(seg.model_copy(update={"acoustic_speaker": best_spk}))

    return enriched
