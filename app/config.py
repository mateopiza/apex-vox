"""
Application Configuration Module
--------------------------------
Provides centralized, validated configuration for the Audio Transcription
and Speaker Diarization web application.

Loads environment variables from `.env` via `python-dotenv` and defines
strongly typed settings with sensible defaults for development, Docker, and
production environments.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# Configure module logger
logger = logging.getLogger("app.config")

# Determine base directory (project root)
BASE_DIR = Path(__file__).resolve().parent.parent

# Attempt to load .env file via python-dotenv if available
try:
    from dotenv import load_dotenv

    env_path = BASE_DIR / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
        logger.debug("Loaded environment variables from %s", env_path)
    else:
        # Also check default system/current working directory .env
        load_dotenv(override=False)
except ImportError:
    # python-dotenv not installed yet (e.g. initial setup)
    logger.debug("python-dotenv not installed; relying on existing environment variables.")


def _parse_bool(val: str | bool | None, default: bool = False) -> bool:
    """Parse string or boolean into boolean flag."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes", "on")


def _parse_list(val: str | list[str] | None, default: list[str] | None = None) -> list[str]:
    """Parse comma-separated string or list into list of strings."""
    if val is None:
        return default or []
    if isinstance(val, list):
        return val
    return [x.strip() for x in str(val).split(",") if x.strip()]


def _parse_float_fallback(
    primary_name: str,
    fallback_name: str | None = None,
    default: float = 0.0,
    fallback_multiplier: float = 1.0,
) -> float:
    """
    Parse float from environment variables with fallback support.

    Checks primary_name first. If unset or empty, checks fallback_name
    (applying fallback_multiplier if specified). If neither is set, returns default.
    """
    val = os.getenv(primary_name)
    if val is not None and val.strip():
        try:
            return float(val.strip())
        except ValueError:
            logger.warning("Invalid float for %s: %r; checking fallback", primary_name, val)
    if fallback_name:
        fval = os.getenv(fallback_name)
        if fval is not None and fval.strip():
            try:
                return float(fval.strip()) * fallback_multiplier
            except ValueError:
                logger.warning("Invalid float for fallback %s: %r", fallback_name, fval)
    return default


def _parse_int_fallback(
    primary_name: str,
    fallback_name: str | None = None,
    default: int = 0,
) -> int:
    """
    Parse integer from environment variables with fallback support.

    Checks primary_name first. If unset or empty, checks fallback_name.
    If neither is set, returns default.
    """
    val = os.getenv(primary_name)
    if val is not None and val.strip():
        try:
            return int(val.strip())
        except ValueError:
            logger.warning("Invalid int for %s: %r; checking fallback", primary_name, val)
    if fallback_name:
        fval = os.getenv(fallback_name)
        if fval is not None and fval.strip():
            try:
                return int(fval.strip())
            except ValueError:
                logger.warning("Invalid int for fallback %s: %r", fallback_name, fval)
    return default


