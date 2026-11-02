"""
Speaker Diarization Service (app/services/diarization.py)
---------------------------------------------------------
Identifies and attributes speakers (1, 2, or multiple speakers automatically)
across timestamped segments using:
1. Deepgram Acoustic Voice Diarization (`deepgram` / `hybrid_deepgram_groq`).
2. Local Acoustic Voiceprint Clustering (`acoustic_local` via F0 pitch + Mel filterbank + Cepstral timbre).
3. Groq LLM (`llama-3.3-70b-versatile`) conversational turn-taking & role attribution (`groq_llm`).
4. Enrolled Voice Profile Recognition (`match_enrolled_voice_profiles`) to label known voices by name.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from groq import Groq

from app.config import settings
from app.models.schemas import DiarizedSegment, WhisperSegment
from app.services.acoustic_diarizer import match_enrolled_voice_profiles
from app.services.audio_engine import format_timestamp_hhmmss
from app.services.groq_service import get_groq_client

logger = logging.getLogger("app.services.diarization")

QUESTION_RE = re.compile(r"[¿?]")
GREETING_OR_TURN_START_RE = re.compile(
    r"^(hola|buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|claro|exacto|"
    r"s[ií]\b|no\b|bueno|mira|oye|gracias|perfecto|entiendo|de\s+acuerdo|"
    r"efectivamente|por\s+supuesto|well|yes|no|sure|right|hello|hi\b)",
    re.IGNORECASE,
)


def _normalize_speaker_label(raw_label: str, max_speakers: Optional[int] = None) -> str:
    """Normalize speaker labels to 'Hablante N' format unless a custom role/name is given."""
    if not raw_label or not str(raw_label).strip():
        return "Hablante 1"
    clean = str(raw_label).strip()
    m = re.match(r"^(?:speaker|orador|hablante|locutor|persona)[_\s-]*(\d+)$", clean, re.IGNORECASE)
    if m:
        idx = int(m.group(1))
        if idx == 0:
            idx = 1
        if max_speakers and max_speakers > 0:
            idx = ((idx - 1) % max_speakers) + 1
        return f"Hablante {idx}"
    return clean


def heuristic_diarize_segments(
    segments: List[WhisperSegment],
    num_speakers: Optional[int] = None,
    pause_threshold_sec: Optional[float] = None,
) -> Tuple[Dict[int, str], Dict[str, str]]:
    """
    Deterministic acoustic-pause and conversational turn-taking diarizer.
    Respects `seg.acoustic_speaker` when present from Deepgram or Local Voiceprint.
    """
    if not segments:
        return {}, {}

    if num_speakers == 1:
        assignments = {seg.id: "Hablante 1" for seg in segments}
        return assignments, {"Hablante 1": "Orador principal"}

    # Check if segments already carry acoustic speaker labels (from Deepgram or Acoustic Clustering)
    has_acoustic_labels = any(bool(s.acoustic_speaker) for s in segments)
    if has_acoustic_labels:
        assignments = {}
        for seg in segments:
            lbl = _normalize_speaker_label(
                seg.acoustic_speaker or "Hablante 1",
                max_speakers=num_speakers,
            )
            assignments[seg.id] = lbl
        unique_spks = list(dict.fromkeys(assignments.values()))
        roles = {spk: f"Voz detectada acústicamente #{i + 1}" for i, spk in enumerate(unique_spks)}
        return assignments, roles

    threshold = (
        pause_threshold_sec
        if pause_threshold_sec is not None
        else settings.ACOUSTIC_PAUSE_THRESHOLD_SEC
    )
    target_max = num_speakers if (num_speakers and num_speakers >= 2) else 2

    assignments = {}
    current_speaker_idx = 1
    prev_text = ""
    prev_file_idx = segments[0].file_order_index

    for i, seg in enumerate(segments):
        if i == 0:
            assignments[seg.id] = f"Hablante {current_speaker_idx}"
            prev_text = seg.text.strip()
            prev_file_idx = seg.file_order_index
            continue

        text = seg.text.strip()
        prev_was_question = bool(QUESTION_RE.search(prev_text))
        curr_is_turn_cue = bool(GREETING_OR_TURN_START_RE.search(text))
        significant_pause = seg.pause_before >= threshold
        long_pause = seg.pause_before >= max(1.2, threshold * 2.0)
        file_changed = seg.file_order_index != prev_file_idx

        should_switch = False
        if prev_was_question and (seg.pause_before >= 0.15 or curr_is_turn_cue):
            should_switch = True
        elif significant_pause and curr_is_turn_cue:
            should_switch = True
        elif long_pause:
            should_switch = True
        elif file_changed and seg.pause_before >= 0.2:
            should_switch = True

        if should_switch:
            current_speaker_idx = (current_speaker_idx % target_max) + 1

        assignments[seg.id] = f"Hablante {current_speaker_idx}"
        prev_text = text
        prev_file_idx = seg.file_order_index

    unique_speakers = list(dict.fromkeys(assignments.values()))
    roles = {spk: f"Participante {idx + 1}" for idx, spk in enumerate(unique_speakers)}
    return assignments, roles


def _build_llm_diarization_prompt(
    batch_segments: List[WhisperSegment],
    num_speakers: Optional[int],
    context_tail: List[Tuple[WhisperSegment, str]],
    preserve_acoustic_tags: bool = False,
) -> Tuple[str, str]:
    """Construct system and user prompts for Groq Llama 3.3 speaker diarization."""
    if num_speakers and num_speakers >= 2:
        speaker_constraint = (
            f"El usuario especificó que hay exactamente {num_speakers} oradores en el audio. "
            f"Usa etiquetas desde 'Hablante 1' hasta 'Hablante {num_speakers}'."
        )
    else:
        speaker_constraint = (
            "Detecta automáticamente el número real de oradores (1, 2 o varios). "
            "Si es un monólogo o narración de una sola persona, asigna todos los segmentos a 'Hablante 1'. "
            "Si hay 2 o más personas, identifica cada cambio de turno y usa 'Hablante 1', 'Hablante 2', etc."
        )

    acoustic_instruction = (
        "Cada segmento incluye `acoustic_voice` obtenido por huella acústica de voz (Deepgram/Voiceprint). "
        "Mantén la separación de voces indicada por `acoustic_voice`, corrigiendo solo si una frase continua "
        "fue dividida erróneamente."
        if preserve_acoustic_tags
        else "Analiza las pistas acústicas (`pause_before` >= 0.4s suele indicar cambio de turno), "
             "signos de interrogación/respuesta, saludos, vocativos y cambios de archivo (`source_file`)."
    )

    system_prompt = (
        "Eres un experto en diarización acústica y lingüística de transcripciones de audio.\n"
        "Tu tarea es analizar una secuencia cronológica de segmentos transcritos con sus marcas de tiempo, "
        "pausas acústicas previas y etiquetas de huella vocal para identificar qué orador pronuncia cada segmento.\n\n"
        "Reglas estrictas:\n"
        f"1. {speaker_constraint}\n"
        f"2. {acoustic_instruction}\n"
        "3. NO modifiques el texto ni los timestamps; solo devuelve el mapeo por `id` de segmento.\n"
        "4. Responde ÚNICAMENTE con un objeto JSON válido con la siguiente estructura exacta:\n"
        "{\n"
        '  "detected_speakers_count": 2,\n'
        '  "speaker_roles": {"Hablante 1": "Descripción breve del rol", "Hablante 2": "Descripción breve"},\n'
        '  "assignments": [\n'
        '    {"id": 0, "speaker": "Hablante 1"},\n'
        '    {"id": 1, "speaker": "Hablante 2"}\n'
        "  ]\n"
        "}"
    )

    lines: List[str] = []
    if context_tail:
        lines.append("=== CONTEXTO PREVIO ===")
        for seg, spk in context_tail:
            lines.append(
                f"[ID={seg.id}] ({format_timestamp_hhmmss(seg.global_start)} - "
                f"{format_timestamp_hhmmss(seg.global_end)}, pause={seg.pause_before:.2f}s) "
                f"-> {spk}: {seg.text}"
            )
        lines.append("\n=== SEGMENTOS A CLASIFICAR ===")

    for seg in batch_segments:
        voice_hint = f", acoustic_voice={seg.acoustic_speaker}" if seg.acoustic_speaker else ""
        lines.append(
            f"[ID={seg.id}] (file={seg.source_file}, "
            f"{format_timestamp_hhmmss(seg.global_start)}-{format_timestamp_hhmmss(seg.global_end)}, "
            f"pause_before={seg.pause_before:.2f}s{voice_hint}): {seg.text}"
        )

    user_prompt = "\n".join(lines)
    return system_prompt, user_prompt


def _call_llm_diarizer_batch(
    client: Groq,
    batch_segments: List[WhisperSegment],
    num_speakers: Optional[int],
    context_tail: List[Tuple[WhisperSegment, str]],
    preserve_acoustic_tags: bool = False,
) -> Tuple[Dict[int, str], Dict[str, str]]:
    """Run LLM diarization on a batch of segments with model fallback."""
    system_prompt, user_prompt = _build_llm_diarization_prompt(
        batch_segments=batch_segments,
        num_speakers=num_speakers,
        context_tail=context_tail,
        preserve_acoustic_tags=preserve_acoustic_tags,
    )

    models_to_try = [settings.DEFAULT_LLM_MODEL, settings.FALLBACK_LLM_MODEL]
    last_err: Optional[Exception] = None

    for llm_model in models_to_try:
        try:
            completion = client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=settings.DIARIZATION_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content or "{}"
            parsed = json.loads(content)

            raw_assignments = parsed.get("assignments") or []
            raw_roles = parsed.get("speaker_roles") or {}

            batch_map: Dict[int, str] = {}
            for item in raw_assignments:
                if isinstance(item, dict) and "id" in item and "speaker" in item:
                    seg_id = int(item["id"])
                    spk = _normalize_speaker_label(str(item["speaker"]), max_speakers=num_speakers)
                    batch_map[seg_id] = spk

            roles_map: Dict[str, str] = {}
            if isinstance(raw_roles, dict):
                for k, v in raw_roles.items():
                    norm_k = _normalize_speaker_label(str(k), max_speakers=num_speakers)
                    roles_map[norm_k] = str(v)

            if batch_map:
                return batch_map, roles_map
        except Exception as exc:
            last_err = exc
            logger.warning("LLM diarization attempt with %s failed: %s", llm_model, exc)

    raise RuntimeError(f"LLM diarization failed across all configured models: {last_err}")


def diarize_segments(
    segments: List[WhisperSegment],
    num_speakers: Optional[int] = None,
    api_key: Optional[str] = None,
    client: Optional[Groq] = None,
    batch_size: int = 100,
    merged_audio_path: Optional[Path] = None,
    trust_acoustic_labels: bool = False,
    voice_owner_id: Optional[str] = None,
) -> Tuple[List[DiarizedSegment], int, Dict[str, str]]:
    """
    Perform speaker diarization across a chronological list of WhisperSegments.
    Matches against enrolled voice profiles when merged_audio_path is provided.
    """
    if not segments:
        return [], 0, {}

    effective_num_speakers = num_speakers if (num_speakers and num_speakers > 0) else None
    has_acoustic = any(bool(s.acoustic_speaker) for s in segments)

    if effective_num_speakers == 1 or len(segments) == 1:
        assignments, roles = heuristic_diarize_segments(segments, num_speakers=1)
    elif trust_acoustic_labels and has_acoustic:
        # Directly preserve Deepgram / Acoustic Voiceprint labels
        assignments, roles = heuristic_diarize_segments(
            segments=segments,
            num_speakers=effective_num_speakers,
        )
    else:
        heuristic_map, heuristic_roles = heuristic_diarize_segments(
            segments=segments,
            num_speakers=effective_num_speakers,
        )
        assignments = dict(heuristic_map)
        roles = dict(heuristic_roles)

        try:
            groq_client = client or get_groq_client(api_key=api_key)
            llm_roles: Dict[str, str] = {}
            context_tail: List[Tuple[WhisperSegment, str]] = []

            for start_idx in range(0, len(segments), batch_size):
                batch = segments[start_idx : start_idx + batch_size]
                batch_map, batch_roles = _call_llm_diarizer_batch(
                    client=groq_client,
                    batch_segments=batch,
                    num_speakers=effective_num_speakers,
                    context_tail=context_tail,
                    preserve_acoustic_tags=has_acoustic,
                )
                for seg in batch:
                    if seg.id in batch_map:
                        assignments[seg.id] = batch_map[seg.id]
                llm_roles.update(batch_roles)
                context_tail = [(seg, assignments[seg.id]) for seg in batch[-8:]]

            if llm_roles:
                roles = llm_roles
        except Exception as exc:
            logger.warning(
                "Falling back to acoustic diarization labels due to LLM error: %s",
                exc,
            )

    # Match speaker clusters against Enrolled Voice Profiles (if any exist)
    if merged_audio_path and merged_audio_path.exists():
        try:
            assignments, matched_roles = match_enrolled_voice_profiles(
                audio_path=merged_audio_path,
                segments=segments,
                speaker_assignments=assignments,
                owner_id=voice_owner_id,
            )
            roles.update(matched_roles)
        except Exception as exc:
            logger.warning("Voice profile matching skipped: %s", exc)

    diarized: List[DiarizedSegment] = []
    seen_speakers: List[str] = []

    for seg in segments:
        speaker_label = assignments.get(seg.id, "Hablante 1")
        if speaker_label not in seen_speakers:
            seen_speakers.append(speaker_label)

        diarized.append(
            DiarizedSegment(
                id=seg.id,
                start=round(seg.global_start, 3),
                end=round(seg.global_end, 3),
                speaker=speaker_label,
                text=seg.text,
                start_formatted=format_timestamp_hhmmss(seg.global_start),
                end_formatted=format_timestamp_hhmmss(seg.global_end),
                source_file=seg.source_file,
                file_order_index=seg.file_order_index,
            )
        )

    final_roles: Dict[str, str] = {}
    for idx, spk in enumerate(seen_speakers):
        final_roles[spk] = roles.get(spk) or f"Orador identificado #{idx + 1}"

    return diarized, len(seen_speakers), final_roles
