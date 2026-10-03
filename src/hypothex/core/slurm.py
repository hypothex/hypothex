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

import errno
import fcntl
import getpass
import json
import logging
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, cast

from pydantic import BaseModel

from hypothex.core.context import Context
from hypothex.core.environment import load_descriptor
from hypothex.core.errors import ConfigError, HypothexError, RunError
from hypothex.core.events import EventLog
from hypothex.core.execution import execute_run
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import utcnow
from hypothex.core.index import Index
from hypothex.core.layout import Layout
from hypothex.core.records import RunRecord, ScoreRecord
from hypothex.core.store import RunStore, run_lock
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
        ``--output``, ``--error``, ``--chdir``, ``--wrap``, in any form).

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
        problem = sbatch_option_problem(item)
        if problem is not None:
            raise SlurmError(f"slurm extra option {problem}")


def render_sbatch(record: RunRecord, defaults: SlurmDefaults, home: Path) -> str:
    """
    Render the batch script that runs ``record`` on a compute node.

    Directives, in order: ``--job-name=hx-<run_id>``,
    ``--output=<run_dir>/logs/slurm-%j.out``, ``--time``, ``--gpus`` (the
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
    node. At the end the exit record ``exit.json`` (``status``,
    ``exit_code``, ``ended_at``) is written next to ``run.yaml``.

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
