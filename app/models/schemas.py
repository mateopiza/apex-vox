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
    storage_provider: str = "apex_vox_cloud"
    summa_enabled: bool = False
    trial_active: bool = False
    trial_ends_at: Optional[str] = None
    auto_billing_enabled: bool = False  # Bold payment links are one-off; renewals are manual
    pro_until: Optional[str] = None  # end of the paid Apex Pro period
    trial_available: bool = False  # sin prueba gratis: siempre False (compatibilidad)


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
    """Create a Bold payment link for 30 days of Apex Pro (USD 10; USD 8 with the welcome promo)."""
    currency: str = "USD"  # solo USD; se ignora cualquier otro valor


class BoldCheckoutResponse(BaseModel):
    """Bold payment link created through the official Link de pagos API."""
    order_id: str  # our reference, echoed back by Bold in the webhook
    payment_link: str  # Bold link id (LNK_...)
    checkout_url: str  # https://checkout.bold.co/... — redirect the payer here
    amount: float
    currency: str
    amount_display: str
    period_days: int = 30
    promo_applied: bool = False
    regular_amount: float = 10.0
    discount_pct: int = 0
    plan_summary: str = ""


class BillingOfferResponse(BaseModel):
    """Precio actual de Apex Pro para la cuenta (con o sin promoción de bienvenida)."""
    currency: str = "USD"
    regular_price: float
    price: float
    promo_eligible: bool
    promo_price: float
    discount_pct: int
    promo_ends_at: Optional[str] = None
    promo_reason: Optional[str] = None  # first_month_only | window_expired | ip_used_this_quarter
    period_days: int = 30
    auto_renewal: bool = False


class SubscribeActionRequest(BaseModel):
    """Obsoleto: la prueba gratis fue retirada (POST /api/billing/subscribe responde 410)."""
    currency: str = "USD"


class PasswordForgotRequest(BaseModel):
    """Ask for a password-reset link."""
    email: str
    lang: str = "es"


class PasswordResetRequest(BaseModel):
    """Set a new password with the token from the reset e-mail."""
    token: str
    password: str


class NewsletterSubscribeRequest(BaseModel):
    """Newsletter sign-up (double opt-in)."""
    email: str
    lang: str = "es"


class OAuthExchangeRequest(BaseModel):
    """One-time code returned to the browser after a Google / GitHub sign-in."""
    code: str


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
    media_token: Optional[str] = Field(
        default=None, description="Signed read-only token for audio, exports and calendar links (?t=); never stored"
    )
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
    storage_provider: str = "apex_vox_cloud"
    s4_object_key: Optional[str] = Field(default=None, exclude=True)  # ruta interna: nunca sale en la API
    expires_at: Optional[str] = None
    summa_report: Optional[ApexSummaReport] = None
    live_notes: List[Dict[str, Any]] = Field(default_factory=list)


class UploadResponse(BaseModel):
    """Response returned by POST /api/upload."""
    session_id: str
    files: List[ProbedAudio]
    media_token: Optional[str] = Field(default=None, description="Signed token for <audio> previews (?t=)")


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
    user_id: Optional[str] = None  # set by the server from the session token
    guest_key: Optional[str] = None  # set by the server for visitors without an account


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
    owner_id: Optional[str] = None  # account that enrolled this voice


# -----------------------------------------------------------------------------
# Apex Box — Unlimited Block Recorder, Virtual/In-Person Meetings & Live Notes
# -----------------------------------------------------------------------------

class BoxOptimalConfigResponse(BaseModel):
    """Calculated optimal block duration and RAM consumption profile for multi-hour recording."""
    optimal_block_seconds: int = 180
    optimal_block_minutes: float = 3.0
    recommended_mime_type: str = "audio/webm;codecs=opus"
    fallback_mime_types: List[str] = Field(
        default_factory=lambda: ["audio/webm", "audio/ogg;codecs=opus", "audio/mp4", "audio/wav"]
    )
    recommended_bitrate_bps: int = 48000
    bytes_per_second: int = 6000
    single_block_size_mb: float = 1.03
    peak_client_ram_mb: float = 2.06
    target_hours_analyzed: float = 10.0
    total_blocks_for_target: int = 200
    unblocked_ram_10h_mb: float = 540.0
    ram_savings_pct: float = 99.6
    rotation_strategy: str = "dual_recorder_zero_gap_ebml"
    explanation_es: str = ""
    explanation_en: str = ""
    presets: List[Dict[str, Any]] = Field(default_factory=list)


