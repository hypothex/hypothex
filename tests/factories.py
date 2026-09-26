"""Shared builders for tests."""

from __future__ import annotations

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
