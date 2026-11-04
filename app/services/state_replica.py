"""
Postgres replica of the account state (app/services/state_replica.py)
---------------------------------------------------------------------
With STATE_BACKEND=postgres, every save of the state file is also sent to Supabase Postgres, in a
background thread, as one row per record. Reads stay local, and the local file written atomically
is the moment a change counts.

What this gives: an off-machine copy, restored automatically if the volume is lost.
What it does not give: losing the volume loses up to the flush lag, including any payment or quota
written in that time. It does not allow a second replica of the app, and does not make writes
cheaper. See docs/deployment.md for the cutover and rollback steps.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger("app.services.state_replica")

META_SECTION = "_meta"
_PLAIN_VALUE_KEY = "__value__"  # top-level values that are not a section of records
_PAGE_SIZE = 1000
_MAX_BACKOFF_SECONDS = 60.0

Row = Tuple[str, str]


class ReplicaConflictError(RuntimeError):
    """Another writer moved the replica's generation: two copies of the app are running."""


class ReplicaUnavailableError(RuntimeError):
    """Postgres could not be reached or refused the request. Worth trying again."""


def to_rows(state: Dict[str, Any]) -> Dict[Row, Any]:
    """One row per record, so that a save only sends what changed."""
    rows: Dict[Row, Any] = {}
    for section, content in state.items():
        if section == META_SECTION:
            continue
        if isinstance(content, dict):
            for key, value in content.items():
                rows[(section, str(key))] = value
        else:
            rows[(section, _PLAIN_VALUE_KEY)] = content
    return rows


def from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    for row in rows:
        if row["key"] == _PLAIN_VALUE_KEY:
            state[row["section"]] = row["value"]
        else:
            state.setdefault(row["section"], {})[row["key"]] = row["value"]
    return state


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class PostgresStateClient:
    """The Supabase REST calls the replica needs. Uses the service role: nothing else can reach these tables."""

    def __init__(self) -> None:
        key = settings.SUPABASE_SERVICE_ROLE_KEY
        self.base = settings.SUPABASE_URL.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            with httpx.Client(timeout=30.0) as client:
                return client.request(method, f"{self.base}{path}", headers=self.headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ReplicaUnavailableError(type(exc).__name__) from exc

    def read_meta(self) -> Tuple[int, bool]:
        resp = self._send("GET", "/app_state_meta?id=eq.1&select=generation,importing")
        if resp.status_code != 200 or not resp.json():
            raise ReplicaUnavailableError(f"app_state_meta answered HTTP {resp.status_code}")
        row = resp.json()[0]
        return int(row["generation"]), bool(row["importing"])

    def set_importing(self, importing: bool) -> None:
        resp = self._send("PATCH", "/app_state_meta?id=eq.1", json={"importing": importing})
        if resp.status_code not in (200, 204):
            raise ReplicaUnavailableError(f"app_state_meta answered HTTP {resp.status_code}")

    def read_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        while True:
            resp = self._send(
                "GET",
                f"/app_state?select=section,key,value&order=section,key&limit={_PAGE_SIZE}&offset={len(rows)}",
            )
            if resp.status_code != 200:
                raise ReplicaUnavailableError(f"app_state answered HTTP {resp.status_code}")
            page = resp.json()
            rows.extend(page)
            if len(page) < _PAGE_SIZE:
                return rows

    def apply(self, expected: int, new: int, upserts: List[Dict[str, Any]], deletes: List[Dict[str, str]]) -> None:
        """One transaction. Refused if the generation is not the one this writer last saw."""
        resp = self._send(
            "POST",
            "/rpc/app_state_apply",
            json={"expected_generation": expected, "new_generation": new, "upserts": upserts, "deletes": deletes},
        )
        if resp.status_code in (200, 204):
            return
        if "generation conflict" in resp.text:
            raise ReplicaConflictError(f"expected generation {expected}")
        raise ReplicaUnavailableError(f"app_state_apply answered HTTP {resp.status_code}")


class StateReplica:
    """Sends the newest saved state to Postgres, skipping intermediate saves. Never blocks a save."""

    def __init__(self, client: Optional[PostgresStateClient] = None) -> None:
        self.client = client or PostgresStateClient()
        self.generation = 0
        self.conflict = False
        self._fingerprints: Dict[Row, str] = {}
        self._pending: Optional[Tuple[bytes, int]] = None
        self._changed = threading.Condition()
        self._flushed = threading.Condition()
        self._sending = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- start-up --------------------------------------------------------------

    def load_remote(self) -> Tuple[Dict[str, Any], int, bool]:
        """Read what Postgres holds, and remember it so that later saves only send differences."""
        generation, importing = self.client.read_meta()
        rows = self.client.read_rows()
        self.generation = generation
        self._fingerprints = {(r["section"], r["key"]): _fingerprint(r["value"]) for r in rows}
        return from_rows(rows), generation, importing

    def start(self) -> None:
        if not self._thread:
            self._thread = threading.Thread(target=self._run, name="state-replica", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._changed:
            self._changed.notify_all()

    # -- saving ----------------------------------------------------------------

    def enqueue(self, data: bytes, generation: int) -> None:
        """Called right after the local file is replaced. Only ever keeps the newest state."""
        with self._changed:
            self._pending = (data, generation)
            self._changed.notify_all()

    def flush(self, timeout: float = 5.0) -> bool:
        """Best effort, for changes that matter (a payment, a deleted account). Call outside any lock."""
        deadline = threading.Event()
        timer = threading.Timer(timeout, deadline.set)
        timer.daemon = True
        timer.start()
        try:
            with self._flushed:
                while (self._pending is not None or self._sending) and not self.conflict and not deadline.is_set():
                    self._flushed.wait(0.05)
                return self._pending is None and not self._sending and not self.conflict
        finally:
            timer.cancel()

    def send(self, data: bytes, generation: int) -> None:
        """Send the differences between this state and the last one Postgres confirmed."""
        rows = to_rows(json.loads(data))
        prints = {row: _fingerprint(value) for row, value in rows.items()}
        upserts = [
            {"section": row[0], "key": row[1], "value": rows[row]}
            for row, fingerprint in prints.items() if self._fingerprints.get(row) != fingerprint
        ]
        deletes = [{"section": row[0], "key": row[1]} for row in self._fingerprints if row not in prints]
        self.client.apply(self.generation, generation, upserts, deletes)
        self.generation = generation
        self._fingerprints = prints

    def _run(self) -> None:
        backoff = settings.STATE_PG_FLUSH_SECONDS
        while not self._stop.is_set():
            with self._changed:
                while self._pending is None and not self._stop.is_set():
                    self._changed.wait(1.0)
                job = self._pending
            if self._stop.wait(backoff) or job is None:
                continue
            with self._changed:
                job = self._pending or job  # lo más reciente que haya llegado durante la espera
                self._sending = True
                self._pending = None
            try:
                self.send(*job)
                backoff = settings.STATE_PG_FLUSH_SECONDS
            except ReplicaConflictError:
                logger.critical(
                    "Another writer changed the Postgres state: is a second copy of the app running? "
                    "Replication stopped; this copy is reported as unhealthy."
                )
                self.conflict = True
                return
            except (ReplicaUnavailableError, ValueError) as exc:
                logger.warning("Could not replicate the state, will retry: %s", exc)
                with self._changed:
                    self._pending = self._pending or job
                backoff = min(max(backoff, 1.0) * 2, _MAX_BACKOFF_SECONDS)
            finally:
                self._sending = False
                with self._flushed:
                    self._flushed.notify_all()
