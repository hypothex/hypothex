"""
SLURM runner: render, submit, track, and cancel one batch job per run.

An env server on a SLURM login node (``hx serve --kind slurm``) submits each
run as a batch job whose script runs ``hx run --child <run_id>`` on the
compute node. The node writes the run folder on the shared filesystem. The
login node tracks the job with ``squeue`` (then ``sacct`` once the job left
the queue) every ``SLURM_POLL_SECONDS`` and marks a run ``lost`` when its job
is gone without an exit record (spec 5.6, 8A.5).
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import getpass
import json
import logging
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

from pydantic import BaseModel

from hypothex.core.context import Context
from hypothex.core.environment import load_descriptor
from hypothex.core.errors import ConfigError, HypothexError, RunError, RunNotFoundError
from hypothex.core.events import EventLog
from hypothex.core.execution import (
    STOP_MARKER,
    execute_run,
    process_alive,
    process_create_time,
    release_worktree,
    score_finished_run,
)
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import utcnow
from hypothex.core.index import Index
from hypothex.core.layout import Layout
from hypothex.core.records import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    RunRecord,
    RunStatus,
    ScoreRecord,
)
from hypothex.core.store import RunStore, dir_lock, run_lock
from hypothex.remote.config import SlurmDefaults, sbatch_option_problem

log = logging.getLogger(__name__)

FINISHED_STATES = frozenset(
    {
        "BOOT_FAIL",
        "CANCELLED",
        "COMPLETED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "TIMEOUT",
    }
)
_SAFE_VALUE = re.compile(r"[A-Za-z0-9_.:+@/,-]+")

SLURM_COMMAND_TIMEOUT = 60.0
SQUEUE_FORMAT = "%i|%T|%N"
SQUEUE_COMMENT_FORMAT = "%i|%T|%N|%k"
SACCT_FORMAT = "JobID,State,ExitCode,NodeList"
SACCT_COMMENT_FORMAT = "JobID,State,ExitCode,NodeList,Comment"
_NO_NODE = frozenset({"", "None assigned", "(null)", "n/a"})

SLURM_EXECUTOR = "slurm"
EXIT_FILE = "exit.json"
"""Exit record the compute node writes after the run ends (``status``, ``exit_code``)."""
NO_FLOCK_ERRNOS = frozenset({errno.ENOSYS, errno.ENOLCK, errno.EOPNOTSUPP})
"""``flock`` errors of shared filesystems without lock support (Lustre, some NFS)."""
SBATCH_FILE = "slurm.sbatch"
SLURM_POLL_SECONDS = 30.0
SLURM_SETTINGS_FILE = "slurm.json"
"""The effective ``SlurmDefaults`` of one run, saved in its folder (reruns reuse them)."""
LAST_SLURM_DEFAULTS = "slurm_defaults.json"
"""``<home>/slurm_defaults.json``: the settings of the last launch that sent them."""
OUTBOX_DIR = "slurm/outbox"
"""``<home>/slurm/outbox/<run_id>.json``: submission intent and publication cursor."""
SUBMIT_SETTLE_SECONDS = 300.0
"""An unknown submission counts as absent only this long after its intent."""
PENDING_STALE_SECONDS = SLURM_COMMAND_TIMEOUT + SUBMIT_SETTLE_SECONDS
"""A ``pending`` intent this old is ``unknown`` even while its submitter lives: sbatch is over."""
LOST_RECHECK_SECONDS = 3600.0
"""A run marked ``lost`` keeps its outbox entry this long: a node end that a shared
filesystem shows late (``run.yaml`` or ``exit.json``) still replaces ``lost``."""
FLOCK_PROBE = ".flock-probe"


class SlurmError(HypothexError):
    """A SLURM command failed, or a SLURM setting cannot be put in an sbatch script."""


class SlurmJob(BaseModel):
    """
    One SLURM job as ``squeue`` or ``sacct`` reports it.

    ``state`` is the first word of SLURM's state (``CANCELLED by 1000`` ->
    ``CANCELLED``). ``exit_code`` is only known from ``sacct``; a job ended by
    signal N gets ``128 + N``.
    """

    job_id: str
    state: str
    node: str | None = None
    exit_code: int | None = None


def is_finished(job: SlurmJob) -> bool:
    """
    Return True if SLURM reports the job as ended.

    Parameters
    ----------
    job : SlurmJob
        The job as reported by SLURM.

    Returns
    -------
    bool
        True for end states such as ``COMPLETED``, ``FAILED``, ``NODE_FAIL``.

    Examples
    --------
    >>> is_finished(SlurmJob(job_id="1", state="COMPLETING"))
    False
    >>> is_finished(SlurmJob(job_id="1", state="NODE_FAIL"))
    True
    """
    return job.state in FINISHED_STATES


def _safe(name: str, value: str) -> str:
    if not _SAFE_VALUE.fullmatch(value):
        raise SlurmError(
            f"slurm {name} {value!r} has characters sbatch cannot take "
            "(use letters, digits, and _ . : + @ / , - only)"
        )
    return value


def validate_defaults(defaults: SlurmDefaults) -> None:
    """
    Check that SLURM settings can go into ``#SBATCH`` lines unchanged.

    Parameters
    ----------
    defaults : SlurmDefaults
        The settings to check.

    Raises
    ------
    SlurmError
        A field holds whitespace or shell characters, or an ``extra`` item is
        not exactly one safe option token or sets an option Hypothex owns
        (``sbatch_option_problem``: ``--job-name``, ``--comment``,
        ``--output``, ``--error``, ``--chdir``, ``--wrap``, in any form; and
        here also ``--requeue`` / ``--no-requeue`` or an abbreviation of them,
        see ``REQUEUE_OPTIONS``, and ``--array`` / ``-a`` in any form, see
        ``ARRAY_OPTION``).

    Examples
    --------
    >>> validate_defaults(SlurmDefaults(partition="gpu", extra=["--mem=32G"]))
    """
    _safe("time", defaults.time)
    if defaults.partition is not None:
        _safe("partition", defaults.partition)
    if defaults.account is not None:
        _safe("account", defaults.account)
    for item in defaults.extra:
        problem = sbatch_option_problem(item) or _requeue_problem(item) or _array_problem(item)
        if problem is not None:
            raise SlurmError(f"slurm extra option {problem}")


REQUEUE_OPTIONS = ("requeue", "no-requeue")
"""sbatch options ``render_sbatch`` owns: every job is ``--no-requeue``.

A requeued job would run ``hx run --child`` a second time under the same job
id; that attempt finds the run already claimed and fails, so SLURM's real end
(``NODE_FAIL``) would be reported as ``FAILED`` after a second allocation.
"""


def _requeue_problem(item: str) -> str | None:
    """Why ``item`` sets a requeue option (``--requeue``, ``--no-req``, ...), or None."""
    if not item.startswith("--"):
        return None  # sbatch has no short form of either
    name = item[2:].split("=", 1)[0]
    taken = next((r for r in REQUEUE_OPTIONS if name and r.startswith(name)), None)
    if taken is None:
        return None
    return (
        f"{item!r} sets --{taken}, which Hypothex sets itself "
        "(every job is --no-requeue: a second attempt cannot run the same run)"
    )


ARRAY_OPTION = "array"
"""The sbatch option (short ``-a``) that makes a job array; ``extra`` may not set it.

