"""Uploads stream, retry and report honestly. Runs against a fake bucket: no real MEGA S4 here."""

import hashlib
import uuid
from pathlib import Path
from typing import Dict, List

import httpx
import pytest

from app.config import settings
from app.services import storage_s4
from app.services.storage_s4 import mega_s4_storage as storage


class FakeBucket:
    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.objects: Dict[str, bytes] = {}
        self.requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else 200
        if isinstance(status, Exception):
            raise status
        if request.method == "PUT" and status == 200:
            self.objects[request.url.path] = request.read()
        return httpx.Response(status)


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "MEGA_S4_ACCESS_KEY_ID", "key")
    monkeypatch.setattr(settings, "MEGA_S4_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setattr(type(storage), "is_cloud_configured", property(lambda self: True))
    monkeypatch.setattr(storage_s4.time, "sleep", lambda _: None)
    real = httpx.Client

    def install(*statuses) -> FakeBucket:
        bucket = FakeBucket(*statuses)
        monkeypatch.setattr(storage_s4.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(bucket), **kw))
        return bucket

    return install


def _key() -> str:
    return f"users/{uuid.uuid4().hex}/jobs/j/merged.mp3"


def _file(tmp_path: Path, size: int = 3 * 1024 * 1024) -> Path:
    path = tmp_path / "merged.mp3"
    path.write_bytes(b"a" * size)
    return path


def test_file_upload_is_signed_with_its_hash_and_has_a_length(cloud, tmp_path: Path) -> None:
    bucket = cloud()
    path = _file(tmp_path)
    key = _key()
    meta = storage.upload_file(key, path, content_type="audio/mpeg", plan="pro")

    request = bucket.requests[0]
    assert meta["cloud_synced"] is True
    assert request.headers["x-amz-content-sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert request.headers["content-length"] == str(path.stat().st_size)
    assert "transfer-encoding" not in request.headers
    assert list(bucket.objects.values()) == [path.read_bytes()]


def test_uploading_a_file_does_not_read_it_whole(cloud, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cloud()
    path = _file(tmp_path)

    real_read_bytes = Path.read_bytes

    def guarded(self):
        assert self != path, "the whole file was read into memory"
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert storage.upload_file(_key(), path, plan="pro")["cloud_synced"] is True


def test_temporary_failures_are_retried(cloud, tmp_path: Path) -> None:
    bucket = cloud(503, httpx.ConnectError("down"), 200)
    assert storage.upload_file(_key(), _file(tmp_path), plan="pro")["cloud_synced"] is True
    assert len(bucket.requests) == 3


def test_a_rejected_upload_is_not_retried(cloud, tmp_path: Path) -> None:
    bucket = cloud(403)
    assert storage.upload_file(_key(), _file(tmp_path), plan="pro")["cloud_synced"] is False
    assert len(bucket.requests) == 1


def test_synced_object_is_not_kept_twice_on_disk(cloud, tmp_path: Path) -> None:
    cloud()
    key = _key()
    storage.upload_file(key, _file(tmp_path), plan="pro")
    assert not (storage.mirror_dir / key).exists()


def test_failed_upload_stays_in_the_mirror_and_can_be_retried(cloud, tmp_path: Path) -> None:
    cloud(500, 500, 500)
    path = _file(tmp_path)
    key = _key()
    meta = storage.upload_file(key, path, content_type="audio/mpeg", plan="free", user_id="u", job_id="j")
    assert meta["cloud_synced"] is False
    assert (storage.mirror_dir / key).read_bytes() == path.read_bytes()
    assert storage.unsynced_count() >= 1

    bucket = cloud()
    assert storage.retry_unsynced_uploads() == 0
    assert storage.get_object_metadata(key)["cloud_synced"] is True
    assert storage.get_object_metadata(key)["expires_at"] == meta["expires_at"]
    assert not (storage.mirror_dir / key).exists()
    assert bucket.objects


def test_without_a_bucket_everything_stays_local(tmp_path: Path) -> None:
    key = _key()
    meta = storage.upload_file(key, _file(tmp_path), plan="pro")
    assert meta["cloud_synced"] is False
    assert (storage.mirror_dir / key).exists()
    assert storage.unsynced_count() == 0
    assert storage.retry_unsynced_uploads() == 0


def test_replacing_an_object_can_keep_its_expiry() -> None:
    key = _key()
    original = storage.upload_object(key, b"1", plan="free")["expires_at"]
    assert original
    kept = storage.upload_object(key, b"2", plan="free", expires_at="2020-01-01T00:00:00+00:00")
    assert kept["expires_at"] == "2020-01-01T00:00:00+00:00"
    assert storage.upload_object(_key(), b"3", plan="pro")["expires_at"] is None


def test_delete_removes_it_everywhere(cloud) -> None:
    bucket = cloud(500, 500, 500)
    key = _key()
    storage.upload_object(key, b"data", plan="free")
    assert (storage.mirror_dir / key).exists()

    bucket = cloud(204)
    assert storage.delete_object(key) is True
    assert bucket.requests[0].method == "DELETE"
    assert "authorization" in bucket.requests[0].headers
    assert not (storage.mirror_dir / key).exists()
    assert storage.get_object_metadata(key) is None


@pytest.mark.parametrize("status", [200, 204, 404])
def test_delete_counts_as_done_when_the_object_is_gone(cloud, status: int) -> None:
    cloud(status)
    assert storage.delete_object(_key()) is True


@pytest.mark.parametrize("failure", [500, 403, httpx.ConnectError("down")])
def test_failed_delete_keeps_the_record_for_a_later_try(cloud, failure) -> None:
    key = _key()
    storage.upload_object(key, b"data", plan="free")
    cloud(failure)
    assert storage.delete_object(key) is False
    assert storage.get_object_metadata(key) is not None


def test_health_reports_unsynced_objects_to_admins(cloud) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    cloud(500, 500, 500)
    storage.upload_object(_key(), b"data", plan="pro")
    body = TestClient(app).get("/api/health").json()
    assert body["storage"]["unsynced_objects"] >= 1
