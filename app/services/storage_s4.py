"""
MEGA S4 Object Storage Service (app/services/storage_s4.py)
-----------------------------------------------------------
Provides S3-compatible cloud object storage backed by MEGA S4
(https://s3.g.s4.mega.io / s3.<region>.s4.mega.io).

Features:
- Pure Python AWS Signature V4 (HMAC-SHA256) + httpx client for zero-dependency
  compatibility with MEGA S4 S3 endpoints (plus optional boto3 support).
- Plan-aware retention policies:
  * Free Plan: 24-hour storage retention (expires_at = created_at + 24 hours).
  * Paid Plan (Apex Pro / Trial): Unlimited storage retention (expires_at = None).
- Automatic local mirror fallback when MEGA S4 credentials are not configured,
  ensuring seamless execution in local development and automated test suites.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlparse

import httpx

from app.config import settings
from app.services.state_store import StateCorruptError, atomic_write_json, read_json

logger = logging.getLogger("app.services.storage_s4")

_PUT_ATTEMPTS = 3
_FROM_PLAN: Any = object()  # compute the expiry from the plan, unlike None (it never expires)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signing_key(secret_key: str, date_stamp: str, region: str, service: str = "s3") -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, "aws4_request")
    return k_signing


class MegaS4StorageService:
    """
    S3-compatible storage engine targeting MEGA S4 (s4.mega.io) with
    24-hour Free tier TTL enforcement and Unlimited Pro tier retention.
    """

    def __init__(self) -> None:
        self.mirror_dir = settings.OUTPUT_DIR / "mega_s4_bucket"
        self.mirror_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.mirror_dir / "_s4_objects_index.json"
        self._index_lock = threading.RLock()

    @property
    def endpoint_url(self) -> str:
        url = (settings.MEGA_S4_ENDPOINT_URL or "https://s3.g.s4.mega.io").strip().rstrip("/")
        # Admite endpoints sin esquema (p. ej. "s3.eu-amsterdam-1.megas4.com").
        return url if re.match(r"^https?://", url, re.I) else f"https://{url}"

    @property
    def region(self) -> str:
        # La firma SigV4 solo es válida si la región coincide con el endpoint regional;
        # se deduce del host (s3.<region>.megas4.com / s3.<region>.s4.mega.io).
        host = urlparse(self.endpoint_url).netloc.lower()
        m = re.match(r"^s3\.([a-z0-9-]+)\.(?:megas4\.com|s4\.mega\.io)$", host)
        if m and m.group(1) != "g":
            return m.group(1)
        return settings.MEGA_S4_REGION or "eu-central-1"

    @property
    def bucket(self) -> str:
        return settings.MEGA_S4_BUCKET_NAME or "apex-vox-storage"

    @property
    def is_cloud_configured(self) -> bool:
        return settings.is_mega_s4_configured

    def compute_expiration_iso(self, plan: str) -> Optional[str]:
        """
        Return ISO-8601 expiration timestamp based on user plan:
        - 'free': +24 hours from now (settings.FREE_RETENTION_HOURS)
        - 'trial' / 'pro': None (unlimited storage)
        """
        norm_plan = (plan or "free").strip().lower()
        if norm_plan in ("pro", "trial", "unlimited", "paid"):
            return None
        now = dt.datetime.now(dt.timezone.utc)
        expires = now + dt.timedelta(hours=settings.FREE_RETENTION_HOURS)
        return expires.isoformat()

    def build_s3v4_headers(
        self,
        method: str,
        object_key: str,
        payload: bytes = b"",
        content_type: str = "application/octet-stream",
        extra_amz_headers: Optional[Dict[str, str]] = None,
        payload_hash: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Construct AWS Signature Version 4 headers for MEGA S4 REST API calls.
        """
        now = dt.datetime.now(dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        parsed = urlparse(self.endpoint_url)
        host = parsed.netloc or "s3.g.s4.mega.io"
        canonical_uri = "/" + self.bucket.strip("/") + "/" + quote(object_key.lstrip("/"), safe="/-_.~")
        payload_hash = payload_hash or _sha256_hex(payload)

        headers_to_sign: Dict[str, str] = {
            "content-type": content_type,
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if extra_amz_headers:
            for k, v in extra_amz_headers.items():
                headers_to_sign[k.lower().strip()] = str(v).strip()

        sorted_keys = sorted(headers_to_sign.keys())
        canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in sorted_keys)
        signed_headers = ";".join(sorted_keys)

        canonical_request = "\n".join(
            [
                method.upper(),
                canonical_uri,
                "",  # query string
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )

        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                algorithm,
                amz_date,
                credential_scope,
                _sha256_hex(canonical_request.encode("utf-8")),
            ]
        )

        signing_key = _get_signing_key(
            settings.MEGA_S4_SECRET_ACCESS_KEY or "local_s4_secret",
            date_stamp,
            self.region,
            "s3",
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        access_key = settings.MEGA_S4_ACCESS_KEY_ID or "local_s4_key"
        authorization_header = (
            f"{algorithm} "
            f"Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        out_headers = {
            "Host": host,
            "Content-Type": content_type,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": authorization_header,
        }
        if extra_amz_headers:
            out_headers.update(extra_amz_headers)
        return out_headers

    def _read_index(self) -> Dict[str, Any]:
        """The index, or StateCorruptError when it is damaged (a missing index is just empty)."""
        if not self.index_path.exists():
            return {}
        index = read_json(self.index_path)
        if not isinstance(index, dict):
            raise StateCorruptError(self.index_path.name)
        return index

    def _load_index(self) -> Dict[str, Any]:
        """Read path: a damaged index lists nothing, but is logged and left for an operator."""
        with self._index_lock:
            try:
                return self._read_index()
            except StateCorruptError as exc:
                logger.error("MEGA S4 local index is unreadable, leaving it untouched: %s", exc)
                return {}

    def _update_index(self, mutate: Callable[[Dict[str, Any]], None]) -> bool:
        """Read-modify-write under the lock. A damaged index is never overwritten."""
        with self._index_lock:
            try:
                index = self._read_index()
                mutate(index)
                atomic_write_json(self.index_path, index)
                return True
            except (StateCorruptError, OSError) as exc:
                logger.error("MEGA S4 local index was not updated: %s", exc)
                return False

    def _object_url(self, object_key: str) -> str:
        return f"{self.endpoint_url}/{self.bucket}/{quote(object_key.lstrip('/'), safe='/-_.~')}"

    def presigned_get_url(
        self,
        object_key: str,
        expires_sec: int = 600,
        download_name: Optional[str] = None,
    ) -> str:
        """URL GET firmada (SigV4 por query string) que caduca en `expires_sec` segundos."""
        now = dt.datetime.now(dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        host = urlparse(self.endpoint_url).netloc
        canonical_uri = "/" + self.bucket.strip("/") + "/" + quote(object_key.lstrip("/"), safe="/-_.~")
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"

        params: Dict[str, str] = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{settings.MEGA_S4_ACCESS_KEY_ID}/{credential_scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(max(1, min(int(expires_sec), 604800))),
            "X-Amz-SignedHeaders": "host",
        }
        if download_name:
            params["response-content-disposition"] = f'attachment; filename="{download_name}"'
        canonical_query = "&".join(
            f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items())
        )
        canonical_request = "\n".join(
            ["GET", canonical_uri, canonical_query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"]
        )
        string_to_sign = "\n".join(
            ["AWS4-HMAC-SHA256", amz_date, credential_scope, _sha256_hex(canonical_request.encode("utf-8"))]
        )
        signing_key = _get_signing_key(settings.MEGA_S4_SECRET_ACCESS_KEY, date_stamp, self.region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{self.endpoint_url}{canonical_uri}?{canonical_query}&X-Amz-Signature={signature}"

    def get_bytes(self, object_key: str) -> bytes:
        """GET firmado (lado servidor) de un objeto privado."""
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(self.presigned_get_url(object_key, 120))
        if resp.status_code != 200:
            raise RuntimeError(f"Almacenamiento respondió HTTP {resp.status_code} para {object_key}")
        return resp.content

    def object_exists(self, object_key: str) -> bool:
        """HEAD firmado contra MEGA S4."""
        headers = self.build_s3v4_headers(method="HEAD", object_key=object_key, content_type="")
        with httpx.Client(timeout=15.0) as client:
            resp = client.head(self._object_url(object_key), headers=headers)
        return resp.status_code == 200

    def put_bytes(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> bool:
        """PUT directo a MEGA S4 (sin espejo local ni índice de retención)."""
        headers = self.build_s3v4_headers(
            method="PUT", object_key=object_key, payload=data, content_type=content_type
        )
        with httpx.Client(timeout=60.0) as client:
            resp = client.put(self._object_url(object_key), content=data, headers=headers)
        if resp.status_code not in (200, 201, 204):
            logger.warning("MEGA S4 PUT %s -> HTTP %s", object_key, resp.status_code)
            return False
        return True

    def _put_with_retries(
        self,
        clean_key: str,
        open_body: Callable[[], Any],
        size: int,
        payload_hash: str,
        content_type: str,
        amz_meta: Dict[str, str],
    ) -> bool:
        """PUT to MEGA S4. Returns whether the object is stored; failures are logged, never raised."""
        s4_url = f"{self.endpoint_url}/{self.bucket}/{clean_key}"
        for attempt in range(1, _PUT_ATTEMPTS + 1):
            try:
                # Signed per attempt: the signature carries the current time.
                headers = self.build_s3v4_headers(
                    method="PUT",
                    object_key=clean_key,
                    content_type=content_type,
                    extra_amz_headers=amz_meta,
                    payload_hash=payload_hash,
                )
                headers["Content-Length"] = str(size)  # S3 rejects chunked uploads
                with open_body() as body, httpx.Client(timeout=30.0) as client:
                    resp = client.put(s4_url, content=body, headers=headers)
                if resp.status_code in (200, 201, 204):
                    return True
                logger.warning("MEGA S4 PUT returned HTTP %s for %s", resp.status_code, clean_key)
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    return False
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("MEGA S4 upload failed (%s): %s", clean_key, type(exc).__name__)
            if attempt < _PUT_ATTEMPTS:
                time.sleep(2.0 ** (attempt - 1))
        return False

    def _store(
        self,
        object_key: str,
        open_body: Callable[[], Any],
        size: int,
        payload_hash: str,
        keep_in_mirror: Callable[[Path], None],
        content_type: str,
        plan: str,
        user_id: Optional[str],
        job_id: Optional[str],
        expires_at: Any,
    ) -> Dict[str, Any]:
        clean_key = object_key.lstrip("/")
        if expires_at is _FROM_PLAN:
            expires_at = self.compute_expiration_iso(plan)
        retention_tag = "unlimited" if expires_at is None else f"{settings.FREE_RETENTION_HOURS}h"

        cloud_synced = False
        if self.is_cloud_configured:
            amz_meta = {"x-amz-meta-plan": plan, "x-amz-meta-retention": retention_tag}
            if expires_at:
                amz_meta["x-amz-meta-expires-at"] = expires_at
            cloud_synced = self._put_with_retries(clean_key, open_body, size, payload_hash, content_type, amz_meta)

        # The local copy is the fallback: only what did not reach the bucket stays here.
        local_dest = self.mirror_dir / clean_key
        if cloud_synced:
            local_dest.unlink(missing_ok=True)
        else:
            local_dest.parent.mkdir(parents=True, exist_ok=True)
            keep_in_mirror(local_dest)

        meta_record = {
            "object_key": clean_key,
            "bucket": self.bucket,
            "endpoint": self.endpoint_url,
            "s4_url": f"{self.endpoint_url}/{self.bucket}/{clean_key}",
            "size_bytes": size,
            "content_type": content_type,
            "plan": plan,
            "user_id": user_id,
            "job_id": job_id,
            "retention": retention_tag,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "expires_at": expires_at,
            "cloud_synced": cloud_synced,
        }
        self._update_index(lambda idx: idx.__setitem__(clean_key, meta_record))
        return meta_record

    def upload_object(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        plan: str = "free",
        user_id: Optional[str] = None,
        job_id: Optional[str] = None,
        expires_at: Any = _FROM_PLAN,
    ) -> Dict[str, Any]:
        """
        Store a small object in MEGA S4 with plan-based retention metadata (or the local mirror).
        Pass `expires_at` when replacing an object, so a new copy does not extend its retention.
        """
        return self._store(
            object_key, lambda: io.BytesIO(data), len(data), _sha256_hex(data), lambda dest: dest.write_bytes(data),
            content_type, plan, user_id, job_id, expires_at,
        )

    def upload_file(
        self,
        object_key: str,
        path: Path,
        content_type: str = "application/octet-stream",
        plan: str = "free",
        user_id: Optional[str] = None,
        job_id: Optional[str] = None,
        expires_at: Any = _FROM_PLAN,
    ) -> Dict[str, Any]:
        """Like `upload_object` for files of any size: nothing is read fully into memory."""
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return self._store(
            object_key, lambda: open(path, "rb"), path.stat().st_size, digest.hexdigest(),
            lambda dest: shutil.copyfile(path, dest), content_type, plan, user_id, job_id, expires_at,
        )

    def delete_object(self, object_key: str) -> bool:
        """Delete an object everywhere. False if the bucket could not confirm it: try again later."""
        clean_key = object_key.lstrip("/")
        if self.is_cloud_configured:
            try:
                headers = self.build_s3v4_headers(method="DELETE", object_key=clean_key, content_type="")
                with httpx.Client(timeout=30.0) as client:
                    resp = client.delete(self._object_url(clean_key), headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("MEGA S4 delete failed (%s): %s", clean_key, type(exc).__name__)
                return False
            if resp.status_code not in (200, 204, 404):  # 404: ya no existe, que es lo que se quería
                logger.warning("MEGA S4 DELETE returned HTTP %s for %s", resp.status_code, clean_key)
                return False
        (self.mirror_dir / clean_key).unlink(missing_ok=True)
        self._update_index(lambda idx: idx.pop(clean_key, None))
        return True

    def retry_unsynced_uploads(self) -> int:
        """Upload again what only reached the local mirror. Returns how many are still pending."""
        if not self.is_cloud_configured:
            return 0
        pending = 0
        for key, meta in self._load_index().items():
            local = self.mirror_dir / key
            if meta.get("cloud_synced") or not local.exists():
                continue
            stored = self.upload_file(
                key, local, meta.get("content_type") or "application/octet-stream", meta.get("plan") or "free",
                meta.get("user_id"), meta.get("job_id"), expires_at=meta.get("expires_at"),
            )
            if not stored["cloud_synced"]:
                pending += 1
        return pending

    def unsynced_count(self) -> int:
        if not self.is_cloud_configured:
            return 0
        return sum(1 for meta in self._load_index().values() if not meta.get("cloud_synced"))

    def get_object_metadata(self, object_key: str) -> Optional[Dict[str, Any]]:
        clean_key = object_key.lstrip("/")
        idx = self._load_index()
        return idx.get(clean_key)

    def list_user_objects(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List stored objects in MEGA S4, automatically filtering out expired 24h free objects."""
        self.cleanup_expired_objects()
        idx = self._load_index()
        items = list(idx.values())
        if user_id:
            items = [i for i in items if i.get("user_id") == user_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items

    def cleanup_expired_objects(self) -> int:
        """
        Enforce the 24-hour storage retention limit for Free plan objects.
        Paid ('pro' / 'trial') objects have expires_at = None and are never deleted.
        """
        now = dt.datetime.now(dt.timezone.utc)
        removed: List[str] = []

        def prune(idx: Dict[str, Any]) -> None:
            for key, meta in list(idx.items()):
                expires_at_str = meta.get("expires_at")
                if not expires_at_str:
                    continue
                try:
                    exp_dt = dt.datetime.fromisoformat(expires_at_str)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=dt.timezone.utc)
                    if now >= exp_dt:
                        (self.mirror_dir / key).unlink(missing_ok=True)
                        del idx[key]
                        removed.append(key)
                except (TypeError, ValueError, OSError):
                    logger.debug("Retention index: unreadable expiry for %s, kept", key)  # ante la duda, no se borra

        self._update_index(prune)
        return len(removed)


mega_s4_storage = MegaS4StorageService()
