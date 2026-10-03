"""
Test doubles for remote hosts, GPUs, and SLURM.

The isolation helpers below back the autouse fixture ``isolate_remote`` in
``tests/conftest.py``: no test reaches a real host, a real hub, a real
``nvidia-smi``, or real SLURM commands. Task 5 adds the fake ``ssh``/``scp``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

DEAD_HUB = "http://127.0.0.1:9"
"""A port nothing listens on: tests never reach a real hub."""
REFUSED_TOOLS = (
    "nvidia-smi", "sbatch", "squeue", "sacct", "scancel", "sinfo", "scontrol", "srun", "salloc",
)  # fmt: skip
"""Host tools every test sees as a refusing stub unless it installs a fake first."""
REFUSED_EXIT = 99
_REFUSE = "#!/bin/sh\necho 'fake ssh: tests never reach real hosts' >&2\nexit 255\n"


def refuse_remote(base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Point ``HYPOTHEX_SSH``/``HYPOTHEX_SCP`` at a script that always fails (exit 255).

    Parameters
    ----------
    base : Path
        Directory for the script (created if missing).
    monkeypatch : pytest.MonkeyPatch
        Used to set the two variables.
    """
    base.mkdir(parents=True, exist_ok=True)
    script = base / "refuse"
    if not script.exists():
        script.write_text(_REFUSE)
        script.chmod(0o755)
    monkeypatch.setenv("HYPOTHEX_SSH", str(script))
    monkeypatch.setenv("HYPOTHEX_SCP", str(script))


def refuse_host_tools(base: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Put refusing stubs of :data:`REFUSED_TOOLS` at the front of ``PATH``.

    Parameters
    ----------
    base : Path
        Directory for the stubs (``<base>/refused-tools``, created if missing).
    monkeypatch : pytest.MonkeyPatch
        Used to prepend the folder to ``PATH``.

    Returns
    -------
    Path
        The stub folder.
    """
    folder = base / "refused-tools"
    folder.mkdir(parents=True, exist_ok=True)
    for tool in REFUSED_TOOLS:
        stub = folder / tool
        if not stub.exists():
            stub.write_text(
                f"#!/bin/sh\necho 'hypothex tests: real {tool} is blocked' >&2\n"
                f"exit {REFUSED_EXIT}\n"
            )
            stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ.get('PATH', '')}")
    return folder
