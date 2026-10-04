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

import asyncio
import contextlib
import os
import shlex
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import pytest
import yaml
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.records import RunRecord
from hypothex.remote.client import EnvClient
from hypothex.remote.config import EnvironmentsFile, HostSpec, load_hosts, save_hosts
from hypothex.remote.hub import HostState, Hub
from hypothex.remote.ssh import SshTarget
from tests.factories import init_git_repo, write_toy_project

T = TypeVar("T")

DOCKER_DIR = Path(__file__).resolve().parent
SSHD_IMAGE = "hypothex-test-sshd:1"
SLURM_COMPOSE = DOCKER_DIR / "slurm" / "docker-compose.yml"
REMOTE_HOME = "~/.hypothex"
REMOTE_PROJECT = "/home/hx/dock"
REMOTE_STORE = "/home/hx/.hypothex/store"
REMOTE_TOY = "/home/hx/toy"
"""Where ``put_toy_project`` puts the scored toy project on a host."""
REMOTE_HX_PYTHON = "/home/hx/.hypothex/runtime/tools/hypothex/bin/python"
"""The Python of the hx that ``hx hosts add`` installs (it has ``hypothex``)."""
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

    def put(self, local: Path, remote: str) -> None:
        """
        Copy a local folder into the container (not over ssh), owned by ``hx``.

        Parameters
        ----------
        local : Path
            Folder on this machine.
        remote : str
            Absolute path in the container; must not exist yet.
        """
        self.exec("rm", "-rf", remote, user="root")  # a rerun in the same module
        run_cmd(["docker", "cp", str(local), f"{self.container}:{remote}"], timeout=120)
        self.exec("chown", "-R", "hx:hx", remote, user="root")

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


# hub in a thread ----------------------------------------------------------------------
def write_hosts(ctx: Context, **hosts: HostSpec) -> None:
    """
    Write the hub's ``environments.yaml``.

    Parameters
    ----------
    ctx : Context
        Hub context.
    **hosts : HostSpec
        Host name -> spec.
    """
    save_hosts(ctx.layout, EnvironmentsFile(environments=dict(hosts)))


