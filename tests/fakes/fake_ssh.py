#!/usr/bin/env python3
"""
Fake ``ssh`` for tests: runs commands locally inside a temp "remote" home.

Environment:

- ``HYPOTHEX_FAKE_REMOTE_ROOT``: directory holding one sub-directory per host
  alias; that sub-directory is ``$HOME`` on the fake host. An alias without a
  directory fails like an unknown hostname (exit 255).
- ``<root>/<alias>/.fake_down``: when present the host refuses connections
  (exit 255), and running tunnels to it exit 255 within 0.2 s.
- ``HYPOTHEX_FAKE_SSH_LOG``: optional file; one JSON line per call with
  ``{"prog": "ssh", "argv": [...]}``.
- ``HYPOTHEX_FAKE_REMOTE_PATH``: optional; when set it is the exact ``PATH`` on
  the fake host (a bare host: no ``~/.local/bin``, only the tools a test chose).

Supported forms: ``ssh [opts] alias <command...>`` (command run with
``/bin/sh -c`` in the fake home, stdio passed through) and
``ssh -N -L [bind:]lport:host:rport [opts] alias`` (a real TCP relay from the
local port to ``host:rport`` on this machine). ``-o BatchMode=yes`` is
required, as Hypothex always passes it.
"""

from __future__ import annotations

import contextlib
import getopt
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import NoReturn

OPTSTRING = "1246ab:c:e:fgi:kl:m:no:p:qstvxAB:CD:E:F:GI:J:KL:MNO:P:Q:R:S:TVw:W:XYy"
STRIP_ENV = ("HYPOTHEX_HOME", "HYPOTHEX_SSH", "HYPOTHEX_SCP", "HYPOTHEX_AGENT")


def log_call(prog: str, argv: list[str]) -> None:
    """Append one JSON line describing this call to ``$HYPOTHEX_FAKE_SSH_LOG``."""
    path = os.environ.get("HYPOTHEX_FAKE_SSH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"prog": prog, "argv": argv}) + "\n")


def fail(message: str, code: int = 255) -> NoReturn:
    """Print ``message`` to stderr and exit with ``code``."""
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.stderr.flush()
    os._exit(code)


def host_home(alias: str) -> Path:
    """Return the fake home of ``alias`` or exit 255 like an unreachable host."""
    root = os.environ.get("HYPOTHEX_FAKE_REMOTE_ROOT")
    if not root:
        fail("fake ssh: HYPOTHEX_FAKE_REMOTE_ROOT is not set")
    host = alias.rsplit("@", 1)[-1]
    home = Path(root) / host
    if not home.is_dir():
        fail(f"ssh: Could not resolve hostname {host}: nodename nor servname provided")
    if (home / ".fake_down").exists():
        fail(f"ssh: connect to host {host} port 22: Connection refused")
    return home


def remote_env(home: Path) -> dict[str, str]:
    """
    Environment for commands on the fake host: ``HOME`` is the fake home.

    ``PATH`` is ``<home>/.local/bin`` plus the test's ``PATH``, or exactly
    ``$HYPOTHEX_FAKE_REMOTE_PATH`` when a test sets it.
    """
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env["HOME"] = str(home)
    env["PWD"] = str(home)
    exact = os.environ.get("HYPOTHEX_FAKE_REMOTE_PATH")
    env["PATH"] = exact or f"{home / '.local' / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    return env


def pump(src: socket.socket, dst: socket.socket) -> None:
    """Copy bytes from ``src`` to ``dst`` until EOF, then half-close ``dst``."""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            dst.shutdown(socket.SHUT_WR)


def bridge(client: socket.socket, host: str, port: int) -> None:
    """Relay one accepted connection to ``host:port``."""
    try:
        upstream = socket.create_connection((host, port), timeout=5)
    except OSError as exc:
        sys.stderr.write(f"channel 2: open failed: connect failed: {exc}\n")
        sys.stderr.flush()
        client.close()
        return
    upstream.settimeout(None)
    back = threading.Thread(target=pump, args=(upstream, client), daemon=True)
    back.start()
    pump(client, upstream)
    back.join()
    client.close()
    upstream.close()


def serve_forward(spec: str, exit_on_failure: bool, home: Path, alias: str) -> None:
    """Listen on the local side of ``-L spec`` and relay until killed or host down."""
    parts = spec.split(":")
    if len(parts) == 3:
        parts = ["127.0.0.1", *parts]
    if len(parts) != 4:
        fail(f"Bad local forwarding specification '{spec}'")
    bind, lport, host, rport = parts
    host = "127.0.0.1" if host == "localhost" else host
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((bind or "127.0.0.1", int(lport)))
    except OSError:
        sys.stderr.write(f"bind [{bind}]:{lport}: Address already in use\n")
        if exit_on_failure:
            fail("Could not request local forwarding.")
        sys.stderr.write("Could not request local forwarding.\n")
        server.close()
    else:
        server.listen(64)

        def accept_loop() -> None:
            while True:
                try:
                    client, _ = server.accept()
                except OSError:
                    return
                threading.Thread(
                    target=bridge, args=(client, host, int(rport)), daemon=True
                ).start()

        threading.Thread(target=accept_loop, daemon=True).start()
    while True:
        time.sleep(0.2)
        if (home / ".fake_down").exists():
            fail(f"Connection to {alias} closed by remote host.")


def main(argv: list[str]) -> None:
    """Entry point; never returns (exits with the remote status)."""
    log_call("ssh", argv)
    try:
        opts, rest = getopt.getopt(argv, OPTSTRING)
    except getopt.GetoptError as exc:
        fail(f"fake ssh: {exc}")
    options: dict[str, str] = {}
    forwards: list[str] = []
    no_command = False
    for flag, value in opts:
        if flag == "-o":
            key, _, val = value.partition("=")
            options[key.strip().lower()] = val.strip()
        elif flag == "-L":
            forwards.append(value)
        elif flag == "-N":
            no_command = True
    if options.get("batchmode", "").lower() != "yes":
        fail("fake ssh: refusing to run without -o BatchMode=yes")
    if not rest:
        fail("fake ssh: missing destination")
    alias, command = rest[0], rest[1:]
    home = host_home(alias)
    if no_command:
        if not forwards:
            fail("fake ssh: -N without -L is not supported")
        exit_on_failure = options.get("exitonforwardfailure", "").lower() == "yes"
        for spec in forwards[1:]:
            threading.Thread(
                target=serve_forward, args=(spec, exit_on_failure, home, alias), daemon=True
            ).start()
        serve_forward(forwards[0], exit_on_failure, home, alias)
        return
    if not command:
        fail("fake ssh: interactive sessions are not supported")
    proc = subprocess.run(["/bin/sh", "-c", " ".join(command)], cwd=home, env=remote_env(home))
    sys.stdout.flush()
    os._exit(proc.returncode if proc.returncode >= 0 else 255)


if __name__ == "__main__":
    main(sys.argv[1:])