@dataclass
class Settings:
    """Centralized application settings dataclass."""

    # -------------------------------------------------------------------------
    # Application & Server Core
    # -------------------------------------------------------------------------
    APP_NAME: str = "Apex Vox — Audio Transcription & Diarization"
    PRODUCT_NAME: str = "Apex Vox"
    APP_VERSION: str = "2.0.0"
    APP_DESCRIPTION: str = (
        "Apex Vox (Core Transcription), Apex Summa (AI Summaries & Minutes), and Apex Box — Powered by Groq, Mega S4, Supabase Cloud & Bold API"
    )
    ENVIRONMENT: str = field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "development")
    )
    DEBUG: bool = field(
        default_factory=lambda: _parse_bool(os.getenv("DEBUG", "false"), default=False)
    )
    HOST: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    LOG_LEVEL: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    CORS_ORIGINS: list[str] = field(
        default_factory=lambda: _parse_list(os.getenv("CORS_ORIGINS", "*"), ["*"])
    )
    # Hostnames accepted in the Host header ("*" disables the check).
    ALLOWED_HOSTS: list[str] = field(
        default_factory=lambda: _parse_list(os.getenv("ALLOWED_HOSTS", "*"), ["*"])
    )
    # Swagger / ReDoc. Defaults to on in development and off in production.
    ENABLE_DOCS: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("ENABLE_DOCS") or None,
            default=os.getenv("ENVIRONMENT", "development").strip().lower() != "production",
        )
    )
    # Send Strict-Transport-Security (enable only when served over HTTPS).
    ENABLE_HSTS: bool = field(
        default_factory=lambda: _parse_bool(os.getenv("ENABLE_HSTS", "false"), default=False)
    )
    STATIC_CACHE_SECONDS: int = field(
        default_factory=lambda: int(os.getenv("STATIC_CACHE_SECONDS", "604800"))
    )
    # Public URL of the app (OAuth and Bold callbacks). Empty = derive from the request.
    PUBLIC_BASE_URL: str = field(
        default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    )
    # Visitors without an account: a few short, ephemeral transcriptions per day.
    GUEST_MAX_AUDIOS_PER_DAY: int = field(
        default_factory=lambda: int(os.getenv("GUEST_MAX_AUDIOS_PER_DAY", "3"))
    )
    GUEST_MAX_AUDIO_MINUTES: float = field(
        default_factory=lambda: float(os.getenv("GUEST_MAX_AUDIO_MINUTES", "30"))
    )
    # Guest results and merged audio are purged from memory/disk after this window.
    GUEST_RESULT_TTL_MINUTES: int = field(
        default_factory=lambda: int(os.getenv("GUEST_RESULT_TTL_MINUTES", "60"))
    )
    # Accounts may be used from at most this many networks (IPs) per calendar month.
    MAX_IPS_PER_MONTH: int = field(
        default_factory=lambda: int(os.getenv("MAX_IPS_PER_MONTH", "3"))
    )
    # Protects operational endpoints (/api/metrics/*). Empty = those endpoints are disabled.
    ADMIN_API_KEY: str = field(
        default_factory=lambda: os.getenv("ADMIN_API_KEY", "").strip()
    )

    # -------------------------------------------------------------------------
    # Telegram audio inbox (one linked chat per Apex Pro account)
    # -------------------------------------------------------------------------
    TELEGRAM_BOT_TOKEN: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )
    TELEGRAM_BOT_USERNAME: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_USERNAME", "").strip()
    )
    TELEGRAM_WEBHOOK_SECRET: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    )

    # Legal / contact details shown in the policies
    LEGAL_ENTITY_NAME: str = field(
        default_factory=lambda: os.getenv("LEGAL_ENTITY_NAME", "IA Labs (ialabs.app)").strip()
    )
    CONTACT_EMAIL: str = field(
        default_factory=lambda: os.getenv("CONTACT_EMAIL", "hola@ialabs.app").strip()
    )
    SECURITY_EMAIL: str = field(
        default_factory=lambda: os.getenv("SECURITY_EMAIL", "seguridad@ialabs.app").strip()
    )

    # -------------------------------------------------------------------------
    # Email (Resend): transactional emails and the newsletter
    # -------------------------------------------------------------------------
    RESEND_API_KEY: str = field(
        default_factory=lambda: os.getenv("RESEND_API_KEY", "").strip()
    )
    EMAIL_FROM: str = field(
        default_factory=lambda: os.getenv("EMAIL_FROM", "Apex Vox <hola@ialabs.app>").strip()
    )
    EMAIL_REPLY_TO: str = field(
        default_factory=lambda: os.getenv("EMAIL_REPLY_TO", "").strip()
    )
    RESEND_NEWSLETTER_SEGMENT_ID: str = field(
        default_factory=lambda: os.getenv(
            "RESEND_NEWSLETTER_SEGMENT_ID", "572f148f-353f-4d56-a808-23d68a9c830b"
        ).strip()
    )
    RESEND_NEWSLETTER_TOPIC_ID: str = field(
        default_factory=lambda: os.getenv(
            "RESEND_NEWSLETTER_TOPIC_ID", "0d50e8f4-c2f8-412a-890a-b90e2c1ab380"
        ).strip()
    )
    SESSION_TTL_DAYS: int = field(
        default_factory=lambda: int(os.getenv("SESSION_TTL_DAYS", "30"))
    )
    # Days of Apex Pro granted by each approved Bold payment.
    PRO_PERIOD_DAYS: int = field(
        default_factory=lambda: int(os.getenv("PRO_PERIOD_DAYS", "30"))
    )
    BOLD_API_BASE_URL: str = field(
        default_factory=lambda: os.getenv("BOLD_API_BASE_URL", "https://integrations.api.bold.co").rstrip("/")
    )

    # -------------------------------------------------------------------------
    # Plans, Quotas & Billing (Bold API)
    # -------------------------------------------------------------------------
    FREE_DAILY_HOURS: float = field(
        default_factory=lambda: float(os.getenv("FREE_DAILY_HOURS", "2.0"))
    )
    FREE_DAILY_SECONDS: int = field(
        default_factory=lambda: int(float(os.getenv("FREE_DAILY_HOURS", "2.0")) * 3600)
    )
    FREE_RETENTION_HOURS: int = field(
        default_factory=lambda: int(os.getenv("FREE_RETENTION_HOURS", "24"))
    )
    PRO_PRICE_COP: int = field(
        default_factory=lambda: int(os.getenv("PRO_PRICE_COP", "30000"))
    )
    PRO_PRICE_USD: float = field(
        default_factory=lambda: float(os.getenv("PRO_PRICE_USD", "10.0"))
    )
    PRO_TRIAL_DAYS: int = field(
        default_factory=lambda: int(os.getenv("PRO_TRIAL_DAYS", "3"))
    )
    BOLD_API_KEY: str = field(
        default_factory=lambda: os.getenv("BOLD_API_KEY", "").strip()
    )
    BOLD_SECRET_KEY: str = field(
        default_factory=lambda: os.getenv("BOLD_SECRET_KEY", "").strip()
    )
    BOLD_WEBHOOK_SECRET: str = field(
        default_factory=lambda: os.getenv("BOLD_WEBHOOK_SECRET", "").strip()
    )
    BOLD_API_BASE_URL: str = field(
        default_factory=lambda: os.getenv(
            "BOLD_API_BASE_URL", "https://integrations.api.bold.co"
        ).strip()
    )

    # -------------------------------------------------------------------------
    # MEGA S4 Object Storage (S3-Compatible)
    # -------------------------------------------------------------------------
    MEGA_S4_ENDPOINT_URL: str = field(
        default_factory=lambda: os.getenv(
            "MEGA_S4_ENDPOINT_URL", "https://s3.g.s4.mega.io"
        ).strip()
    )
    MEGA_S4_REGION: str = field(
        default_factory=lambda: os.getenv("MEGA_S4_REGION", "eu-central-1").strip()
    )
    MEGA_S4_BUCKET_NAME: str = field(
        default_factory=lambda: os.getenv(
            "MEGA_S4_BUCKET_NAME", "apex-vox-storage"
        ).strip()
    )
    MEGA_S4_ACCESS_KEY_ID: str = field(
        default_factory=lambda: os.getenv("MEGA_S4_ACCESS_KEY_ID", "").strip()
    )
    MEGA_S4_SECRET_ACCESS_KEY: str = field(
        default_factory=lambda: os.getenv("MEGA_S4_SECRET_ACCESS_KEY", "").strip()
    )

    # -------------------------------------------------------------------------
    # Supabase Cloud Configuration
    # -------------------------------------------------------------------------
    SUPABASE_URL: str = field(
        default_factory=lambda: os.getenv("SUPABASE_URL", "").strip()
    )
    SUPABASE_ANON_KEY: str = field(
        default_factory=lambda: os.getenv("SUPABASE_ANON_KEY", "").strip()
    )
    SUPABASE_SERVICE_ROLE_KEY: str = field(
        default_factory=lambda: os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )

    # -------------------------------------------------------------------------
    # Paths & Storage
    # -------------------------------------------------------------------------
    BASE_DIR: Path = field(default_factory=lambda: BASE_DIR)
    UPLOAD_DIR: Path = field(
        default_factory=lambda: Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
    )
    OUTPUT_DIR: Path = field(
        default_factory=lambda: Path(os.getenv("OUTPUT_DIR", str(BASE_DIR / "outputs")))
    )
    TEMP_DIR: Path = field(
        default_factory=lambda: Path(os.getenv("TEMP_DIR", str(BASE_DIR / "temp")))
    )

    # -------------------------------------------------------------------------
    # Groq & Deepgram API Configuration
    # -------------------------------------------------------------------------
    GROQ_API_KEY: str = field(
        default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip()
    )
    DEEPGRAM_API_KEY: str = field(
        default_factory=lambda: os.getenv("DEEPGRAM_API_KEY", "").strip()
    )
    DEEPGRAM_MODEL: str = field(
        default_factory=lambda: os.getenv("DEEPGRAM_MODEL", "nova-2")
    )
    DEFAULT_DIARIZATION_ENGINE: str = field(
        default_factory=lambda: os.getenv(
            "DEFAULT_DIARIZATION_ENGINE", "hybrid_deepgram_groq"
        )
    )
    GROQ_BASE_URL: str | None = field(
        default_factory=lambda: os.getenv("GROQ_BASE_URL", None)
    )
    GROQ_TIMEOUT_SECONDS: float = field(
        default_factory=lambda: float(os.getenv("GROQ_TIMEOUT_SECONDS", "120.0"))
    )
    GROQ_MAX_RETRIES: int = field(
        default_factory=lambda: int(os.getenv("GROQ_MAX_RETRIES", "3"))
    )

    # -------------------------------------------------------------------------
    # Models: Speech-to-Text (Whisper)
    # -------------------------------------------------------------------------
    DEFAULT_MODEL: str = field(
        default_factory=lambda: os.getenv("DEFAULT_MODEL", "whisper-large-v3")
    )
    FALLBACK_MODEL: str = field(
        default_factory=lambda: os.getenv("FALLBACK_MODEL", "whisper-large-v3-turbo")
    )
    AVAILABLE_WHISPER_MODELS: list[str] = field(
        default_factory=lambda: [
            "whisper-large-v3",
            "whisper-large-v3-turbo",
            "distil-whisper-large-v3",
        ]
    )
    WHISPER_RESPONSE_FORMAT: str = "verbose_json"
    WHISPER_TEMPERATURE: float = 0.0

    # -------------------------------------------------------------------------
    # Models: LLM & Diarization
    # -------------------------------------------------------------------------
    DEFAULT_LLM_MODEL: str = field(
        default_factory=lambda: os.getenv("DEFAULT_LLM_MODEL", "llama-3.3-70b-versatile")
    )
    FALLBACK_LLM_MODEL: str = field(
        default_factory=lambda: os.getenv("FALLBACK_LLM_MODEL", "llama-3.1-8b-instant")
    )
    AVAILABLE_LLM_MODELS: list[str] = field(
        default_factory=lambda: [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
        ]
    )
    DIARIZATION_MAX_SPEAKERS: int = field(
        default_factory=lambda: int(os.getenv("DIARIZATION_MAX_SPEAKERS", "10"))
    )
    DIARIZATION_TEMPERATURE: float = 0.0
    ACOUSTIC_PAUSE_THRESHOLD_SEC: float = field(
        default_factory=lambda: float(os.getenv("ACOUSTIC_PAUSE_THRESHOLD_SEC", "0.5"))
    )

    # -------------------------------------------------------------------------
    # Upload & File Limits
    # -------------------------------------------------------------------------
    MAX_FILE_SIZE_MB: int = field(
        default_factory=lambda: int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    )
    MAX_TOTAL_UPLOAD_SIZE_MB: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOTAL_UPLOAD_SIZE_MB", "500"))
    )
    MAX_FILES_PER_UPLOAD: int = field(
        default_factory=lambda: int(os.getenv("MAX_FILES_PER_UPLOAD", "20"))
    )
    ALLOWED_EXTENSIONS: set[str] = field(
        default_factory=lambda: {
            ".mp3",
            ".ogg",
            ".wav",
            ".m4a",
            ".flac",
            ".webm",
            ".mp4",
        }
    )

    # -------------------------------------------------------------------------
    # Audio Processing & Chunking Parameters
    # -------------------------------------------------------------------------
    GROQ_PAYLOAD_LIMIT_MB: float = 25.0
    GROQ_PAYLOAD_LIMIT_BYTES: int = field(
        default_factory=lambda: _parse_int_fallback(
            "GROQ_PAYLOAD_LIMIT_BYTES", "CHUNK_MAX_BYTES", 25 * 1024 * 1024
        )
    )
    CHUNK_TARGET_DURATION_SEC: float = field(
        default_factory=lambda: _parse_float_fallback(
            "CHUNK_TARGET_DURATION_SEC",
            "CHUNK_DURATION_MINUTES",
            600.0,
            fallback_multiplier=60.0,
        )
    )
    CHUNK_SEARCH_WINDOW_SEC: float = field(
        default_factory=lambda: float(os.getenv("CHUNK_SEARCH_WINDOW_SEC", "45.0"))
    )
    CHUNK_MAX_SEARCH_WINDOW_SEC: float = field(
        default_factory=lambda: float(os.getenv("CHUNK_MAX_SEARCH_WINDOW_SEC", "90.0"))
    )
    SILENCE_NOISE_THRESHOLD_DB: float = field(
        default_factory=lambda: _parse_float_fallback(
            "SILENCE_NOISE_THRESHOLD_DB", "SILENCE_THRESHOLD_DB", -30.0
        )
    )
    SILENCE_MIN_DURATION_SEC: float = field(
        default_factory=lambda: float(os.getenv("SILENCE_MIN_DURATION_SEC", "0.5"))
    )
    AUDIO_SAMPLE_RATE: int = field(
        default_factory=lambda: int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
    )
    AUDIO_CHANNELS: int = field(
        default_factory=lambda: int(os.getenv("AUDIO_CHANNELS", "1"))
    )
    AUDIO_BITRATE: str = field(
        default_factory=lambda: os.getenv("AUDIO_BITRATE", "64k")
    )
    AUDIO_OUTPUT_FORMAT: str = field(
        default_factory=lambda: os.getenv("AUDIO_OUTPUT_FORMAT", "mp3")
    )

    # -------------------------------------------------------------------------
    # Job Management & Lifecycle
    # -------------------------------------------------------------------------
    JOB_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: int(os.getenv("JOB_TIMEOUT_SECONDS", "1800"))
    )
    CLEANUP_TEMP_FILES: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("CLEANUP_TEMP_FILES", "true"), default=True
        )
    )
    JOB_RETENTION_HOURS: int = field(
        default_factory=lambda: int(os.getenv("JOB_RETENTION_HOURS", "24"))
    )

    # -------------------------------------------------------------------------
    # Post-initialization & Directory Creation
    # -------------------------------------------------------------------------
    def __post_init__(self) -> None:
        """Create directories and validate configuration state."""
        self._ensure_directories()
        self._check_groq_api_key()

    def _ensure_directories(self) -> None:
        """Ensure upload, output, and temp directories exist."""
        try:
            self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            self.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Failed to create storage directory: %s", e)

    def _check_groq_api_key(self) -> None:
        """Log a non-blocking warning if GROQ_API_KEY is not configured."""
        if not self.is_groq_configured:
            logger.warning(
                "GROQ_API_KEY is not configured. Healthcheck and static UI will work, "
                "but transcription requests will fail until GROQ_API_KEY is set in environment or .env."
            )

    @property
    def CHUNK_DURATION_MINUTES(self) -> float:
        """Target chunk duration expressed in minutes."""
        return self.CHUNK_TARGET_DURATION_SEC / 60.0

    @property
    def CHUNK_MAX_BYTES(self) -> int:
        """Maximum chunk payload limit in bytes (alias for GROQ_PAYLOAD_LIMIT_BYTES)."""
        return self.GROQ_PAYLOAD_LIMIT_BYTES

    @property
    def SILENCE_THRESHOLD_DB(self) -> float:
        """Silence detection threshold in dB (alias for SILENCE_NOISE_THRESHOLD_DB)."""
        return self.SILENCE_NOISE_THRESHOLD_DB

    @property
    def is_email_configured(self) -> bool:
        """Return True when a Resend API key is available."""
        return bool(self.RESEND_API_KEY)

    @property
    def GUEST_MAX_AUDIO_SECONDS(self) -> float:
        return self.GUEST_MAX_AUDIO_MINUTES * 60.0

    @property
    def is_production(self) -> bool:
        """Return True when ENVIRONMENT is 'production'."""
        return str(self.ENVIRONMENT).strip().lower() == "production"

    @property
    def is_groq_configured(self) -> bool:
        """Return True if a non-empty GROQ_API_KEY is configured."""
        return bool(self.GROQ_API_KEY and self.GROQ_API_KEY.strip())

    @property
    def is_deepgram_configured(self) -> bool:
        """Return True if a non-empty DEEPGRAM_API_KEY is configured."""
        return bool(self.DEEPGRAM_API_KEY and self.DEEPGRAM_API_KEY.strip())

    @property
    def is_supabase_configured(self) -> bool:
        """Return True if Supabase Cloud URL and API key are configured."""
        return bool(
            self.SUPABASE_URL
            and self.SUPABASE_URL.strip()
            and (self.SUPABASE_ANON_KEY or self.SUPABASE_SERVICE_ROLE_KEY)
        )

    @property
    def is_mega_s4_configured(self) -> bool:
        """Return True if MEGA S4 S3-compatible credentials are configured."""
        return bool(
            self.MEGA_S4_ENDPOINT_URL
            and self.MEGA_S4_ACCESS_KEY_ID
            and self.MEGA_S4_SECRET_ACCESS_KEY
        )

    @property
    def is_bold_configured(self) -> bool:
        """Return True if Bold API payment keys are configured."""
        return bool(self.BOLD_API_KEY and self.BOLD_API_KEY.strip())

    def validate_for_transcription(self) -> None:
        """
        Validate that requirements for transcription are satisfied.
        Called by transcription service before executing a job.
        Raises RuntimeError if GROQ_API_KEY is missing.
        """
        if not self.is_groq_configured:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Please provide a valid Groq API key "
                "in your .env file or container environment variables."
            )


