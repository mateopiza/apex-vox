"""
Transcript Quality Control, Hallucination Filter & Format Cleaner
(app/services/transcript_cleaner.py)
-----------------------------------------------------------------
Eliminates Whisper silence/dead-air hallucinations and formatting noise
before delivering the transcript to the user:

1. Known Whisper boilerplate hallucinations (Amara.org, subtítulos, etc.).
2. Isolated noise tokens ("y", "3", "no y", "no no no no", "gracias gracias").
3. Consecutive repetitive monosyllable/short-word loops ("no" x10, "y" x14, "gracias" x47).
4. Post-meeting / dead-air sparse hallucination tails (e.g., 30-second periodic
   "gracias" or short random 1-5 word phantom phrases during silent stretches).
5. Acoustic RMS silence verification when the audio file is present.
6. Text formatting normalization (punctuation, whitespace, repeated stutters).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, List, Optional, Sequence, TypeVar

import numpy as np

from app.models.schemas import DiarizedSegment, WhisperSegment
from app.services.acoustic_diarizer import SAMPLE_RATE, load_pcm_float32

logger = logging.getLogger("app.services.transcript_cleaner")

SegT = TypeVar("SegT", WhisperSegment, DiarizedSegment)

# 1. Known Whisper silence hallucination boilerplate patterns
BOILERPLATE_HALLUCINATION_RE = re.compile(
    r"(subt[ií]tulos\s+(realizados|creados|por)|amara\.org|suscr[ií]bete\s+al\s+canal|"
    r"gracias\s+por\s+ver\s+el\s+v[ií]deo|transcripci[oó]n\s+por|traducci[oó]n\s+por|"
    r"copyright\s+\d{4}|todos\s+los\s+derechos\s+reservados)",
    re.IGNORECASE,
)

# 2. Pure noise tokens that are never valid standalone speech segments
PURE_NOISE_TOKENS = {
    "y",
    "e",
    "o",
    "u",
    "a",
    "eh",
    "ah",
    "mm",
    "mmm",
    "hm",
    "uh",
    "um",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
    "no y",
    "y no",
    "y sí",
    "sí y",
    "porque no",
}

# 3. Words commonly hallucinated by Whisper on 30s silence windows
SILENCE_LOOP_WORDS = {
    "gracias",
    "muchas gracias",
    "no",
    "sí",
    "si",
    "y",
    "bueno",
    "bien",
    "usted",
    "por mí",
    "por mi",
}


def _normalize_for_match(text: str) -> str:
    """Lowercase and strip punctuation/extra spaces for hallucination matching."""
    cleaned = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _words_of(text: str) -> List[str]:
    norm = _normalize_for_match(text)
    return norm.split() if norm else []


def _is_repetitive_word_loop(words: List[str]) -> bool:
    """
    Detect intra-segment repetition loops such as:
    - "no no no no", "no no"
    - "gracias gracias", "Gracias Gracias Gracias"
    - "y y y"
    """
    if len(words) < 2:
        return False
    unique = set(words)
    if len(unique) == 1 and words[0] in {"no", "gracias", "y", "sí", "si", "bueno", "bien", "hola", "3"}:
        return True
    # Check if >= 80% of tokens in a short segment are the same filler word
    if len(words) <= 6:
        for w in unique:
            if w in {"no", "gracias", "y", "sí", "si"} and (words.count(w) / len(words)) >= 0.75:
                return True
    return False


def _is_immediate_noise_segment(text: str) -> bool:
    """Return True if a segment is unconditionally a Whisper noise artifact."""
    norm = _normalize_for_match(text)
    if not norm:
        return True
    if BOILERPLATE_HALLUCINATION_RE.search(norm):
        return True
    if norm in PURE_NOISE_TOKENS:
        return True
    words = norm.split()
    if _is_repetitive_word_loop(words):
        return True
    # Single numeric token or single character
    if len(words) == 1 and (words[0].isdigit() or len(words[0]) <= 1):
        return True
    return False


def _get_start(seg: Any) -> float:
    if hasattr(seg, "global_start"):
        return float(seg.global_start)
    return float(getattr(seg, "start", 0.0))


def _get_end(seg: Any) -> float:
    if hasattr(seg, "global_end"):
        return float(seg.global_end)
    return float(getattr(seg, "end", 0.0))


def _clean_segment_text_format(text: str) -> str:
    """Clean internal formatting glitches in valid segments."""
    s = re.sub(r"\s+", " ", text).strip()
    # Collapse 3+ consecutive identical words inside a sentence (e.g. "gracias gracias gracias Sebas" -> "Gracias, Sebas")
    s = re.sub(
        r"\b(gracias|no|s[ií]|y|bueno|eh)\b(?:\s+\1\b){2,}",
        r"\1",
        s,
        flags=re.IGNORECASE,
    )
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s


def filter_hallucinated_segments(
    segments: Sequence[SegT],
    audio_path: Optional[Path] = None,
) -> List[SegT]:
    """
    Multi-pass quality control filter that removes Whisper silence hallucinations,
    repetitive token loops, and post-meeting dead-air phantom phrases.
    Works on both `WhisperSegment` and `DiarizedSegment` lists.
    """
    if not segments:
        return []

    n_total = len(segments)
    keep_flags = [True] * n_total
    norm_texts = [_normalize_for_match(s.text) for s in segments]
    word_lists = [_words_of(s.text) for s in segments]
    word_counts = [len(w) for w in word_lists]
    starts = [_get_start(s) for s in segments]
    ends = [_get_end(s) for s in segments]

    # Calculate gap before and after each segment
    gaps_before: List[float] = []
    gaps_after: List[float] = []
    for i in range(n_total):
        gb = max(0.0, starts[i] - ends[i - 1]) if i > 0 else starts[i]
        ga = max(0.0, starts[i + 1] - ends[i]) if i + 1 < n_total else 30.0
        gaps_before.append(gb)
        gaps_after.append(ga)

    # -------------------------------------------------------------------------
    # Pass 1: Unconditional Noise & Intra-Segment Repetition Filter
    # -------------------------------------------------------------------------
    for i, seg in enumerate(segments):
        if _is_immediate_noise_segment(seg.text):
            keep_flags[i] = False

    # -------------------------------------------------------------------------
    # Pass 2: Consecutive / Cluster Repetition Filter
    # (e.g. runs of "no", "gracias", "y" or identical short phrases)
    # -------------------------------------------------------------------------
    for i in range(n_total):
        if not keep_flags[i]:
            continue
        norm_i = norm_texts[i]
        wc_i = word_counts[i]

        if wc_i <= 3:
            # Count how many nearby segments in [i-4 .. i+4] have the same normalized text
            # or belong to SILENCE_LOOP_WORDS
            win_start = max(0, i - 4)
            win_end = min(n_total, i + 5)
            same_count = sum(
                1
                for j in range(win_start, win_end)
                if j != i and norm_texts[j] == norm_i
            )
            if same_count >= 2:
                keep_flags[i] = False
                continue

            # Isolated 1-word "gracias" / "no" / "sí" surrounded by long silences (>= 8s before & after)
            if norm_i in SILENCE_LOOP_WORDS and gaps_before[i] >= 8.0 and gaps_after[i] >= 8.0:
                keep_flags[i] = False

    # -------------------------------------------------------------------------
    # Pass 3: Sparse Dead-Air / Post-Meeting Silence Zone Detector
    # Detects stretches where real conversation has stopped (low words-per-minute,
    # large inter-segment gaps, dominated by short 1-5 word phantom hallucinations).
    # -------------------------------------------------------------------------
    # Check rolling neighborhoods of 8 segments
    window_size = 8
    if n_total >= window_size:
        for i in range(n_total):
            if not keep_flags[i]:
                continue
            # Only consider short segments (<= 5 words) as candidates for dead-air noise
            if word_counts[i] > 5:
                continue

            w_lo = max(0, i - 3)
            w_hi = min(n_total, w_lo + window_size)
            w_lo = max(0, w_hi - window_size)

            win_indices = list(range(w_lo, w_hi))
            short_or_flagged = sum(
                1
                for j in win_indices
                if (not keep_flags[j]) or word_counts[j] <= 5 or norm_texts[j] in SILENCE_LOOP_WORDS
            )
            avg_words = sum(word_counts[j] for j in win_indices) / float(len(win_indices))
            span_sec = max(1.0, ends[w_hi - 1] - starts[w_lo])
            words_per_sec = sum(word_counts[j] for j in win_indices if keep_flags[j]) / span_sec

            # In dead-air hallucination stretches, almost all segments are short (<=5 words)
            # and speech density is very low (< 0.45 words/sec, vs ~2.2 words/sec in real speech)
            if short_or_flagged >= 7 and avg_words <= 3.8 and words_per_sec < 0.45:
                keep_flags[i] = False

    # -------------------------------------------------------------------------
    # Pass 4: Optional Acoustic RMS Energy Verification on borderline short segments
    # -------------------------------------------------------------------------
    if audio_path and audio_path.exists():
        try:
            full_pcm = load_pcm_float32(audio_path)
            if full_pcm.size > SAMPLE_RATE:
                for i in range(n_total):
                    if not keep_flags[i] or word_counts[i] > 5:
                        continue
                    # Check if borderline short segment has actual acoustic energy
                    if gaps_before[i] >= 3.0 or gaps_after[i] >= 3.0:
                        s_idx = max(0, int(starts[i] * SAMPLE_RATE))
                        e_idx = min(full_pcm.size, int(max(ends[i], starts[i] + 0.2) * SAMPLE_RATE))
                        seg_pcm = full_pcm[s_idx:e_idx]
                        if seg_pcm.size > 0:
                            rms = float(np.sqrt(np.mean(seg_pcm ** 2)))
                            # rms < 0.004 corresponds to ~ -48 dBFS (background silence)
                            if rms < 0.004:
                                keep_flags[i] = False
        except Exception as exc:
            logger.debug("Acoustic RMS silence check skipped: %s", exc)

    # -------------------------------------------------------------------------
    # Pass 5: Rebuild Clean, Re-Indexed Segment List with Formatted Text
    # -------------------------------------------------------------------------
    cleaned_segments: List[SegT] = []
    new_id = 0
    for i, seg in enumerate(segments):
        if not keep_flags[i]:
            continue
        polished_text = _clean_segment_text_format(seg.text)
        if not polished_text or _is_immediate_noise_segment(polished_text):
            continue
        cleaned_segments.append(
            seg.model_copy(update={"id": new_id, "text": polished_text})
        )
        new_id += 1

    removed_count = n_total - len(cleaned_segments)
    if removed_count > 0:
        logger.info(
            "Transcript Cleaner removed %d hallucinated/noise segments (kept %d/%d).",
            removed_count,
            len(cleaned_segments),
            n_total,
        )

    return cleaned_segments
