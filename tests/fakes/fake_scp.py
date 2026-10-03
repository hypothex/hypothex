#!/usr/bin/env python3
"""
Fake ``scp`` for tests: copies between this machine and fake host homes.

Uses the same environment as ``fake_ssh.py``: ``HYPOTHEX_FAKE_REMOTE_ROOT``
(one sub-directory per alias, the alias's ``$HOME``), the ``.fake_down``
marker, and ``HYPOTHEX_FAKE_SSH_LOG`` (logged with ``"prog": "scp"``).

A remote operand is ``[user@]alias:path``. ``~``, ``~/x`` and relative paths
resolve against the fake home; absolute remote paths must lie inside the
fake root so a test can never write to real system paths. Every resolved
remote path (``..`` and symlinks followed) must stay inside the fake root.
With ``HYPOTHEX_FAKE_SCP_ANY_HOST=1`` an unknown alias gets an empty home
under the root instead of failing (``tests.api.envserver.write_fake_scp``).
Like real ``scp``, the destination's parent directory must exist and
directories need ``-r``.
"""

from __future__ import annotations

import getopt
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import NoReturn

OPTSTRING = "12346ABCTdfOpqRrstvD:F:i:J:l:o:P:S:X:"
REMOTE = re.compile(r"^(?:[^/:@]+@)?(?P<host>[^/:]+):(?P<path>.*)$")


def log_call(argv: list[str]) -> None:
    """Append one JSON line describing this call to ``$HYPOTHEX_FAKE_SSH_LOG``."""
    path = os.environ.get("HYPOTHEX_FAKE_SSH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"prog": "scp", "argv": argv}) + "\n")


def fail(message: str, code: int = 1) -> NoReturn:
    """Print ``message`` to stderr and exit with ``code``."""
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.stderr.flush()
    sys.exit(code)


def resolve(operand: str) -> Path:
    """Map an operand to a path on this machine (fake home for remote operands)."""
    match = REMOTE.match(operand)
    if match is None:
        return Path(operand)
    root_env = os.environ.get("HYPOTHEX_FAKE_REMOTE_ROOT")
    if not root_env:
        fail("fake scp: HYPOTHEX_FAKE_REMOTE_ROOT is not set", 255)
    root = Path(root_env).resolve()
    host = match.group("host")
    home = root / host
    if host in (".", ".."):
        fail(f"ssh: Could not resolve hostname {host}: nodename nor servname provided", 255)
    if not home.is_dir() and os.environ.get("HYPOTHEX_FAKE_SCP_ANY_HOST") == "1":
        home.mkdir()
    if not home.is_dir():
        fail(f"ssh: Could not resolve hostname {host}: nodename nor servname provided", 255)
    if (home / ".fake_down").exists():
        fail(f"ssh: connect to host {host} port 22: Connection refused", 255)
    raw = match.group("path")
    if raw in ("", "~"):
        path = home
    elif raw.startswith("~/"):
        path = home / raw[2:]
    else:
        path = home / raw  # an absolute ``raw`` replaces ``home``
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        fail(f"fake scp: {raw} is outside the fake remote root")
    return resolved


def copy(src_operand: str, src: Path, dst: Path, recursive: bool) -> None:
    """Copy ``src`` to ``dst`` with scp's file/directory rules."""
    if not src.exists():
        fail(f"scp: {src_operand}: No such file or directory")
    if src.is_dir() and not recursive:
        fail(f"scp: {src_operand}: not a regular file")
    if dst.is_dir():
        dst = dst / src.name
    if not dst.parent.is_dir():
        fail(f"scp: {dst.parent}: No such file or directory")
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copyfile(src, dst)


def main(argv: list[str]) -> None:
    """Entry point; exits 0 on success, 1 on copy errors, 255 on connect errors."""
    log_call(argv)
    try:
        opts, operands = getopt.getopt(argv, OPTSTRING)
    except getopt.GetoptError as exc:
        fail(f"fake scp: {exc}")
    batch = [v for f, v in opts if f == "-o" and v.replace(" ", "").lower() == "batchmode=yes"]
    if not batch:
        fail("fake scp: refusing to run without -o BatchMode=yes", 255)
    recursive = any(flag == "-r" for flag, _ in opts)
    if len(operands) < 2:
        fail("usage: scp [-r] source ... target")
    *sources, target = operands
    remote = [REMOTE.match(op) is not None for op in operands]
    if (remote[-1] and any(remote[:-1])) or not any(remote):
        fail("fake scp: exactly one side must be remote")
    dst = resolve(target)
    for operand in sources:
        copy(operand, resolve(operand), dst, recursive)
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
