import json
import subprocess
import sys
from pathlib import Path

import pytest

from hypothex.core import envcapture
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


def test_capture_env_pip_freeze_ignores_stderr_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A warning on stderr from ``pip freeze`` must not leak into requirements.txt."""

    def fake_run(
        cmd: list[str], capture_output: bool, text: bool, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        if cmd[-3:] == ["-m", "pip", "freeze"]:
            return subprocess.CompletedProcess(
                cmd,
                returncode=0,
                stdout="numpy==1.26.4\n",
                stderr="DeprecationWarning: pkg_resources is deprecated\n",
            )
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(envcapture.subprocess, "run", fake_run)
    repo = tmp_path / "repo"
    repo.mkdir()
    env_dir = tmp_path / "env"
    capture_env(repo, env_dir, [sys.executable])
    requirements = (env_dir / "requirements.txt").read_text()
    assert requirements == "numpy==1.26.4\n"
    assert "DeprecationWarning" not in requirements


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected"),
    [
        ("Python 3.12.4\n", "Creating virtual environment at: .venv\n", "Python 3.12.4"),
        ("", "Python 2.7.18\n", "Python 2.7.18"),
    ],
)
def test_capture_env_project_python_ignores_wrapper_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str, expected: str
) -> None:
    # DF-19: uv's "Creating virtual environment" text on stderr went into project_python
    def fake_run(
        cmd: list[str], capture_output: bool, text: bool, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "--version":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout, stderr=stderr)
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

    monkeypatch.setattr(envcapture.subprocess, "run", fake_run)
    capture_env(tmp_path, tmp_path / "env", ["uv", "run", "python"])
    system = json.loads((tmp_path / "env" / "system.json").read_text())
    assert system["project_python"] == expected
