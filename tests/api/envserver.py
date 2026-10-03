"""Test helpers: in-process env servers and fakes for remote work.

Nothing here reaches a real host or hub. Servers run in threads on 127.0.0.1 with a
random port; the fake ``scp`` (``tests/fakes/fake_scp.py``) copies only inside a fake
root on this machine. The autouse ``isolate_remote`` fixture (``tests/conftest.py``)
already points ``HYPOTHEX_SSH``/``HYPOTHEX_SCP`` at a script that always fails and
``HYPOTHEX_HUB_URL`` at a dead port.
"""

from __future__ import annotations

import json
import shlex
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI

from hypothex.core.context import Context
from hypothex.remote.config import (
    EnvironmentsFile,
    HostKind,
    HostSpec,
    SlurmDefaults,
    save_hosts,
)
from tests.fakes import FAKES_DIR


def wait_until(check: Callable[[], Any], timeout: float = 20.0, interval: float = 0.1) -> Any:
    """
    Poll ``check`` until it returns a truthy value.

    Parameters
    ----------
    check : callable
        Returns the value to test; exceptions count as "not yet".
    timeout : float
        Seconds before giving up.
    interval : float
        Seconds between polls.

    Returns
    -------
    Any
        The first truthy value.

    Raises
    ------
    AssertionError
        On timeout, with the last value or exception.
    """
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = check()
        except Exception as exc:  # noqa: BLE001 - keep polling until the deadline
            last = exc
        else:
            if last:
                return last
        time.sleep(interval)
    raise AssertionError(f"condition not met in {timeout}s; last value: {last!r}")


