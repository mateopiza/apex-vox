"""
Supabase Cloud Backend Service (app/services/supabase_service.py)
-----------------------------------------------------------------
Manages user authentication, profiles, daily audio quota tracking,
subscription plans, and transcription history backed by Supabase Cloud
(PostgREST & GoTrue Auth REST APIs) with automatic local JSON persistence
fallback when Supabase Cloud credentials are not set in `.env`.

Business Rules Enforced:
1. Free Plan ('free'):
   - Registration grants 2 hours free per day (7,200 seconds/day) across 1 or multiple audios.
   - Storage retention is 24 hours (expires_at = created_at + 24h).
2. Paid Plan ('trial' / 'pro'):
   - $30,000 COP / $10 USD per month via Bold API.
   - Includes 3-day free trial with automatic recurring billing.
   - Unlimited daily audio transcriptions and unlimited storage retention.
   - Unlocks Apex Summa AI intelligence report & formal Minutes ('Actas') generator.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import secrets
import threading
import uuid
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.models.schemas import QuotaUsageResponse, UserProfileResponse

logger = logging.getLogger("app.services.supabase_service")


_PBKDF2_ITERATIONS = 310_000
MIN_PASSWORD_LENGTH = 8


def _legacy_hash_password(password: str, salt: str = "apex_vox_salt") -> str:
    """Pre-2.1 scheme (unsalted SHA-256). Only used to verify and migrate old accounts."""
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt, expected = stored.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
            )
            return hmac.compare_digest(digest.hex(), expected)
        except ValueError:
            return False
    return hmac.compare_digest(_legacy_hash_password(password), stored)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _today_str() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


class SupabaseCloudService:
    """
    Production client for Supabase Cloud (Auth + PostgREST) with synchronized
    local state persistence for offline/test resilience.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._db_file = settings.OUTPUT_DIR / "supabase_cloud_state.json"
        self._ensure_seed_state()

    @property
    def is_cloud_configured(self) -> bool:
        return settings.is_supabase_configured

    def _rest_headers(self, use_service_role: bool = True) -> Dict[str, str]:
        key = (
            settings.SUPABASE_SERVICE_ROLE_KEY
            if use_service_role and settings.SUPABASE_SERVICE_ROLE_KEY
            else settings.SUPABASE_ANON_KEY
        )
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _ensure_seed_state(self) -> None:
        with self._lock:
            if not self._db_file.exists():
                self._db_file.parent.mkdir(parents=True, exist_ok=True)
                initial = {
                    "users": {},
                    "tokens": {},
                    "daily_usage": {},
                    "subscriptions": {},
                    "transcriptions": {},
                }
                self._db_file.write_text(
                    json.dumps(initial, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    def _load_db(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_seed_state()
            try:
                db = json.loads(self._db_file.read_text(encoding="utf-8"))
                for key in ("users", "tokens", "daily_usage", "subscriptions", "transcriptions", "payments", "handoffs"):
                    db.setdefault(key, {})
                return db
            except Exception:
                return {
                    "users": {},
                    "tokens": {},
                    "daily_usage": {},
                    "subscriptions": {},
                    "transcriptions": {},
                    "payments": {},
                    "handoffs": {},
                }

    def _save_db(self, db: Dict[str, Any]) -> None:
        with self._lock:
            self._db_file.parent.mkdir(parents=True, exist_ok=True)
            self._db_file.write_text(
                json.dumps(db, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _sync_to_supabase_table(
        self, table: str, record: Dict[str, Any], upsert_col: Optional[str] = None
    ) -> bool:
        """Sync a record to Supabase Cloud PostgREST if SUPABASE_URL is configured."""
        if not self.is_cloud_configured:
            return False
        base = settings.SUPABASE_URL.rstrip("/")
        url = f"{base}/rest/v1/{table}"
        headers = self._rest_headers(use_service_role=True)
        if upsert_col:
            headers["Prefer"] = "resolution=merge-duplicates,return=representation"
            url = f"{url}?on_conflict={upsert_col}"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=record, headers=headers)
                return resp.status_code in (200, 201, 204)
        except Exception as exc:
            logger.debug("Supabase Cloud sync skipped for %s: %s", table, exc)
            return False

    # -------------------------------------------------------------------------
    # User Registration & Login
    # -------------------------------------------------------------------------

    def register_user(
        self,
        email: str,
        password: str,
        full_name: str = "",
        preferred_language: str = "es",
    ) -> UserProfileResponse:
        """
        Register a new user in Supabase Cloud & grant the Free tier:
        2 hours of audio per day (in 1 or multiple audios) + 24-hour storage retention.
        """
        clean_email = email.strip().lower()
        if not clean_email or "@" not in clean_email:
            raise ValueError("Correo electrónico inválido / Invalid email address.")
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres / "
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )

        with self._lock:
            db = self._load_db()
            for uid, u in db["users"].items():
                if u.get("email", "").lower() == clean_email:
                    raise ValueError(f"El correo '{clean_email}' ya está registrado.")

            user_id = str(uuid.uuid4())
            now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

            user_record = {
                "user_id": user_id,
                "email": clean_email,
                "full_name": full_name.strip() or clean_email.split("@")[0].capitalize(),
                "password_hash": _hash_password(password),
                "plan": "free",
                "preferred_language": preferred_language if preferred_language in ("es", "en") else "es",
                "trial_started_at": None,
                "trial_ends_at": None,
                "trial_used": False,
                "pro_until": None,
                "auto_billing_enabled": False,
                "auth_providers": ["email"],
                "created_at": now_iso,
            }

            db["users"][user_id] = user_record
            token = self._issue_token(db, user_id)
            self._save_db(db)

        # Sync to Supabase Cloud if configured
        self._sync_to_supabase_table(
            "profiles",
            {
                "id": user_id,
                "email": clean_email,
                "full_name": user_record["full_name"],
                "password_hash": user_record["password_hash"],
                "plan": "free",
                "preferred_language": user_record["preferred_language"],
                "created_at": now_iso,
            },
            upsert_col="email",
        )

        quota = self.get_user_quota(user_id)
        return UserProfileResponse(
            user_id=user_id,
            email=clean_email,
            full_name=user_record["full_name"],
            plan="free",
            preferred_language=user_record["preferred_language"],
            access_token=token,
            created_at=now_iso,
            quota=quota,
        )

    def login_user(self, email: str, password: str) -> UserProfileResponse:
        clean_email = email.strip().lower()

        with self._lock:
            db = self._load_db()
            matched_user = None
            for uid, u in db["users"].items():
                if u.get("email", "").lower() == clean_email:
                    matched_user = u
                    break

            if not matched_user or not _verify_password(password, matched_user.get("password_hash", "")):
                raise ValueError("Credenciales inválidas. Verifica tu correo y contraseña.")

            # Transparently migrate legacy SHA-256 hashes to PBKDF2.
            if not str(matched_user.get("password_hash", "")).startswith("pbkdf2_sha256$"):
                matched_user["password_hash"] = _hash_password(password)
            user_id = matched_user["user_id"]
            token = self._issue_token(db, user_id)
            self._save_db(db)

        return self._profile_response(user_id, token)

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------

    def _issue_token(self, db: Dict[str, Any], user_id: str) -> str:
        token = f"apx_{secrets.token_urlsafe(32)}"
        expires = _now() + dt.timedelta(days=settings.SESSION_TTL_DAYS)
        db["tokens"][token] = {"user_id": user_id, "expires_at": expires.isoformat()}
        return token

    @staticmethod
    def _clean_token(authorization: Optional[str]) -> str:
        clean = (authorization or "").strip()
        if clean.lower().startswith("bearer "):
            clean = clean[7:].strip()
        return clean

    def get_user_by_token(self, authorization: Optional[str]) -> Optional[Dict[str, Any]]:
        """Resolve a session token (raw or 'Bearer <token>'). User ids are never accepted."""
        token = self._clean_token(authorization)
        if not token.startswith("apx_"):
            return None
        with self._lock:
            db = self._load_db()
            entry = db["tokens"].get(token)
            if entry is None:
                return None
            if isinstance(entry, str):  # legacy, non-expiring token
                uid = entry
            else:
                expires = _parse_iso(entry.get("expires_at"))
                if expires and _now() >= expires:
                    db["tokens"].pop(token, None)
                    self._save_db(db)
                    return None
                uid = entry.get("user_id")
            user = db["users"].get(uid)
            if user and self._refresh_plan_expiry(user):
                self._save_db(db)
            return dict(user) if user else None

    def revoke_token(self, authorization: Optional[str]) -> None:
        token = self._clean_token(authorization)
        with self._lock:
            db = self._load_db()
            if db["tokens"].pop(token, None) is not None:
                self._save_db(db)

    def _profile_response(self, user_id: str, token: str = "") -> UserProfileResponse:
        with self._lock:
            user = self._load_db()["users"].get(user_id) or {}
        quota = self.get_user_quota(user_id)
        return UserProfileResponse(
            user_id=user_id,
            email=user.get("email", ""),
            full_name=user.get("full_name", ""),
            plan=quota.plan,
            preferred_language=user.get("preferred_language", "es"),
            access_token=token,
            created_at=user.get("created_at", ""),
            quota=quota,
        )

    def get_profile(self, user_id: str) -> UserProfileResponse:
        return self._profile_response(user_id)

    # -------------------------------------------------------------------------
    # OAuth (Google / GitHub via Supabase Auth)
    # -------------------------------------------------------------------------

    def upsert_oauth_user(
        self,
        email: str,
        full_name: str,
        provider: str,
        preferred_language: str = "es",
    ) -> UserProfileResponse:
        """Sign in (or create) the account that owns this provider-verified e-mail."""
        clean_email = (email or "").strip().lower()
        if not clean_email or "@" not in clean_email:
            raise ValueError("El proveedor no devolvió un correo verificado.")
        now_iso = _now().isoformat()
        with self._lock:
            db = self._load_db()
            user = next(
                (u for u in db["users"].values() if u.get("email", "").lower() == clean_email),
                None,
            )
            created = user is None
            if created:
                user = {
                    "user_id": str(uuid.uuid4()),
                    "email": clean_email,
                    "full_name": (full_name or "").strip() or clean_email.split("@")[0].capitalize(),
                    "password_hash": "",
                    "plan": "free",
                    "preferred_language": preferred_language if preferred_language in ("es", "en") else "es",
                    "trial_started_at": None,
                    "trial_ends_at": None,
                    "trial_used": False,
                    "pro_until": None,
                    "auto_billing_enabled": False,
                    "auth_providers": [provider],
                    "created_at": now_iso,
                }
                db["users"][user["user_id"]] = user
            else:
                providers = set(user.get("auth_providers") or ["email"])
                providers.add(provider)
                user["auth_providers"] = sorted(providers)
                if full_name and not user.get("full_name"):
                    user["full_name"] = full_name.strip()
            token = self._issue_token(db, user["user_id"])
            self._save_db(db)

        if created:
            self._sync_to_supabase_table(
                "profiles",
                {
                    "id": user["user_id"],
                    "email": clean_email,
                    "full_name": user["full_name"],
                    "plan": "free",
                    "preferred_language": user["preferred_language"],
                    "created_at": now_iso,
                },
                upsert_col="email",
            )
        return self._profile_response(user["user_id"], token)

    def create_handoff_code(self, access_token: str, ttl_seconds: int = 120) -> str:
        """One-time code that lets the browser pick up a session after an OAuth redirect."""
        code = secrets.token_urlsafe(24)
        with self._lock:
            db = self._load_db()
            now = _now()
            db["handoffs"] = {
                k: v for k, v in db["handoffs"].items()
                if (_parse_iso(v.get("expires_at")) or now) > now
            }
            db["handoffs"][code] = {
                "token": access_token,
                "expires_at": (now + dt.timedelta(seconds=ttl_seconds)).isoformat(),
            }
            self._save_db(db)
        return code

    def consume_handoff_code(self, code: str) -> Optional[UserProfileResponse]:
        with self._lock:
            db = self._load_db()
            entry = db["handoffs"].pop(code or "", None)
            self._save_db(db)
        if not entry:
            return None
        expires = _parse_iso(entry.get("expires_at"))
        if expires and _now() >= expires:
            return None
        user = self.get_user_by_token(entry["token"])
        if not user:
            return None
        return self._profile_response(user["user_id"], entry["token"])

    def get_user_by_token_or_id(self, identifier: Optional[str]) -> Optional[Dict[str, Any]]:
        """Internal helper for server-trusted ids. Never pass client-supplied ids here."""
        if not identifier:
            return None
        clean = identifier.strip()
        if clean.lower().startswith("bearer "):
            clean = clean[7:].strip()

        with self._lock:
            db = self._load_db()
            if clean in db["tokens"]:
                entry = db["tokens"][clean]
                uid = entry if isinstance(entry, str) else entry.get("user_id")
                return db["users"].get(uid)
            if clean in db["users"]:
                return db["users"][clean]
        return None

    # -------------------------------------------------------------------------
    # Quota & Plan Management (2h Free/day vs Unlimited Pro)
    # -------------------------------------------------------------------------

    @staticmethod
    def _refresh_plan_expiry(user: Dict[str, Any]) -> bool:
        """Downgrade expired trials / paid periods to the free plan. Returns True if changed."""
        plan = str(user.get("plan", "free")).lower()
        now = _now()
        if plan == "trial":
            ends = _parse_iso(user.get("trial_ends_at"))
            if ends and now >= ends:
                pro_until = _parse_iso(user.get("pro_until"))
                user["plan"] = "pro" if pro_until and pro_until > now else "free"
                return True
        elif plan == "pro":
            pro_until = _parse_iso(user.get("pro_until"))
            if pro_until and now >= pro_until:
                user["plan"] = "free"
                return True
        return False

    def get_user_quota(self, user_id: str) -> QuotaUsageResponse:
        with self._lock:
            db = self._load_db()
            user = db["users"].get(user_id)
            if user and self._refresh_plan_expiry(user):
                self._save_db(db)
            plan = (user.get("plan", "free") if user else "free").lower()
            today = _today_str()
            usage_key = f"{user_id}:{today}"
            usage_entry = db["daily_usage"].get(usage_key, {})
            used_sec = float(usage_entry.get("used_seconds", 0.0))

            is_paid = plan in ("pro", "trial")
            daily_limit = None if is_paid else settings.FREE_DAILY_SECONDS
            remaining = None if is_paid else max(0.0, float(settings.FREE_DAILY_SECONDS) - used_sec)
            retention = None if is_paid else settings.FREE_RETENTION_HOURS

            if plan == "trial":
                display_name = "Apex Pro (Prueba Gratis 3 Días)"
            elif plan == "pro":
                display_name = "Apex Pro (Ilimitado)"
            else:
                display_name = "Plan Gratis (2h / día · 24h almacenamiento)"

            return QuotaUsageResponse(
                user_id=user_id,
                plan=plan,
                plan_display_name=display_name,
                daily_limit_seconds=daily_limit,
                used_today_seconds=round(used_sec, 2),
                remaining_today_seconds=round(remaining, 2) if remaining is not None else None,
                is_unlimited=is_paid,
                retention_hours=retention,
                storage_provider="mega_s4",
                summa_enabled=is_paid,
                trial_active=(plan == "trial"),
                trial_ends_at=user.get("trial_ends_at") if user else None,
                auto_billing_enabled=False,
                pro_until=user.get("pro_until") if user else None,
                trial_available=bool(user) and not user.get("trial_used") and plan == "free",
            )

    def check_and_consume_quota(
        self,
        user_id: Optional[str],
        duration_seconds: float,
        audios_count: int = 1,
        plan_override: Optional[str] = None,
    ) -> QuotaUsageResponse:
        """
        Verify if user has enough daily quota for the requested audio duration
        (across 1 or multiple audios per day) and record the usage.
        Raises PermissionError if Free user exceeds 2 hours (7,200 seconds) today.
        """
        uid = user_id or "guest_default"
        with self._lock:
            db = self._load_db()
            if uid not in db["users"]:
                # Auto-provision guest/default profile so quota tracking works seamlessly
                db["users"][uid] = {
                    "user_id": uid,
                    "email": f"{uid}@apexvox.local",
                    "full_name": "Usuario Apex Vox",
                    "password_hash": "",
                    "plan": plan_override or "free",
                    "preferred_language": "es",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            if plan_override in ("free", "trial", "pro"):
                db["users"][uid]["plan"] = plan_override

            user = db["users"][uid]
            self._refresh_plan_expiry(user)
            plan = user.get("plan", "free").lower()
            is_paid = plan in ("pro", "trial")

            today = _today_str()
            usage_key = f"{uid}:{today}"
            current_entry = db["daily_usage"].get(
                usage_key, {"used_seconds": 0.0, "audios_count": 0}
            )
            used_before = float(current_entry.get("used_seconds", 0.0))

            if not is_paid and (used_before + duration_seconds) > settings.FREE_DAILY_SECONDS:
                rem = max(0.0, settings.FREE_DAILY_SECONDS - used_before)
                raise PermissionError(
                    f"Has alcanzado el límite de 2 horas gratis al día ({settings.FREE_DAILY_SECONDS}s). "
                    f"Disponible hoy: {rem:.0f}s, requerido: {duration_seconds:.0f}s. "
                    f"Activa la prueba gratis de 3 días del Plan Apex Pro ($30.000 COP / $10 USD mes) para transcripciones ilimitadas."
                )

            current_entry["used_seconds"] = round(used_before + max(0.0, duration_seconds), 3)
            current_entry["audios_count"] = int(current_entry.get("audios_count", 0)) + max(1, audios_count)
            current_entry["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            db["daily_usage"][usage_key] = current_entry
            self._save_db(db)

        return self.get_user_quota(uid)

    def start_trial(self, user_id: str) -> UserProfileResponse:
        """Start the one-time 3-day Apex Pro trial for a registered account."""
        with self._lock:
            db = self._load_db()
            user = db["users"].get(user_id)
            if not user:
                raise LookupError("Cuenta no encontrada.")
            self._refresh_plan_expiry(user)
            if user.get("trial_used"):
                raise PermissionError("La prueba gratis de 3 días ya fue utilizada en esta cuenta.")
            if user.get("plan") in ("pro", "trial"):
                raise PermissionError("Tu cuenta ya tiene Apex Pro activo.")
            now = _now()
            user["plan"] = "trial"
            user["trial_used"] = True
            user["trial_started_at"] = now.isoformat()
            user["trial_ends_at"] = (now + dt.timedelta(days=settings.PRO_TRIAL_DAYS)).isoformat()
            self._save_db(db)
        return self._profile_response(user_id)

    def record_pending_payment(
        self,
        user_id: str,
        reference: str,
        payment_link: str,
        amount: int,
        currency: str,
    ) -> None:
        with self._lock:
            db = self._load_db()
            db["payments"][reference] = {
                "reference": reference,
                "payment_link": payment_link,
                "user_id": user_id,
                "amount": amount,
                "currency": currency,
                "status": "pending",
                "created_at": _now().isoformat(),
            }
            self._save_db(db)

    def list_pending_payments(self, user_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            db = self._load_db()
            return [
                dict(p) for p in db["payments"].values()
                if p.get("user_id") == user_id and p.get("status") == "pending"
            ]

    def activate_paid_period(
        self,
        user_id: str,
        reference: str,
        currency: str = "COP",
        source: str = "bold",
    ) -> UserProfileResponse:
        """
        Grant PRO_PERIOD_DAYS of Apex Pro for an approved payment. Idempotent per
        payment reference, so webhook retries and manual confirmation never stack.
        """
        with self._lock:
            db = self._load_db()
            user = db["users"].get(user_id)
            if not user:
                raise LookupError("Cuenta no encontrada.")
            payment = db["payments"].setdefault(
                reference,
                {
                    "reference": reference,
                    "user_id": user_id,
                    "currency": currency,
                    "status": "pending",
                    "created_at": _now().isoformat(),
                },
            )
            if payment.get("user_id") != user_id:
                raise PermissionError("La referencia de pago no pertenece a esta cuenta.")
            if payment.get("status") == "paid":
                self._save_db(db)
                return self._profile_response(user_id)

            now = _now()
            self._refresh_plan_expiry(user)
            # Stack on top of whatever access is still running (trial or paid period).
            candidates = [_parse_iso(user.get("pro_until"))]
            if user.get("plan") == "trial":
                candidates.append(_parse_iso(user.get("trial_ends_at")))
            start = max([d for d in candidates if d and d > now] or [now])
            user["pro_until"] = (start + dt.timedelta(days=settings.PRO_PERIOD_DAYS)).isoformat()
            if user.get("plan") != "trial":
                user["plan"] = "pro"
            payment.update(
                {"status": "paid", "paid_at": now.isoformat(), "source": source, "currency": currency.upper()}
            )
            db["subscriptions"][reference] = {
                "order_id": reference,
                "user_id": user_id,
                "plan": "pro",
                "status": "active",
                "amount": settings.PRO_PRICE_COP if currency.upper() == "COP" else int(settings.PRO_PRICE_USD),
                "currency": currency.upper(),
                "period_days": settings.PRO_PERIOD_DAYS,
                "pro_until": user["pro_until"],
                "created_at": now.isoformat(),
            }
            self._save_db(db)
        return self._profile_response(user_id)

    def save_transcription_record(self, record: Dict[str, Any]) -> None:
        """Persist transcription metadata and Mega S4 keys in Supabase Cloud & local DB."""
        job_id = record.get("job_id")
        if not job_id:
            return
        with self._lock:
            db = self._load_db()
            db["transcriptions"][job_id] = record
            self._save_db(db)
        self._sync_to_supabase_table("transcriptions", record, upsert_col="job_id")

    def list_user_transcriptions(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return non-expired transcription records for the user portal."""
        now = dt.datetime.now(dt.timezone.utc)
        with self._lock:
            db = self._load_db()
            items: List[Dict[str, Any]] = []
            for jid, rec in db.get("transcriptions", {}).items():
                if user_id and rec.get("user_id") != user_id:
                    continue
                exp_str = rec.get("expires_at")
                if exp_str:
                    try:
                        exp_dt = dt.datetime.fromisoformat(exp_str)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=dt.timezone.utc)
                        if now >= exp_dt:
                            continue
                    except Exception:
                        pass
                items.append(rec)
            items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            return items


supabase_service = SupabaseCloudService()
