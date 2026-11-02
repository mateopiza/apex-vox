"""
Pydantic Schemas & Interface Contracts
--------------------------------------
Defines all data structures for audio upload, transcription, speaker diarization,
voice profile enrollment, job status polling, and transcript exporting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.services.audio_engine import ProbedAudio


# -----------------------------------------------------------------------------
# Apex Summa — AI Summary, Analytics, Calendar, Charts & Minutes Schemas
# -----------------------------------------------------------------------------

class SpeakerAnalyticsItem(BaseModel):
    """Per-speaker quantitative participation metrics for 'Quién habló más' & charts."""
    speaker: str
    role: str = ""
    total_duration_sec: float = 0.0
    duration_formatted: str = "00:00:00"
    talk_percentage: float = 0.0
    word_count: int = 0
    turn_count: int = 0
    words_per_minute: float = 0.0
    avg_turn_sec: float = 0.0


class TopicItem(BaseModel):
    """Discussion topic identified in the transcript ('De qué se habló')."""
    title: str
    summary: str
    relevance_pct: int = 25
    keywords: List[str] = Field(default_factory=list)


class CalloutItem(BaseModel):
    """Critical warning, callout, blocker, or attention point ('Llamados de atención')."""
    title: str
    description: str
    speaker: str = ""
    timestamp: str = "00:00:00"
    severity: str = "alta"  # alta | media | informativa


class CalendarTaskItem(BaseModel):
    """Actionable upcoming task formatted for a calendar ('Próximas tareas en calendario')."""
    task_id: str
    title: str
    description: str = ""
    assignee: str = "Equipo"
    due_date: str  # YYYY-MM-DD
    due_time: str = "09:00"
    priority: str = "alta"  # alta | media | baja
    category: str = "Seguimiento"


class TimelineDensityPoint(BaseModel):
    """Time bucket metric for timeline charts ('Gráficas de la transcripción')."""
    bucket_label: str  # e.g. "00:00 - 02:00"
    start_sec: float
    end_sec: float
    word_count: int
    active_speakers: int
    dominant_speaker: str = ""


class TranscriptionChartsData(BaseModel):
    """Structured datasets for rendering Apex Summa interactive charts."""
    speaker_distribution: List[SpeakerAnalyticsItem] = Field(default_factory=list)
    timeline_density: List[TimelineDensityPoint] = Field(default_factory=list)
    topic_weights: List[Dict[str, Any]] = Field(default_factory=list)


class ApexSummaReport(BaseModel):
    """Complete Apex Summa AI intelligence report generated after transcription."""
    job_id: str
    generated_at: str
    language: str = "es"
    is_locked: bool = False  # True if free plan and not unlocked yet
    # 1. Quién habló más
    dominant_speaker: str = ""
    dominant_speaker_pct: float = 0.0
    speaker_stats: List[SpeakerAnalyticsItem] = Field(default_factory=list)
    # 2. De qué se habló
    executive_summary: str = ""
    topics: List[TopicItem] = Field(default_factory=list)
    # 3. Objetivos
    objectives: List[str] = Field(default_factory=list)
    # 4. Llamados de atención
    callouts: List[CalloutItem] = Field(default_factory=list)
    # 5. Próximas tareas en forma de calendario
    calendar_tasks: List[CalendarTaskItem] = Field(default_factory=list)
    # 6. Gráficas de la transcripción
    charts: TranscriptionChartsData = Field(default_factory=TranscriptionChartsData)
    # 7. Opciones de actas disponibles
    available_minutes_templates: List[Dict[str, str]] = Field(default_factory=list)


class MinutesGenerationRequest(BaseModel):
    """Request payload to generate formal meeting minutes ('Actas')."""
    template_type: str = "consejo"  # consejo | comite | asamblea | seguimiento | ejecutiva
    language: str = "es"
    organization_name: Optional[str] = "Apex Vox Enterprise"
    meeting_title: Optional[str] = None
    custom_notes: Optional[str] = None


class MinutesDocumentResponse(BaseModel):
    """Generated formal minutes ('Acta') document."""
    job_id: str
    template_type: str
    template_title: str
    language: str = "es"
    generated_at: str
    markdown_content: str
    html_content: str


# -----------------------------------------------------------------------------
# Auth, Users, Plans, Quotas & Billing (Supabase Cloud + Bold API + Mega S4)
# -----------------------------------------------------------------------------

class UserRegisterRequest(BaseModel):
    """Registration payload for obtaining 2 free hours/day (24h retention) or Pro plan."""
    email: str
    password: str
    full_name: str = ""
    preferred_language: str = "es"


class UserLoginRequest(BaseModel):
    """Login request payload."""
    email: str
    password: str


class QuotaUsageResponse(BaseModel):
    """Daily audio quota and storage retention status for a user."""
    user_id: str
    plan: str = "free"  # free | trial | pro
    plan_display_name: str = "Plan Gratis (2h / día)"
    daily_limit_seconds: Optional[int] = 7200  # 7200s (2 hours) for free, None for unlimited
    used_today_seconds: float = 0.0
    remaining_today_seconds: Optional[float] = 7200.0
    is_unlimited: bool = False
    retention_hours: Optional[int] = 24  # 24h for free, None for unlimited
    storage_provider: str = "mega_s4"
    summa_enabled: bool = False
    trial_active: bool = False
    trial_ends_at: Optional[str] = None
    auto_billing_enabled: bool = False


class UserProfileResponse(BaseModel):
    """Authenticated user profile with plan, quota, and subscription state."""
    user_id: str
    email: str
    full_name: str
    plan: str = "free"  # free | trial | pro
    preferred_language: str = "es"
    access_token: str = ""
    created_at: str = ""
    quota: QuotaUsageResponse


class BoldCheckoutRequest(BaseModel):
    """Request to create a Bold API payment checkout session ($30,000 COP / $10 USD)."""
    user_id: Optional[str] = None
    currency: str = "COP"  # COP (30000) or USD (10)
    start_trial: bool = True  # 3-day free trial + automatic billing
    redirect_url: Optional[str] = None


class BoldCheckoutResponse(BaseModel):
    """Bold API checkout parameters including SHA256 integrity signature."""
    order_id: str
    amount: int
    currency: str
    amount_display: str
    trial_days: int = 3
    auto_billing: bool = True
    bold_api_key: str
    integrity_signature: str
    checkout_url: str
    plan_summary: str


class SubscribeActionRequest(BaseModel):
    """Activate 3-day free trial or Pro subscription with automatic billing."""
    user_id: Optional[str] = None
    currency: str = "COP"
    payment_reference: Optional[str] = None
    auto_billing: bool = True


class WhisperSegment(BaseModel):
    """Timed segment returned by Whisper/STT and aligned to the continuous global timeline."""
    id: int
    start: float  # local chunk start
    end: float    # local chunk end
    text: str
    global_start: float  # calculated continuous global start
    global_end: float    # calculated continuous global end
    source_file: str
    file_order_index: int
    pause_before: float  # acoustic pause in seconds from previous segment end
    acoustic_speaker: Optional[str] = None  # Speaker ID from Deepgram or Acoustic Voiceprint


class DiarizedSegment(BaseModel):
    """Final diarized transcript segment with speaker label and formatted timestamps."""
    id: int
    start: float
    end: float
    speaker: str  # e.g. "Hablante 1", "Hablante 2", or enrolled name "Carlos"
    text: str
    start_formatted: str  # "HH:MM:SS"
    end_formatted: str    # "HH:MM:SS"
    source_file: str
    file_order_index: int
    confidence: Optional[float] = None


class TranscriptionResult(BaseModel):
    """Complete transcription and diarization output for a multi-audio job."""
    job_id: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    plan: str = "free"
    status: str = "completed"
    detected_speakers_count: int = 1
    speaker_roles: Dict[str, str] = Field(default_factory=dict)
    total_duration_sec: float = 0.0
    total_duration_formatted: str = "00:00:00"
    model_used: str = "whisper-large-v3"
    diarization_engine_used: str = "hybrid_deepgram_groq"
    engine_brand: str = "Mc-Lewis"
    language: Optional[str] = None
    file_order: List[str] = Field(default_factory=list)
    segments: List[DiarizedSegment] = Field(default_factory=list)
    full_text: str = ""
    storage_provider: str = "mega_s4"
    s4_object_key: Optional[str] = None
    expires_at: Optional[str] = None
    summa_report: Optional[ApexSummaReport] = None


class UploadResponse(BaseModel):
    """Response returned by POST /api/upload."""
    session_id: str
    files: List[ProbedAudio]


class ReorderRequest(BaseModel):
    """Request payload for updating file sequence order in a session."""
    session_id: str
    file_order: List[str]


class TranscribeRequest(BaseModel):
    """Request payload for POST /api/transcribe."""
    session_id: str
    file_order: List[str] = Field(default_factory=list)
    model: str = "whisper-large-v3"
    diarization_engine: str = "Mc-Lewis"  # Mc-Ayrton | Mc-Lewis | Mc-Norris | Mc-Piastri (or legacy IDs)
    language: Optional[str] = None
    num_speakers: Optional[int] = None  # None or 0 = Auto-detect; 1, 2, 3+ = explicit
    prompt_hint: Optional[str] = None
    api_key: Optional[str] = None  # Optional Groq API key override
    deepgram_api_key: Optional[str] = None  # Optional Deepgram API key override
    user_id: Optional[str] = None
    plan_override: Optional[str] = None  # Optional 'free' | 'trial' | 'pro' for playground testing


class TranscribeResponse(BaseModel):
    """Response returned when a transcription job is queued."""
    job_id: str
    session_id: str
    status: str = "queued"


class JobStatusResponse(BaseModel):
    """Response returned by GET /api/jobs/{job_id}/status."""
    job_id: str
    session_id: Optional[str] = None
    status: str  # "queued", "processing", "completed", "failed"
    progress: int = 0
    current_step: str = ""
    error: Optional[str] = None
    total_chunks: int = 0
    completed_chunks: int = 0


class RenameSpeakersRequest(BaseModel):
    """Request payload to rename speaker labels in a completed job."""
    speaker_map: Dict[str, str]


class VoiceProfile(BaseModel):
    """Enrolled speaker voiceprint profile for automatic voice identification."""
    profile_id: str
    name: str
    role: str = ""
    sample_duration_sec: float = 0.0
    pitch_hz: float = 0.0
    embedding: List[float] = Field(default_factory=list)
    created_at: str = ""
