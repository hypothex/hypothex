import json
import sys
from pathlib import Path

import pytest

from hypothex.core.envcapture import capture_env


def test_capture_env_writes_system_and_allowlisted_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_text("lock")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("SECRET_TOKEN", "do-not-store")
    env_dir = tmp_path / "env"
    capture_env(repo, env_dir, [sys.executable])
    system = json.loads((env_dir / "system.json").read_text())
    assert system["project_python"].startswith("Python 3")
    env_vars = json.loads((env_dir / "env_vars.json").read_text())
    assert env_vars == {"CUDA_VISIBLE_DEVICES": "0,1"}
    assert (env_dir / "uv.lock").read_text() == "lock"
    assert "do-not-store" not in "".join(p.read_text() for p in env_dir.iterdir())


def test_capture_env_survives_missing_python(tmp_path: Path) -> None:
    capture_env(tmp_path, tmp_path / "env", ["/nonexistent/python"])
    system = json.loads((tmp_path / "env" / "system.json").read_text())
    assert system["project_python"] is None