@contextmanager
def serve_app(app: FastAPI) -> Iterator[str]:
    """
    Serve ``app`` with uvicorn in a thread on a random 127.0.0.1 port.

    Parameters
    ----------
    app : FastAPI
        The application (its lifespan runs).

    Yields
    ------
    str
        Base URL, e.g. ``http://127.0.0.1:53211``.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        wait_until(lambda: server.started, timeout=20)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()


def write_hosts(home: Path, hosts: dict[str, HostSpec]) -> None:
    """Write ``<home>/environments.yaml`` with exactly ``hosts``."""
    save_hosts(Context.open(home).layout, EnvironmentsFile(environments=hosts))


def write_fake_gpus(path: Path, count: int = 8, external: tuple[int, ...] = ()) -> Path:
    """
    Write a ``HYPOTHEX_FAKE_GPUS`` file: ``count`` A100s, ``external`` busy elsewhere.

    Parameters
    ----------
    path : Path
        File to write.
    count : int
        Number of GPUs.
    external : tuple of int
        Indices used by processes that are not hx runs.

    Returns
    -------
    Path
        ``path``.
    """
    rows = [
        {
            "index": i,
            "name": "NVIDIA A100 80GB",
            "util": 63.0 if i in external else 0.0,
            "mem_used_mb": 33600 if i in external else 0,
            "mem_total_mb": 81920,
            "external": i in external,
            "run_id": None,
        }
        for i in range(count)
    ]
    path.write_text(json.dumps(rows))
    return path


def write_fake_scp(folder: Path) -> Path:
    """
    Write a fake ``scp`` confined to ``folder`` and return its path.

    The script runs ``tests/fakes/fake_scp.py`` with ``folder`` as its fake root
    (``HYPOTHEX_FAKE_REMOTE_ROOT``) and ``HYPOTHEX_FAKE_SCP_ANY_HOST=1``: every alias
    gets the home ``folder/<alias>``, an absolute remote path must lie inside
    ``folder``, and ``-o BatchMode=yes`` is required. Nothing outside ``folder`` is
    ever read or written for a remote operand.

    Parameters
    ----------
    folder : Path
        Existing directory; holds the script (``fake-scp``) and is the fake root.

    Returns
    -------
    Path
        The executable script; point ``HYPOTHEX_SCP`` at it.

    Examples
    --------
    >>> monkeypatch.setenv("HYPOTHEX_SCP", str(write_fake_scp(tmp_path)))  # doctest: +SKIP
    """
    path = folder / "fake-scp"
    env = (
        f"HYPOTHEX_FAKE_REMOTE_ROOT={shlex.quote(str(folder.resolve()))} "
        "HYPOTHEX_FAKE_SCP_ANY_HOST=1"
    )
    script = shlex.quote(str(FAKES_DIR / "fake_scp.py"))
    path.write_text(f'#!/bin/sh\n{env} exec {shlex.quote(sys.executable)} {script} "$@"\n')
    path.chmod(0o755)
    return path


@contextmanager
def env_server(
    home: Path, *, kind: str | None = "ssh", background: bool = False
) -> Iterator[tuple[str, Context]]:
    """
    Run an env server for ``home`` in a thread.

    Parameters
    ----------
    home : Path
        The fake host's Hypothex home.
    kind : str or None
        Descriptor kind (``ssh``, ``slurm``).
    background : bool
        Run the repair and scheduler loops.

    Yields
    ------
    tuple of (str, Context)
        Base URL and a context on the same home.
    """
    from hypothex.api.app import create_app

    ctx = Context.open(home)
    with serve_app(create_app(home, background_repair=background, kind=kind)) as url:
        yield url, ctx


@dataclass
class Remote:
    """A hub (``client``) wired to one in-process env server named ``gpu1``."""

    client: httpx.Client
    hub: Context
    env: Context
    env_url: str
    env_repo: Path
    hub_repo: Path
    hub_url: str


def host_state(client: httpx.Client, name: str) -> str:
    """Return the connection state of ``name`` from ``GET /api/v1/hosts``."""
    rows = client.get("/api/v1/hosts").json()
    return next(r["state"]["state"] for r in rows if r["name"] == name)


@contextmanager
def remote_hub(
    tmp_path: Path,
    *,
    kind: HostKind = "ssh",
    slurm: SlurmDefaults | None = None,
    rate: float | None = 2.0,
    map_project: bool = True,
    threaded: bool = False,
    hub_home: Path | None = None,
    env_background: bool = False,
) -> Iterator[Remote]:
    """
    Start an env server ``gpu1`` and a hub whose ``environments.yaml`` points at it.

    Both repos are the toy project (``project: toy``): ``gpu1``'s checkout is a
    clone of the hub's repo through a bare ``origin`` (the hub repo has it as its
    ``origin`` remote, so a pushed commit can be fetched on ``gpu1``). The hub's
    repo is registered on the hub; ``gpu1``'s checkout is mapped for ``toy`` unless
    ``map_project`` is False. Waits until the hub shows ``gpu1`` connected.

    Parameters
    ----------
    tmp_path : Path
        Where homes and repos go.
    kind : HostKind
        ``ssh`` or ``slurm`` (env descriptor and host entry).
    slurm : SlurmDefaults, optional
        SLURM defaults of the host entry (default ``SlurmDefaults()`` for slurm).
    rate : float or None
        ``usd_per_gpu_hour``.
    map_project : bool
        Map ``toy`` to the host checkout.
    threaded : bool
        Serve the hub on a real port (for the CLI and MCP) instead of a TestClient.
    hub_home : Path, optional
        Hub home (default ``tmp_path / "hub-home"``).
    env_background : bool
        Run the env server's repair and scheduler loops.

    Yields
    ------
    Remote
    """
    from fastapi.testclient import TestClient

    from hypothex.api.app import create_app
    from tests.factories import git, write_toy_project

    hub_repo = write_toy_project(tmp_path / "hub-repo")
    # gpu1's checkout is a clone through a shared "origin", like a real host: the hub
    # pins its own HEAD (spec 8A.4), and a commit pushed later is fetchable on gpu1
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(hub_repo), str(origin))
    git(hub_repo, "remote", "add", "origin", str(origin))
    env_repo = tmp_path / "gpu1-repo"
    git(tmp_path, "clone", "-q", str(origin), str(env_repo))
    home = hub_home or tmp_path / "hub-home"
    with env_server(tmp_path / "gpu1-home", kind=kind, background=env_background) as (
        env_url,
        env_ctx,
    ):
        defaults = slurm if slurm is not None else (SlurmDefaults() if kind == "slurm" else None)
        spec = HostSpec(
            route="url",
            url=env_url,
            kind=kind,
            usd_per_gpu_hour=rate,
            slurm=defaults,
            projects={"toy": str(env_repo.resolve())} if map_project else {},
        )
        write_hosts(home, {"gpu1": spec})
        hub_ctx = Context.open(home)
        hub_ctx.register_project(hub_repo)
        app = create_app(home, background_repair=False)
        if threaded:
            with serve_app(app) as hub_url, httpx.Client(base_url=hub_url, timeout=120) as client:
                wait_until(lambda: host_state(client, "gpu1") == "connected", timeout=30)
                yield Remote(client, hub_ctx, env_ctx, env_url, env_repo, hub_repo, hub_url)
        else:
            with TestClient(app, base_url="http://127.0.0.1:7777") as test_client:
                wait_until(lambda: host_state(test_client, "gpu1") == "connected", timeout=30)
                yield Remote(
                    test_client,
                    hub_ctx,
                    env_ctx,
                    env_url,
                    env_repo,
                    hub_repo,
                    "http://127.0.0.1:7777",
                )
