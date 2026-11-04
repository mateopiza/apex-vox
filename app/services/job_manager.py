"""
Session & Job Manager Service (app/services/job_manager.py)
-----------------------------------------------------------
Manages multi-audio upload sessions, interactive sequence ordering,
background transcription/diarization pipeline execution, merged audio preview
generation, and persistent result storage.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, List, Optional, Union

from app.errors import UserFacingError, public_error
from app.logsafe import clean
from app.config import (
    get_public_engine_label,
    resolve_engine_code,
    resolve_model_code,
    settings,
)
from app.models.schemas import (
    DiarizedSegment,
    JobStatusResponse,
    TranscribeRequest,
    TranscriptionResult,
)
from app.services.acoustic_diarizer import cluster_segments_acoustically
from app.services.apex_summa import generate_apex_summa_report
from app.services.state_store import StateCorruptError, atomic_write_bytes, atomic_write_json, read_json
from app.services.audio_engine import (
    ProbedAudio,
    format_timestamp_hhmmss,
    probe_audio,
    process_audio_sequence,
)
from app.services.deepgram_service import (
    align_groq_segments_with_deepgram_diarization,
    transcribe_and_diarize_chunks_deepgram,
)
from app.services.diarization import diarize_segments
from app.services.groq_service import transcribe_chunks_sequence
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service
from app.services.transcript_cleaner import filter_hallucinated_segments

logger = logging.getLogger("app.services.job_manager")

_COPY_CHUNK_BYTES = 1024 * 1024
_SAFE_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TERMINAL_STATUSES = ("completed", "failed")
_ACTIVE_STATUSES = ("queued", "processing")
_FINISHED_JOB_MEMORY_SECONDS = 3600.0
_MAX_RESULTS_IN_MEMORY = 200
_INTERRUPTED_MESSAGE = (
    "El servidor se reinició mientras se procesaba este audio. Súbelo de nuevo; no se descontó de tu cuota. / "
    "The server restarted while processing this audio. Please upload it again; it did not count against your quota."
)
_TIMED_OUT_MESSAGE = (
    "Este audio tardó demasiado en procesarse. Intenta de nuevo; no se descontó de tu cuota. / "
    "This audio took too long to process. Please try again; it did not count against your quota."
)

# ffmpeg and the provider calls are heavy: only this many recordings are processed at once. Jobs
# stay "queued" while they wait. Nothing that holds a slot asks for another, so it cannot deadlock.
_pipeline_slots = threading.BoundedSemaphore(max(1, settings.JOB_CONCURRENCY))


@contextmanager
def pipeline_slot() -> Iterator[None]:
    with _pipeline_slots:
        yield


class JobTimeoutError(UserFacingError):
    """The job went over JOB_TIMEOUT_SECONDS."""


class UploadTooLargeError(ValueError):
    """An uploaded file went over its size limit. The message is safe to show to the user."""


def upload_too_large_message(limit_bytes: int) -> str:
    limit_mb = max(1, limit_bytes // (1024 * 1024))
    return f"El archivo supera el límite de {limit_mb} MB. / The file is over the {limit_mb} MB limit."


def _store_upload(content: Union[bytes, BinaryIO], dest: Path, max_bytes: Optional[int]) -> int:
    """Write an upload to disk without holding it in memory. Returns its size; nothing stays on failure."""
    if isinstance(content, (bytes, bytearray)):
        if max_bytes is not None and len(content) > max_bytes:
            raise UploadTooLargeError(upload_too_large_message(max_bytes))
        dest.write_bytes(content)
        return len(content)
    written = 0
    try:
        with open(dest, "wb") as out:
            while chunk := content.read(_COPY_CHUNK_BYTES):
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    raise UploadTooLargeError(upload_too_large_message(max_bytes))
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return written


@dataclass
class QuotaCharge:
    """What a job used of a plan or guest allowance, so a failure can give it back exactly once."""
    owner: str
    day: str
    audios: int
    seconds: float = 0.0
    guest: bool = False


@dataclass
class UploadedTrack:
    """Internal representation of an uploaded audio file within a session."""
    file_id: str
    filename: str
    file_path: Path
    probed: ProbedAudio


@dataclass
class UploadSession:
    """Holds uploaded tracks and user-defined sequence order."""
    session_id: str
    session_dir: Path
    tracks: Dict[str, UploadedTrack] = field(default_factory=dict)
    ordered_ids: List[str] = field(default_factory=list)
    owner: Optional[str] = None  # user id or guest key that created the session


class JobManager:
    """Thread-safe manager for upload sessions and transcription jobs."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, UploadSession] = {}
        self._jobs: Dict[str, JobStatusResponse] = {}
        self._results: Dict[str, TranscriptionResult] = {}
        self._job_owners: Dict[str, str] = {}  # job id -> cuenta o clave del invitado
        self._charges: Dict[str, QuotaCharge] = {}  # job id -> cargo pendiente de un trabajo en curso
        self._result_edit_locks: Dict[str, threading.Lock] = {}
        self._finished_at: Dict[str, float] = {}  # job id -> cuándo terminó (monotonic)
        self._guest_expiry: Dict[str, float] = {}  # job id -> cuándo se borra el resultado del invitado

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def create_or_get_session(self, session_id: Optional[str] = None, owner: Optional[str] = None) -> UploadSession:
        """Reuse the caller's own session; a foreign or unknown id starts a fresh one."""
        with self._lock:
            existing = self._sessions.get(session_id) if session_id else None
            if existing and (owner is None or existing.owner in (None, owner)):
                if existing.owner is None:
                    existing.owner = owner
                return existing

            sid = uuid.uuid4().hex[:16]
            session_dir = settings.UPLOAD_DIR / sid
            session_dir.mkdir(parents=True, exist_ok=True)
            session = UploadSession(session_id=sid, session_dir=session_dir, owner=owner)
            self._sessions[sid] = session
            return session

    def session_owned_by(self, session_id: str, owner: Optional[str]) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            return bool(session) and (session.owner is None or session.owner == owner)

    def discard_session(self, session_id: str) -> None:
        """Forget a session and delete its uploaded files (used for guest jobs)."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            shutil.rmtree(session.session_dir, ignore_errors=True)

    def _purge_guest_job(self, job_id: str) -> None:
        with self._lock:
            self._results.pop(job_id, None)
            self._jobs.pop(job_id, None)
            self._job_owners.pop(job_id, None)
            self._finished_at.pop(job_id, None)
            self._guest_expiry.pop(job_id, None)
            self._result_edit_locks.pop(job_id, None)
        (settings.OUTPUT_DIR / f"{job_id}_merged.mp3").unlink(missing_ok=True)
        job_file = self._job_file(job_id)
        if job_file:
            job_file.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # Job status on disk: it survives a restart, and interrupted jobs fail honestly
    # -------------------------------------------------------------------------

    @staticmethod
    def _job_file(job_id: str) -> Optional[Path]:
        if not _SAFE_JOB_ID.fullmatch(job_id or ""):
            return None
        return settings.OUTPUT_DIR / "jobs" / f"{job_id}.json"

    def _persist_job(self, job_id: str) -> None:
        """Save the job's status. A failure here must never stop the job itself."""
        job_file = self._job_file(job_id)
        with self._lock:
            status = self._jobs.get(job_id)
            if not status or not job_file:
                return
            charge = self._charges.get(job_id)
            record = {
                "status": status.model_dump(mode="json"),
                "owner": self._job_owners.get(job_id),
                "charge": asdict(charge) if charge else None,
            }
        try:
            atomic_write_json(job_file, record)
        except OSError as exc:
            logger.warning("Could not save the status of job %s: %s", clean(job_id), type(exc).__name__)

    def _read_job_file(self, job_id: str) -> Optional[Dict]:
        job_file = self._job_file(job_id)
        if not job_file or not job_file.exists():
            return None
        try:
            record = read_json(job_file)
        except StateCorruptError as exc:
            logger.warning("Unreadable job status: %s", exc)
            return None
        return record if isinstance(record, dict) else None

    def recover_interrupted_jobs(self) -> int:
        """At start-up: jobs that were running when the process stopped failed. Give back their quota."""
        recovered = 0
        for job_file in sorted((settings.OUTPUT_DIR / "jobs").glob("*.json")):
            job_id = job_file.stem
            with self._lock:
                if job_id in self._jobs:
                    continue  # lo está ejecutando este proceso
            record = self._read_job_file(job_id)
            if not record or (record.get("status") or {}).get("status") not in _ACTIVE_STATUSES:
                continue
            charge = record.get("charge")
            status = JobStatusResponse(**{
                **record["status"], "status": "failed", "error": _INTERRUPTED_MESSAGE,
                "current_step": f"Error: {_INTERRUPTED_MESSAGE}",
            })
            with self._lock:
                self._jobs[job_id] = status
                self._finished_at[job_id] = time.monotonic()
                if record.get("owner"):
                    self._job_owners[job_id] = record["owner"]
                if charge:
                    self._charges[job_id] = QuotaCharge(**charge)
            self._settle_charge(job_id, refund=True)
            self._persist_job(job_id)
            recovered += 1
        if recovered:
            logger.warning("Marked %d interrupted job(s) as failed after a restart.", recovered)
        return recovered

    def evict(self) -> None:
        """Drop what can be read back from disk, and expired guest results. Runs periodically."""
        now_wall, now = time.time(), time.monotonic()
        with self._lock:
            expired_guests = [j for j, at in self._guest_expiry.items() if at <= now_wall]
        for job_id in expired_guests:
            self._purge_guest_job(job_id)
        with self._lock:
            for job_id, finished in list(self._finished_at.items()):
                if job_id not in self._guest_expiry and now - finished >= _FINISHED_JOB_MEMORY_SECONDS:
                    self._jobs.pop(job_id, None)
                    self._job_owners.pop(job_id, None)
                    self._result_edit_locks.pop(job_id, None)
                    self._finished_at.pop(job_id, None)
            excess = len(self._results) - _MAX_RESULTS_IN_MEMORY
            for job_id in list(self._results):  # los menos usados primero
                if excess <= 0:
                    break
                if job_id not in self._guest_expiry and (settings.OUTPUT_DIR / f"{job_id}_result.json").exists():
                    del self._results[job_id]
                    excess -= 1

    def get_session(self, session_id: str) -> Optional[UploadSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def add_file_to_session(
        self,
        session_id: str,
        filename: str,
        content: Union[bytes, BinaryIO],
        owner: Optional[str] = None,
        max_bytes: Optional[int] = None,
    ) -> ProbedAudio:
        """Save an upload (bytes or an open file), probe with ffprobe, and register in session."""
        ext = Path(filename).suffix.lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Formato no soportado '{ext}' en '{filename}'. "
                f"Formatos permitidos: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}"
            )

        session = self.create_or_get_session(session_id, owner)
        file_id = f"track_{uuid.uuid4().hex[:8]}"
        safe_name = Path(filename).name
        dest_path = session.session_dir / f"{file_id}_{safe_name}"
        if _store_upload(content, dest_path, max_bytes) == 0:
            dest_path.unlink(missing_ok=True)
            raise ValueError(f"El archivo '{filename}' está vacío (0 bytes).")

        try:
            meta = probe_audio(dest_path)
        except Exception as exc:
            dest_path.unlink(missing_ok=True)
            logger.warning("Could not probe an upload: %s", type(exc).__name__)
            raise ValueError(
                f"El archivo '{safe_name}' no es un audio válido o está dañado. / "
                f"'{safe_name}' is not a valid audio file or is damaged."
            ) from exc

        probed = meta.to_probed_audio(file_id=file_id)
        # Preserve original user-facing filename
        probed.filename = safe_name

        with self._lock:
            track = UploadedTrack(
                file_id=file_id,
                filename=safe_name,
                file_path=dest_path,
                probed=probed,
            )
            session.tracks[file_id] = track
            session.ordered_ids.append(file_id)

        return probed

    def session_size_bytes(self, session_id: str) -> int:
        with self._lock:
            session = self._sessions.get(session_id)
            return sum(t.probed.size_bytes for t in session.tracks.values()) if session else 0

    def get_session_files(self, session_id: str) -> List[ProbedAudio]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Sesión '{session_id}' no encontrada.")
            return [
                session.tracks[fid].probed
                for fid in session.ordered_ids
                if fid in session.tracks
            ]

    def reorder_session_files(
        self, session_id: str, file_order: List[str]
    ) -> List[ProbedAudio]:
        """Update the sequence order of files in a session (by file_id or filename)."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Sesión '{session_id}' no encontrada.")

            resolved_ids: List[str] = []
            remaining_ids = list(session.ordered_ids)

            for identifier in file_order:
                if identifier in session.tracks and identifier not in resolved_ids:
                    resolved_ids.append(identifier)
                    if identifier in remaining_ids:
                        remaining_ids.remove(identifier)
                else:
                    # Fallback match by filename
                    matched_id = next(
                        (
                            fid
                            for fid in remaining_ids
                            if session.tracks[fid].filename == identifier
                        ),
                        None,
                    )
                    if matched_id:
                        resolved_ids.append(matched_id)
                        remaining_ids.remove(matched_id)

            # Append any remaining tracks not explicitly mentioned so nothing is lost
            resolved_ids.extend(remaining_ids)
            session.ordered_ids = resolved_ids

            return [session.tracks[fid].probed for fid in session.ordered_ids]

    def remove_file_from_session(self, session_id: str, file_id: str) -> List[ProbedAudio]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Sesión '{session_id}' no encontrada.")
            track = session.tracks.pop(file_id, None)
            if track:
                track.file_path.unlink(missing_ok=True)
            if file_id in session.ordered_ids:
                session.ordered_ids.remove(file_id)
            return [session.tracks[fid].probed for fid in session.ordered_ids]

    # -------------------------------------------------------------------------
    # Job Execution Pipeline
    # -------------------------------------------------------------------------

    def create_job(self, req: TranscribeRequest) -> JobStatusResponse:
        with self._lock:
            session = self._sessions.get(req.session_id)
            if not session or not session.tracks:
                raise KeyError(
                    f"La sesión '{req.session_id}' no existe o no contiene archivos de audio."
                )

            if req.file_order:
                self.reorder_session_files(req.session_id, req.file_order)

            job_id = f"job_{uuid.uuid4().hex[:16]}"
            status = JobStatusResponse(
                job_id=job_id,
                session_id=req.session_id,
                status="queued",
                progress=0,
                current_step="En cola para procesamiento...",
            )
            self._jobs[job_id] = status
            if session.owner:
                self._job_owners[job_id] = session.owner
        self._persist_job(job_id)
        return status

    def register_job(
        self, status: JobStatusResponse, result: Optional[TranscriptionResult], owner: Optional[str]
    ) -> None:
        """Registra un trabajo creado fuera de create_job (p. ej. Apex Box) con su dueño."""
        with self._lock:
            self._jobs[status.job_id] = status
            if result is not None:
                self._results[status.job_id] = result
            if owner:
                self._job_owners[status.job_id] = owner
            if status.status in _TERMINAL_STATUSES:
                self._finished_at[status.job_id] = time.monotonic()
        self._persist_job(status.job_id)

    def job_owner(self, job_id: str) -> Optional[str]:
        """Quién creó el trabajo (se guarda al crearlo: la sesión de un invitado se descarta al terminar)."""
        with self._lock:
            owner = self._job_owners.get(job_id)
        if owner:
            return owner
        record = self._read_job_file(job_id)
        return record.get("owner") if record else None

    def record_charge(self, job_id: str, charge: QuotaCharge) -> None:
        with self._lock:
            self._charges[job_id] = charge
        self._persist_job(job_id)

    def _settle_charge(self, job_id: str, refund: bool) -> None:
        """Forget a job's charge, giving it back if the job failed. Safe to call more than once."""
        with self._lock:
            charge = self._charges.pop(job_id, None)
        if not charge or not refund:
            return
        try:
            if charge.guest:
                supabase_service.refund_guest_audios(charge.owner, charge.audios, charge.day)
            else:
                supabase_service.refund_quota(charge.owner, charge.seconds, charge.day, charge.audios)
        except Exception:
            logger.exception("Could not refund the quota of job %s", clean(job_id))

    def _update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        current_step: Optional[str] = None,
        error: Optional[str] = None,
        total_chunks: Optional[int] = None,
        completed_chunks: Optional[int] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = max(0, min(100, progress))
            if current_step is not None:
                job.current_step = current_step
            if error is not None:
                job.error = error
            if total_chunks is not None:
                job.total_chunks = total_chunks
            if completed_chunks is not None:
                job.completed_chunks = completed_chunks
            if status in _TERMINAL_STATUSES:
                self._finished_at[job_id] = time.monotonic()
        if status is not None:  # solo los cambios de estado; el progreso no se escribe a disco
            self._persist_job(job_id)

    def _build_merged_preview_audio(
        self, chunk_paths: List[Path], output_path: Path
    ) -> Optional[Path]:
        """Concatenate extracted 16kHz mono MP3 chunks into a single playable timeline file."""
        if not chunk_paths:
            return None
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if len(chunk_paths) == 1:
                shutil.copyfile(chunk_paths[0], output_path)
                return output_path

            concat_list_file = output_path.parent / f"{output_path.stem}_concat.txt"
            lines = [f"file '{str(p.resolve())}'" for p in chunk_paths]
            concat_list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

            cmd = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list_file),
                "-c",
                "copy",
                str(output_path),
            ]
            subprocess.run(cmd, check=True, timeout=120.0)
            concat_list_file.unlink(missing_ok=True)
            return output_path
        except Exception as exc:
            logger.warning("Failed to build merged preview audio: %s", exc)
            return None

    def execute_job(self, job_id: str, req: TranscribeRequest) -> TranscriptionResult:
        """
        Execute the full end-to-end audio processing, Groq transcription, and
        speaker diarization pipeline for a job, once a pipeline slot is free.
        """
        with pipeline_slot():
            return self._run_job(job_id, req)

    def _run_job(self, job_id: str, req: TranscribeRequest) -> TranscriptionResult:
        deadline = time.monotonic() + settings.JOB_TIMEOUT_SECONDS

        def check_deadline() -> None:
            if time.monotonic() > deadline:
                raise JobTimeoutError(_TIMED_OUT_MESSAGE)

        job_temp_dir = settings.TEMP_DIR / job_id
        job_temp_dir.mkdir(parents=True, exist_ok=True)
        is_guest = bool(req.guest_key) and not req.user_id

        try:
            self._update_job(
                job_id,
                status="processing",
                progress=5,
                current_step="Ordenando archivos y analizando silencios con FFmpeg...",
            )

            session = self.get_session(req.session_id)
            if not session:
                raise UserFacingError(f"Sesión '{req.session_id}' no encontrada.")

            ordered_tracks = [
                session.tracks[fid]
                for fid in session.ordered_ids
                if fid in session.tracks
            ]
            if not ordered_tracks:
                raise UserFacingError("No hay archivos de audio en la sesión para procesar.")

            ordered_paths = [t.file_path for t in ordered_tracks]
            ordered_filenames = [t.filename for t in ordered_tracks]

            # 1. Audio Slicing, Chunking (<25MB) & Global Timeline Offset Calculation
            probed_list, chunks = process_audio_sequence(
                file_paths=ordered_paths,
                output_dir=job_temp_dir,
            )

            # Map original user-facing filenames onto chunks
            for chunk in chunks:
                seq_idx = chunk.file_sequence_index
                if 0 <= seq_idx < len(ordered_filenames):
                    chunk.source_file_name = ordered_filenames[seq_idx]

            total_duration = round(sum(p.duration_sec for p in probed_list), 3)

            # Plan comes from the account set by the server (never from the client).
            effective_user = None if is_guest else supabase_service.get_user_by_id(req.user_id)
            resolved_uid = effective_user["user_id"] if effective_user else None
            if is_guest:
                effective_plan = "guest"
            else:
                charge_day = supabase_service.usage_day()
                quota_state = supabase_service.check_and_consume_quota(
                    user_id=resolved_uid,
                    duration_seconds=total_duration,
                    audios_count=len(ordered_tracks),
                )
                effective_plan = quota_state.plan
                if resolved_uid:
                    self.record_charge(
                        job_id,
                        QuotaCharge(owner=resolved_uid, day=charge_day, audios=len(ordered_tracks), seconds=total_duration),
                    )

            engine_brand = get_public_engine_label(req.diarization_engine)
            engine = resolve_engine_code(req.diarization_engine)
            resolved_model = resolve_model_code(req.model or req.diarization_engine)

            self._update_job(
                job_id,
                progress=20,
                total_chunks=len(chunks),
                completed_chunks=0,
                current_step=f"Audio preparado en {len(chunks)} fragmento(s) (<25 MB). Procesando con {engine_brand} (Potenciado por Groq)...",
            )

            # Build merged audio file for continuous web player playback & acoustic voiceprint
            merged_audio_path = settings.OUTPUT_DIR / f"{job_id}_merged.mp3"
            self._build_merged_preview_audio([c.file_path for c in chunks], merged_audio_path)

            has_dg_key = bool((req.deepgram_api_key or settings.DEEPGRAM_API_KEY or "").strip())

            def on_chunk_progress(idx: int, total: int, msg: str) -> None:
                check_deadline()
                pct = 20 + int(((idx + 0.5) / max(1, total)) * 45)
                self._update_job(
                    job_id,
                    progress=pct,
                    completed_chunks=idx,
                    current_step=msg,
                )

            if engine == "deepgram" and has_dg_key:
                whisper_segments = transcribe_and_diarize_chunks_deepgram(
                    chunks=chunks,
                    language=req.language,
                    num_speakers=req.num_speakers,
                    deepgram_api_key=req.deepgram_api_key,
                    progress_callback=on_chunk_progress,
                )
                trust_acoustic = True
            else:
                # Step 2A: Transcribe chunks sequentially via Groq
                whisper_segments = transcribe_chunks_sequence(
                    chunks=chunks,
                    model=resolved_model,
                    language=req.language,
                    prompt_hint=req.prompt_hint,
                    api_key=req.api_key,
                    progress_callback=on_chunk_progress,
                )
                trust_acoustic = False

                # Step 2B: Enrich segments with acoustic voice separation
                if engine in ("hybrid_deepgram_groq", "deepgram") and has_dg_key and whisper_segments:
                    self._update_job(
                        job_id,
                        progress=70,
                        completed_chunks=len(chunks),
                        current_step=f"Ejecutando separación acústica de voz ({engine_brand})...",
                    )
                    whisper_segments = align_groq_segments_with_deepgram_diarization(
                        chunks=chunks,
                        groq_segments=whisper_segments,
                        language=req.language,
                        num_speakers=req.num_speakers,
                        deepgram_api_key=req.deepgram_api_key,
                    )
                    trust_acoustic = any(bool(s.acoustic_speaker) for s in whisper_segments)

                # If acoustic_local selected (or acoustic tags not yet populated), run local voiceprint clustering
                if (
                    (engine in ("acoustic_local", "deepgram") or not any(bool(s.acoustic_speaker) for s in whisper_segments))
                    and merged_audio_path.exists()
                    and whisper_segments
                ):
                    self._update_job(
                        job_id,
                        progress=74,
                        completed_chunks=len(chunks),
                        current_step=f"Analizando huella vocal acústica ({engine_brand})...",
                    )
                    whisper_segments = cluster_segments_acoustically(
                        audio_path=merged_audio_path,
                        segments=whisper_segments,
                        num_speakers=req.num_speakers,
                    )
                    if engine in ("acoustic_local", "deepgram"):
                        trust_acoustic = True

            check_deadline()
            # Step 2.5: Clean silence hallucinations & noise before diarization
            self._update_job(
                job_id,
                progress=78,
                completed_chunks=len(chunks),
                current_step="Control de calidad: limpiando alucinaciones en tramos de silencio...",
            )
            whisper_segments = filter_hallucinated_segments(
                whisper_segments,
                audio_path=merged_audio_path if merged_audio_path.exists() else None,
            )

            self._update_job(
                job_id,
                progress=84,
                completed_chunks=len(chunks),
                current_step="Identificando oradores y perfiles de voz registrados...",
            )

            check_deadline()
            # 3. Speaker Diarization & Enrolled Voice Profile Matching
            diarized_segs, speaker_count, speaker_roles = diarize_segments(
                segments=whisper_segments,
                num_speakers=req.num_speakers,
                api_key=req.api_key,
                merged_audio_path=merged_audio_path if merged_audio_path.exists() else None,
                trust_acoustic_labels=trust_acoustic,
                voice_owner_id=resolved_uid,
            )

            # Final pass of format & silence hallucination cleaning
            diarized_segs = filter_hallucinated_segments(
                diarized_segs,
                audio_path=merged_audio_path if merged_audio_path.exists() else None,
            )
            unique_final_speakers = list(dict.fromkeys(s.speaker for s in diarized_segs))
            if unique_final_speakers:
                speaker_count = len(unique_final_speakers)

            full_text = "\n".join(
                f"[{s.start_formatted} - {s.end_formatted}] {s.speaker}: {s.text}"
                for s in diarized_segs
            )

            check_deadline()
            # 4. Store in MEGA S4 with plan-based retention (24h for free, unlimited for pro/trial)
            expires_at = mega_s4_storage.compute_expiration_iso(effective_plan)
            s4_result_key = f"users/{resolved_uid or 'public'}/jobs/{job_id}/result.json"
            s4_audio_key = f"users/{resolved_uid or 'public'}/jobs/{job_id}/merged.mp3"

            result = TranscriptionResult(
                job_id=job_id,
                session_id=req.session_id,
                user_id=resolved_uid,
                plan=effective_plan,
                status="completed",
                detected_speakers_count=speaker_count,
                speaker_roles=speaker_roles,
                total_duration_sec=total_duration,
                total_duration_formatted=format_timestamp_hhmmss(total_duration),
                model_used=resolved_model,
                diarization_engine_used=engine,
                engine_brand=engine_brand,
                language=req.language,
                file_order=ordered_filenames,
                segments=diarized_segs,
                full_text=full_text,
                storage_provider="apex_vox_cloud",
                s4_object_key=s4_result_key,
                expires_at=expires_at,
            )

            if is_guest:
                ttl = settings.GUEST_RESULT_TTL_MINUTES
                result.storage_provider = "none"
                result.s4_object_key = None
                result.expires_at = (
                    datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ttl)
                ).isoformat()
                result.summa_report = None
                with self._lock:
                    self._results[job_id] = result
                    self._guest_expiry[job_id] = time.time() + ttl * 60
                self.discard_session(req.session_id)
                self._settle_charge(job_id, refund=False)
                self._update_job(
                    job_id,
                    status="completed",
                    progress=100,
                    current_step="Transcripción lista. Sin cuenta no se guarda ni se analiza.",
                )
                return result

            # 5. Generate Apex Summa AI Intelligence Report
            self._update_job(
                job_id,
                progress=93,
                completed_chunks=len(chunks),
                current_step="Generando resumen inteligente Apex Summa, gráficas y calendario...",
            )
            summa_report = generate_apex_summa_report(
                result=result,
                language=req.language or "es",
                api_key=req.api_key,
                is_locked=(effective_plan == "free"),
            )
            result.summa_report = summa_report

            result_json_bytes = json.dumps(
                result.model_dump(mode="json"), ensure_ascii=False, indent=2
            ).encode("utf-8")

            # Persist result to local outputs directory & MEGA S4 bucket
            result_file = settings.OUTPUT_DIR / f"{job_id}_result.json"
            atomic_write_bytes(result_file, result_json_bytes)

            mega_s4_storage.upload_object(
                object_key=s4_result_key,
                data=result_json_bytes,
                content_type="application/json",
                plan=effective_plan,
                user_id=resolved_uid,
                job_id=job_id,
            )
            if merged_audio_path.exists():
                mega_s4_storage.upload_object(
                    object_key=s4_audio_key,
                    data=merged_audio_path.read_bytes(),
                    content_type="audio/mpeg",
                    plan=effective_plan,
                    user_id=resolved_uid,
                    job_id=job_id,
                )

            # Persist metadata in Supabase Cloud
            supabase_service.save_transcription_record(
                {
                    "job_id": job_id,
                    "user_id": resolved_uid,
                    "session_id": req.session_id,
                    "title": (ordered_filenames[0] if ordered_filenames else "Transcripción"),
                    "engine_brand": engine_brand,
                    "total_duration_sec": total_duration,
                    "total_duration_formatted": result.total_duration_formatted,
                    "detected_speakers_count": speaker_count,
                    "storage_provider": "apex_vox_cloud",
                    "s4_audio_key": s4_audio_key,
                    "s4_result_key": s4_result_key,
                    "retention_policy": "unlimited" if expires_at is None else "24h",
                    "expires_at": expires_at,
                    "plan": effective_plan,
                    "file_order": ordered_filenames,
                    "dominant_speaker": summa_report.dominant_speaker,
                    "created_at": summa_report.generated_at,
                    "source": "upload",
                    "speakers": sorted({s.speaker for s in result.segments}),
                }
            )

            with self._lock:
                self._results[job_id] = result

            self._settle_charge(job_id, refund=False)
            self._update_job(
                job_id,
                status="completed",
                progress=100,
                current_step="Transcripción Apex Vox y análisis Apex Summa completados con éxito.",
            )
            return result

        except Exception as exc:
            logger.exception("Job %s failed: %s", job_id, exc)
            self._settle_charge(job_id, refund=True)
            if is_guest:  # sin cuenta no se guarda nada, tampoco si falló
                self.discard_session(req.session_id)
            self._update_job(
                job_id,
                status="failed",
                error=public_error(exc),
                current_step=f"Error: {public_error(exc)}",
            )
            raise
        finally:
            if settings.CLEANUP_TEMP_FILES:
                shutil.rmtree(job_temp_dir, ignore_errors=True)

    def get_job_status(self, job_id: str) -> Optional[JobStatusResponse]:
        with self._lock:
            status = self._jobs.get(job_id)
        if status:
            return status
        record = self._read_job_file(job_id)
        if record and record.get("status"):
            return JobStatusResponse(**record["status"])
        # Trabajos anteriores a estos archivos: si hay resultado, terminó.
        if _SAFE_JOB_ID.fullmatch(job_id or "") and (settings.OUTPUT_DIR / f"{job_id}_result.json").exists():
            return JobStatusResponse(
                job_id=job_id, session_id="", status="completed", progress=100, current_step="Transcripción lista."
            )
        return None

    def get_job_result(self, job_id: str) -> Optional[TranscriptionResult]:
        with self._lock:
            if job_id in self._results:
                self._results[job_id] = self._results.pop(job_id)  # el más reciente va al final
                return self._results[job_id]

        # Check disk persistence
        result_file = settings.OUTPUT_DIR / f"{job_id}_result.json"
        if result_file.exists():
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
                res = TranscriptionResult(**data)
                with self._lock:
                    self._results[job_id] = res
                return res
            except Exception as exc:
                logger.warning("Failed to load persisted result for %s: %s", clean(job_id), type(exc).__name__)
        return None

    def rename_speakers(
        self, job_id: str, speaker_map: Dict[str, str]
    ) -> TranscriptionResult:
        """Rename speaker labels across all segments of a completed job."""
        with self._lock:
            edit_lock = self._result_edit_locks.setdefault(job_id, threading.Lock())
        with edit_lock:  # dos renombres seguidos no se pisan
            return self._rename_speakers(job_id, speaker_map)

    def _rename_speakers(
        self, job_id: str, speaker_map: Dict[str, str]
    ) -> TranscriptionResult:
        result = self.get_job_result(job_id)
        if not result:
            raise KeyError(f"Resultado del trabajo '{job_id}' no encontrado.")

        clean_map = {
            k.strip(): v.strip()
            for k, v in speaker_map.items()
            if k.strip() and v.strip()
        }

        updated_segments: List[DiarizedSegment] = []
        for seg in result.segments:
            new_spk = clean_map.get(seg.speaker, seg.speaker)
            updated_segments.append(seg.model_copy(update={"speaker": new_spk}))

        new_roles: Dict[str, str] = {}
        for spk, role in result.speaker_roles.items():
            new_roles[clean_map.get(spk, spk)] = role

        unique_speakers = list(dict.fromkeys(s.speaker for s in updated_segments))
        full_text = "\n".join(
            f"[{s.start_formatted} - {s.end_formatted}] {s.speaker}: {s.text}"
            for s in updated_segments
        )

        updated_result = result.model_copy(
            update={
                "segments": updated_segments,
                "speaker_roles": new_roles,
                "detected_speakers_count": len(unique_speakers),
                "full_text": full_text,
            }
        )
        if updated_result.plan == "guest":
            # Guest results are memory-only and never analysed.
            updated_result.summa_report = None
            with self._lock:
                self._results[job_id] = updated_result
            return updated_result

        updated_result.summa_report = generate_apex_summa_report(
            result=updated_result,
            language=updated_result.language or "es",
            is_locked=(updated_result.plan == "free"),
        )

        with self._lock:
            self._results[job_id] = updated_result

        result_file = settings.OUTPUT_DIR / f"{job_id}_result.json"
        atomic_write_json(result_file, updated_result.model_dump(mode="json"), indent=2)
        return updated_result


# Singleton job manager instance
job_manager = JobManager()
