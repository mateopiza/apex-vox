"""`.env` loading: only the project's own file, never a parent directory's, and never in tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import load_dotenv_files


def test_test_suite_never_loads_dotenv() -> None:
    assert os.environ.get("APEX_VOX_SKIP_DOTENV") == "1"


def test_parent_directory_dotenv_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A checkout nested inside another one (git worktree) must not inherit the outer .env.
    (tmp_path / ".env").write_text("APEX_E2E_PARENT_SECRET=prod-key\n")
    project = tmp_path / "nested" / "checkout"
    project.mkdir(parents=True)
    monkeypatch.chdir(project)
    monkeypatch.delenv("APEX_VOX_SKIP_DOTENV")
    monkeypatch.delenv("APEX_E2E_PARENT_SECRET", raising=False)

    assert load_dotenv_files(project) is None
    assert "APEX_E2E_PARENT_SECRET" not in os.environ


def test_project_dotenv_is_loaded_without_overriding_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("APEX_E2E_FROM_FILE=file\nAPEX_E2E_ALREADY_SET=file\n")
    monkeypatch.delenv("APEX_VOX_SKIP_DOTENV")
    monkeypatch.delenv("APEX_E2E_FROM_FILE", raising=False)
    monkeypatch.setenv("APEX_E2E_ALREADY_SET", "shell")

    assert load_dotenv_files(tmp_path) == tmp_path / ".env"
    assert os.environ["APEX_E2E_FROM_FILE"] == "file"
    assert os.environ["APEX_E2E_ALREADY_SET"] == "shell"
    monkeypatch.delenv("APEX_E2E_FROM_FILE")


def test_skip_flag_disables_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("APEX_E2E_SKIPPED=file\n")
    monkeypatch.delenv("APEX_E2E_SKIPPED", raising=False)

    assert load_dotenv_files(tmp_path) is None
    assert "APEX_E2E_SKIPPED" not in os.environ