class HubThread:
    """
    Run a ``Hub`` on a private asyncio loop in a daemon thread.

    The test thread polls ``state()`` and reads mirrored files while the hub's
    supervisors run. Use as a context manager: enter starts, exit stops.

    Parameters
    ----------
    ctx : Context
        Hub context; hosts come from its ``environments.yaml``.
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.hub = Hub(ctx, load_hosts(ctx.layout))
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="hx-hub", daemon=True)

    def __enter__(self) -> HubThread:
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self.hub.start(), self._loop).result(timeout=60)
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.hub.stop(), self._loop).result(timeout=60)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)
            self._loop.close()

    def client(self, name: str) -> EnvClient:
        """
        Return the hub's current client for a host (follows reconnects).

        Parameters
        ----------
        name : str

        Returns
        -------
        EnvClient
        """
        return self.hub.client(name)

    def wait_connected(
        self, name: str, *, timeout: float, after: HostState | None = None
    ) -> HostState:
        """
        Wait until a host is ``connected`` (and, with ``after``, reconnected since then).

        Parameters
        ----------
        name : str
            Host name.
        timeout : float
            Seconds to wait.
        after : HostState, optional
            An earlier state; the new one must have a later ``since``.

        Returns
        -------
        HostState

        Raises
        ------
        AssertionError
            On timeout; the message names the last ``HostState`` (its
            ``message`` carries the bootstrap error).
        """

        def check() -> HostState:
            # Raise (not return None) while not ready so wait_until keeps the
            # state as ``last``: its ``message`` carries the bootstrap error.
            state = self.hub.state(name)
            if state.state != "connected":
                raise AssertionError(repr(state))
            if after is not None and state.since <= after.since:
                raise AssertionError(f"not reconnected since {after.since!r}: {state!r}")
            return state

        return wait_until(check, timeout=timeout, what=f"host {name} connected", interval=0.25)


def launch(client: EnvClient, command: list[str], **extra: Any) -> dict[str, Any]:
    """
    Launch a run in the remote toy project ``dock`` through an env server.

    Parameters
    ----------
    client : EnvClient
        Client of the env server (tunnelled).
    command : list of str
        Command to run on the host.
    **extra
        Extra launch fields (``gpus``, ``slurm``, ...).

    Returns
    -------
    dict
        The created run record.
    """
    body: dict[str, Any] = {
        "repo": REMOTE_PROJECT,
        "command": command,
        "hypothesis": "docker integration",
        "command_id": uuid.uuid4().hex,
        **extra,
    }
    return client.post_json("/api/v1/runs", body)


def remote_record(hub: HubThread, host: str, run_id: str) -> dict[str, Any]:
    """
    Return a run's record as the host's env server reports it.

    Parameters
    ----------
    hub : HubThread
    host : str
    run_id : str

    Returns
    -------
    dict
    """
    return hub.client(host).get_json(f"/api/v1/runs/{run_id}")["record"]


def wait_remote_status(
    hub: HubThread, host: str, run_id: str, status: str, *, timeout: float
) -> dict[str, Any]:
    """
    Wait until the host reports ``status`` for a run.

    Parameters
    ----------
    hub : HubThread
    host : str
    run_id : str
    status : str
    timeout : float

    Returns
    -------
    dict
        The remote record.
    """

    def check() -> dict[str, Any] | None:
        record = remote_record(hub, host, run_id)
        return record if record["status"] == status else None

    return wait_until(check, timeout=timeout, what=f"{host}:{run_id} {status}")


def wait_mirrored(ctx: Context, run_id: str, status: str, *, timeout: float) -> RunRecord:
    """
    Wait until the hub's mirror of a ``dock`` run has ``status``.

    Parameters
    ----------
    ctx : Context
        Hub context.
    run_id : str
    status : str
    timeout : float

    Returns
    -------
    RunRecord
        The mirrored record read from the hub's ``run.yaml``.
    """

    def check() -> RunRecord | None:
        record = ctx.store.read_record("dock", run_id)
        return record if record.status == status else None

    return wait_until(check, timeout=timeout, what=f"hub mirror of {run_id} {status}")


def mirrored_text(ctx: Context, run_id: str, rel: str, needle: str, *, timeout: float) -> str:
    """
    Wait until a mirrored file of a ``dock`` run contains ``needle``; return its text.

    Parameters
    ----------
    ctx : Context
    run_id : str
    rel : str
        Path inside the run folder, e.g. ``logs/stdout.log``.
    needle : str
    timeout : float

    Returns
    -------
    str
    """
    path = ctx.layout.run_dir("dock", run_id) / rel

    def check() -> str | None:
        text = path.read_text(encoding="utf-8")
        return text if needle in text else None

    return wait_until(check, timeout=timeout, what=f"{needle!r} in mirrored {rel}")


def host_cursor(ctx: Context, host: str) -> int:
    """
    Return the hub's persisted event cursor for a host (0 when none).

    Parameters
    ----------
    ctx : Context
    host : str

    Returns
    -------
    int
    """
    with contextlib.closing(sqlite3.connect(ctx.layout.index_db)) as conn:
        row = conn.execute(
            "SELECT MAX(last_sequence) FROM host_cursors WHERE host = ?", (host,)
        ).fetchone()
    return int(row[0] or 0)


# hub app and a scored project ------------------------------------------------------------
WRITE_PREDS_075 = (
    "import json, os, pathlib; d = pathlib.Path(os.environ['HYPOTHEX_RUN_DIR']) / 'predictions'; "
    "d.mkdir(exist_ok=True); f = open(d / 'predictions.jsonl', 'w'); "
    "[f.write(json.dumps(dict(id='ex-' + str(i), prediction=i % 2)) + chr(10)) for i in range(4)]"
)
"""``python3 -c`` code: toy predictions 0 1 0 1 (accuracy 0.75); no braces, as a
command's ``{name}`` is a template variable."""


