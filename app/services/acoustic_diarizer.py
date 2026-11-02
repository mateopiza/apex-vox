"""
Local Acoustic Voiceprint Diarizer & Speaker Identification (app/services/acoustic_diarizer.py)
-----------------------------------------------------------------------------------------------
Provides:
1. Fast acoustic voice feature extraction (Fundamental Pitch F0, Spectral Centroid,
   Spectral Rolloff, Formant Log-Mel Filterbank & Cepstral coefficients) from 16kHz
   mono PCM audio via FFmpeg + NumPy.
2. Unsupervised cosine-distance clustering of segments by voice timbre (1, 2, or N speakers).
3. Enrolled Voice Profile management ("Perfiles de Voz"): enroll a short sample of a
   known person's voice and automatically identify them across future transcriptions.
"""

from __future__ import annotations

import datetime
import json
import logging
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.config import settings
from app.models.schemas import VoiceProfile, WhisperSegment

logger = logging.getLogger("app.services.acoustic_diarizer")

SAMPLE_RATE = 16000
N_MELS = 18


def load_pcm_float32(
    audio_path: Path | str,
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
) -> np.ndarray:
    """Decode audio slice into 16kHz mono float32 numpy array via FFmpeg pipe."""
    cmd = ["ffmpeg", "-v", "error"]
    if start_sec is not None and start_sec > 0:
        cmd.extend(["-ss", f"{start_sec:.3f}"])
    if end_sec is not None and end_sec > (start_sec or 0.0):
        cmd.extend(["-to", f"{end_sec:.3f}"])
    cmd.extend([
        "-i",
        str(audio_path),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "pipe:1",
    ])
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60.0,
    )
    if res.returncode != 0 or not res.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(res.stdout, dtype=np.float32)


