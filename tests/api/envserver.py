"""Test helpers: in-process env servers and fakes for remote work.

Nothing here reaches a real host or hub. Servers run in threads on 127.0.0.1 with a
random port; the fake ``scp`` copies local paths. The autouse ``isolate_remote``
fixture (``tests/conftest.py``) already points ``HYPOTHEX_SSH``/``HYPOTHEX_SCP`` at a
script that always fails and ``HYPOTHEX_HUB_URL`` at a dead port.
"""

from __future__ import annotations

import json
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

FAKE_SCP = '''#!PYTHON
"""Fake scp for tests: `alias:/path` is the local /path. No network."""
import os
import shutil
import sys

VALUED = {"-o", "-P", "-i", "-F", "-l", "-c", "-S", "-J"}
args, paths, i = sys.argv[1:], [], 0
while i < len(args):
    if args[i] in VALUED:
        i += 2
        continue
    if args[i].startswith("-"):
        i += 1
        continue
    paths.append(args[i])
    i += 1


def local(p):
    return p.split(":", 1)[1] if ":" in p and not p.startswith("/") else p


src, dst = local(paths[-2]), local(paths[-1])
if not os.path.exists(src):
    print(f"scp: {src}: No such file or directory", file=sys.stderr)
    sys.exit(1)
(shutil.copytree if os.path.isdir(src) else shutil.copy)(src, dst)
'''


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
    """Write the fake ``scp`` script into ``folder`` and return its path."""
    path = folder / "fake-scp"
    path.write_text(FAKE_SCP.replace("PYTHON", sys.executable, 1))
    path.chmod(0o755)
    return path