def write_scored_toy_project(repo: Path) -> Path:
    """
    Write the toy project (task ``toy-acc``) for a host and commit it.

    It is ``tests.factories.write_toy_project`` with the evaluation Python set
    to the hx that ``hx hosts add`` installs on the host (``REMOTE_HX_PYTHON``),
    so the host scores a run without ``uv run`` in the project.

    Parameters
    ----------
    repo : Path
        New folder on this machine.

    Returns
    -------
    Path
        ``repo``; copy it to the host with ``put`` so both sides share the commit.
    """
    write_toy_project(repo, use_git=False)
    path = repo / "hypothex.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["env"] = {"python": [REMOTE_HX_PYTHON]}
    config.pop("stages", None)  # its infer stage names this machine's Python
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    init_git_repo(repo)
    return repo


def add_host(home: Path, name: str, alias: str, *options: str, projects: dict[str, str]) -> None:
    """
    Add a host as a user does: ``hx hosts add --ssh`` (installs hx), then ``hx hosts map``.

    Parameters
    ----------
    home : Path
        The hub's home.
    name : str
        Host name.
    alias : str
        The ssh alias (the box's isolated wrappers must be in ``HYPOTHEX_SSH``/``SCP``).
    *options : str
        More ``hx hosts add`` options, e.g. ``--slurm``, ``--usd-per-gpu-hour 2``.
    projects : dict of str to str
        Project -> checkout path on the host, for ``hx hosts map``.
    """
    from typer.testing import CliRunner

    from hypothex.cli.main import app

    runner = CliRunner()
    base = ["--home", str(home), "hosts"]
    added = runner.invoke(app, [*base, "add", name, "--ssh", alias, *options, "--json"])
    assert added.exit_code == 0, added.output
    for project, path in projects.items():
        mapped = runner.invoke(app, [*base, "map", project, name, path])
        assert mapped.exit_code == 0, mapped.output


@contextlib.contextmanager
def hub_app(ctx: Context, host: str, *, timeout: float) -> Iterator[TestClient]:
    """
    Run the hub's HTTP app (``hx serve`` on the hub) and wait until ``host`` is connected.

    Unlike ``HubThread``, requests go through the hub's routes, as the UI,
    CLI, and MCP send them (``POST /api/v1/hosts/{host}/runs``).

    Parameters
    ----------
    ctx : Context
        Hub context; hosts come from its ``environments.yaml``.
    host : str
        Host to wait for.
    timeout : float
        Seconds to wait for the connection (a first bootstrap installs hx).

    Yields
    ------
    TestClient
        Client of the hub's app.
    """

    def connected() -> bool:
        rows = client.get("/api/v1/hosts").json()
        state = next(r["state"] for r in rows if r["name"] == host)
        if state["state"] != "connected":
            raise AssertionError(repr(state))  # kept as "last" for the timeout message
        return True

    app = create_app(ctx.layout.home, background_repair=False)
    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        wait_until(connected, timeout=timeout, what=f"host {host} connected", interval=0.5)
        yield client


def board_row(client: TestClient, project: str, task: str, run_id: str) -> dict[str, Any] | None:
    """
    Return the hub leaderboard row that holds ``run_id`` (None while it has none).

    Parameters
    ----------
    client : TestClient
        Client of the hub's app.
    project : str
    task : str
    run_id : str

    Returns
    -------
    dict or None
    """
    board = client.get(f"/api/v1/tasks/{project}/{task}/leaderboard").json()
    return next((row for row in board["rows"] if run_id in row["run_ids"]), None)


