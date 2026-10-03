"""
Test doubles for remote hosts, GPUs, and SLURM.

The isolation helpers back the autouse fixture ``isolate_remote`` in
``tests/conftest.py``: no test reaches a real host, a real hub, a real
``nvidia-smi``, or real SLURM commands. The fake ``ssh``/``scp`` run locally:
use the ``fake_remote`` fixture, which points ``HYPOTHEX_SSH``/``HYPOTHEX_SCP``
at wrappers around ``fake_ssh.py`` and ``fake_scp.py``.

Examples
--------
>>> def test_uname(fake_remote):  # doctest: +SKIP
...     fake_remote.add_host("gpu1")
...     res = run_remote(fake_remote.target("gpu1"), "echo $HOME")
...     assert res.stdout.decode().strip() == str(fake_remote.home("gpu1"))
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from hypothex.remote.ssh import SshTarget

FAKES_DIR = Path(__file__).resolve().parent
DEAD_HUB = "http://127.0.0.1:9"
"""A port nothing listens on: tests never reach a real hub."""
REFUSED_TOOLS = (
    "nvidia-smi", "sbatch", "squeue", "sacct", "scancel", "sinfo", "scontrol", "srun", "salloc",
)  # fmt: skip
"""Host tools every test sees as a refusing stub unless it installs a fake first."""
REFUSED_EXIT = 99
_REFUSE = "#!/bin/sh\necho 'fake ssh: tests never reach real hosts' >&2\nexit 255\n"


@dataclass(frozen=True)
class FakeRemote:
    """
    Handle on the fake remote world of one test.

    Attributes
    ----------
    root : Path
        ``HYPOTHEX_FAKE_REMOTE_ROOT``; one sub-directory per host alias.
    log_path : Path
        ``HYPOTHEX_FAKE_SSH_LOG``; one JSON line per fake ``ssh``/``scp`` call.
    ssh_bin : str
        Executable wrapper that runs ``fake_ssh.py``.
    scp_bin : str
        Executable wrapper that runs ``fake_scp.py``.
    """

    root: Path
    log_path: Path
    ssh_bin: str
    scp_bin: str

    def add_host(self, alias: str) -> Path:
        """Create the fake host ``alias`` and return its home directory."""
        home = self.home(alias)
        home.mkdir(parents=True, exist_ok=True)
        return home

    def home(self, alias: str) -> Path:
        """Return the home directory of ``alias`` (``$HOME`` on that host)."""
        return self.root / alias

    def set_down(self, alias: str, down: bool) -> None:
        """Make ``alias`` refuse connections (and drop its tunnels) or come back."""
        marker = self.home(alias) / ".fake_down"
        if down:
            marker.touch()
        else:
            marker.unlink(missing_ok=True)

    def calls(self, prog: str | None = None) -> list[list[str]]:
        """Return the argv of every logged call, optionally only ``"ssh"`` or ``"scp"``."""
        if not self.log_path.exists():
            return []
        rows = [json.loads(line) for line in self.log_path.read_text().splitlines() if line]
        return [row["argv"] for row in rows if prog is None or row["prog"] == prog]

    def target(self, alias: str, connect_timeout: int = 10) -> SshTarget:
        """Return an :class:`SshTarget` for ``alias`` that uses the fake binaries."""
        from hypothex.remote.ssh import SshTarget

        return SshTarget(
            alias=alias,
            ssh_bin=self.ssh_bin,
            scp_bin=self.scp_bin,
            connect_timeout=connect_timeout,
        )


def _wrapper(path: Path, script: Path) -> str:
    command = f"exec {shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    path.write_text(f'#!/bin/sh\n{command} "$@"\n')
    path.chmod(0o755)
    return str(path)


def install_fake_remote(base: Path, monkeypatch: pytest.MonkeyPatch) -> FakeRemote:
    """
    Create wrappers under ``base`` and point the environment at them.

    Parameters
    ----------
    base : Path
        Empty directory for ``bin/``, ``hosts/`` and ``calls.jsonl``.
    monkeypatch : pytest.MonkeyPatch
        Used to set ``HYPOTHEX_SSH``, ``HYPOTHEX_SCP``,
        ``HYPOTHEX_FAKE_REMOTE_ROOT`` and ``HYPOTHEX_FAKE_SSH_LOG``.

    Returns
    -------
    FakeRemote
        Handle for adding hosts and reading the call log.
    """
    bin_dir = base / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    root = base / "hosts"
    root.mkdir(exist_ok=True)
    fake = FakeRemote(
        root=root,
        log_path=base / "calls.jsonl",
        ssh_bin=_wrapper(bin_dir / "ssh", FAKES_DIR / "fake_ssh.py"),
        scp_bin=_wrapper(bin_dir / "scp", FAKES_DIR / "fake_scp.py"),
    )
    monkeypatch.setenv("HYPOTHEX_SSH", fake.ssh_bin)
    monkeypatch.setenv("HYPOTHEX_SCP", fake.scp_bin)
    monkeypatch.setenv("HYPOTHEX_FAKE_REMOTE_ROOT", str(root))
    monkeypatch.setenv("HYPOTHEX_FAKE_SSH_LOG", str(fake.log_path))
    return fake


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
