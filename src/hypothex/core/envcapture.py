"""Capture the software and hardware environment of a run."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

from hypothex.core.fsutil import atomic_write_text

ENV_ALLOWLIST = (
    "CUDA_VISIBLE_DEVICES",
    "CUBLAS_WORKSPACE_CONFIG",
    "HF_HUB_OFFLINE",
    "OMP_NUM_THREADS",
    "PYTHONHASHSEED",
    "SLURM_JOB_ID",
    "SLURM_JOB_NODELIST",
    "TRANSFORMERS_OFFLINE",
)


def _run(cmd: list[str], timeout: float = 30) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout + out.stderr).strip() if out.returncode == 0 else None


def capture_env(repo: Path, env_dir: Path, python_cmd: list[str]) -> None:
    """
    Write ``system.json``, ``env_vars.json``, packages, and GPU info into ``env_dir``.

    Every probe is best effort: a missing tool never fails the run.

    Parameters
    ----------
    repo : Path
        Project repo (``uv.lock`` is copied from here when present).
    env_dir : Path
        Destination folder.
    python_cmd : list of str
        How to invoke the project's Python, e.g. ``["uv", "run", "python"]``.
    """
    env_dir.mkdir(parents=True, exist_ok=True)
    system = {
        "hx_python": platform.python_version(),
        "project_python": _run([*python_cmd, "--version"]),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "hostname": socket.gethostname(),
        "cpu_count": os.cpu_count(),
    }
    atomic_write_text(env_dir / "system.json", json.dumps(system, indent=2))
    env_vars = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    atomic_write_text(env_dir / "env_vars.json", json.dumps(env_vars, indent=2))
    lock = repo / "uv.lock"
    if lock.is_file():
        shutil.copy2(lock, env_dir / "uv.lock")
    else:
        freeze = _run([*python_cmd, "-m", "pip", "freeze"])
        if freeze:
            atomic_write_text(env_dir / "requirements.txt", freeze + "\n")
    gpus = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv"])
    if gpus:
        atomic_write_text(env_dir / "nvidia-smi.csv", gpus + "\n")
