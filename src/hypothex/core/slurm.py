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

import re
import shlex
import sys
from pathlib import Path

from pydantic import BaseModel

from hypothex.core.errors import HypothexError
from hypothex.core.layout import Layout
from hypothex.core.records import RunRecord
from hypothex.remote.config import SlurmDefaults, sbatch_option_problem

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
