"""
Docker integration harness: a throwaway sshd box and a small SLURM cluster.

Nothing here touches the user's real hosts or SSH setup. Keys, ``ssh_config``, and
``known_hosts`` live in pytest temp dirs; the ``ssh``/``scp`` wrappers always pass
``-F <temp config>``, so ``~/.ssh/config``, ``~/.ssh/known_hosts``, and the user's
ssh agent are never read. Tests marked ``docker`` are skipped when Docker is not
running (set ``HYPOTHEX_REQUIRE_DOCKER=1`` to turn the skip into an error, as CI does).
They are deselected by default (``addopts = -m 'not docker'``). Run them with::

    HYPOTHEX_REQUIRE_DOCKER=1 uv run pytest -m docker -v
"""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import pytest

from hypothex.remote.ssh import SshTarget

T = TypeVar("T")

DOCKER_DIR = Path(__file__).resolve().parent
SSHD_IMAGE = "hypothex-test-sshd:1"
SLURM_COMPOSE = DOCKER_DIR / "slurm" / "docker-compose.yml"
REMOTE_HOME = "~/.hypothex"
REMOTE_PROJECT = "/home/hx/dock"
REMOTE_STORE = "/home/hx/.hypothex/store"
BOOTSTRAP_TIMEOUT = 600.0  # first install downloads hypothex's dependencies from PyPI
DESCRIPTOR_PY = (
    "import sys, urllib.request; "
    "url = 'http://127.0.0.1:' + sys.argv[1] + '/.well-known/hypothex/environment'; "
    "print(urllib.request.urlopen(url, timeout=10).read().decode())"
)
SSH_CONFIG = """\
Host {alias}
  HostName 127.0.0.1
  Port {port}
  User hx
  IdentityFile "{key}"
  IdentitiesOnly yes
  IdentityAgent none
  StrictHostKeyChecking no
  UserKnownHostsFile "{known_hosts}"
  GlobalKnownHostsFile /dev/null
  ControlMaster no
  ControlPath none
  LogLevel ERROR
"""


# skipping -------------------------------------------------------------------------
def _succeeds(cmd: list[str]) -> bool:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def docker_skip_reason() -> str | None:
    """
    Say why Docker integration tests cannot run here.

    Returns
    -------
    str or None
        A short reason, or None when Docker, Compose v2, and OpenSSH are usable.
    """
    if shutil.which("docker") is None:
        return "docker CLI not found"
    if not _succeeds(["docker", "info", "--format", "{{.ServerVersion}}"]):
        return "Docker daemon is not running"
    if not _succeeds(["docker", "compose", "version"]):
        return "docker compose v2 is not installed"
    if shutil.which("ssh") is None or shutil.which("ssh-keygen") is None:
        return "OpenSSH client (ssh, ssh-keygen) not found"
    return None


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``docker`` tests (after ``-m`` deselection) when Docker is unusable."""
    marked = [item for item in items if item.get_closest_marker("docker") is not None]
    if not marked:
        return
    reason = docker_skip_reason()
    if reason is None:
        return
    if os.environ.get("HYPOTHEX_REQUIRE_DOCKER") == "1":
        raise pytest.UsageError(f"HYPOTHEX_REQUIRE_DOCKER=1 but {reason}")
    for item in marked:
        item.add_marker(pytest.mark.skip(reason=reason))


# small helpers --------------------------------------------------------------------
def run_cmd(
    cmd: list[str],
    *,
    timeout: float = 600,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run a command and capture text output.

    Parameters
    ----------
    cmd : list of str
        Command and arguments.
    timeout : float
        Seconds before ``subprocess.TimeoutExpired``.
    check : bool
        Raise ``AssertionError`` with both streams when the exit code is not 0.
    env : dict, optional
        Extra environment variables on top of ``os.environ``.

    Returns
    -------
    subprocess.CompletedProcess
        The finished process.
    """
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **(env or {})},
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"{shlex.join(cmd)} exited {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def wait_until(
    fn: Callable[[], T | None], *, timeout: float, what: str, interval: float = 0.5
) -> T:
    """
    Poll ``fn`` until it returns a truthy value.

    Exceptions raised by ``fn`` count as "not yet" and are shown on timeout.

    Parameters
    ----------
    fn : callable
        Returns the awaited value, or a falsy value / raises while not ready.
    timeout : float
        Seconds to wait.
    what : str
        Description used in the timeout message.
    interval : float
        Seconds between polls.

    Returns
    -------
    object
        The first truthy value ``fn`` returned.

    Raises
    ------
    AssertionError
        On timeout, naming ``what`` and the last value or exception.
    """
    deadline = time.monotonic() + timeout
    last: object = None
    while True:
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 - "not ready yet"
            value, last = None, exc
        else:
            last = value
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout:.0f}s waiting for {what}: {last!r}")
        time.sleep(interval)


