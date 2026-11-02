"""
Transcript Exporter Service (app/services/exporter.py)
------------------------------------------------------
Formats and exports TranscriptionResult objects into TXT, JSON, SRT, VTT, CSV,
and Markdown (.md) formats with accurate chronological timestamps and speaker labels.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Tuple

from app.models.schemas import TranscriptionResult
from app.services.audio_engine import format_timestamp_srt, format_timestamp_vtt

SUPPORTED_EXPORT_FORMATS = {"txt", "json", "srt", "vtt", "csv", "md"}


def export_to_txt(result: TranscriptionResult) -> str:
    """Format transcription result as readable chronological plain text."""
    lines = [
        "======================================================================",
        "TRANSCRIPCIÓN DE AUDIO Y DIARIZACIÓN DE ORADORES",
        "======================================================================",
        f"ID de Trabajo     : {result.job_id}",
        f"Duración Total    : {result.total_duration_formatted} ({result.total_duration_sec:.2f}s)",
        f"Oradores Detectados: {result.detected_speakers_count}",
        f"Modelo Whisper    : {result.model_used}",
    ]
    if result.file_order:
        lines.append(f"Orden de Archivos : {', '.join(result.file_order)}")
    lines.append("======================================================================\n")

    current_file = None
    for seg in result.segments:
        if seg.source_file and seg.source_file != current_file:
            current_file = seg.source_file
            lines.append(f"\n--- [Archivo #{seg.file_order_index + 1}: {current_file}] ---")
        lines.append(
            f"[{seg.start_formatted} - {seg.end_formatted}] {seg.speaker}: {seg.text}"
        )

    return "\n".join(lines).strip() + "\n"


def export_to_srt(result: TranscriptionResult) -> str:
    """Format transcription result as standard SubRip (.srt) subtitles."""
    blocks = []
    for idx, seg in enumerate(result.segments, start=1):
        start_srt = format_timestamp_srt(seg.start)
        end_srt = format_timestamp_srt(max(seg.end, seg.start + 0.1))
        blocks.append(f"{idx}\n{start_srt} --> {end_srt}\n[{seg.speaker}] {seg.text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def export_to_vtt(result: TranscriptionResult) -> str:
    """Format transcription result as WebVTT (.vtt) subtitles."""
    blocks = ["WEBVTT"]
    for idx, seg in enumerate(result.segments, start=1):
        start_vtt = format_timestamp_vtt(seg.start)
        end_vtt = format_timestamp_vtt(max(seg.end, seg.start + 0.1))
        blocks.append(f"{idx}\n{start_vtt} --> {end_vtt}\n<v {seg.speaker}>{seg.text}")
    return "\n\n".join(blocks) + "\n"


def export_to_json(result: TranscriptionResult) -> str:
    """Format transcription result as pretty-printed UTF-8 JSON."""
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"


def export_to_csv(result: TranscriptionResult) -> str:
    """Format transcription result as UTF-8 CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "file_order_index",
        "source_file",
        "start_sec",
        "end_sec",
        "start_formatted",
        "end_formatted",
        "speaker",
        "text",
    ])
    for seg in result.segments:
        writer.writerow([
            seg.id,
            seg.file_order_index,
            seg.source_file,
            f"{seg.start:.3f}",
            f"{seg.end:.3f}",
            seg.start_formatted,
            seg.end_formatted,
            seg.speaker,
            seg.text,
        ])
    return output.getvalue()


def export_to_md(result: TranscriptionResult) -> str:
    """Format transcription result as structured Markdown."""
    lines = [
        "# Transcripción de Audio con Marcas de Tiempo y Oradores",
        "",
        f"- **Job ID:** `{result.job_id}`",
        f"- **Duración Total:** `{result.total_duration_formatted}` ({result.total_duration_sec:.2f}s)",
        f"- **Oradores Detectados:** `{result.detected_speakers_count}`",
        f"- **Modelo:** `{result.model_used}`",
    ]
    if result.file_order:
        lines.append(f"- **Secuencia de Archivos:** {', '.join(f'`{f}`' for f in result.file_order)}")
    lines.append("\n---\n")

    current_file = None
    for seg in result.segments:
        if seg.source_file and seg.source_file != current_file:
            current_file = seg.source_file
            lines.append(f"\n### Archivo #{seg.file_order_index + 1}: `{current_file}`\n")
        lines.append(
            f"- **`[{seg.start_formatted} - {seg.end_formatted}]` {seg.speaker}:** {seg.text}"
        )

    return "\n".join(lines).strip() + "\n"


def format_transcript_export(
    result: TranscriptionResult, fmt: str
) -> Tuple[str, str, str]:
    """
    Generate exported content, MIME media_type, and file extension for the requested format.

    Returns:
        (content_str, media_type, file_extension)
    """
    clean_fmt = fmt.strip().lower().lstrip(".")
    if clean_fmt not in SUPPORTED_EXPORT_FORMATS:
        raise ValueError(
            f"Formato de exportación no soportado: '{fmt}'. "
            f"Formatos válidos: {', '.join(sorted(SUPPORTED_EXPORT_FORMATS))}"
        )

    if clean_fmt == "txt":
        return export_to_txt(result), "text/plain; charset=utf-8", "txt"
    if clean_fmt == "srt":
        return export_to_srt(result), "application/x-subrip; charset=utf-8", "srt"
    if clean_fmt == "vtt":
        return export_to_vtt(result), "text/vtt; charset=utf-8", "vtt"
    if clean_fmt == "json":
        return export_to_json(result), "application/json; charset=utf-8", "json"
    if clean_fmt == "csv":
        return export_to_csv(result), "text/csv; charset=utf-8", "csv"
    if clean_fmt == "md":
        return export_to_md(result), "text/markdown; charset=utf-8", "md"

    raise ValueError(f"Unsupported format: {fmt}")
