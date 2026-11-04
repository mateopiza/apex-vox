"""The lockfile and the image must stay in step with what the project declares."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _name(requirement: str) -> str:
    return re.split(r"[\[<>=~! ]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")


def test_every_declared_dependency_is_pinned_in_the_lockfile() -> None:
    declared = [
        _name(line) for line in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    pinned = {
        _name(line) for line in (REPO / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.startswith(("#", " "))
    }
    assert declared and set(declared) <= pinned


def test_the_image_installs_the_lockfile() -> None:
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir -r requirements.lock" in dockerfile
    assert "COPY requirements.txt requirements.lock requirements-dev.txt" in dockerfile


def test_ci_uses_the_lockfile_and_the_shared_lint_config() -> None:
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "-c requirements.lock" in workflow
    assert "ruff check app tests scripts\n" in workflow
    assert "--cov=app" in workflow
    assert "--fail-under" not in workflow  # coverage is reported, not a gate
    assert "State.Health.Status" in workflow
