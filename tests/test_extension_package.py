"""One codebase, two packages: the served ZIP and the Chrome Web Store build."""

import io
import json
import subprocess
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.extension_package import build_zip_bytes, store_manifest, write_store_package

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / "extension"


def _names(data: bytes) -> set:
    return set(zipfile.ZipFile(io.BytesIO(data)).namelist())


def _manifest(data: bytes) -> dict:
    return json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))


def _assert_only_runtime_files(names: set) -> None:
    assert not [n for n in names if n.startswith(("doc/", "scripts/", "versionenvio/", "dist/"))]
    assert not [n for n in names if n.endswith((".md", ".zip", ".sh", ".map"))]
    assert {"manifest.json", "service-worker.js", "recorder/recorder.js", "content/session-bridge.js"} <= names


def test_served_zip_has_only_what_the_extension_runs() -> None:
    res = TestClient(app).get("/api/box/extension.zip")
    assert res.status_code == 200
    names = _names(res.content)
    _assert_only_runtime_files(names)
    assert "_locales/es/messages.json" in names  # the manifest declares a default locale
    assert any("localhost" in h for h in _manifest(res.content)["host_permissions"])


def test_store_package_has_no_development_permissions() -> None:
    data = build_zip_bytes(EXT, for_store=True)
    names = _names(data)
    _assert_only_runtime_files(names)
    assert {"_locales/es/messages.json", "_locales/en/messages.json"} <= names
    manifest = _manifest(data)
    assert manifest["host_permissions"] == ["https://apex-vox.ialabs.app/*"]
    assert manifest["content_scripts"][0]["matches"] == ["https://apex-vox.ialabs.app/*"]
    assert "localhost" not in json.dumps(manifest)


def test_store_manifest_leaves_the_original_alone() -> None:
    original = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    store_manifest(original)
    assert any("localhost" in h for h in original["host_permissions"])


def test_script_builds_the_package_with_the_manifest_version(tmp_path: Path) -> None:
    target = write_store_package(EXT, tmp_path)
    version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
    assert target.name == f"apex-box-v{version}-chrome-webstore.zip"
    assert version == "3.3.1"
    script = (EXT / "scripts" / "package-extension.sh").read_text(encoding="utf-8")
    assert "versionenvio" not in script
    assert subprocess.run(["bash", "-n", str(EXT / "scripts" / "package-extension.sh")], check=False).returncode == 0


def test_old_copy_of_the_extension_is_gone() -> None:
    assert not (EXT / "versionenvio").exists()
    assert not (EXT / "CHROMEWEBSTORE.md").exists() and not (EXT / "doc" / "CHROMEWEBSTORE.md").exists()
    assert (REPO / "CHROMEWEBSTORE.md").exists()


def test_extension_locks_itself_without_localhost_permission() -> None:
    recorder = (EXT / "recorder" / "recorder.js").read_text(encoding="utf-8")
    worker = (EXT / "service-worker.js").read_text(encoding="utf-8")
    html = (EXT / "recorder" / "recorder.html").read_text(encoding="utf-8")
    assert "LOCKED_TO_CLOUD" in recorder and "getManifest().host_permissions" in recorder
    assert "lockedToCloud" in worker and "getManifest().host_permissions" in worker
    assert 'id="server-locked"' in html and 'id="server-settings"' in html


def test_store_description_names_no_third_party_trademarks() -> None:
    for lang in ("es", "en"):
        messages = json.loads((EXT / "_locales" / lang / "messages.json").read_text(encoding="utf-8"))
        text = messages["extDescription"]["message"]
        assert len(text) <= 132
        assert not any(mark in text for mark in ("Zoom", "Meet", "Teams", "Webex", "Google"))
