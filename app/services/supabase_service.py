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
2. Paid Plan ('pro'):
   - USD 10 per 30 days via a one-off Bold payment link (Bold has no subscriptions:
     every month is paid manually; nothing is charged automatically). No free trial.
   - Welcome promo: 20% off the first month if paid within 24 h of creating the account,
     at most one promo per network (IP) per 90 days.
   - Unlimited daily audio transcriptions and unlimited storage retention.
   - Unlocks Apex Summa AI intelligence report & formal Minutes ('Actas') generator.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

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
                for key in ("users", "tokens", "daily_usage", "subscriptions", "transcriptions", "payments", "handoffs", "promo_ips"):
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
                    "promo_ips": {},
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

    def email_registered(self, email: str) -> bool:
        clean = (email or "").strip().lower()
        with self._lock:
            return any(u.get("email", "").lower() == clean for u in self._load_db()["users"].values())

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

            if plan == "trial":  # cuentas antiguas con prueba en curso
                display_name = "Apex Pro"
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
                trial_available=False,
            )

    def check_and_consume_quota(
        self,
        user_id: Optional[str],
        duration_seconds: float,
        audios_count: int = 1,
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
                    "plan": "free",
                    "preferred_language": "es",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }

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

    # -------------------------------------------------------------------------
    # Precio y promoción de bienvenida
    # -------------------------------------------------------------------------

    def _ip_hash(self, client_ip: str) -> str:
        return self._digest(f"ip:{client_ip}")[:20]

    @staticmethod
    def _has_paid(db: Dict[str, Any], user_id: str) -> bool:
        return any(
            p.get("user_id") == user_id and p.get("status") == "paid" for p in db["payments"].values()
        )

    @staticmethod
    def _promo_ip_blocked(db: Dict[str, Any], ip_hash: str, now: dt.datetime) -> bool:
        used = _parse_iso((db.get("promo_ips") or {}).get(ip_hash, {}).get("used_at"))
        return bool(used and now - used < dt.timedelta(days=settings.PROMO_IP_COOLDOWN_DAYS))

    def promo_ends_at(self, user: Dict[str, Any]) -> Optional[dt.datetime]:
        created = _parse_iso(user.get("created_at"))
        return created + dt.timedelta(hours=settings.PROMO_WINDOW_HOURS) if created else None

    def billing_offer(self, user_id: str, client_ip: str) -> Dict[str, Any]:
        """
        Precio que pagaría ahora la cuenta: USD 10, o USD 10 menos el 20 % si está dentro de
        las primeras 24 h desde su creación, nunca ha pagado y su red no usó la promoción
        en los últimos 90 días.
        """
        regular = round(float(settings.PRO_PRICE_USD), 2)
        promo_price = round(regular * (100 - settings.PROMO_DISCOUNT_PCT) / 100, 2)
        now = _now()
        with self._lock:
            db = self._load_db()
            user = db["users"].get(user_id)
            if not user:
                raise LookupError("Cuenta no encontrada.")
            ends = self.promo_ends_at(user)
            reason = None
            if user.get("promo_used") or self._has_paid(db, user_id):
                reason = "first_month_only"
            elif not ends or now >= ends:
                reason = "window_expired"
            elif client_ip and self._promo_ip_blocked(db, self._ip_hash(client_ip), now):
                reason = "ip_used_this_quarter"
        eligible = reason is None
        return {
            "currency": "USD",
            "regular_price": regular,
            "price": promo_price if eligible else regular,
            "promo_eligible": eligible,
            "promo_price": promo_price,
            "discount_pct": settings.PROMO_DISCOUNT_PCT,
            "promo_ends_at": ends.isoformat() if ends and eligible else None,
            "promo_reason": reason,
            "period_days": settings.PRO_PERIOD_DAYS,
            "auto_renewal": False,
        }

    def record_pending_payment(
        self,
        user_id: str,
        reference: str,
        payment_link: str,
        amount: float,
        currency: str,
        promo: bool = False,
        client_ip: str = "",
    ) -> None:
        with self._lock:
            db = self._load_db()
            db["payments"][reference] = {
                "reference": reference,
                "payment_link": payment_link,
                "user_id": user_id,
                "amount": amount,
                "currency": currency,
                "promo": bool(promo),
                "ip_hash": self._ip_hash(client_ip) if client_ip else None,
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
        currency: str = "USD",
        source: str = "bold",
        on_activated: Optional[Callable[[Dict[str, Any], Dict[str, Any]], None]] = None,
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
            # Cada pago suma un mes sobre el acceso que siga vigente (renovación anticipada).
            candidates = [_parse_iso(user.get("pro_until"))]
            if user.get("plan") == "trial":  # cuentas antiguas con prueba en curso
                candidates.append(_parse_iso(user.get("trial_ends_at")))
            start = max([d for d in candidates if d and d > now] or [now])
            user["pro_until"] = (start + dt.timedelta(days=settings.PRO_PERIOD_DAYS)).isoformat()
            user["plan"] = "pro"
            if payment.get("promo"):
                user["promo_used"] = True
                if payment.get("ip_hash"):
                    db["promo_ips"][payment["ip_hash"]] = {"used_at": now.isoformat(), "user_id": user_id}
            payment.update(
                {"status": "paid", "paid_at": now.isoformat(), "source": source, "currency": currency.upper()}
            )
            db["subscriptions"][reference] = {
                "order_id": reference,
                "user_id": user_id,
                "plan": "pro",
                "status": "active",
                "amount": payment.get("amount", settings.PRO_PRICE_USD),
                "promo": bool(payment.get("promo")),
                "currency": currency.upper(),
                "period_days": settings.PRO_PERIOD_DAYS,
                "pro_until": user["pro_until"],
                "created_at": now.isoformat(),
            }
            self._save_db(db)
            snapshot_user, snapshot_payment = dict(user), dict(payment)
        if on_activated:
            try:
                on_activated(snapshot_user, snapshot_payment)
            except Exception as exc:  # notifications must never undo a payment
                logger.warning("Payment activation hook failed: %s", exc)
        return self._profile_response(user_id)

    # -------------------------------------------------------------------------
    # Correos de facturación programados (promo por vencer, renovación, vencido)
    # -------------------------------------------------------------------------

    def collect_due_billing_emails(self) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Devuelve los correos que tocan ahora y los marca como enviados (una sola vez):
        - "promo_reminder": faltan 6 h o menos para que termine la promoción y la cuenta es elegible.
        - "renewal_reminder": faltan RENEWAL_REMINDER_DAYS días o menos para que termine el mes pagado.
        - "expired": el mes pagado terminó hace menos de 7 días.
        """
        now = _now()
        due: List[Tuple[str, Dict[str, Any]]] = []
        with self._lock:
            db = self._load_db()
            changed = False
            for user_id, user in db["users"].items():
                if not user.get("email") or user.get("email", "").endswith(".local"):
                    continue
                sent = user.setdefault("billing_emails", {})
                ends = self.promo_ends_at(user)
                if (
                    ends and now < ends <= now + dt.timedelta(hours=6)
                    and "promo_reminder" not in sent
                    and not user.get("promo_used") and not self._has_paid(db, user_id)
                    and not any(
                        self._promo_ip_blocked(db, h, now)
                        for hashes in (user.get("ip_months") or {}).values() for h in hashes
                    )
                ):
                    due.append(("promo_reminder", {**user, "promo_ends_at": ends.isoformat()}))
                    sent["promo_reminder"] = now.isoformat()
                    changed = True

                pro_until = _parse_iso(user.get("pro_until"))
                if pro_until:
                    key = pro_until.isoformat()[:19]
                    renewal_key, expired_key = f"renewal_reminder:{key}", f"expired:{key}"
                    if (
                        now < pro_until <= now + dt.timedelta(days=settings.RENEWAL_REMINDER_DAYS)
                        and renewal_key not in sent
                    ):
                        due.append(("renewal_reminder", dict(user)))
                        sent[renewal_key] = now.isoformat()
                        changed = True
                    elif pro_until <= now < pro_until + dt.timedelta(days=7) and expired_key not in sent:
                        self._refresh_plan_expiry(user)
                        due.append(("expired", dict(user)))
                        sent[expired_key] = now.isoformat()
                        changed = True
            if changed:
                self._save_db(db)
        return due

    # -------------------------------------------------------------------------
    # Secrets & one-time tokens
    # -------------------------------------------------------------------------

    def _app_secret(self) -> bytes:
        """Server secret for HMACs; persisted on the data volume when not set via env."""
        env_secret = os.getenv("APP_SECRET_KEY", "").strip()
        if env_secret:
            return env_secret.encode("utf-8")
        path = settings.OUTPUT_DIR / ".app_secret"
        with self._lock:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(secrets.token_hex(32), encoding="utf-8")
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
            return path.read_text(encoding="utf-8").strip().encode("utf-8")

    def _digest(self, value: str) -> str:
        return hmac.new(self._app_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()

    # -------------------------------------------------------------------------
    # Account sharing guard: at most MAX_IPS_PER_MONTH networks per account
    # -------------------------------------------------------------------------

    def register_account_ip(self, user_id: str, client_ip: str) -> bool:
        """
        Record the (hashed) network an account is used from this month.
        Returns False when it would be a new network beyond the monthly limit.
        """
        if not user_id or not client_ip:
            return True
        month = _now().strftime("%Y-%m")
        ip_hash = self._digest(f"ip:{client_ip}")[:20]
        with self._lock:
            db = self._load_db()
            user = db["users"].get(user_id)
            if not user:
                return True
            months = user.setdefault("ip_months", {})
            for key in [k for k in months if k != month]:
                months.pop(key, None)
            seen = months.setdefault(month, [])
            if ip_hash in seen:
                return True
            if len(seen) >= settings.MAX_IPS_PER_MONTH:
                return False
            seen.append(ip_hash)
            self._save_db(db)
            return True

    def account_ip_usage(self, user_id: str) -> Dict[str, int]:
        month = _now().strftime("%Y-%m")
        with self._lock:
            user = self._load_db()["users"].get(user_id) or {}
            used = len((user.get("ip_months") or {}).get(month, []))
        return {"used": used, "limit": settings.MAX_IPS_PER_MONTH}

    # -------------------------------------------------------------------------
    # Guests (no account): a few ephemeral transcriptions per day, per IP
    # -------------------------------------------------------------------------

    def guest_key(self, client_ip: str) -> str:
        """Pseudonymous id for a visitor; the IP itself is never stored."""
        return "guest_" + self._digest(f"guest:{client_ip or 'unknown'}")[:24]

    def guest_audios_used_today(self, guest_key: str) -> int:
        with self._lock:
            db = self._load_db()
            return int(db.setdefault("guest_usage", {}).get(f"{guest_key}:{_today_str()}", 0))

    def guest_audios_remaining(self, guest_key: str) -> int:
        return max(0, settings.GUEST_MAX_AUDIOS_PER_DAY - self.guest_audios_used_today(guest_key))

    def consume_guest_audios(self, guest_key: str, count: int) -> int:
        """Reserve `count` audios of today's guest allowance. Raises PermissionError when exceeded."""
        with self._lock:
            db = self._load_db()
            usage = db.setdefault("guest_usage", {})
            today = _today_str()
            # Keep only today's counters.
            for key in [k for k in usage if not k.endswith(today)]:
                usage.pop(key, None)
            used = int(usage.get(f"{guest_key}:{today}", 0))
            if used + count > settings.GUEST_MAX_AUDIOS_PER_DAY:
                raise PermissionError(
                    f"Sin cuenta puedes transcribir hasta {settings.GUEST_MAX_AUDIOS_PER_DAY} audios al día. "
                    f"Crea tu cuenta gratis para tener 2 horas diarias, historial y Apex Summa. / "
                    f"Without an account you can transcribe up to {settings.GUEST_MAX_AUDIOS_PER_DAY} audios per day."
                )
            usage[f"{guest_key}:{today}"] = used + count
            self._save_db(db)
            return settings.GUEST_MAX_AUDIOS_PER_DAY - used - count

    # -------------------------------------------------------------------------
    # Password reset
    # -------------------------------------------------------------------------

    def create_password_reset(self, email: str, ttl_minutes: int = 60) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Returns (token, user) for a known e-mail, or None (callers must not reveal which)."""
        clean = (email or "").strip().lower()
        with self._lock:
            db = self._load_db()
            user = next((u for u in db["users"].values() if u.get("email", "").lower() == clean), None)
            if not user:
                return None
            token = secrets.token_urlsafe(32)
            resets = db.setdefault("password_resets", {})
            now = _now()
            for key in [k for k, v in resets.items() if (_parse_iso(v.get("expires_at")) or now) <= now]:
                resets.pop(key, None)
            resets[self._digest(f"reset:{token}")] = {
                "user_id": user["user_id"],
                "expires_at": (now + dt.timedelta(minutes=ttl_minutes)).isoformat(),
            }
            self._save_db(db)
            return token, dict(user)

    def reset_password(self, token: str, new_password: str) -> UserProfileResponse:
        if len(new_password or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres / "
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        with self._lock:
            db = self._load_db()
            entry = db.setdefault("password_resets", {}).pop(self._digest(f"reset:{token or ''}"), None)
            expires = _parse_iso(entry.get("expires_at")) if entry else None
            if not entry or not expires or _now() >= expires:
                self._save_db(db)
                raise PermissionError("El enlace para restablecer la contraseña expiró o ya fue usado.")
            user = db["users"].get(entry["user_id"])
            if not user:
                raise PermissionError("Cuenta no encontrada.")
            user["password_hash"] = _hash_password(new_password)
            # Sign out every existing session.
            db["tokens"] = {
                t: v for t, v in db["tokens"].items()
                if (v if isinstance(v, str) else v.get("user_id")) != user["user_id"]
            }
            token_new = self._issue_token(db, user["user_id"])
            self._save_db(db)
        return self._profile_response(user["user_id"], token_new)

    # -------------------------------------------------------------------------
    # Newsletter (double opt-in)
    # -------------------------------------------------------------------------

    def newsletter_request(self, email: str, lang: str = "es") -> Optional[str]:
        """Store a pending subscription and return the confirmation token (None if already confirmed)."""
        clean = (email or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", clean) or len(clean) > 254:
            raise ValueError("Correo electrónico inválido / Invalid email address.")
        with self._lock:
            db = self._load_db()
            news = db.setdefault("newsletter", {})
            entry = news.get(clean)
            if entry and entry.get("status") == "confirmed":
                return None
            token = secrets.token_urlsafe(24)
            news[clean] = {
                "status": "pending",
                "lang": lang if lang in ("es", "en") else "es",
                "token": self._digest(f"news:{token}"),
                "requested_at": _now().isoformat(),
            }
            self._save_db(db)
            return token

    def newsletter_confirm(self, token: str) -> Optional[Dict[str, Any]]:
        digest = self._digest(f"news:{token or ''}")
        with self._lock:
            db = self._load_db()
            for email, entry in db.setdefault("newsletter", {}).items():
                if entry.get("token") == digest and entry.get("status") == "pending":
                    requested = _parse_iso(entry.get("requested_at"))
                    if requested and _now() - requested > dt.timedelta(days=7):
                        return None
                    entry.update(status="confirmed", token=None, confirmed_at=_now().isoformat())
                    self._save_db(db)
                    return {"email": email, "lang": entry.get("lang", "es")}
        return None

    def newsletter_unsubscribe_token(self, email: str) -> str:
        return self._digest(f"unsub:{email.strip().lower()}")[:32]

    def newsletter_unsubscribe(self, email: str, token: str) -> bool:
        clean = (email or "").strip().lower()
        if not hmac.compare_digest(self.newsletter_unsubscribe_token(clean), token or ""):
            return False
        with self._lock:
            db = self._load_db()
            entry = db.setdefault("newsletter", {}).setdefault(clean, {})
            entry.update(status="unsubscribed", unsubscribed_at=_now().isoformat())
            self._save_db(db)
        return True

    def delete_account(self, user_id: str) -> Dict[str, Any]:
        """Right to erasure: remove the account, its sessions, history, payments link and voice profiles."""
        with self._lock:
            db = self._load_db()
            user = db["users"].pop(user_id, None)
            if not user:
                raise LookupError("Cuenta no encontrada.")
            db["tokens"] = {
                t: v for t, v in db["tokens"].items()
                if (v if isinstance(v, str) else v.get("user_id")) != user_id
            }
            removed_jobs = [jid for jid, rec in db.get("transcriptions", {}).items() if rec.get("user_id") == user_id]
            for jid in removed_jobs:
                db["transcriptions"].pop(jid, None)
            for key in [k for k in db.get("daily_usage", {}) if k.startswith(f"{user_id}:")]:
                db["daily_usage"].pop(key, None)
            for ref, pay in db.get("payments", {}).items():
                if pay.get("user_id") == user_id:
                    pay["user_id"] = "deleted"  # keep accounting record without personal link
            self._save_db(db)
        for jid in removed_jobs:
            for suffix in ("_result.json", "_merged.mp3"):
                (settings.OUTPUT_DIR / f"{jid}{suffix}").unlink(missing_ok=True)
        try:
            from app.services.acoustic_diarizer import _load_all_profiles, save_voice_profiles

            save_voice_profiles([p for p in _load_all_profiles() if p.owner_id != user_id])
        except Exception as exc:
            logger.warning("Voice profile cleanup failed: %s", exc)
        return {"email": user.get("email", ""), "jobs_deleted": len(removed_jobs)}

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
