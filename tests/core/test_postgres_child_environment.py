"""The Docker helper must scrub libpq defaults after its final environment merge."""

import os
import subprocess
from typing import Any

import pytest

from tests.docker.conftest import run_cmd


def test_run_cmd_scrubs_parent_and_override_pg_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = {
        "PGHOST": "remote.invalid",
        "PGHOSTADDR": "192.0.2.2",
        "PGSERVICE": "ambient",
        "PGSERVICEFILE": "/synthetic/services",
        "PGPASSWORD": "synthetic-parent",
        "PGPASSFILE": "/synthetic/passwords",
        "POSTGRES_PASSWORD": "fixture-secret",
    }
    for key, value in parent.items():
        monkeypatch.setenv(key, value)
    overrides = {"PGHOST": "other.invalid", "PGPASSWORD": "synthetic-child", "FIXTURE": "yes"}
    captured: list[dict[str, str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append(dict(kwargs["env"]))
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert run_cmd(["synthetic"], env=overrides).stdout == "ok"
    assert len(captured) == 1 and not any(key.upper().startswith("PG") for key in captured[0])
    assert captured[0]["POSTGRES_PASSWORD"] == "fixture-secret"
    assert captured[0]["FIXTURE"] == "yes"
    assert overrides == {
        "PGHOST": "other.invalid",
        "PGPASSWORD": "synthetic-child",
        "FIXTURE": "yes",
    }
    assert all(os.environ[key] == value for key, value in parent.items())
