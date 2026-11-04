"""
Durable JSON files (app/services/state_store.py)
------------------------------------------------
Accounts, payments, the storage index and voice profiles live in JSON files on the data volume.
A crash or a full disk during a plain write leaves a truncated file, and reading a damaged file
as "empty" lets the next save erase everything. So writes replace the file atomically and damaged
files raise instead of looking empty.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


class StateCorruptError(RuntimeError):
    """A state file is missing or unreadable. Nothing may be saved over it."""


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace `path` with `data`: readers and crashes see the old file or the new one, never a mix."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = 0o600
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    # The rename itself must also survive a crash (not supported on every filesystem).
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass  # the file itself is already safe; some filesystems cannot sync a directory
    finally:
        os.close(dir_fd)


def atomic_write_json(path: Path, value: Any, indent: int | None = None) -> None:
    atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, indent=indent).encode("utf-8"))


def read_json(path: Path) -> Any:
    """Parse a JSON file, or raise StateCorruptError (the file is left as it is)."""
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise StateCorruptError(f"{Path(path).name}: {type(exc).__name__}") from exc
