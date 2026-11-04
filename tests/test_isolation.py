"""The test run itself must stay away from real data and real services."""

import tempfile
from pathlib import Path

import httpx
import pytest
import requests

from app.config import settings
from app.services.storage_s4 import mega_s4_storage
from app.services.supabase_service import supabase_service

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("path", [settings.UPLOAD_DIR, settings.OUTPUT_DIR, settings.TEMP_DIR])
def test_data_directories_are_outside_the_repo(path: Path) -> None:
    assert not path.resolve().is_relative_to(REPO_ROOT)
    assert path.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())


def test_service_singletons_use_the_throwaway_directories() -> None:
    assert supabase_service._db_file.parent == settings.OUTPUT_DIR
    assert mega_s4_storage.mirror_dir.is_relative_to(settings.OUTPUT_DIR)


def test_httpx_refuses_external_hosts() -> None:
    with pytest.raises(httpx.ConnectError, match="blocked"):
        httpx.get("https://example.com/")


def test_requests_refuses_external_hosts() -> None:
    with pytest.raises(requests.ConnectionError, match="blocked"):
        requests.get("https://example.com/", timeout=1)


def test_mock_transport_is_allowed() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(204)))
    assert client.get("https://example.com/").status_code == 204