# SLURM cluster ----------------------------------------------------------------------------
@dataclass
class SlurmCluster:
    """A running compose project: mysql, slurmdbd, slurmctld (+ sshd), compute node c1."""

    project: str
    access: SshAccess
    env: dict[str, str] = field(default_factory=dict)

    def compose(
        self, *args: str, timeout: float = 600, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """
        Run ``docker compose`` for this cluster.

        Parameters
        ----------
        *args : str
        timeout : float
        check : bool

        Returns
        -------
        subprocess.CompletedProcess
        """
        cmd = ["docker", "compose", "-f", str(SLURM_COMPOSE), "-p", self.project, *args]
        return run_cmd(cmd, timeout=timeout, check=check, env=self.env)

    def exec(
        self, *argv: str, service: str = "slurmctld", user: str = "hx", check: bool = True
    ) -> str:
        """
        Run a command in a cluster container; return stdout.

        Parameters
        ----------
        *argv : str
        service : str
        user : str
        check : bool

        Returns
        -------
        str
        """
        args = ("exec", "-T", "-u", user, "-w", "/home/hx", service, *argv)
        return self.compose(*args, timeout=120, check=check).stdout

    def sh(self, script: str) -> str:
        """
        Run a shell script as ``hx`` on the login node; return stdout.

        Parameters
        ----------
        script : str

        Returns
        -------
        str
        """
        return self.exec("sh", "-c", script)

    def put(self, local: Path, remote: str) -> None:
        """
        Copy a local folder to the shared ``/home`` (login and compute node), owned by ``hx``.

        Parameters
        ----------
        local : Path
            Folder on this machine.
        remote : str
            Absolute path under ``/home/hx``; must not exist yet.
        """
        self.exec("rm", "-rf", remote, user="root")  # a rerun in the same module
        self.compose("cp", str(local), f"slurmctld:{remote}", timeout=120)
        self.exec("chown", "-R", "hx:hx", remote, user="root")

    def node_state(self) -> str:
        """
        Return ``sinfo``'s state of node ``c1`` (e.g. ``idle``, ``down*``).

        Returns
        -------
        str
        """
        return self.exec("sinfo", "-h", "-n", "c1", "-o", "%T").strip()

    def job_state(self, job_id: str) -> str:
        """
        Return a job's live state from ``squeue``, else its final state from ``sacct``.

        Parameters
        ----------
        job_id : str

        Returns
        -------
        str
            e.g. ``RUNNING``, ``COMPLETED``, ``CANCELLED by 1000``, ``NODE_FAIL``.
        """
        live = self.exec("squeue", "-h", "-j", job_id, "-o", "%T", check=False).strip()
        if live:
            return live
        return self.exec("sacct", "-n", "-X", "-P", "-j", job_id, "-o", "State").strip()

    def sacct(self, job_id: str, column: str) -> str:
        """
        Return one ``sacct`` column of a job.

        Parameters
        ----------
        job_id : str
        column : str
            e.g. ``JobName``, ``NodeList``.

        Returns
        -------
        str
        """
        return self.exec("sacct", "-n", "-X", "-P", "-j", job_id, "-o", column).strip()


@pytest.fixture(scope="module")
def slurm_cluster(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SlurmCluster]:
    """Build and start the SLURM compose project; tear it down with its volumes."""
    port = free_port()
    access = make_ssh_access(tmp_path_factory.mktemp("slurm-access"), "hx-docker-slurm", port)
    cluster = SlurmCluster(
        project=f"hxslurm{uuid.uuid4().hex[:8]}",
        access=access,
        env={"HX_AUTHORIZED_KEY": access.public_key, "HX_SLURM_SSH_PORT": str(port)},
    )
    try:
        cluster.compose("build", timeout=1800)
        cluster.compose("up", "-d", timeout=600)
        wait_until(lambda: cluster.node_state() == "idle", timeout=300, what="SLURM node c1 idle")
        wait_for_ssh(access)
        yield cluster
    except BaseException:
        print(cluster.compose("logs", "--no-color", "--tail", "200", check=False).stdout)
        raise
    finally:
        cluster.compose("down", "-v", "--remove-orphans", timeout=300, check=False)