def extract_voice_embedding(samples: np.ndarray) -> Tuple[np.ndarray, float]:
    """
    Compute a 24-dimensional normalized acoustic voiceprint vector and average pitch (Hz)
    from a 16kHz mono float32 waveform.

    Features:
    - [0..17]: 18-band Log-Frequency Vocal Tract Filterbank (80 Hz - 7600 Hz)
    - [18..21]: Cepstral timbre coefficients (DCT of log-spectrum)
    - [22]: Normalized Spectral Centroid
    - [23]: Normalized Fundamental Pitch (F0 in 75 - 400 Hz vocal range)
    """
    if samples.size < 400:
        return np.zeros(24, dtype=np.float32), 0.0

    # Remove DC offset and normalize peak amplitude
    y = samples.astype(np.float32) - float(np.mean(samples))
    peak = float(np.max(np.abs(y)))
    if peak > 1e-6:
        y = y / peak

    frame_len = 512  # 32 ms at 16kHz
    hop_len = 256    # 16 ms hop
    if y.size < frame_len:
        y = np.pad(y, (0, frame_len - y.size))

    num_frames = 1 + (y.size - frame_len) // hop_len
    frames = np.lib.stride_tricks.as_strided(
        y,
        shape=(num_frames, frame_len),
        strides=(y.strides[0] * hop_len, y.strides[0]),
    ).copy()

    # Keep active voiced frames (above 15th percentile energy)
    frame_energy = np.mean(frames ** 2, axis=1)
    energy_thresh = max(1e-5, float(np.percentile(frame_energy, 20)))
    voiced_frames = frames[frame_energy >= energy_thresh]
    if voiced_frames.shape[0] == 0:
        voiced_frames = frames

    window = np.hanning(frame_len).astype(np.float32)
    windowed = voiced_frames * window
    mag_spec = np.abs(np.fft.rfft(windowed, n=frame_len, axis=1))  # shape: (N, 257)
    freqs = np.fft.rfftfreq(frame_len, d=1.0 / SAMPLE_RATE)

    # 1. Fundamental Pitch (F0) estimation via autocorrelation in [75 Hz, 400 Hz]
    min_lag = int(SAMPLE_RATE / 400.0)  # 40 samples
    max_lag = int(SAMPLE_RATE / 75.0)   # 213 samples
    pitches: List[float] = []
    for f in voiced_frames[:60]:
        corr = np.correlate(f, f, mode="full")[frame_len - 1 :]
        if corr[0] > 1e-5:
            sub = corr[min_lag:max_lag]
            best_lag = min_lag + int(np.argmax(sub))
            if sub[best_lag - min_lag] / corr[0] > 0.25:
                pitches.append(float(SAMPLE_RATE / best_lag))

    median_pitch = float(np.median(pitches)) if pitches else 150.0

    # 2. Spectral Centroid
    spec_sum = np.sum(mag_spec, axis=1) + 1e-8
    centroids = np.sum(mag_spec * freqs[None, :], axis=1) / spec_sum
    mean_centroid = float(np.mean(centroids))

    # 3. 18-band Log-Spaced Vocal Tract Filterbank (80 Hz to 7600 Hz)
    band_edges = np.geomspace(80.0, 7600.0, N_MELS + 1)
    band_energies = np.zeros(N_MELS, dtype=np.float32)
    mean_spec = np.mean(mag_spec, axis=0)

    for b in range(N_MELS):
        mask = (freqs >= band_edges[b]) & (freqs < band_edges[b + 1])
        if np.any(mask):
            band_energies[b] = float(np.log1p(np.mean(mean_spec[mask]) * 100.0))

    # Normalize filterbank shape (zero-mean, unit-std per segment to capture timbre relative shape)
    b_std = float(np.std(band_energies))
    if b_std > 1e-6:
        norm_bands = (band_energies - float(np.mean(band_energies))) / b_std
    else:
        norm_bands = band_energies

    # 4. Low-order DCT (Cepstral envelope coefficients)
    n_idx = np.arange(N_MELS, dtype=np.float32)
    cepstral = np.zeros(4, dtype=np.float32)
    for k in range(1, 5):
        cepstral[k - 1] = float(
            np.sum(norm_bands * np.cos(np.pi * k * (2 * n_idx + 1) / (2 * N_MELS)))
        ) / N_MELS

    norm_centroid = (mean_centroid - 1500.0) / 1000.0
    norm_pitch = (median_pitch - 170.0) / 75.0

    vec = np.concatenate([
        norm_bands * 0.5,
        cepstral * 1.2,
        np.array([norm_centroid, norm_pitch * 1.8], dtype=np.float32),
    ])

    norm = float(np.linalg.norm(vec))
    if norm > 1e-6:
        vec = vec / norm

    return vec.astype(np.float32), round(median_pitch, 1)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity in [-1.0, 1.0] between two vectors."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-7 or nb < 1e-7:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cluster_segments_acoustically(
    audio_path: Path | str,
    segments: List[WhisperSegment],
    num_speakers: Optional[int] = None,
) -> List[WhisperSegment]:
    """
    Extract acoustic voiceprint embeddings for each segment from the merged audio
    and cluster segments by voice timbre into 1, 2, or K speakers.
    """
    if not segments:
        return []

    if num_speakers == 1 or len(segments) == 1:
        return [s.model_copy(update={"acoustic_speaker": "Hablante 1"}) for s in segments]

    full_pcm = load_pcm_float32(audio_path)
    if full_pcm.size < SAMPLE_RATE // 4:
        return segments

    embeddings: List[np.ndarray] = []
    pitches: List[float] = []

    for seg in segments:
        s_idx = max(0, int(seg.global_start * SAMPLE_RATE))
        e_idx = min(full_pcm.size, int(max(seg.global_end, seg.global_start + 0.25) * SAMPLE_RATE))
        slice_pcm = full_pcm[s_idx:e_idx]
        emb, pitch = extract_voice_embedding(slice_pcm)
        embeddings.append(emb)
        pitches.append(pitch)

    emb_matrix = np.stack(embeddings, axis=0)  # (N, 24)
    n_segs = len(segments)

    # Determine target number of speakers K
    if num_speakers and num_speakers >= 2:
        k_clusters = min(num_speakers, n_segs)
    else:
        # Automatic speaker count estimation via pairwise cosine similarity & pitch spread
        sims = emb_matrix @ emb_matrix.T
        off_diag = sims[np.triu_indices(n_segs, k=1)]
        pitch_std = float(np.std([p for p in pitches if p > 0] or [0.0]))

        if off_diag.size == 0 or (float(np.mean(off_diag)) > 0.86 and pitch_std < 14.0):
            k_clusters = 1
        elif float(np.percentile(off_diag, 15)) < 0.35 and n_segs >= 6:
            k_clusters = 3
        else:
            k_clusters = 2

    if k_clusters == 1:
        return [s.model_copy(update={"acoustic_speaker": "Hablante 1"}) for s in segments]

    # Furthest-first initialization (k-means++ deterministic seeding)
    centroids = [emb_matrix[0]]
    for _ in range(1, k_clusters):
        dists = np.array([
            min(1.0 - float(np.dot(vec, c)) for c in centroids)
            for vec in emb_matrix
        ])
        next_idx = int(np.argmax(dists))
        centroids.append(emb_matrix[next_idx])

    labels = np.zeros(n_segs, dtype=np.int32)
    for _ in range(15):
        # Assign each segment to closest centroid
        for i in range(n_segs):
            sims_i = [float(np.dot(emb_matrix[i], c)) for c in centroids]
            labels[i] = int(np.argmax(sims_i))

        # Recompute centroids
        for c_idx in range(k_clusters):
            members = emb_matrix[labels == c_idx]
            if members.shape[0] > 0:
                mean_c = np.mean(members, axis=0)
                norm_c = float(np.linalg.norm(mean_c))
                if norm_c > 1e-6:
                    centroids[c_idx] = mean_c / norm_c

    # Order speaker labels by first appearance so first speaker is always Hablante 1
    label_remap: Dict[int, str] = {}
    next_num = 1
    enriched: List[WhisperSegment] = []

    for i, seg in enumerate(segments):
        raw_lbl = int(labels[i])
        if raw_lbl not in label_remap:
            label_remap[raw_lbl] = f"Hablante {next_num}"
            next_num += 1
        enriched.append(seg.model_copy(update={"acoustic_speaker": label_remap[raw_lbl]}))

    return enriched