ENGINE_ALIAS_MAP: dict[str, str] = {
    "mc-ayrton": "deepgram",
    "mc_ayrton": "deepgram",
    "ayrton": "deepgram",
    "mc-lewis": "hybrid_deepgram_groq",
    "mc_lewis": "hybrid_deepgram_groq",
    "lewis": "hybrid_deepgram_groq",
    "mc-norris": "acoustic_local",
    "mc_norris": "acoustic_local",
    "norris": "acoustic_local",
    "mc-piastri": "groq_llm",
    "mc_piastri": "groq_llm",
    "piastri": "groq_llm",
    # Direct internal keys remain valid
    "hybrid_deepgram_groq": "hybrid_deepgram_groq",
    "deepgram": "deepgram",
    "acoustic_local": "acoustic_local",
    "groq_llm": "groq_llm",
}

ENGINE_PUBLIC_BRAND_MAP: dict[str, str] = {
    "deepgram": "Mc-Ayrton",
    "mc-ayrton": "Mc-Ayrton",
    "hybrid_deepgram_groq": "Mc-Lewis",
    "mc-lewis": "Mc-Lewis",
    "acoustic_local": "Mc-Norris",
    "mc-norris": "Mc-Norris",
    "groq_llm": "Mc-Piastri",
    "mc-piastri": "Mc-Piastri",
}

