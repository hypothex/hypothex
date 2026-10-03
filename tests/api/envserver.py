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
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from hypothex.core.context import Context
from hypothex.remote.config import EnvironmentsFile, HostSpec, save_hosts
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
