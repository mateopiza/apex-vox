"""The Postgres replica, against a fake Supabase: no real database is involved in these tests."""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from app.config import settings
from app.services import state_replica
from app.services.state_replica import (
    META_SECTION,
    PostgresStateClient,
    ReplicaConflictError,
    ReplicaUnavailableError,
    StateReplica,
    from_rows,
    to_rows,
)
from app.services.supabase_service import SupabaseCloudService


class FakeSupabase:
    """The parts of PostgREST the replica uses, including the generation check of the RPC."""

    def __init__(self) -> None:
        self.rows: Dict[tuple, Any] = {}
        self.generation = 0
        self.importing = False
        self.applied: List[dict] = []
        self.fail_next = 0
        self.gate = threading.Event()
        self.gate.set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.gate.wait(5)
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(503, text="unavailable")
        path = request.url.path
        if path.endswith("/app_state_meta"):
            if request.method == "PATCH":
                self.importing = json.loads(request.content)["importing"]
                return httpx.Response(204)
            return httpx.Response(200, json=[{"generation": self.generation, "importing": self.importing}])
        if path.endswith("/app_state"):
            offset = int(request.url.params.get("offset", 0))
            limit = int(request.url.params.get("limit", 1000))
            items = [{"section": s, "key": k, "value": v} for (s, k), v in sorted(self.rows.items())]
            return httpx.Response(200, json=items[offset:offset + limit])
        if path.endswith("/rpc/app_state_apply"):
            body = json.loads(request.content)
            if body["expected_generation"] != self.generation:
                return httpx.Response(400, json={"message": "app_state generation conflict: expected 1, found 2"})
            for item in body["upserts"]:
                self.rows[(item["section"], item["key"])] = item["value"]
            for item in body["deletes"]:
                self.rows.pop((item["section"], item["key"]), None)
            self.generation = body["new_generation"]
            self.applied.append(body)
            return httpx.Response(200, json=self.generation)
        return httpx.Response(404)


@pytest.fixture
def supabase(monkeypatch: pytest.MonkeyPatch) -> FakeSupabase:
    fake = FakeSupabase()
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(settings, "STATE_PG_FLUSH_SECONDS", 0.01)
    real = httpx.Client
    monkeypatch.setattr(state_replica.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(fake), **kw))
    return fake