class BoxCreateSessionRequest(BaseModel):
    """Request payload to start an unlimited block-recording session in Apex Box."""
    title: str = "Reunión en Vivo — Apex Box"
    mode: str = "presencial"  # "presencial" (mic/room/mobile) | "virtual" (Zoom, Meet, Teams + mic)
    platform: str = "in_person"  # "in_person" | "google_meet" | "zoom" | "microsoft_teams" | "webex" | "mobile_pwa"
    meeting_url: Optional[str] = None
    block_duration_sec: int = 180
    language: Optional[str] = "es"
    diarization_engine: str = "Mc-Lewis"
    num_speakers: Optional[int] = None
    prompt_hint: Optional[str] = None
    user_id: Optional[str] = None
    plan: str = "pro"
    device_type: str = "desktop_extension"  # "desktop_extension" | "mobile_webapp" | "desktop_webapp"


class BoxNoteRequest(BaseModel):
    """Request payload to create or update a live timestamped note during a meeting."""
    text: str
    tag: str = "nota"  # "nota" | "acuerdo" | "tarea" | "alerta" | "idea" | "pregunta"
    category: Optional[str] = None
    timestamp_sec: Optional[float] = None
    speaker: Optional[str] = None
    author: Optional[str] = None


class BoxNoteItem(BaseModel):
    """Timestamped note taken live during an Apex Box recording session."""
    note_id: str
    box_session_id: str
    timestamp_sec: float = 0.0
    timestamp_formatted: str = "00:00:00"
    tag: str = "nota"
    category: str = "nota"
    speaker: str = ""
    author: str = ""
    text: str
    created_at: str = ""


class BoxBlockInfo(BaseModel):
    """Metadata for a single recorded and uploaded audio block in an unlimited session."""
    block_index: int
    file_id: str
    filename: str
    duration_sec: float
    start_offset_sec: float
    end_offset_sec: float
    timeline_range: str
    size_bytes: int
    transcribed: bool = False
    placeholder: bool = False  # no real transcript: the block's text is a stand-in and it was not charged
    segments_count: int = 0
    uploaded_at: str = ""


class BoxBlockUploadResponse(BaseModel):
    """Response returned immediately when a recorded block is uploaded and incrementally processed."""
    box_session_id: str
    upload_session_id: str
    block: BoxBlockInfo
    new_segments: List[DiarizedSegment] = Field(default_factory=list)
    total_blocks_received: int = 0
    total_duration_sec: float = 0.0
    total_duration_formatted: str = "00:00:00"
    total_segments_count: int = 0
    estimated_client_ram_mb: float = 1.05
    ram_freed_total_mb: float = 0.0
    status: str = "recording"


class BoxSessionStateResponse(BaseModel):
    """Complete live state of an Apex Box unlimited recording session."""
    box_session_id: str
    upload_session_id: str
    title: str
    mode: str
    platform: str
    meeting_url: Optional[str] = None
    device_type: str = "desktop_extension"
    block_duration_sec: int = 180
    language: str = "es"
    diarization_engine: str = "Mc-Lewis"
    engine_brand: str = "Mc-Lewis"
    status: str = "recording"  # "recording" | "paused" | "finalizing" | "completed"
    created_at: str = ""
    updated_at: str = ""
    total_blocks: int = 0
    total_duration_sec: float = 0.0
    total_duration_formatted: str = "00:00:00"
    estimated_client_ram_mb: float = 1.05
    ram_freed_total_mb: float = 0.0
    blocks: List[BoxBlockInfo] = Field(default_factory=list)
    segments: List[DiarizedSegment] = Field(default_factory=list)
    notes: List[BoxNoteItem] = Field(default_factory=list)
    final_job_id: Optional[str] = None


class BoxFinalizeRequest(BaseModel):
    """Request payload to finalize a multi-hour recording session and generate full Apex Summa & Minutes."""
    run_full_pipeline: bool = False
    generate_minutes: bool = True
    organization_name: Optional[str] = "Apex Vox Enterprise"
    generate_minutes_template: Optional[str] = "ejecutiva"
    minutes_type: Optional[str] = None


class BoxFinalizeResponse(BaseModel):
    """Response returned when an Apex Box session is finalized into a full TranscriptionResult + Summa Report."""
    box_session_id: str
    job_id: str
    upload_session_id: str
    status: str = "completed"
    total_blocks_processed: int = 0
    total_blocks: int = 0
    total_duration_sec: float = 0.0
    total_duration_formatted: str = "00:00:00"
    notes_integrated_count: int = 0
    result: TranscriptionResult
    minutes_document: Optional[MinutesDocumentResponse] = None
    minutes: Optional[MinutesDocumentResponse] = None

