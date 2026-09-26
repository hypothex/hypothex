"""Shared builders for tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from hypothex.core.ids import utcnow
from hypothex.core.records import RunRecord, RunStatus


def make_record(run_id: str = "r1", project: str = "toy", **overrides: Any) -> RunRecord:
    """Build a valid RunRecord with sensible defaults."""
    base: dict[str, Any] = {
        "run_id": run_id,
        "project": project,
        "task": "t",
        "command": ["echo", "hi"],
        "command_template": ["echo", "hi"],
        "cwd": "/tmp",
        "environment_id": "env1",
        "host": "mac",
        "config_hash": "sha256:abc",
        "status": RunStatus.QUEUED,
        "created_at": utcnow(),
    }
    base.update(overrides)
    return RunRecord.model_validate(base)


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` with a fixed identity; return stdout."""
    out = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def init_git_repo(repo: Path) -> str:
    """Init a repo, commit everything in it, and return the commit sha."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    return git(repo, "rev-parse", "HEAD")