MODEL_ALIAS_MAP: dict[str, str] = {
    "mc-ayrton": "whisper-large-v3",
    "mc-lewis": "whisper-large-v3",
    "mc-norris": "whisper-large-v3",
    "mc-piastri": "whisper-large-v3-turbo",
    "whisper-large-v3": "whisper-large-v3",
    "whisper-large-v3-turbo": "whisper-large-v3-turbo",
    "distil-whisper-large-v3": "distil-whisper-large-v3",
}


def resolve_engine_code(raw_engine: str | None) -> str:
    """Resolve user-facing engine code (e.g. 'Mc-Ayrton', 'Mc-Lewis') to internal pipeline key."""
    if not raw_engine:
        return settings.DEFAULT_DIARIZATION_ENGINE or "hybrid_deepgram_groq"
    cleaned = raw_engine.strip().lower()
    return ENGINE_ALIAS_MAP.get(cleaned, cleaned)


def get_public_engine_label(raw_engine: str | None) -> str:
    """Return the public Mc-Series label for a given engine code."""
    if not raw_engine:
        return "Mc-Lewis"
    cleaned = raw_engine.strip().lower()
    return ENGINE_PUBLIC_BRAND_MAP.get(cleaned, "Mc-Lewis")


def resolve_model_code(raw_model: str | None) -> str:
    """Resolve user-facing model code (e.g. 'Mc-Ayrton' or 'whisper-large-v3') to Groq model ID."""
    if not raw_model:
        return settings.DEFAULT_MODEL or "whisper-large-v3"
    cleaned = raw_model.strip().lower()
    return MODEL_ALIAS_MAP.get(cleaned, raw_model.strip())