@pytest.fixture
def service_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, supabase: FakeSupabase):
    """A service in postgres mode on its own folder, like the app on a server."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(settings, "STATE_BACKEND", "postgres")
    started: List[SupabaseCloudService] = []

    def make() -> SupabaseCloudService:
        service = SupabaseCloudService()
        started.append(service)
        return service

    yield make
    for service in started:
        if service._replica:
            service._replica.stop()


def _state(**users: Any) -> Dict[str, Any]:
    return {"users": users, "tokens": {}, "daily_usage": {}, "subscriptions": {}, "transcriptions": {}}


def _replica(supabase: FakeSupabase) -> StateReplica:
    replica = StateReplica(PostgresStateClient())
    replica.load_remote()
    return replica


def _encoded(state: Dict[str, Any]) -> bytes:
    return json.dumps(state).encode("utf-8")


# Rows ----------------------------------------------------------------------


def test_rows_round_trip_without_the_generation() -> None:
    state = {"users": {"a": {"x": 1}}, "tokens": {}, "version": 3, META_SECTION: {"generation": 9}}
    rows = to_rows(state)
    assert rows == {("users", "a"): {"x": 1}, ("version", "__value__"): 3}
    back = from_rows([{"section": s, "key": k, "value": v} for (s, k), v in rows.items()])
    assert back == {"users": {"a": {"x": 1}}, "version": 3}


# Sending differences -------------------------------------------------------


def test_only_changes_are_sent(supabase: FakeSupabase) -> None:
    replica = _replica(supabase)
    replica.send(_encoded(_state(a={"n": 1}, b={"n": 1})), 1)
    replica.send(_encoded(_state(a={"n": 2}, b={"n": 1})), 2)
    last = supabase.applied[-1]
    assert [u["key"] for u in last["upserts"]] == ["a"]
    assert last["deletes"] == []
    replica.send(_encoded(_state(a={"n": 2})), 3)
    assert supabase.applied[-1]["deletes"] == [{"section": "users", "key": "b"}]
    assert supabase.applied[-1]["upserts"] == []
    assert supabase.rows == {("users", "a"): {"n": 2}}


def test_large_state_reads_every_page(supabase: FakeSupabase, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_replica, "_PAGE_SIZE", 2)
    supabase.rows = {("users", str(i)): {"n": i} for i in range(5)}
    assert len(PostgresStateClient().read_rows()) == 5


def test_second_writer_is_detected(supabase: FakeSupabase) -> None:
    replica = _replica(supabase)
    supabase.generation = 7  # someone else wrote
    with pytest.raises(ReplicaConflictError):
        replica.send(_encoded(_state(a={})), 1)


def test_unavailable_postgres_is_retryable(supabase: FakeSupabase) -> None:
    replica = _replica(supabase)
    supabase.fail_next = 1
    with pytest.raises(ReplicaUnavailableError):
        replica.send(_encoded(_state(a={})), 1)
    replica.send(_encoded(_state(a={})), 1)
    assert ("users", "a") in supabase.rows


# Background thread ---------------------------------------------------------


def _wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_saves_are_coalesced_and_the_newest_wins(supabase: FakeSupabase) -> None:
    replica = _replica(supabase)
    supabase.gate.clear()
    for generation in range(1, 6):
        replica.enqueue(_encoded(_state(a={"n": generation})), generation)
    replica.start()
    time.sleep(0.05)
    replica.enqueue(_encoded(_state(a={"n": 99})), 99)
    supabase.gate.set()
    assert _wait_for(lambda: supabase.generation == 99)
    assert supabase.rows[("users", "a")] == {"n": 99}
    assert len(supabase.applied) < 6
    replica.stop()


def test_failed_send_is_retried(supabase: FakeSupabase) -> None:
    replica = _replica(supabase)
    supabase.fail_next = 2
    replica.start()
    replica.enqueue(_encoded(_state(a={"n": 1})), 1)
    assert _wait_for(lambda: supabase.generation == 1, timeout=20)
    replica.stop()


def test_conflict_stops_replicating(supabase: FakeSupabase) -> None:
    replica = _replica(supabase)
    supabase.generation = 50
    replica.start()
    replica.enqueue(_encoded(_state(a={})), 1)
    assert _wait_for(lambda: replica.conflict)
    assert replica.flush(0.5) is False
    replica.stop()


def test_flush_waits_for_the_send_and_gives_up_at_the_timeout(supabase: FakeSupabase) -> None:
    replica = _replica(supabase)
    replica.start()
    replica.enqueue(_encoded(_state(a={})), 1)
    assert replica.flush(5) is True
    assert supabase.generation == 1

    supabase.gate.clear()
    replica.enqueue(_encoded(_state(b={})), 2)
    assert replica.flush(0.1) is False
    supabase.gate.set()
    replica.stop()


# The service in postgres mode ----------------------------------------------


def test_json_mode_uses_no_replica(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    assert settings.STATE_BACKEND == "json"
    service = SupabaseCloudService()
    service.register_user("a@example.com", "password123")
    assert service._replica is None
    assert META_SECTION not in service._load_db()


def test_refuses_to_start_with_no_state_anywhere(service_factory) -> None:
    with pytest.raises(RuntimeError, match="deployment.md"):
        service_factory()


def test_refuses_to_start_during_an_import(service_factory, supabase: FakeSupabase, tmp_path: Path) -> None:
    (tmp_path / "supabase_cloud_state.json").write_text(json.dumps(_state()), encoding="utf-8")
    supabase.importing = True
    with pytest.raises(RuntimeError, match="imported"):
        service_factory()


def test_refuses_to_start_without_the_service_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(settings, "STATE_BACKEND", "postgres")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY"):
        SupabaseCloudService()


def test_lost_volume_is_restored_from_postgres(service_factory, supabase: FakeSupabase, tmp_path: Path) -> None:
    supabase.rows = {("users", "u1"): {"user_id": "u1", "email": "a@example.com"}}
    supabase.generation = 12
    service = service_factory()
    assert service._load_db()["users"]["u1"]["email"] == "a@example.com"
    assert service._local_generation(service._load_db()) == 12


def test_local_changes_that_never_left_are_pushed_at_start(service_factory, supabase: FakeSupabase, tmp_path: Path) -> None:
    supabase.rows = {("users", "old"): {"n": 1}}
    supabase.generation = 3
    state = _state(new={"n": 2})
    state[META_SECTION] = {"generation": 5}
    (tmp_path / "supabase_cloud_state.json").write_text(json.dumps(state), encoding="utf-8")
    service = service_factory()
    assert supabase.generation == 5
    assert ("users", "new") in supabase.rows and ("users", "old") not in supabase.rows
    assert "new" in service._load_db()["users"]


def test_saves_reach_postgres_without_blocking_the_lock(service_factory, supabase: FakeSupabase, tmp_path: Path) -> None:
    (tmp_path / "supabase_cloud_state.json").write_text(json.dumps(_state()), encoding="utf-8")
    service = service_factory()
    supabase.gate.clear()  # Postgres stops answering
    db = service._load_db()
    db["users"]["u1"] = {"user_id": "u1", "email": "slow@example.com"}
    begin = time.monotonic()
    service._save_db(db)
    assert time.monotonic() - begin < 1
    assert service._read_snapshot()["users"]["u1"]["email"] == "slow@example.com"  # the file counts
    assert ("users", "u1") not in supabase.rows
    supabase.gate.set()
    assert _wait_for(lambda: ("users", "u1") in supabase.rows)
    assert supabase.generation == service._local_generation(service._load_db())


def test_generation_survives_a_restart(service_factory, supabase: FakeSupabase, tmp_path: Path) -> None:
    (tmp_path / "supabase_cloud_state.json").write_text(json.dumps(_state()), encoding="utf-8")
    first = service_factory()
    first.register_user("one@example.com", "password123")
    assert _wait_for(lambda: supabase.generation == first._local_generation(first._load_db()) and supabase.generation > 0)
    first._replica.stop()
    second = service_factory()
    second.register_user("two@example.com", "password123")
    assert _wait_for(lambda: any(v.get("email") == "two@example.com" for k, v in supabase.rows.items() if k[0] == "users"))
    assert second.replica_healthy()


def test_health_reports_a_conflict(service_factory, supabase: FakeSupabase, tmp_path: Path) -> None:
    (tmp_path / "supabase_cloud_state.json").write_text(json.dumps(_state()), encoding="utf-8")
    service = service_factory()
    assert service.replica_healthy() is True
    supabase.generation = 500
    service.register_user("x@example.com", "password123")
    assert _wait_for(lambda: not service.replica_healthy())


# The importer --------------------------------------------------------------


@pytest.fixture
def importer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, supabase: FakeSupabase):
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "import_state_to_postgres.py"
    spec = importlib.util.spec_from_file_location("import_state_to_postgres", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    (tmp_path / "supabase_cloud_state.json").write_text(json.dumps(_state(u1={"email": "secret@example.com"})), encoding="utf-8")
    return module


def test_import_dry_run_changes_nothing_and_prints_counts_only(importer, supabase: FakeSupabase, capsys) -> None:
    assert importer.run(dry_run=True, force=False) == 0
    out = capsys.readouterr().out
    assert "users: 1" in out and "secret@example.com" not in out
    assert supabase.rows == {} and supabase.generation == 0


def test_import_copies_the_state_and_the_app_can_start(importer, supabase: FakeSupabase, tmp_path: Path, service_factory) -> None:
    assert importer.run(dry_run=False, force=False) == 0
    assert supabase.rows[("users", "u1")] == {"email": "secret@example.com"}
    assert supabase.importing is False
    local = json.loads((tmp_path / "supabase_cloud_state.json").read_text(encoding="utf-8"))
    assert local[META_SECTION]["generation"] == supabase.generation
    service = service_factory()
    assert service.replica_healthy() and supabase.generation == local[META_SECTION]["generation"]


def test_import_refuses_to_overwrite_without_force(importer, supabase: FakeSupabase) -> None:
    supabase.rows = {("users", "other"): {}}
    assert importer.run(dry_run=False, force=False) == 3
    assert ("users", "other") in supabase.rows
    assert importer.run(dry_run=False, force=True) == 0
    assert ("users", "other") not in supabase.rows


# The SQL -------------------------------------------------------------------


def test_migration_keeps_the_tables_private() -> None:
    sql = (Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "20261104120000_app_state.sql").read_text(encoding="utf-8")
    assert "force row level security" in sql
    assert "revoke all on table public.app_state, public.app_state_meta from anon, authenticated" in sql
    assert "from public, anon, authenticated" in sql
    assert "generation conflict" in sql
    assert "create policy" not in sql