def free_port() -> int:
    """
    Return a TCP port on 127.0.0.1 that was free a moment ago.

    Returns
    -------
    int
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# isolated ssh access ----------------------------------------------------------------
@dataclass(frozen=True)
class SshAccess:
    """A throwaway key, ssh config alias, and ``ssh``/``scp`` wrappers in a temp dir."""

    alias: str
    config: Path
    ssh: Path
    scp: Path
    public_key: str

    def target(self) -> SshTarget:
        """
        Return the transport target that uses the wrappers.

        Returns
        -------
        SshTarget
        """
        return SshTarget(alias=self.alias, ssh_bin=str(self.ssh), scp_bin=str(self.scp))

    def env(self) -> dict[str, str]:
        """
        Return the variables that make Hypothex use the wrappers.

        Returns
        -------
        dict of str to str
            ``HYPOTHEX_SSH`` and ``HYPOTHEX_SCP``.
        """
        return {"HYPOTHEX_SSH": str(self.ssh), "HYPOTHEX_SCP": str(self.scp)}


def _wrapper(path: Path, binary: str, config: Path) -> Path:
    real = shutil.which(binary)
    if real is None:
        raise AssertionError(f"{binary} not found on PATH")
    path.write_text(
        f'#!/bin/sh\nexec {shlex.quote(real)} -F {shlex.quote(str(config))} "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def make_ssh_access(directory: Path, alias: str, port: int) -> SshAccess:
    """
    Create a key pair, an ssh config with one alias, and wrappers, all in ``directory``.

    Parameters
    ----------
    directory : Path
        Temp directory to hold everything (created if missing).
    alias : str
        ``Host`` alias pointing at ``127.0.0.1:port`` as user ``hx``.
    port : int
        Host port published by the container's sshd.

    Returns
    -------
    SshAccess
    """
    directory.mkdir(parents=True, exist_ok=True)
    key = directory / "id_ed25519"
    if not key.exists():
        run_cmd(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "hypothex-docker-test"]
            + ["-f", str(key)]
        )
    config = directory / "ssh_config"
    config.write_text(
        SSH_CONFIG.format(alias=alias, port=port, key=key, known_hosts=directory / "known_hosts"),
        encoding="utf-8",
    )
    config.chmod(0o600)
    return SshAccess(
        alias=alias,
        config=config,
        ssh=_wrapper(directory / "ssh", "ssh", config),
        scp=_wrapper(directory / "scp", "scp", config),
        public_key=(directory / "id_ed25519.pub").read_text(encoding="utf-8").strip(),
    )


def wait_for_ssh(access: SshAccess, timeout: float = 120) -> None:
    """
    Wait until ``ssh <alias> true`` succeeds through the wrapper.

    Parameters
    ----------
    access : SshAccess
    timeout : float
        Seconds to wait.
    """

    def ok() -> bool:
        cmd = [str(access.ssh), "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", access.alias]
        return run_cmd([*cmd, "true"], timeout=20, check=False).returncode == 0

    wait_until(ok, timeout=timeout, what=f"sshd behind {access.alias}")


# per-test ssh environment -----------------------------------------------------------
ACCESS_FIXTURES = ("sshd_box", "slurm_cluster")
"""Module fixtures (Tasks 54, 56) whose ``.access`` holds the isolated wrappers."""


@pytest.fixture(autouse=True)
def docker_ssh_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Put back the isolated ``ssh``/``scp`` wrappers after the root ``isolate_remote``.

    The root autouse fixture (``tests/conftest.py``) runs first and points
    ``HYPOTHEX_SSH``/``HYPOTHEX_SCP`` at a script that always fails, for every test.
    A test that uses ``sshd_box`` or ``slurm_cluster`` (directly or through
    ``slurm_hub``) gets that box's wrappers back here, so a module-scoped hub that
    reconnects during the test builds its ``SshTarget`` from the wrappers. Any
    other test keeps the refusing script.
    """
    for name in ACCESS_FIXTURES:
        if name in request.fixturenames:
            box = request.getfixturevalue(name)
            for key, value in box.access.env().items():
                monkeypatch.setenv(key, value)
            return


# sshd box -------------------------------------------------------------------------------
@dataclass
class SshBox:
    """One running sshd container (user ``hx``, toy project at ``/home/hx/dock``)."""

    container: str
    access: SshAccess

    def exec(self, *argv: str, user: str = "hx", timeout: float = 120) -> str:
        """
        Run a command inside the container (not over ssh); return stdout.

        Parameters
        ----------
        *argv : str
        user : str
        timeout : float

        Returns
        -------
        str
        """
        cmd = ["docker", "exec", "-u", user, self.container, *argv]
        return run_cmd(cmd, timeout=timeout).stdout

    def sh(self, script: str, *, user: str = "hx") -> str:
        """
        Run a shell script inside the container; return stdout.

        Parameters
        ----------
        script : str
        user : str

        Returns
        -------
        str
        """
        return self.exec("sh", "-c", script, user=user)

    def restart(self) -> None:
        """Restart the container (kills the env server) and wait for sshd."""
        run_cmd(["docker", "restart", "-t", "1", self.container], timeout=120)
        wait_for_ssh(self.access)


@pytest.fixture(scope="session")
def sshd_image() -> str:
    """Build the sshd test image (cached by Docker after the first build)."""
    run_cmd(["docker", "build", "-t", SSHD_IMAGE, str(DOCKER_DIR / "sshd")], timeout=1800)
    return SSHD_IMAGE


@pytest.fixture(scope="module")
def sshd_box(sshd_image: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[SshBox]:
    """Start one sshd container per test module on a fixed localhost port."""
    port = free_port()
    access = make_ssh_access(tmp_path_factory.mktemp("sshd-access"), "hx-docker-sshd", port)
    name = f"hx-sshd-{uuid.uuid4().hex[:8]}"
    run_cmd(
        ["docker", "run", "-d", "--name", name, "--label", "hypothex-test=1"]
        + ["-p", f"127.0.0.1:{port}:22", "-e", f"AUTHORIZED_KEY={access.public_key}"]
        + [sshd_image]
    )
    try:
        wait_for_ssh(access)
        yield SshBox(container=name, access=access)
    finally:
        run_cmd(["docker", "rm", "-f", name], check=False)
