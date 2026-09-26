"""Host side of the metric worker subprocess."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import EvalError


def default_python_cmd(repo: Path, config: ProjectConfig) -> list[str]:
    """
    Return the command that runs Python in the project's environment.

    Parameters
    ----------
    repo : Path
        Repository root.
    config : ProjectConfig
        The project's parsed ``hypothex.yaml``.

    Returns
    -------
    list of str
        ``env.python`` from ``hypothex.yaml`` if set, else
        ``["uv", "run", "--project", <repo>, "python"]``.
    """
    if config.env.python:
        return list(config.env.python)
    return ["uv", "run", "--project", str(repo), "python"]


def run_worker(
    action: str,
    request: dict[str, Any],
    python_cmd: list[str],
    cwd: Path,
    timeout: float | None = None,
) -> dict[str, Any]:
    """
    Run ``hypothex.eval_worker`` in the project environment and return its result.

    Parameters
    ----------
    action : {"evaluate", "describe"}
        Worker action to run.
    request : dict
        Worker request (see ``hypothex.eval_worker``).
    python_cmd : list of str
        Project Python command.
    cwd : Path
        Working directory (the repo).
    timeout : float, optional
        Seconds before giving up.

    Returns
    -------
    dict
        The worker's result (see ``hypothex.eval_worker.evaluate``/``describe``).

    Raises
    ------
    EvalError
        If the worker cannot start, produces no result, or reports a fatal error.
    """
    with tempfile.TemporaryDirectory(prefix="hx-eval-") as tmp:
        req = Path(tmp) / "request.json"
        out = Path(tmp) / "result.json"
        req.write_text(json.dumps(request, default=str), encoding="utf-8")
        cmd = [
            *python_cmd,
            "-m",
            "hypothex.eval_worker",
            action,
            "--request",
            str(req),
            "--out",
            str(out),
        ]
        try:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EvalError(
                f"could not start the metric worker with {python_cmd!r}: {exc}"
            ) from exc
        if not out.is_file():
            raise EvalError(
                f"metric worker exited {proc.returncode} without a result; is hypothex installed "
                f"in the project environment? stderr: {proc.stderr[-2000:]}"
            )
        result = json.loads(out.read_text(encoding="utf-8"))
    if "fatal" in result:
        raise EvalError(result["fatal"])
    return result