Every task of an array runs the batch script, so each task after the first
would run ``hx run --child`` for the same run, find it already claimed, and
fail: one run is one job.
"""
ARRAY_SHORT = "a"


def _array_problem(item: str) -> str | None:
    """Why ``item`` makes a job array (``--array=1-3``, ``--arr=0-9``, ``-a1-3``), or None."""
    if item.startswith("--"):
        name = item[2:].split("=", 1)[0]
        taken = bool(name) and ARRAY_OPTION.startswith(name)
    else:
        taken = item.startswith(f"-{ARRAY_SHORT}")
    if not taken:
        return None
    return (
        f"{item!r} sets --{ARRAY_OPTION}, which Hypothex cannot run "
        "(each array task would run the same run again)"
    )


def render_sbatch(record: RunRecord, defaults: SlurmDefaults, home: Path) -> str:
    """
    Render the batch script that runs ``record`` on a compute node.

    Directives, in order: ``--job-name=hx-<run_id>``,
    ``--output=<run_dir>/logs/slurm-%j.out``, ``--no-requeue`` (a node
    failure must end the job, not start a second attempt that finds the run
    already claimed: ``REQUEUE_OPTIONS``), ``--time``, ``--gpus`` (the
    run's ``gpus_requested``, else ``defaults.gpus``; left out when 0),
    ``--partition`` and ``--account`` (when set), then each ``extra`` item.
    The body runs ``hx run --child <run_id>`` with this Python, so the node
    uses the same install as the login node (shared filesystem).

    Parameters
    ----------
    record : RunRecord
        A queued run.
    defaults : SlurmDefaults
        Partition, account, time limit, GPU count, and extra directives.
    home : Path
        The Hypothex home on the shared filesystem (absolute).

    Returns
    -------
    str
        The script text, ending in a newline.

    Raises
    ------
    SlurmError
        Unsafe settings (see ``validate_defaults``) or a run folder path with
        whitespace (``#SBATCH`` lines cannot hold it).

    Examples
    --------
    For run ``r1`` of project ``toy``, ``SlurmDefaults(partition="gpu")``, and
    home ``/h``, the script starts::

        #!/bin/bash
        #SBATCH --job-name=hx-r1
        #SBATCH --output=/h/store/toy/runs/r1/logs/slurm-%j.out
        #SBATCH --no-requeue
        #SBATCH --time=02:00:00
        #SBATCH --gpus=1
        #SBATCH --partition=gpu

        exec /path/to/python -m hypothex.cli.main --home /h run --child r1
    """
    validate_defaults(defaults)
    run_dir = Layout(home).run_dir(record.project, record.run_id)
    if any(ch.isspace() for ch in str(run_dir)):
        raise SlurmError(
            f"run folder {run_dir} contains whitespace, which #SBATCH --output cannot hold; "
            "use a Hypothex home path without spaces"
        )
    gpus = record.gpus_requested or defaults.gpus
    directives = [
        f"--job-name=hx-{record.run_id}",
        f"--output={run_dir / 'logs' / 'slurm-%j.out'}",
        "--no-requeue",
        f"--time={defaults.time}",
    ]
    if gpus > 0:
        directives.append(f"--gpus={gpus}")
    if defaults.partition is not None:
        directives.append(f"--partition={defaults.partition}")
    if defaults.account is not None:
        directives.append(f"--account={defaults.account}")
    directives.extend(defaults.extra)
    child = shlex.join(
        [sys.executable, "-m", "hypothex.cli.main", "--home", str(home)]
        + ["run", "--child", record.run_id]
    )
    lines = ["#!/bin/bash", *(f"#SBATCH {d}" for d in directives), "", f"exec {child}", ""]
    return "\n".join(lines)


class SlurmTimeout(SlurmError):
    """A SLURM command did not answer within ``SLURM_COMMAND_TIMEOUT``."""


class SubmitUnknownError(SlurmError):
    """``sbatch`` failed in a way that may still have created the job."""


SBATCH_REJECTIONS = (
    "invalid partition",
    "invalid account",
    "invalid qos",
    "invalid generic resource",
    "invalid feature specification",
    "invalid job array specification",
    "invalid --time specification",
    "invalid time limit",
    "invalid node name",
    "invalid wckey",
    "invalid numeric value",
    "requested node configuration is not available",
    "requested partition configuration not available",
    "requested time limit is invalid",
    "node count specification invalid",
    "memory specification can not be satisfied",
    "more processors requested than permitted",
    "job violates accounting/qos policy",
    "user's group not permitted to use this partition",
    "access/permission denied",
    "unrecognized option",
    "unrecognised option",
    "option requires an argument",
)
"""sbatch messages that prove SLURM refused the job (matched on ``sbatch: ...`` lines)."""
_JOB_ID = re.compile(r"^(\d+)(;\S+)?$")


def _exec(
    argv: list[str], *, input_text: str | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run one SLURM command and return how it ended (``SlurmError`` if it never ran)."""
    if shutil.which(argv[0]) is None:
        raise SlurmError(f"{argv[0]} not found on PATH; is this a SLURM login node?")
    try:
        return subprocess.run(
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=SLURM_COMMAND_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise SlurmTimeout(f"{argv[0]} timed out after {SLURM_COMMAND_TIMEOUT:.0f}s") from exc
    except OSError as exc:
        raise SlurmError(f"could not run {argv[0]}: {exc}") from exc


def _detail(out: subprocess.CompletedProcess[str]) -> str:
    return out.stderr.strip()[-500:] or out.stdout.strip()[-500:]


def _run(argv: list[str], *, input_text: str | None = None, cwd: Path | None = None) -> str:
    """Run one SLURM command; return stdout or raise ``SlurmError``."""
    out = _exec(argv, input_text=input_text, cwd=cwd)
    if out.returncode != 0:
        raise SlurmError(f"{shlex.join(argv)} failed (exit {out.returncode}): {_detail(out)}")
    return out.stdout


def _parsable_job_id(stdout: str) -> str | None:
    """The job id ``sbatch --parsable`` printed (``id`` or ``id;cluster``), or None."""
    lines = stdout.strip().splitlines()
    match = _JOB_ID.fullmatch(lines[-1].strip()) if lines else None
    return match.group(1) if match else None


def _rejected(stderr: str) -> bool:
    """True when sbatch's stderr names a recognised SLURM rejection."""
    for line in stderr.lower().splitlines():
        if line.startswith("sbatch:") and any(r in line for r in SBATCH_REJECTIONS):
            return True
    return False


def submit(script: str, cwd: Path, *, comment: str | None = None) -> str:
    """
    Submit a batch script with ``sbatch --parsable`` (script on stdin).

    Parameters
    ----------
    script : str
        The script text (see ``render_sbatch``).
    cwd : Path
        Directory sbatch runs in (the job's default working directory).
    comment : str, optional
        ``--comment`` for the job; ``submit_run`` passes its unique submission
        identity so a crash after ``sbatch`` can be matched to the job
        (``find_submitted``).

    Returns
    -------
    str
        The job id, e.g. ``"48213077"`` (a ``;cluster`` suffix is dropped).

    Raises
    ------
    SubmitUnknownError
        SLURM may have accepted the job: sbatch timed out, died by a signal,
        printed no job id (or garbage), printed one next to an error, or
        failed with a message that is not a recognised rejection. Never treat
        this as a rejection (``reconcile`` looks for the job by its comment).
    SlurmError
        SLURM refused the job, on positive evidence only: sbatch is missing,
        or it exited non-zero, printed no job id, and named a rejection from
        ``SBATCH_REJECTIONS``.
    """
    argv = ["sbatch", "--parsable"]
    if comment is not None:
        argv.append(f"--comment={comment}")
    try:
        out = _exec(argv, input_text=script, cwd=cwd)
    except SlurmTimeout as exc:
        raise SubmitUnknownError(f"{exc}; the job may exist") from exc
    job_id = _parsable_job_id(out.stdout)
    if out.returncode == 0 and job_id is not None:
        return job_id
    if out.returncode > 0 and job_id is None and _rejected(out.stderr):
        raise SlurmError(f"sbatch refused the job (exit {out.returncode}): {_detail(out)}")
    if out.returncode < 0:
        why = f"sbatch was killed by signal {-out.returncode}"
    elif out.returncode == 0:
        why = f"sbatch --parsable printed {out.stdout.strip()[-200:]!r}, not a job id"
    else:
        why = f"sbatch failed (exit {out.returncode}) without a known rejection: {_detail(out)}"
    raise SubmitUnknownError(f"{why}; the job may exist")


def _node(raw: str) -> str | None:
    return None if raw.strip() in _NO_NODE else raw.strip()


def _exit_code(raw: str) -> int | None:
    code, _, sig = raw.strip().partition(":")
    if not code.isdigit():
        return None
    if sig.isdigit() and int(sig) != 0:
        return 128 + int(sig)
    return int(code)


def poll(job_ids: list[str]) -> dict[str, SlurmJob]:
    """
    Look up jobs: first in ``squeue`` (queued or running), then in ``sacct``.

    ``squeue`` lists all of this user's jobs (``squeue -j`` fails on some
    SLURM versions once a job left the queue). Jobs not in the queue are
    looked up with ``sacct -X``. A failing ``sacct`` (for example accounting
    disabled) is logged and treated as "no record".

    Parameters
    ----------
    job_ids : list of str

    Returns
    -------
    dict of str to SlurmJob
        Only the jobs SLURM knows; a job that vanished from both is absent.

    Raises
    ------
    SlurmError
        If ``squeue`` fails: then nothing is known and callers must not
        conclude that jobs are gone.
    """
    if not job_ids:
        return {}
    wanted = set(job_ids)
    jobs: dict[str, SlurmJob] = {}
    queue = _run(
        ["squeue", "--noheader", f"--user={getpass.getuser()}", f"--format={SQUEUE_FORMAT}"]
    )
    for line in queue.splitlines():
        parts = line.strip().split("|")
        if len(parts) == 3 and parts[0] in wanted:
            jobs[parts[0]] = SlurmJob(job_id=parts[0], state=parts[1], node=_node(parts[2]))
    missing = [j for j in job_ids if j not in jobs]
    if not missing:
        return jobs
    try:
        acct = _run(
            [
                "sacct",
                "-X",
                "--noheader",
                "--parsable2",
                f"--format={SACCT_FORMAT}",
                f"--jobs={','.join(missing)}",
            ]
        )
    except SlurmError as exc:
        log.warning("sacct failed; treating jobs %s as unknown: %s", missing, exc)
        return jobs
    for line in acct.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 4 or parts[0] not in wanted or parts[0] in jobs:
            continue
        state = parts[1].split()[0] if parts[1].strip() else "UNKNOWN"
        jobs[parts[0]] = SlurmJob(
            job_id=parts[0], state=state, node=_node(parts[3]), exit_code=_exit_code(parts[2])
        )
    return jobs


def _sacct_job(line: str) -> SlurmJob | None:
    parts = line.strip().split("|")
    if len(parts) != 4 or not parts[0].isdigit():
        return None
    state = parts[1].split()[0] if parts[1].strip() else "UNKNOWN"
    return SlurmJob(
        job_id=parts[0], state=state, node=_node(parts[3]), exit_code=_exit_code(parts[2])
    )


def find_submitted(comment: str) -> tuple[SlurmJob | None, bool]:
    """
    Find the job that carries a submission's unique comment, if SLURM has one.

    ``submit_run`` records its intent (with a unique ``hx-<run_id>-<nonce>``
    comment) before it calls ``sbatch``. When the outcome is unknown (a crash,
    a timeout), this finds the job: in ``squeue`` (``%k``), else in ``sacct``
    (``Comment``), each filtered by exactly this comment. A job name alone
    never identifies a submission.

    Parameters
    ----------
    comment : str
        The comment the submission used.

    Returns
    -------
    tuple of (SlurmJob or None, bool)
        The job (the newest if several) and whether the answer is complete:
        True when both commands answered. ``(None, True)`` means SLURM has no
        such job; ``(None, False)`` means unknown (``sacct`` failed, or the
        cluster's accounting does not store job comments, so ``sacct`` cannot
        see them: ``comment_accounting``).

    Raises
    ------
    SlurmError
        If ``squeue`` fails (then nothing is known).
    """
    queue = _run(
        [
            "squeue",
            "--noheader",
            f"--user={getpass.getuser()}",
            f"--format={SQUEUE_COMMENT_FORMAT}",
        ]
    )
    for line in queue.splitlines():
        parts = line.strip().split("|", 3)
        if len(parts) == 4 and parts[3] == comment:
            return SlurmJob(job_id=parts[0], state=parts[1], node=_node(parts[2])), True
    if not comment_accounting():
        return None, False  # sacct keeps no comments here: its silence proves nothing
    try:
        acct = _run(
            [
                "sacct",
                "-X",
                "--noheader",
                "--parsable2",
                f"--format={SACCT_COMMENT_FORMAT}",
                "--starttime=now-7days",
            ]
        )
    except SlurmError as exc:
        log.warning("sacct failed; job with comment %s is not known yet: %s", comment, exc)
        return None, False
    jobs: list[SlurmJob] = []
    for line in acct.splitlines():
        row, _, found = line.strip().rpartition("|")
        job = _sacct_job(row) if found == comment else None
        if job is not None:
            jobs.append(job)
    return (max(jobs, key=lambda j: int(j.job_id)) if jobs else None), True


_COMMENT_ACCOUNTING: dict[str, bool] = {}
"""The answer of ``comment_accounting`` for this server's life (key ``"answer"``)."""


def _stores_job_comment(config: str) -> bool:
    """Read ``scontrol show config``: are job comments kept in accounting?"""
    for line in config.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "AccountingStoreFlags":
            return "job_comment" in {flag.strip().lower() for flag in value.split(",")}
        if key == "AccountingStoreJobComment":  # SLURM before 21.08
            return value.lower() in ("yes", "true", "1")
    return False


def comment_accounting(*, refresh: bool = False) -> bool:
    """
    Return True when SLURM's accounting stores job comments.

    Only then can ``sacct`` find a job by its ``--comment``, so only then can
    a missing comment prove that SLURM never took a submission. Probes
    ``scontrol show config`` (``AccountingStoreFlags`` containing
    ``job_comment``; older SLURM: ``AccountingStoreJobComment = Yes``) once
    per server start: ``SlurmPoller`` refreshes it when it starts. A failing
    probe answers False and is not cached.

    Parameters
    ----------
    refresh : bool
        Probe again instead of using the cached answer.

    Returns
    -------
    bool
    """
    if not refresh and "answer" in _COMMENT_ACCOUNTING:
        return _COMMENT_ACCOUNTING["answer"]
    try:
        config = _run(["scontrol", "show", "config"])
    except SlurmError as exc:
        log.warning("scontrol show config failed; job comments count as not stored: %s", exc)
        _COMMENT_ACCOUNTING.pop("answer", None)  # never cached: asked again next time
        return False
    answer = _stores_job_comment(config)
    _COMMENT_ACCOUNTING["answer"] = answer
    return answer


def reset_comment_accounting() -> None:
    """Forget the cached ``comment_accounting`` answer (a new server start, or a test)."""
    _COMMENT_ACCOUNTING.clear()


def cancel(job_id: str) -> None:
    """
    Cancel a job with ``scancel``.

    Parameters
    ----------
    job_id : str

    Raises
    ------
    SlurmError
        scancel is missing or fails (for example the job already left the queue).
    """
    _run(["scancel", job_id])


def lost_reason(job_id: str, job: SlurmJob | None) -> str:
    """
    Explain why a run whose SLURM job ended without an exit record is lost.

    Parameters
    ----------
    job_id : str
    job : SlurmJob or None
        The ``sacct`` record; None when SLURM has none.

    Returns
    -------
    str

    Examples
    --------
    >>> lost_reason("7", SlurmJob(job_id="7", state="NODE_FAIL", node="n2"))
    'SLURM ended job 7 with NODE_FAIL on n2; no exit record'
    >>> lost_reason("7", None)
    'slurm job 7 left the queue; SLURM reports no end state for it; no exit record'
    """
    if job is None:  # neutral: no accounting record (or sacct failed); the cause is not known
        return (
            f"slurm job {job_id} left the queue; SLURM reports no end state for it; no exit record"
        )
    where = f" on {job.node}" if job.node else ""
    code = f" (exit {job.exit_code})" if job.exit_code is not None else ""
    return f"SLURM ended job {job_id} with {job.state}{where}{code}; no exit record"


def _visible_gpus(env: Mapping[str, str], fallback: int) -> list[int]:
    raw = env.get("CUDA_VISIBLE_DEVICES", "").strip()
    if not raw:
        return list(range(max(fallback, 0)))
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if all(p.isdigit() for p in parts):
        return [int(p) for p in parts]
    return list(range(len(parts)))  # GPU UUIDs: only the count is meaningful


def flock_supported(home: Path) -> bool:
    """
    Tell whether ``flock`` works on the filesystem that holds ``home``.

    Parameters
    ----------
    home : Path
        The Hypothex home (created if missing; the probe file is
        ``<home>/.flock-probe``).

    Returns
    -------
    bool
        False when ``flock`` answers ``ENOSYS``, ``ENOLCK``, or ``EOPNOTSUPP``
        (Lustre mounted without ``-o flock``, some NFS setups).
    """
    home.mkdir(parents=True, exist_ok=True)
    fd = os.open(home / FLOCK_PROBE, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError as exc:
        if exc.errno in NO_FLOCK_ERRNOS:
            return False
        raise
    finally:
        os.close(fd)
    return True


def require_flock(home: Path) -> None:
    """
    Refuse a SLURM home whose filesystem has no ``flock``.

    Every run-state write (the login node's API, ``sbatch`` submission,
    ``scancel``, the poller, and ``hx run --child`` on the node) takes the run
    lock, so a SLURM env server needs ``flock`` on its home.

    Parameters
    ----------
    home : Path

    Raises
    ------
    ConfigError
        ``flock`` does not work there.
    """
    if not flock_supported(home):
        raise ConfigError(
            f"{home} does not support flock, which a SLURM env server needs for its run "
            "locks; mount it with flock (Lustre: -o flock) or set home: in "
            "environments.yaml to a shared path that has it"
        )


class _NodeIndex:
    """Stand-in for the SQLite index on a compute node: nothing is indexed there."""

    def get_run(self, run_id: str) -> None:
        """Always None: the node finds runs by folder (``RunStore.find_project_of``)."""
        return None

    def upsert_run(self, record: RunRecord) -> None:
        """Do nothing; the login node indexes the run when it reads ``run.yaml``."""

    def upsert_project(self, entry: object) -> None:
        """Do nothing; projects are registered on the login node."""

    def replace_metric_points(self, run_id: str, points: object) -> None:
        """Do nothing; the login node indexes ``metrics.jsonl`` when it syncs the run."""

    def add_score(self, run_id: str, score: object) -> None:
        """Do nothing; finished runs are scored on the login node."""


class _NodeEvents:
    """Stand-in for the SQLite event log on a compute node: no events are written there."""

    def append(self, event_type: str, **fields: Any) -> None:
        """Do nothing; the login node emits the run's events (``sync_node_run``)."""


@dataclass
class NodeContext(Context):
    """
    The run-folder-only ``Context`` that ``hx run --child`` uses on a compute node.

    SQLite in WAL mode does not work across hosts on NFS, Lustre, or GPFS. So
    the node never opens ``index.db`` or
    ``events.db``: it writes only run-folder files (atomic ``run.yaml``,
    ``logs/``, ``metrics.jsonl``, and the exit record ``exit.json``). Only the
    env server process on the login node opens the SQLite files; its
    ``SlurmPoller`` reads the node's ``run.yaml`` changes and emits
    ``run.started`` / ``run.finished`` / ``run.failed`` / ``run.killed`` and
    updates the index (``sync_node_run``).

    Every update also sets the SLURM executor fields: ``execute_run`` keeps the
    fields recorded before start (``type``, ``slurm_job_id``, ``host``), but the
    node name and the GPU indices are known only here.

    Examples
    --------
    >>> ctx = NodeContext.open_node(Path("~/.hypothex"), node="n7")  # doctest: +SKIP
    """

    job_id: str | None = None
    node: str | None = None
    gpus: list[int] | None = None

    @classmethod
    def open_node(
        cls,
        home: Path,
        *,
        job_id: str | None = None,
        node: str | None = None,
        gpus: list[int] | None = None,
    ) -> NodeContext:
        """
        Open a home for run-folder writes only (no index, no event log).

        Parameters
        ----------
        home : Path
            The Hypothex home on the shared filesystem.
        job_id, node : str, optional
            ``SLURM_JOB_ID`` and the node name.
        gpus : list of int, optional
            GPU indices visible to the job.

        Returns
        -------
        NodeContext
        """
        layout = Layout(home.expanduser().resolve())
        return cls(
            layout=layout,
            store=RunStore(layout),
            index=cast(Index, _NodeIndex()),
            events=cast(EventLog, _NodeEvents()),
            descriptor=load_descriptor(layout),
            job_id=job_id,
            node=node,
            gpus=gpus,
        )

    def find_record(self, run_id: str) -> RunRecord:
        """
        Read a run's record from its folder (no index lookup).

        Parameters
        ----------
        run_id : str

        Returns
        -------
        RunRecord
        """
        return self.store.read_record(self.store.find_project_of(run_id), run_id)

    def create_run(self, record: RunRecord) -> RunRecord:
        """
        Refuse: runs are created on the login node.

        Parameters
        ----------
        record : RunRecord

        Raises
        ------
        RunError
            Always.
        """
        raise RunError(f"a compute node never creates runs ({record.run_id})")

    def update_run(
        self,
        run_id: str,
        event_type: str,
        mutate: Callable[[RunRecord], RunRecord],
        payload: dict[str, Any] | None = None,
    ) -> RunRecord:
        """
        Apply ``mutate`` and the SLURM executor fields, then write ``run.yaml`` only.

        No event is emitted and nothing is indexed here; the login node does
        both when its poller sees the new ``run.yaml``.

        Parameters
        ----------
        run_id : str
        event_type : str
            Ignored on the node (the login node picks the event from the status).
        mutate : callable
        payload : dict, optional
            Ignored on the node.

        Returns
        -------
        RunRecord
        """
        project = self.store.find_project_of(run_id)
        with run_lock(self.layout.run_dir(project, run_id)):
            current = self.store.read_record(project, run_id)
            updated = mutate(current)
            executor = updated.executor.model_copy(
                update={
                    "type": SLURM_EXECUTOR,
                    "slurm_job_id": current.executor.slurm_job_id or self.job_id,
                    "node": self.node or current.executor.node,
                    "gpus": self.gpus if self.gpus is not None else current.executor.gpus,
                    "host": current.executor.host,
                }
            )
            updated = updated.model_copy(update={"executor": executor})
            self.store.write_record(updated)  # atomic rename
        return updated

    def add_score(self, record: RunRecord, score: ScoreRecord) -> None:
        """
        Refuse: finished runs are scored on the login node (``sync_node_run``).

        Parameters
        ----------
        record : RunRecord
        score : ScoreRecord

        Raises
        ------
        RunError
            Always.
        """
        raise RunError(f"a compute node never scores runs ({record.run_id})")

    def emit(
        self, event_type: str, record: RunRecord, payload: dict[str, Any] | None = None
    ) -> None:
        """
        Drop an informational event (the node has no event log).

        Parameters
        ----------
        event_type : str
        record : RunRecord
        payload : dict, optional
        """


def run_child(
    home: Path,
    run_id: str,
    *,
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
) -> RunRecord:
    """
    Execute a submitted run inside its SLURM job (``hx run --child``).

    Reads ``SLURM_JOB_ID``, ``SLURMD_NODENAME`` (else the hostname), and
    ``CUDA_VISIBLE_DEVICES`` (else ``gpus_requested`` indices) and records
    them in ``executor`` for the whole run. Uses a :class:`NodeContext`: no
    SQLite file is opened on the compute node. Scoring is left to the login
    node, so the git worktree of a pinned run is kept here; the login node
    removes it once it published the end (``sync_node_run``). At the end the
    exit record ``exit.json`` (``status``, ``exit_code``, ``ended_at``) is
    written next to ``run.yaml``.

    Parameters
    ----------
    home : Path
        The Hypothex home (shared with the login node).
    run_id : str
        A ``queued`` run.
    stdout_sink, stderr_sink : binary file, optional
        Where to echo the command's output (the job's ``slurm-%j.out``).

    Returns
    -------
    RunRecord
        The final record.

    Raises
    ------
    RunError
        If the run is not queued.
    """
    env = os.environ
    ctx = NodeContext.open_node(
        home,
        job_id=env.get("SLURM_JOB_ID"),
        node=env.get("SLURMD_NODENAME") or socket.gethostname(),
    )
    ctx.gpus = _visible_gpus(env, ctx.find_record(run_id).gpus_requested)
    final = execute_run(
        ctx, run_id, stdout_sink=stdout_sink, stderr_sink=stderr_sink, auto_evaluate=False
    )
    exit_record = {
        "run_id": final.run_id,
        "status": final.status.value,
        "exit_code": final.exit_code,
        "ended_at": (final.ended_at or utcnow()).isoformat(),
    }
    atomic_write_text(ctx.run_dir(final) / EXIT_FILE, json.dumps(exit_record))
    return final


def _end(status: RunStatus) -> Callable[[RunRecord], RunRecord]:
    def mutate(r: RunRecord) -> RunRecord:
        if r.status in TERMINAL_STATUSES:
            return r
        return r.model_copy(update={"status": status, "ended_at": utcnow()})

    return mutate


def _outbox_path(layout: Layout, run_id: str) -> Path:
    return layout.home / OUTBOX_DIR / f"{run_id}.json"


def _outbox_lock(layout: Layout) -> contextlib.AbstractContextManager[None]:
    return dir_lock(layout.home / OUTBOX_DIR)


def _done(entry: dict[str, Any]) -> bool:
    """
    An entry can go: terminal status published, job known, no cancel or node end pending.

    A ``lost`` run's entry stays while it holds ``lost_at`` (``LOST_RECHECK_SECONDS``).
    """
    try:
        published = RunStatus(entry["published"])
    except (KeyError, ValueError):
        return False
    return (
        published in TERMINAL_STATUSES
        and entry.get("state") == "submitted"
        and not entry.get("cancel_requested")
        and not entry.get("node_end_pending")
        and not entry.get("lost_at")
    )


def track_slurm_run(
    layout: Layout,
    record: RunRecord,
    *,
    comment: str | None = None,
    submitter: dict[str, Any] | None = None,
) -> None:
    """
    Put a SLURM run in this login node's outbox.

    The entry holds the submission intent (``state``, ``comment``, the
    submitting process, ``intent_at``), a stop that came before the job id
    (``cancel_requested``), and ``published``: the last status the login node
    published as an event. ``reconcile`` walks the outbox, not the index, so
    nothing the compute node writes is ever skipped (Task 29).

    Parameters
    ----------
    layout : Layout
    record : RunRecord
        The run; its current status is what the index already shows.
    comment : str, optional
        The ``--comment`` given to ``sbatch``.
    submitter : dict, optional
        ``{"pid", "create_time"}`` of the process that calls ``sbatch``.
    """
    job_id = record.executor.slurm_job_id
    entry = {
        "run_id": record.run_id,
        "state": "submitted" if job_id else "pending",
        "job_id": job_id,
        "comment": comment,
        "submitter": submitter,
        "intent_at": utcnow().isoformat(),
        "cancel_requested": False,
        "published": record.status.value,
    }
    with _outbox_lock(layout):
        atomic_write_text(_outbox_path(layout, record.run_id), json.dumps(entry))


def _intent(layout: Layout, run_id: str) -> dict[str, Any] | None:
    try:
        entry = json.loads(_outbox_path(layout, run_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def _update_intent(layout: Layout, run_id: str, **fields: Any) -> dict[str, Any] | None:
    """Change an outbox entry under the outbox lock; it is removed once done."""
    path = _outbox_path(layout, run_id)
    with _outbox_lock(layout):
        entry = _intent(layout, run_id)
        if entry is None:
            return None
        entry.update(fields)
        if _done(entry):
            path.unlink(missing_ok=True)
        else:
            atomic_write_text(path, json.dumps(entry))
    return entry


def _drop_intent(layout: Layout, run_id: str) -> None:
    with _outbox_lock(layout):
        _outbox_path(layout, run_id).unlink(missing_ok=True)


def read_outbox(layout: Layout) -> list[dict[str, Any]]:
    """
    Return the outbox entries, oldest run id first; unreadable ones are skipped.

    Parameters
    ----------
    layout : Layout

    Returns
    -------
    list of dict
    """
    folder = layout.home / OUTBOX_DIR
    entries: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            RunStatus(entry["published"])
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("skipping unreadable SLURM outbox entry %s", path)
            continue
        entries.append(entry)
    return entries


def mark_published(layout: Layout, record: RunRecord) -> None:
    """
    Record that the login node published ``record.status``.

    The entry goes once that status is terminal and the submission is settled
    (job known, no cancel pending); else ``reconcile`` keeps working on it.

    Parameters
    ----------
    layout : Layout
    record : RunRecord
    """
    _update_intent(layout, record.run_id, published=record.status.value)


def _as_slurm(host: str) -> Callable[[RunRecord], RunRecord]:
    """Mark a run as a SLURM run before ``sbatch`` (its pids are no longer local)."""

    def mutate(r: RunRecord) -> RunRecord:
        update: dict[str, Any] = {"type": SLURM_EXECUTOR, "host": r.executor.host or host}
        if r.status == RunStatus.QUEUED:
            update.update(pid=None, pid_create_time=None, child_pid=None)
        return r.model_copy(update={"executor": r.executor.model_copy(update=update)})

    return mutate


def _with_job(job_id: str) -> Callable[[RunRecord], RunRecord]:
    def mutate(r: RunRecord) -> RunRecord:
        update = {"type": SLURM_EXECUTOR, "slurm_job_id": r.executor.slurm_job_id or job_id}
        return r.model_copy(update={"executor": r.executor.model_copy(update=update)})

    return mutate


def _end_if_active(
    ctx: Context,
    run_id: str,
    event_type: str,
    mutate: Callable[[RunRecord], RunRecord],
    payload: dict[str, Any],
    *,
    replaces: frozenset[RunStatus] = frozenset(),
) -> RunRecord | None:
    """
    End an active SLURM run and emit ``event_type``; None when it had already ended.

    ``replaces`` names end statuses this end may still overwrite (``lost``,
    the login node's guess, which the node's own exit record corrects).

    ``Context.update_run`` emits its event even when ``mutate`` keeps a record
    that the compute node ended first (a ``run.lost`` carrying ``finished``).
    Here the check, the write, the event, and the index update happen under
    the run lock, and nothing is written or emitted for a run that ended: the
    caller then publishes the node's own end (``sync_node_run``, Task 29).
    """
    project = ctx.find_record(run_id).project
    with run_lock(ctx.layout.run_dir(project, run_id)):
        current = ctx.store.read_record(project, run_id)
        if current.status in TERMINAL_STATUSES and current.status not in replaces:
            return None
        ended = mutate(current)
        ctx.store.write_record(ended)
        ctx.events.append(
            event_type,
            project=project,
            run_id=run_id,
            payload={"status": ended.status.value, **payload},
        )
        ctx.index.upsert_run(ended)
    return ended


def _fail_submission(ctx: Context, record: RunRecord, exc: SlurmError) -> RunError:
    """SLURM rejected the job for sure: fail the run and forget the intent."""
    with _publish_lock(ctx.run_dir(record)):
        failed = _end_if_active(
            ctx, record.run_id, "run.failed", _end(RunStatus.FAILED), {"reason": f"sbatch: {exc}"}
        )
        if failed is not None:  # no job ever ran in the checkout
            release_worktree(ctx, failed)
        _drop_intent(ctx.layout, record.run_id)
    return RunError(f"could not submit run {record.run_id} to SLURM: {exc}")


def _cancel_requested(ctx: Context, run_id: str, job_id: str) -> bool:
    """
    ``scancel`` a job whose run was stopped before its job id was known.

    Returns True once the job is cancelled or already ended (``cancel_requested``
    is cleared then); False to try again on the next poll.
    """
    try:
        cancel(job_id)
    except SlurmError as exc:
        try:
            job = poll([job_id]).get(job_id)
        except SlurmError:
            return False
        if job is not None and not is_finished(job):
            log.warning("run %s: could not cancel slurm job %s yet: %s", run_id, job_id, exc)
            return False
    _update_intent(ctx.layout, run_id, cancel_requested=False)
    return True


def _record_job(ctx: Context, run_id: str, job_id: str, *, recovered: bool = False) -> RunRecord:
    """
    Record a submission's job id; carry out a stop that arrived before it.

    The intent is updated under the outbox lock, and a stop sets
    ``cancel_requested`` under the same lock (``stop_slurm_run``, Task 30), so
    exactly one of them cancels the job.
    """
    entry = _update_intent(ctx.layout, run_id, state="submitted", job_id=job_id)
    payload: dict[str, Any] = {"slurm_job_id": job_id}
    if recovered:
        payload["recovered"] = True
    record = ctx.update_run(run_id, "run.submitted", _with_job(job_id), payload)
    if entry is not None and entry.get("cancel_requested"):
        _cancel_requested(ctx, run_id, job_id)
    return record


def submit_run(ctx: Context, record: RunRecord, defaults: SlurmDefaults) -> RunRecord:
    """
    Submit a queued run as a SLURM job and record the job id.

    The intent is written before ``sbatch`` runs: the outbox entry (state
    ``pending``, a unique comment ``hx-<run_id>-<nonce>``, this process) and
    ``run.submitting``, which marks the run as a SLURM run. Then:

    - a job id: recorded (``run.submitted``); a stop that came first is
      carried out now (``scancel``);
    - an unknown outcome (sbatch timed out, a communication error, no job
      id): state ``unknown``, event ``run.submit_unknown``, and the run stays
      ``queued``; ``reconcile`` finds the job by its comment, or fails the run
      once SLURM provably never took it;
    - a rejection: the run is ``failed`` and ``RunError`` is raised;
    - any other error (a busy index, an undecodable ``sbatch`` answer): the
      intent becomes ``unknown`` like a timeout, since this process outlives
      the call and ``reconcile`` would otherwise wait for it, and the error
      propagates.

    The script is saved as ``<run_dir>/slurm.sbatch``. The run stays
    ``queued`` until ``hx run --child`` starts on the node.

    Parameters
    ----------
    ctx : Context
    record : RunRecord
        A run just created by ``prepare_run``.
    defaults : SlurmDefaults

    Returns
    -------
    RunRecord
        The run with ``executor.type == "slurm"`` (and ``executor.slurm_job_id``
        unless the outcome is unknown).

    Raises
    ------
    RunError
        SLURM rejected the job; the run is then recorded as ``failed``.
    """
    run_dir = ctx.run_dir(record)
    try:
        script = render_sbatch(record, defaults, ctx.layout.home)
    except SlurmError as exc:
        raise _fail_submission(ctx, record, exc) from exc
    atomic_write_text(run_dir / SBATCH_FILE, script)
    atomic_write_text(run_dir / SLURM_SETTINGS_FILE, defaults.model_dump_json())
    comment = f"hx-{record.run_id}-{secrets.token_hex(4)}"
    me = os.getpid()
    submitter = {"pid": me, "create_time": process_create_time(me)}
    track_slurm_run(ctx.layout, record, comment=comment, submitter=submitter)
    try:
        ctx.update_run(
            record.run_id, "run.submitting", _as_slurm(ctx.descriptor.label), {"comment": comment}
        )
        try:
            job_id = submit(script, Path(record.cwd), comment=comment)
        except SubmitUnknownError as exc:
            # sbatch may have accepted it: never a rejection. reconcile resolves it by comment
            _update_intent(ctx.layout, record.run_id, state="unknown")
            current = ctx.find_record(record.run_id)
            ctx.emit("run.submit_unknown", current, {"reason": str(exc)[:500], "comment": comment})
            return current
        except SlurmError as exc:
            raise _fail_submission(ctx, record, exc) from exc
        return _record_job(ctx, record.run_id, job_id)
    except Exception:
        # any other error (a busy index, an undecodable sbatch answer): this process lives
        # on, so a `pending` intent would never settle; reconcile resolves it by comment
        _settle_pending(ctx.layout, record.run_id)
        raise


def _settle_pending(layout: Layout, run_id: str) -> None:
    """Mark a ``pending`` intent ``unknown``: its ``sbatch`` call is over, outcome unseen."""
    with _outbox_lock(layout):
        entry = _intent(layout, run_id)
        if entry is not None and entry.get("state") == "pending":
            entry["state"] = "unknown"
            atomic_write_text(_outbox_path(layout, run_id), json.dumps(entry))


def run_slurm_settings(run_dir: Path) -> SlurmDefaults | None:
    """
    Return the SLURM settings a run was submitted with.

    Parameters
    ----------
    run_dir : Path
        The run folder.

    Returns
    -------
    SlurmDefaults or None
        ``<run_dir>/slurm.json``, or None for a run that was not submitted to
        SLURM (no such file).

    Raises
    ------
    RunError
        The file exists but cannot be read or is not valid settings.
    """
    return _read_settings(run_dir / SLURM_SETTINGS_FILE)


def _read_settings(path: Path) -> SlurmDefaults | None:
    """Read a settings file: None when absent; RunError when present but bad."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("cannot read SLURM settings %s: %s", path, exc)
        raise RunError(f"cannot read SLURM settings {path}: {exc}") from exc
    try:
        return SlurmDefaults.model_validate_json(text)
    except ValueError as exc:
        log.warning("invalid SLURM settings %s: %s", path, exc)
        raise RunError(
            f"invalid SLURM settings in {path}; fix or delete the file: {str(exc)[:300]}"
        ) from exc


def remember_slurm_defaults(layout: Layout, defaults: SlurmDefaults) -> None:
    """
    Save the settings a launch sent, for later launches that send none.

    An env server never sees the hub's ``environments.yaml``; the hub sends
    its ``slurm:`` block with every launch, and this keeps the latest one.

    Parameters
    ----------
    layout : Layout
    defaults : SlurmDefaults
    """
    atomic_write_text(layout.home / LAST_SLURM_DEFAULTS, defaults.model_dump_json())


def last_slurm_defaults(layout: Layout) -> SlurmDefaults | None:
    """
    Return the settings :func:`remember_slurm_defaults` saved last.

    Parameters
    ----------
    layout : Layout

    Returns
    -------
    SlurmDefaults or None
        None when no launch has sent settings yet (no such file).

    Raises
    ------
    RunError
        The file exists but cannot be read or is not valid settings.
    """
    return _read_settings(layout.home / LAST_SLURM_DEFAULTS)


def _exit_fields(data: object) -> dict[str, Any] | str:
    """The checked fields of an exit record, or why it cannot be used."""
    if not isinstance(data, dict):
        return "not a JSON object"
    try:
        status = RunStatus(data.get("status"))
    except ValueError:
        return f"status {data.get('status')!r} is not a run status"
    if status not in TERMINAL_STATUSES:
        return f"status {status.value!r} is not an end status"
    exit_code = data.get("exit_code")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        return f"exit_code {exit_code!r} is not an integer"
    raw = data.get("ended_at")
    ended_at: datetime | None = None
    if raw is not None:
        try:
            ended_at = datetime.fromisoformat(raw) if isinstance(raw, str) else None
        except ValueError:
            ended_at = None
        if ended_at is None:
            return f"ended_at {raw!r} is not an ISO 8601 time"
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=UTC)
    return {"status": status, "exit_code": exit_code, "ended_at": ended_at}


def _read_exit(run_dir: Path) -> dict[str, Any] | None:
    """
    The node's exit record, checked: ``status`` (an end status), ``exit_code``, ``ended_at``.

    None when there is none, and (with a warning) when it cannot be used: a
    bad record must never stop the poll at this run (or at the runs after it).
    """
    path = run_dir / EXIT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("ignoring unreadable exit record %s: %s", path, exc)
        return None
    fields = _exit_fields(data)
    if isinstance(fields, str):
        log.warning("ignoring exit record %s: %s", path, fields)
        return None
    return fields


def _apply_exit(exit_record: dict[str, Any]) -> Callable[[RunRecord], RunRecord]:
    """Apply the node's exit record to an active run, or over a login-node ``lost``."""

    def mutate(r: RunRecord) -> RunRecord:
        if r.status in TERMINAL_STATUSES and r.status != RunStatus.LOST:
            return r
        return r.model_copy(
            update={
                "status": exit_record["status"],
                "exit_code": exit_record["exit_code"],
                "ended_at": exit_record["ended_at"] or utcnow(),
            }
        )

    return mutate


PUBLISH_LOCK = ".publish.lock"
"""Lock file in a SLURM run's folder held while the login node publishes its status."""
_PUBLISH_HELD = threading.local()


@contextlib.contextmanager
def _publish_lock(run_dir: Path) -> Iterator[None]:
    """
    Serialize publishing one run's status, across threads and processes.

    The poller and a stop request can publish the same run at once; each
    reads the outbox cursor, emits, and moves the cursor under this lock, so
    an end is emitted once. Re-entrant within a thread. Lock order: this
    lock, then the run lock, then the outbox lock.
    """
    held: set[str] = _PUBLISH_HELD.__dict__.setdefault("paths", set())
    key = str(run_dir)
    if key in held:
        yield
        return
    with (run_dir / PUBLISH_LOCK).open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def sync_node_run(ctx: Context, current: RunRecord) -> RunRecord | None:
    """
    Publish what the compute node wrote to a SLURM run's folder (login node only).

    The node never opens ``index.db`` or ``events.db`` (Task 27). Here the env
    server emits the event for the node's new status, updates the index and
    the metric points, scores a finished task run, and then removes the git
    worktree of an ended pinned run (``release_worktree``). All of it happens
    under the run's publication lock, with ``run.yaml`` and the outbox cursor
    (``published``: the status the login node last published, whatever the
    index shows) read again under it, so two threads never publish one
    status twice. A run without an outbox entry counts as published.

    Parameters
    ----------
    ctx : Context
        The env server's full context.
    current : RunRecord
        The run (read again from ``run.yaml`` under the lock).

    Returns
    -------
    RunRecord or None
        The run when its status was published, else None.
    """
    with _publish_lock(ctx.run_dir(current)):
        return _sync_node_run(ctx, ctx.store.read_record(current.project, current.run_id))


def _sync_node_run(ctx: Context, current: RunRecord) -> RunRecord | None:
    """``sync_node_run``'s body; the caller holds the publication lock."""
    seen = _published(ctx.layout, current)
    changed = False
    if current.status in ACTIVE_STATUSES or current.status == RunStatus.LOST:
        exit_record = _read_exit(ctx.run_dir(current))
        if exit_record is not None and exit_record["status"] != current.status:
            # run.yaml lost the node's last write (or the login node wrote lost over it
            # while a shared filesystem hid it); the exit record wins
            status = exit_record["status"].value
            applied = _end_if_active(
                ctx,
                current.run_id,
                f"run.{status}",
                _apply_exit(exit_record),
                {"exit_code": exit_record["exit_code"], "source": "exit.json"},
                replaces=frozenset({RunStatus.LOST}),
            )
            if applied is not None:
                current, seen, changed = applied, applied.status, True
            else:  # ended meanwhile: the terminal record is published below
                current = ctx.find_record(current.run_id)
    if current.status != seen:
        event = (
            "run.started" if current.status == RunStatus.RUNNING else f"run.{current.status.value}"
        )
        payload: dict[str, Any] = {"status": current.status.value, "source": "node"}
        if current.exit_code is not None:
            payload["exit_code"] = current.exit_code
        ctx.events.append(event, project=current.project, run_id=current.run_id, payload=payload)
        ctx.index.upsert_run(current)
        changed = True
    if changed or current.status == RunStatus.RUNNING:
        points = ctx.store.read_metric_points(current.project, current.run_id)
        ctx.index.replace_metric_points(current.run_id, points)
    scored = bool(ctx.store.read_scores(current.project, current.run_id))
    if changed and current.status == RunStatus.FINISHED and current.task and not scored:
        score_finished_run(ctx, current)  # the node never scores (auto_evaluate=False)
    if current.status in TERMINAL_STATUSES:
        release_worktree(ctx, current)  # after scoring, which reads the checkout
    if changed or current.status in TERMINAL_STATUSES:
        mark_published(ctx.layout, current)  # last: a crash before it publishes again
    return current if changed else None


def _published(layout: Layout, current: RunRecord) -> RunStatus:
    """The status the login node last published for a run (its outbox entry's cursor)."""
    entry = _intent(layout, current.run_id)
    try:
        return RunStatus(entry["published"]) if entry is not None else current.status
    except (KeyError, ValueError):
        return current.status


def _publish_node_end(ctx: Context, run_id: str) -> RunRecord:
    """A requested end lost the race with the node: publish the node's own end instead."""
    current = ctx.find_record(run_id)
    return sync_node_run(ctx, current) or ctx.find_record(run_id)


UNRESOLVED_SUBMISSION = "submission outcome unknown; check squeue/sacct"
"""Shown on a run whose submission no lookup can settle (no comment accounting)."""


def _intent_age(entry: dict[str, Any], key: str = "intent_at") -> float:
    """Seconds since the outbox entry's ``key`` time; infinite when it is missing or bad."""
    try:
        return (utcnow() - datetime.fromisoformat(entry[key])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return float("inf")


def _resolve_intent(ctx: Context, entry: dict[str, Any], current: RunRecord) -> RunRecord | None:
    """
    Settle a submission whose job id is not known, by its comment only.

    A job carrying the comment is recorded. The run fails, and the intent is
    dropped, only when SLURM provably never took the job: both ``squeue`` and
    ``sacct`` answered without it, its ``sbatch`` call is over (a ``pending``
    intent counts as over once its submitter is dead or
    ``PENDING_STALE_SECONDS`` passed), and ``SUBMIT_SETTLE_SECONDS`` passed
    since the intent. Anything less leaves the intent for the next poll. When
    the node ended the run meanwhile, its end is published instead of a
    failure, and only then is the intent dropped. Without comment accounting
    the answer is never complete: the run stays ``unknown`` and gets one
    ``run.submit_unknown`` event naming ``UNRESOLVED_SUBMISSION``; but a run
    that already ended (a stop) is forgotten once ``squeue`` still lacks the
    job after the settle window, as nothing is left to cancel.
    """
    run_id = current.run_id
    comment = entry.get("comment")
    if not comment:
        return None
    try:
        job, complete = find_submitted(comment)
    except SlurmError as exc:
        log.warning("run %s: squeue failed; submission still unknown: %s", run_id, exc)
        return None
    if job is not None:
        return _record_job(ctx, run_id, job.job_id, recovered=True)
    if entry.get("state") == "pending":
        submitter = entry.get("submitter") or {}
        alive = process_alive(submitter.get("pid"), submitter.get("create_time"))
        if alive and _intent_age(entry) < PENDING_STALE_SECONDS:
            return None  # sbatch may still answer it
        entry = _update_intent(ctx.layout, run_id, state="unknown") or entry
    if _intent_age(entry) < SUBMIT_SETTLE_SECONDS:
        return None
    if not complete:
        if current.status in TERMINAL_STATUSES:
            # stopped (or ended) and still not in squeue after the settle window: the job
            # can never start now, so nothing is left to cancel; publish, then forget it
            with _publish_lock(ctx.run_dir(current)):
                published = sync_node_run(ctx, current)
                _drop_intent(ctx.layout, run_id)
            return published
        if not comment_accounting() and not entry.get("unresolved_notice"):
            _update_intent(ctx.layout, run_id, unresolved_notice=True)
            ctx.emit(
                "run.submit_unknown",
                current,
                {"reason": UNRESOLVED_SUBMISSION, "comment": comment, "comment_accounting": False},
            )
        return None
    with _publish_lock(ctx.run_dir(current)):
        failed = _end_if_active(
            ctx,
            run_id,
            "run.failed",
            _end(RunStatus.FAILED),
            {
                "reason": f"sbatch never accepted job hx-{run_id}: "
                f"no job with comment {comment} in squeue or sacct"
            },
        )
        if failed is None:  # the node ended it first: publish that end, never drop it unseen
            failed = _publish_node_end(ctx, run_id)
        else:  # SLURM never took the job, so nothing ran in the checkout
            release_worktree(ctx, failed)
        _drop_intent(ctx.layout, run_id)  # after the end: a crash in between only repeats it
    return failed


def _tracked_slurm_runs(
    ctx: Context,
) -> tuple[list[tuple[str, RunRecord]], list[RunRecord]]:
    """
    Sync every outbox run from its folder; return (job id, run) pairs to poll and changes.

    One run's failure (a bad record, a store error) is logged and skipped: it
    never stops the runs after it, and its entry stays for the next poll.
    """
    found: list[tuple[str, RunRecord]] = []
    changed: list[RunRecord] = []
    for entry in read_outbox(ctx.layout):
        try:
            pair = _track_entry(ctx, entry, changed)
        except HypothexError as exc:
            log.warning(
                "SLURM run %s: sync failed; trying again next poll: %s", entry.get("run_id"), exc
            )
            continue
        except Exception:
            log.exception("SLURM run %s: sync failed; trying again next poll", entry.get("run_id"))
            continue
        if pair is not None:
            found.append(pair)
    return sorted(found, key=lambda pair: pair[1].run_id), changed


def _track_entry(
    ctx: Context, entry: dict[str, Any], changed: list[RunRecord]
) -> tuple[str, RunRecord] | None:
    """Sync one outbox run (changes go to ``changed``); its (job id, run) when it needs a poll."""
    run_id = str(entry["run_id"])
    try:
        current = ctx.find_record(run_id)
    except RunNotFoundError:  # the run is gone; any other store error keeps the entry
        _drop_intent(ctx.layout, run_id)
        return None
    if current.environment_id != ctx.descriptor.environment_id:
        _drop_intent(ctx.layout, run_id)
        return None
    published = sync_node_run(ctx, current)
    if published is not None:
        changed.append(published)
        current = published
    if entry.get("lost_at"):  # marked lost: the sync above publishes a late node end
        late = current.status != RunStatus.LOST
        if late or _intent_age(entry, "lost_at") >= LOST_RECHECK_SECONDS:
            _update_intent(ctx.layout, run_id, lost_at=None)  # done: the entry goes
        return None
    job_id = entry.get("job_id") or current.executor.slurm_job_id
    if job_id is None:
        resolved = _resolve_intent(ctx, entry, current)
        if resolved is not None:
            changed.append(resolved)
        return None  # tracked from the next poll on
    if entry.get("state") != "submitted":  # the node's run.yaml names the job
        entry = _update_intent(ctx.layout, run_id, state="submitted", job_id=job_id) or entry
    if current.executor.slurm_job_id is None:
        # the submitter died between the outbox write and run.yaml (``_record_job``)
        current = _record_job(ctx, run_id, job_id, recovered=True)
        changed.append(current)
        if entry.get("cancel_requested"):
            return None  # ``_record_job`` carried out the stop (or the next poll retries it)
    if entry.get("cancel_requested"):
        _cancel_requested(ctx, run_id, job_id)
        return None
    if entry.get("node_end_pending") and current.status in TERMINAL_STATUSES:
        if (ctx.run_dir(current) / EXIT_FILE).exists():  # the node's last write is there
            settled = _settle_node_end(ctx, run_id, job_id, None)
            if settled is not None:
                changed.append(settled)
            return None
        return job_id, current  # settled once SLURM shows the job ended
    if current.status in ACTIVE_STATUSES:
        return job_id, current
    return None


def _node_end_pending(layout: Layout, run_id: str) -> bool:
    entry = _intent(layout, run_id)
    return bool(entry is not None and entry.get("node_end_pending"))


def _settle_node_end(
    ctx: Context, run_id: str, job_id: str, job: SlurmJob | None
) -> RunRecord | None:
    """
    Sync what the node wrote after a stop that outlived its grace, then forget the run.

    ``stop_slurm_run`` publishes ``killed`` while the node may still be
    shutting down; the node then writes its final record (usage, artifacts,
    ``ended_at``) with the same status, so no status change shows it. Once its
    exit record is there or SLURM shows the job ended, the record is indexed
    again (with a ``run.slurm_state`` event when it changed), the worktree is
    released, and the outbox entry goes.

    Returns
    -------
    RunRecord or None
        The run when its indexed record changed.
    """
    project = ctx.find_record(run_id).project
    with _publish_lock(ctx.layout.run_dir(project, run_id)):
        published = _sync_node_run(ctx, ctx.store.read_record(project, run_id))
        current = ctx.store.read_record(project, run_id)
        changed = published is not None
        if ctx.index.get_run(run_id) != current:
            ctx.index.upsert_run(current)
            points = ctx.store.read_metric_points(project, run_id)
            ctx.index.replace_metric_points(run_id, points)
            ctx.events.append(
                "run.slurm_state",
                project=project,
                run_id=run_id,
                payload={
                    "status": current.status.value,
                    "slurm_job_id": job_id,
                    "slurm_state": job.state if job is not None else None,
                    "final": True,
                },
            )
            changed = True
        release_worktree(ctx, current)
        _update_intent(ctx.layout, run_id, node_end_pending=False)  # last: a crash syncs again
    return current if changed else None


def _set_node(node: str) -> Callable[[RunRecord], RunRecord]:
    def mutate(r: RunRecord) -> RunRecord:
        if r.status in TERMINAL_STATUSES:
            return r
        return r.model_copy(update={"executor": r.executor.model_copy(update={"node": node})})

    return mutate


def reconcile(
    ctx: Context, *, confirm_gone: dict[str, SlurmJob | None] | None = None
) -> list[RunRecord]:
    """
    Compare this environment's active SLURM runs with SLURM and fix their state.

    - First, for every run in the SLURM outbox (not the index's active runs),
      publish what the compute node wrote (``sync_node_run``): the node writes
      only ``run.yaml`` and ``exit.json``, so the events and the index updates
      of SLURM runs come from here. A run whose job id was never recorded (its
      submitter crashed after ``sbatch``) is matched to its job by name and
      comment, or failed when its submitter is dead and SLURM has no job. A
      job id that only the outbox holds (the submitter died before writing
      ``run.yaml``) is recorded in ``run.yaml`` with ``run.submitted``.
    - Job queued or running: keep; record its node when SLURM assigned one.
    - Run already has an exit record (``run.yaml`` is terminal): keep.
    - Job ended (``sacct``) or vanished, and no exit record: mark ``lost``.
      The outbox entry stays for ``LOST_RECHECK_SECONDS``: a node end that a
      shared filesystem shows later (``run.yaml`` or ``exit.json``) is then
      published over ``lost``, and a finished task run is scored.

    Parameters
    ----------
    ctx : Context
    confirm_gone : dict of str to SlurmJob or None, optional
        Job ids seen gone by the previous call, with the ``sacct`` record seen
        then. When given, a run is marked lost only on the second call in a row
        that finds its job gone (this tolerates a shared filesystem that shows
        the node's final ``run.yaml`` late), and the lost reason uses whichever
        poll had SLURM's end state. Updated in place. None marks at once.

    Returns
    -------
    list of RunRecord
        Runs whose record changed (status published from the node, node
        recorded, or marked lost).

    Raises
    ------
    SlurmError
        If ``squeue`` fails; only the folder sync has happened then.
    """
    runs, changed = _tracked_slurm_runs(ctx)
    if not runs:
        if confirm_gone is not None:
            confirm_gone.clear()
        return changed
    jobs = poll([job_id for job_id, _ in runs])
    gone_now: dict[str, SlurmJob | None] = {}
    for job_id, record in runs:
        try:  # one run's failure is logged and never stops the runs after it
            updated = _reconcile_job(ctx, job_id, record, jobs.get(job_id), confirm_gone, gone_now)
        except HypothexError as exc:
            log.warning(
                "SLURM run %s: reconcile failed; trying again next poll: %s", record.run_id, exc
            )
            continue
        except Exception:
            log.exception("SLURM run %s: reconcile failed; trying again next poll", record.run_id)
            continue
        if updated is not None:
            changed.append(updated)
    if confirm_gone is not None:
        confirm_gone.clear()
        confirm_gone.update(gone_now)
    return changed


def _reconcile_job(
    ctx: Context,
    job_id: str,
    record: RunRecord,
    job: SlurmJob | None,
    confirm_gone: dict[str, SlurmJob | None] | None,
    gone_now: dict[str, SlurmJob | None],
) -> RunRecord | None:
    """Compare one active run with its job (``reconcile``); the run when its record changed."""
    current = ctx.find_record(record.run_id)
    if current.status in TERMINAL_STATUSES and _node_end_pending(ctx.layout, current.run_id):
        if job is not None and not is_finished(job):
            return None  # stopped, and the node is still shutting down
        if confirm_gone is not None and job_id not in confirm_gone:
            gone_now[job_id] = job  # the node's last write may show late on a shared filesystem
            return None
        return _settle_node_end(ctx, current.run_id, job_id, job)
    if current.status in TERMINAL_STATUSES:  # the node ended it since the folder sync
        return _publish_node_end(ctx, current.run_id)
    if job is not None and not is_finished(job):
        if job.node is not None and job.node != current.executor.node:
            return ctx.update_run(
                current.run_id,
                "run.slurm_state",
                _set_node(job.node),
                {"slurm_job_id": job_id, "slurm_state": job.state, "node": job.node},
            )
        return None
    if confirm_gone is not None and job_id not in confirm_gone:
        gone_now[job_id] = job
        return None
    if job is None and confirm_gone is not None:
        job = confirm_gone.get(job_id)  # sacct had the end state at the first poll
    with _publish_lock(ctx.run_dir(current)):
        if _read_exit(ctx.run_dir(current)) is not None:  # the node's end showed up meanwhile
            return _publish_node_end(ctx, current.run_id)
        lost = _end_if_active(
            ctx,
            current.run_id,
            "run.lost",
            _end(RunStatus.LOST),
            {
                "reason": lost_reason(job_id, job),
                "slurm_job_id": job_id,
                "slurm_state": job.state if job is not None else None,
            },
        )
        if lost is None:  # the node's end arrived first: publish it, never "lost"
            return _publish_node_end(ctx, current.run_id)
        release_worktree(ctx, lost)
        # acknowledged after the event of this end; the entry stays for LOST_RECHECK_SECONDS
        # so a node end that a shared filesystem shows late still replaces lost
        _update_intent(
            ctx.layout, lost.run_id, published=lost.status.value, lost_at=utcnow().isoformat()
        )
    return lost


def stop_slurm_run(ctx: Context, record: RunRecord, *, grace: float) -> RunRecord:
    """
    Stop a SLURM run with ``scancel``; it ends as ``killed``.

    A queued (pending) job is marked killed at once. For a running job,
    SLURM sends SIGTERM to ``hx run --child``, which records ``killed``
    itself; after ``grace`` seconds without that, the run is marked here, and
    its outbox entry stays (``node_end_pending``) until the node's exit record
    appears or SLURM shows the job ended: what the node writes meanwhile
    (usage, artifacts, ``ended_at``) is then indexed and the worktree released
    (``_settle_node_end``).

    Parameters
    ----------
    ctx : Context
    record : RunRecord
        An active run with ``executor.type == "slurm"``.
    grace : float
        Seconds to wait for the node to record the end.

    Returns
    -------
    RunRecord
        The final record.

    Raises
    ------
    RunError
        scancel failed and the job is still queued or running.
    """
    job_id = record.executor.slurm_job_id or _job_or_cancel_request(ctx, record.run_id)
    if job_id is not None:
        try:
            cancel(job_id)
        except SlurmError as exc:
            job = poll([job_id]).get(job_id)
            if job is not None and not is_finished(job):
                raise RunError(
                    f"could not cancel slurm job {job_id} of run {record.run_id}: {exc}"
                ) from exc
    # only now: a marker left by a failed scancel would make a job that later ends
    # normally record `killed` on the node
    atomic_write_text(ctx.run_dir(record) / STOP_MARKER, utcnow().isoformat())
    node_running = record.status == RunStatus.RUNNING and job_id is not None
    if record.status == RunStatus.RUNNING:
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            current = ctx.find_record(record.run_id)
            if current.status in TERMINAL_STATUSES:
                return _publish_node_end(ctx, record.run_id)
            time.sleep(0.1)
    with _publish_lock(ctx.run_dir(record)):  # the poller may publish this run right now
        killed = _end_if_active(
            ctx,
            record.run_id,
            "run.killed",
            _end(RunStatus.KILLED),
            {"reason": "stopped", "slurm_job_id": job_id},
        )
        if killed is None:  # the node's end came first: publish that end, not `killed`
            return _publish_node_end(ctx, record.run_id)
        if node_running:  # the node may still write its end: reconcile syncs it later
            _update_intent(
                ctx.layout, record.run_id, published=killed.status.value, node_end_pending=True
            )
        else:
            release_worktree(ctx, killed)
            mark_published(ctx.layout, killed)
    return killed


def _job_or_cancel_request(ctx: Context, run_id: str) -> str | None:
    """
    The job of a submission whose id is not recorded yet, or a cancel request.

    The job is looked up by the intent's comment. Without a job, ``cancel_requested``
    is set under the outbox lock, the same lock ``_record_job`` takes when
    ``sbatch`` answers or ``reconcile`` finds the job: whichever runs second
    sees the other's change, so the job that appears later is cancelled.
    """
    entry = _intent(ctx.layout, run_id)
    if entry is None:
        return None
    found: SlurmJob | None = None
    if entry.get("job_id") is None and entry.get("comment"):
        try:
            found, _ = find_submitted(entry["comment"])
        except SlurmError as exc:
            log.warning("run %s: squeue failed while stopping: %s", run_id, exc)
    with _outbox_lock(ctx.layout):
        entry = _intent(ctx.layout, run_id)
        if entry is None:
            return None
        if entry.get("job_id"):
            return str(entry["job_id"])
        if found is None:
            entry["cancel_requested"] = True
        else:
            entry.update(state="submitted", job_id=found.job_id)
        atomic_write_text(_outbox_path(ctx.layout, run_id), json.dumps(entry))
    if found is None:
        return None
    payload = {"slurm_job_id": found.job_id, "recovered": True}
    ctx.update_run(run_id, "run.submitted", _with_job(found.job_id), payload)
    return found.job_id


class SlurmPoller:
    """
    Reconcile SLURM runs now and then every ``interval`` seconds (daemon thread).

    A run is marked lost only after two polls in a row find its job gone.

    Parameters
    ----------
    ctx : Context
    interval : float
        Seconds between polls (``SLURM_POLL_SECONDS`` in ``hx serve``).

    Examples
    --------
    >>> poller = SlurmPoller(ctx)  # doctest: +SKIP
    >>> poller.start()  # doctest: +SKIP
    >>> poller.stop()  # doctest: +SKIP
    """

    def __init__(self, ctx: Context, interval: float = SLURM_POLL_SECONDS) -> None:
        self.ctx = ctx
        self.interval = interval
        self._gone: dict[str, SlurmJob | None] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        """True while the polling thread runs."""
        return self._thread is not None and self._thread.is_alive()

    def poll_once(self) -> list[RunRecord]:
        """
        Run one reconcile; a SLURM or store error is logged, not raised.

        Returns
        -------
        list of RunRecord
            Runs whose record changed.
        """
        try:
            return reconcile(self.ctx, confirm_gone=self._gone)
        except HypothexError as exc:
            log.warning("slurm poll failed: %s", exc)
            return []

    def _loop(self) -> None:
        try:
            comment_accounting(refresh=True)  # a new server start asks SLURM again
        except Exception:
            log.exception("slurm comment accounting probe crashed")
        while True:
            try:
                self.poll_once()
            except Exception:
                log.exception("slurm poll crashed")
            if self._stop.wait(self.interval):
                return

    def start(self) -> None:
        """Start the polling thread (no-op while a thread, even a stopping one, is alive)."""
        if self.alive:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hx-slurm-poller", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> bool:
        """
        Stop the polling thread and wait for it.

        A thread still busy after ``timeout`` (a SLURM command can block for
        ``SLURM_COMMAND_TIMEOUT``) stays owned: ``alive`` is still True and
        ``start`` will not start a second thread beside it.

        Parameters
        ----------
        timeout : float, optional
            Seconds to wait; None waits until the thread ends.

        Returns
        -------
        bool
            True when no polling thread is left.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                return False
        self._thread = None
        return True


def cancel_if_pending(ctx: Context, record: RunRecord) -> RunRecord:
    """
    Cancel a SLURM run only while its job is still pending (``scancel --state=PENDING``).

    The controller applies the state filter, so a job that started a moment
    ago is never cancelled. The run is marked ``killed`` only when SLURM then
    shows the job ``CANCELLED``.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    record : RunRecord
        A queued SLURM run.

    Returns
    -------
    RunRecord
        ``killed``, or the run unchanged (its job started, or its job id is not
        recorded yet: ``reconcile`` handles that one first).
    """
    job_id = record.executor.slurm_job_id
    if job_id is None:
        return record
    try:
        _run(["scancel", "--state=PENDING", job_id])
    except SlurmError as exc:
        log.info("scancel --state=PENDING %s: %s", job_id, exc)
        return ctx.find_record(record.run_id)
    job = poll([job_id]).get(job_id)
    if job is None or not job.state.startswith("CANCELLED"):
        return ctx.find_record(record.run_id)  # it started: leave it to run
    with _publish_lock(ctx.run_dir(record)):  # the poller may publish this run right now
        killed = _end_if_active(
            ctx,
            record.run_id,
            "run.killed",
            _end(RunStatus.KILLED),
            {"reason": "cancelled while queued", "slurm_job_id": job_id},
        )
        if killed is None:  # the node's end came first: publish that end, not `killed`
            return _publish_node_end(ctx, record.run_id)
        release_worktree(ctx, killed)
        mark_published(ctx.layout, killed)
    return killed
