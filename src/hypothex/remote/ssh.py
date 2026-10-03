"""
SSH transport: run scripts, copy files, and hold port-forward tunnels.

Every call goes through the user's own ``ssh``/``scp`` binaries, so their
``~/.ssh/config``, agent, and keys apply. Tests substitute fakes through the
``HYPOTHEX_SSH`` and ``HYPOTHEX_SCP`` environment variables.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess

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