# Singleton settings instance
settings = Settings()


@lru_cache()
def get_settings() -> Settings:
    """Return the cached settings singleton (FastAPI dependency compatible)."""
    return settings


# -----------------------------------------------------------------------------
# Backward Compatibility Module-Level Aliases
# -----------------------------------------------------------------------------
# Existing codebase imports these names directly from app.config
UPLOAD_DIR = settings.UPLOAD_DIR
OUTPUT_DIR = settings.OUTPUT_DIR
TEMP_DIR = settings.TEMP_DIR
DEFAULT_GROQ_API_KEY = settings.GROQ_API_KEY
DEFAULT_MODEL = settings.DEFAULT_MODEL
DEFAULT_LLM_MODEL = settings.DEFAULT_LLM_MODEL
MAX_FILE_SIZE_MB = settings.MAX_FILE_SIZE_MB
CHUNK_TARGET_DURATION_SEC = settings.CHUNK_TARGET_DURATION_SEC
CHUNK_DURATION_MINUTES = settings.CHUNK_DURATION_MINUTES
GROQ_PAYLOAD_LIMIT_BYTES = settings.GROQ_PAYLOAD_LIMIT_BYTES
CHUNK_MAX_BYTES = settings.CHUNK_MAX_BYTES
SILENCE_NOISE_THRESHOLD_DB = settings.SILENCE_NOISE_THRESHOLD_DB
SILENCE_THRESHOLD_DB = settings.SILENCE_THRESHOLD_DB

