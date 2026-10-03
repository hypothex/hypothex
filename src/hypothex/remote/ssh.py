"""
SSH transport: run scripts, copy files, and hold port-forward tunnels.

Every call goes through the user's own ``ssh``/``scp`` binaries, so their
``~/.ssh/config``, agent, and keys apply. Tests substitute fakes through the
``HYPOTHEX_SSH`` and ``HYPOTHEX_SCP`` environment variables.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from hypothex.core.errors import HypothexError

SSH_FAILURE_CODE = 255
_STDERR_TAIL = 2000


class SshError(HypothexError):
    """An ``ssh`` or ``scp`` call could not connect, timed out, or failed."""


def _default_ssh() -> str:
    return os.environ.get("HYPOTHEX_SSH") or "ssh"


def _default_scp() -> str:
    return os.environ.get("HYPOTHEX_SCP") or "scp"


class SshTarget(BaseModel):
    """
    How to reach one host over SSH.

    Parameters
    ----------
    alias : str
        A ``Host`` from ``~/.ssh/config`` or ``[user@]hostname``. Must not start
        with ``-`` and must not contain whitespace.
    ssh_bin : str
        The ``ssh`` binary. Default: ``$HYPOTHEX_SSH`` or ``"ssh"``.
    scp_bin : str
        The ``scp`` binary. Default: ``$HYPOTHEX_SCP`` or ``"scp"``.
    connect_timeout : int
        Seconds for ``-o ConnectTimeout``.

    Examples
    --------
    >>> SshTarget(alias="gpu1", ssh_bin="ssh", scp_bin="scp").alias
    'gpu1'
    """

    alias: str
    ssh_bin: str = Field(default_factory=_default_ssh)
    scp_bin: str = Field(default_factory=_default_scp)
    connect_timeout: int = Field(10, ge=1)

    @field_validator("alias")
    @classmethod
    def _check_alias(cls, value: str) -> str:
        if not value or value.startswith("-") or any(ch.isspace() for ch in value):
            raise ValueError(f"invalid ssh alias {value!r}")
        return value


def _base_options(target: SshTarget) -> list[str]:
    return [
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={target.connect_timeout}",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
    ]


def _tail(data: bytes) -> str:
    return data.decode("utf-8", "replace").strip()[-_STDERR_TAIL:]


def _run(
    argv: list[str], *, stdin: bytes | None, timeout: float, what: str
) -> subprocess.CompletedProcess[bytes]:
    """Run one ssh/scp process in its own process group; kill the group on timeout."""
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise SshError(f"{argv[0]} not found; is OpenSSH installed?") from exc
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise SshError(f"{what} timed out after {timeout:g}s") from None
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def run_remote(
    target: SshTarget,
    script: str,
    *,
    timeout: float = 120,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """
    Run a POSIX ``sh`` script on the host.

    Without ``input_bytes`` the script is sent on stdin to ``sh -s``. With
    ``input_bytes`` the script is passed as ``sh -c <script>`` and the bytes
    become the script's stdin.

    Parameters
    ----------
    target : SshTarget
        Host to run on.
    script : str
        POSIX shell script.
    timeout : float
        Seconds before the ``ssh`` process group is killed.
    input_bytes : bytes, optional
        Data for the script's stdin.

    Returns
    -------
    subprocess.CompletedProcess of bytes
        The script's exit code, stdout, and stderr. A non-zero exit from the
        script is returned, not raised.

    Raises
    ------
    SshError
        ``ssh`` is missing, the call timed out, or ``ssh`` exited 255
        (connection or authentication failure; a script that itself exits 255
        is reported the same way).

    Examples
    --------
    >>> res = run_remote(SshTarget(alias="gpu1"), "uname -s")  # doctest: +SKIP
    >>> res.stdout  # doctest: +SKIP
    b'Linux\\n'
    """
    argv = [target.ssh_bin, *_base_options(target), target.alias]
    if input_bytes is None:
        argv += ["sh", "-s"]
        stdin = script.encode("utf-8")
    else:
        argv += ["sh", "-c", shlex.quote(script)]
        stdin = input_bytes
    res = _run(argv, stdin=stdin, timeout=timeout, what=f"ssh {target.alias}")
    if res.returncode == SSH_FAILURE_CODE:
        raise SshError(f"ssh {target.alias} failed (exit 255): {_tail(res.stderr)}")
    return res


REMOTE_COPY_PATH = re.compile(r"^(~|~/[A-Za-z0-9_.+@/=-]*|[A-Za-z0-9_.+@/=-]+)$")
"""Shell-safe remote path for ``scp``: ``~``, ``~/...``, absolute, or relative."""


def _check_remote_path(remote_path: str, *, source: bool = False) -> None:
    # -s (SFTP) already keeps the remote shell out; this is the second fence.
    parts = remote_path.split("/")
    if not REMOTE_COPY_PATH.fullmatch(remote_path) or ".." in parts:
        raise SshError(f"invalid remote path {remote_path!r}")
    if source and parts[-1] in ("", ".", "~"):
        raise SshError(f"invalid remote path {remote_path!r}: no file name")


def copy_to(target: SshTarget, local: Path, remote_path: str, *, timeout: float = 300) -> None:
    """
    Copy a local file or directory to the host with ``scp -s -r`` (SFTP).

    The remote parent directory must exist. ``-s`` forces the SFTP protocol,
    so the remote shell never parses ``remote_path``.

    Parameters
    ----------
    target : SshTarget
        Destination host.
    local : Path
        File or directory to send.
    remote_path : str
        Destination path on the host; relative paths and ``~/`` are relative
        to the remote home.
    timeout : float
        Seconds before ``scp`` is killed.

    Raises
    ------
    SshError
        ``remote_path`` is not shell-safe or has a ``..`` part, ``local`` does
        not exist, ``scp`` failed, or the call timed out.

    Examples
    --------
    >>> wheel = Path("dist/hypothex-0.2.0-py3-none-any.whl")
    >>> copy_to(SshTarget(alias="gpu1"), wheel, "~/.hypothex/runtime/wheels/")  # doctest: +SKIP
    """
    _check_remote_path(remote_path)
    if not local.exists():
        raise SshError(f"cannot copy {local}: no such file or directory")
    argv = [target.scp_bin, *_base_options(target), "-s", "-q", "-r"]
    argv += [str(local), f"{target.alias}:{remote_path}"]
    res = _run(argv, stdin=None, timeout=timeout, what=f"scp to {target.alias}")
    if res.returncode != 0:
        raise SshError(
            f"scp {local} -> {target.alias}:{remote_path} failed (exit {res.returncode}): "
            f"{_tail(res.stderr)}"
        )


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


PULL_RESERVED_PREFIX = ".hx-"
"""A pull never writes a destination whose name starts with this (reserved for Hypothex)."""
_TXN_NAME = re.compile(r"[0-9a-f]{32}")


def copy_from(
    target: SshTarget, remote_path: str, local: Path, *, work: Path, timeout: float = 600
) -> None:
    """
    Copy a remote file or directory to ``local`` with ``scp -s -r`` (SFTP).

    ``remote_path`` must be shell-safe, have no ``..`` part, and name a file
    or directory (not ``/``, ``~``, or a path ending in ``/``); ``local``'s
    name must not start with ``.hx-``. Hypothex's own state lives only in
    ``work`` (the hub passes ``<hub home>/pulls``), never next to ``local``:
    the copy lands in a unique staging folder ``work/stage/pull-*`` and is
    renamed into place only on success, so ``local`` is never left
    half-written and concurrent pulls never share a staging path. An existing
    file is replaced atomically (``os.replace``). An existing folder cannot be
    renamed over, so the swap is first recorded in ``work/txn/<uuid>.json``
    (``{txn, dest}``), the old folder is moved to ``work/backup/<uuid>``, and
    it is removed only once the new one is in place. A swap cut short (a
    crash) is finished or undone by the next ``copy_from``, which reads only
    the records in ``work/txn``: no file in any destination folder is ever
    read or moved by recovery, whatever its name. Installs are serialized
    (``flock`` on ``work/txn``).

    Parameters
    ----------
    target : SshTarget
        Source host.
    remote_path : str
        Path on the host; relative paths and ``~/`` are relative to the
        remote home.
    local : Path
        Destination path. Parent directories are created.
    work : Path
        Folder for pull state (``stage/``, ``txn/``, ``backup/``); must be on
        the same filesystem as ``local``.
    timeout : float
        Seconds before ``scp`` is killed.

    Raises
    ------
    SshError
        ``remote_path`` is refused, ``local``'s name is reserved, ``scp``
        failed (for example the remote path is missing), or the call timed out.

    Examples
    --------
    >>> dest, work = Path("pulled/best.pt"), Path("pulls")
    >>> copy_from(SshTarget(alias="gpu1"), "~/ckpt/best.pt", dest, work=work)  # doctest: +SKIP
    """
    _check_remote_path(remote_path, source=True)
    if local.name.startswith(PULL_RESERVED_PREFIX):
        raise SshError(
            f"invalid destination {local.name!r}: names starting with "
            f"{PULL_RESERVED_PREFIX!r} are reserved"
        )
    txn_dir, _, stage_dir = _pull_dirs(work)
    local.parent.mkdir(parents=True, exist_ok=True)
    with _install_lock(txn_dir):
        _recover_swaps(work)  # a recorded swap was cut short: finish or undo it
    # A unique staging folder per call: two pulls of one file never share it.
    stage = Path(tempfile.mkdtemp(prefix="pull-", dir=stage_dir))
    part = stage / local.name
    argv = [target.scp_bin, *_base_options(target), "-s", "-q", "-r"]
    argv += [f"{target.alias}:{remote_path}", str(part)]
    try:
        res = _run(argv, stdin=None, timeout=timeout, what=f"scp from {target.alias}")
        if res.returncode != 0 or not part.exists():
            raise SshError(
                f"scp {target.alias}:{remote_path} -> {local} failed "
                f"(exit {res.returncode}): {_tail(res.stderr)}"
            )
        _install(part, local, work)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _pull_dirs(work: Path) -> tuple[Path, Path, Path]:
    """``(txn, backup, stage)`` folders under ``work``, created when missing."""
    dirs = (work / "txn", work / "backup", work / "stage")
    for folder in dirs:
        folder.mkdir(parents=True, exist_ok=True)
    return dirs


@contextmanager
def _install_lock(folder: Path) -> Iterator[None]:
    """Serialize pull installs (``flock`` on ``folder``: no lock file)."""
    fd = os.open(folder, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing drops the lock


def _write_record(path: Path, data: dict[str, str]) -> None:
    """Create a transaction record durably (``O_EXCL``: a uuid name is never reused)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, json.dumps(data).encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _recover_swaps(work: Path) -> None:
    """
    Finish or undo folder swaps cut short (install lock held).

    Only the records in ``work/txn/<uuid>.json`` are read, and each acts only
    on its own absolute ``dest`` and ``work/backup/<uuid>``. A record that is
    unreadable or whose ``txn`` is not its own name is left alone (a record is
    complete and fsynced before anything moves).
    """
    txn_dir, backup_dir, _ = _pull_dirs(work)
    for record in sorted(txn_dir.glob("*.json")):
        txn = record.stem
        if _TXN_NAME.fullmatch(txn) is None:
            continue
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("txn") != txn:
            continue
        dest = data.get("dest")
        if not isinstance(dest, str) or not Path(dest).is_absolute():
            continue
        dest_path, backup_path = Path(dest), backup_dir / txn
        if backup_path.exists() or backup_path.is_symlink():
            if dest_path.exists() or dest_path.is_symlink():
                _remove(backup_path)  # the new folder is in: only the cleanup was missed
            else:
                os.replace(backup_path, dest_path)  # no successor arrived: put it back
        record.unlink(missing_ok=True)


def _install(part: Path, local: Path, work: Path) -> None:
    """Move ``part`` to ``local``; an existing ``local`` is never lost, even by a crash."""
    txn_dir, backup_dir, _ = _pull_dirs(work)
    with _install_lock(txn_dir):
        _recover_swaps(work)
        if part.is_dir() and local.is_dir() and not local.is_symlink():
            # os.replace cannot overwrite a non-empty folder: record the swap, move the old
            # folder to work/backup/<txn>, then swap (_recover_swaps reads the record)
            txn = uuid.uuid4().hex
            backup = backup_dir / txn
            record = txn_dir / f"{txn}.json"
            _write_record(record, {"txn": txn, "dest": str(local.absolute())})
            os.replace(local, backup)
            try:
                os.replace(part, local)
            except OSError:
                os.replace(backup, local)
                record.unlink(missing_ok=True)
                raise
            _remove(backup)
            record.unlink()
            return
        if part.is_dir() and (local.exists() or local.is_symlink()):
            _remove(local)  # a folder replacing a file: no atomic swap exists for this case
        os.replace(part, local)  # atomic for a file over a file or a symlink
