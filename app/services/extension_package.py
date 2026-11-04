"""
Chrome extension packaging (app/services/extension_package.py)
---------------------------------------------------------------
One list of what belongs in a package, used by the ZIP the app serves and by the Chrome Web Store
build. Standard library only, so that `extension/scripts/package-extension.sh` can run it directly.

The store build drops the localhost permissions, which store review rejects. Without them the
extension locks itself to the official server, so there is one codebase and no separate copy.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List

EXCLUDED_DIRS = {"doc", "scripts", "versionenvio", "dist", "node_modules", "__pycache__", ".git"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db"}
EXCLUDED_SUFFIXES = {".md", ".zip", ".sh", ".map", ".pyc"}
_LOCAL_HOSTS = ("localhost", "127.0.0.1")


def package_files(ext_dir: Path) -> Iterator[Path]:
    """Paths inside `ext_dir` that go in a package, in a stable order."""
    for path in sorted(ext_dir.rglob("*")):
        relative = path.relative_to(ext_dir)
        if path.is_dir() or EXCLUDED_DIRS.intersection(relative.parts):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix in EXCLUDED_SUFFIXES:
            continue
        yield relative


def _without_local_hosts(patterns: List[str]) -> List[str]:
    return [p for p in patterns if not any(host in p for host in _LOCAL_HOSTS)]


def store_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """The manifest for the Chrome Web Store: no development permissions."""
    built = json.loads(json.dumps(manifest))
    built["host_permissions"] = _without_local_hosts(built.get("host_permissions", []))
    for script in built.get("content_scripts", []):
        script["matches"] = _without_local_hosts(script.get("matches", []))
    return built


def build_zip_bytes(ext_dir: Path, for_store: bool = False) -> bytes:
    """A ZIP of the extension. `for_store` is the version to upload to the Chrome Web Store."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in package_files(ext_dir):
            if for_store and relative == Path("manifest.json"):
                manifest = json.loads((ext_dir / relative).read_text(encoding="utf-8"))
                archive.writestr(str(relative), json.dumps(store_manifest(manifest), ensure_ascii=False, indent=2))
            else:
                archive.write(ext_dir / relative, arcname=str(relative))
    return buf.getvalue()


def write_store_package(ext_dir: Path, out_dir: Path) -> Path:
    version = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))["version"]
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"apex-box-v{version}-chrome-webstore.zip"
    target.write_bytes(build_zip_bytes(ext_dir, for_store=True))
    return target


if __name__ == "__main__":
    print(write_store_package(Path(sys.argv[1]), Path(sys.argv[2])))