# -----------------------------------------------------------------------------
# Voice Profile Enrollment & Speaker Recognition Store
# -----------------------------------------------------------------------------

def _profiles_file_path() -> Path:
    return settings.OUTPUT_DIR / "voice_profiles.json"


def list_voice_profiles(owner_id: Optional[str] = None) -> List[VoiceProfile]:
    """Profiles of one account. Without an owner, nothing (profiles are private)."""
    if not owner_id:
        return []
    return [p for p in _load_all_profiles() if p.owner_id == owner_id]


def _load_all_profiles() -> List[VoiceProfile]:
    path = _profiles_file_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [VoiceProfile(**item) for item in raw if isinstance(item, dict)]
    except Exception as exc:
        logger.warning("Failed to load voice profiles: %s", exc)
        return []


def save_voice_profiles(profiles: List[VoiceProfile]) -> None:
    path = _profiles_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [p.model_dump(mode="json") for p in profiles]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def enroll_voice_profile(
    name: str,
    audio_bytes: bytes,
    filename: str = "sample.mp3",
    role: str = "",
    owner_id: Optional[str] = None,
) -> VoiceProfile:
    """
    Extract acoustic voiceprint embedding from an uploaded reference audio sample
    and save it as a named VoiceProfile.
    """
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("El nombre del perfil de voz no puede estar vacío.")
    if not audio_bytes:
        raise ValueError("El archivo de muestra de voz está vacío.")

    temp_path = settings.TEMP_DIR / f"enroll_{uuid.uuid4().hex[:8]}_{Path(filename).name}"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(audio_bytes)

    try:
        pcm = load_pcm_float32(temp_path)
        if pcm.size < SAMPLE_RATE // 4:
            raise ValueError("La muestra de audio es demasiado corta o inválida.")
        emb, pitch = extract_voice_embedding(pcm)
        duration_sec = round(pcm.size / float(SAMPLE_RATE), 2)
    finally:
        temp_path.unlink(missing_ok=True)

    if not owner_id:
        raise ValueError("Inicia sesión para registrar perfiles de voz.")
    profiles = _load_all_profiles()
    # Replace this owner's existing profile with the same name (case-insensitive)
    profiles = [
        p for p in profiles
        if not (p.owner_id == owner_id and p.name.lower() == clean_name.lower())
    ]

    profile = VoiceProfile(
        profile_id=f"vp_{uuid.uuid4().hex[:8]}",
        name=clean_name,
        role=role.strip() or "Orador registrado",
        sample_duration_sec=duration_sec,
        pitch_hz=pitch,
        embedding=[round(float(x), 5) for x in emb.tolist()],
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        owner_id=owner_id,
    )
    profiles.append(profile)
    save_voice_profiles(profiles)
    return profile


def delete_voice_profile(profile_id: str, owner_id: Optional[str]) -> List[VoiceProfile]:
    profiles = [
        p for p in _load_all_profiles()
        if not (p.profile_id == profile_id and p.owner_id == owner_id)
    ]
    save_voice_profiles(profiles)
    return list_voice_profiles(owner_id)


def match_enrolled_voice_profiles(
    audio_path: Optional[Path],
    segments: List[WhisperSegment],
    speaker_assignments: Dict[int, str],
    similarity_threshold: float = 0.78,
    owner_id: Optional[str] = None,
) -> Tuple[Dict[int, str], Dict[str, str]]:
    """
    If enrolled VoiceProfiles exist and audio_path is available, compute the average
    acoustic embedding of each diarized speaker cluster and match against enrolled profiles.
    """
    profiles = list_voice_profiles(owner_id)
    if not profiles or not audio_path or not audio_path.exists() or not segments:
        return speaker_assignments, {}

    full_pcm = load_pcm_float32(audio_path)
    if full_pcm.size < SAMPLE_RATE // 2:
        return speaker_assignments, {}

    # Compute mean embedding per assigned speaker
    speaker_vecs: Dict[str, List[np.ndarray]] = {}
    for seg in segments:
        spk = speaker_assignments.get(seg.id, "Hablante 1")
        s_idx = max(0, int(seg.global_start * SAMPLE_RATE))
        e_idx = min(full_pcm.size, int(max(seg.global_end, seg.global_start + 0.25) * SAMPLE_RATE))
        if e_idx - s_idx >= 400:
            emb, _ = extract_voice_embedding(full_pcm[s_idx:e_idx])
            speaker_vecs.setdefault(spk, []).append(emb)

    speaker_rename_map: Dict[str, str] = {}
    matched_roles: Dict[str, str] = {}
    used_profiles: set[str] = set()

    for spk, vecs in speaker_vecs.items():
        if not vecs:
            continue
        mean_vec = np.mean(np.stack(vecs, axis=0), axis=0)
        best_profile: Optional[VoiceProfile] = None
        best_sim = -1.0

        for prof in profiles:
            if prof.profile_id in used_profiles or not prof.embedding:
                continue
            prof_vec = np.array(prof.embedding, dtype=np.float32)
            if prof_vec.size != mean_vec.size:
                continue
            sim = cosine_similarity(mean_vec, prof_vec)
            if sim > best_sim:
                best_sim = sim
                best_profile = prof

        if best_profile and best_sim >= similarity_threshold:
            speaker_rename_map[spk] = best_profile.name
            matched_roles[best_profile.name] = (
                f"{best_profile.role} (Voz identificada, similitud {int(best_sim * 100)}%)"
            )
            used_profiles.add(best_profile.profile_id)

    if not speaker_rename_map:
        return speaker_assignments, {}

    updated_assignments = {
        seg_id: speaker_rename_map.get(spk, spk)
        for seg_id, spk in speaker_assignments.items()
    }
    return updated_assignments, matched_roles
