"""Pydantic models for everything stored in a run folder."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    """Lifecycle state of a run."""

    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    KILLED = "killed"
    LOST = "lost"


ACTIVE_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})
TERMINAL_STATUSES = frozenset(
    {RunStatus.FINISHED, RunStatus.FAILED, RunStatus.KILLED, RunStatus.LOST}
)


class RunKind(StrEnum):
    """What a run executes."""

    FULL = "full"
    INFER = "infer"


class GitInfo(BaseModel):
    """
    Git state of the working copy a run was launched from.

    ``dirty`` is True only for changes to tracked files (what ``git.diff``
    captures). Untracked files are counted separately in
    ``untracked_count``; ``untracked`` holds the first 20 of their paths,
    relative to the repo root.
    """

    repo: str | None = None
    commit: str | None = None
    branch: str | None = None
    dirty: bool = False
    untracked_count: int = 0
    untracked: list[str] = Field(default_factory=list)


class DatasetRef(BaseModel):
    """The exact dataset a run used, with its fingerprint at launch."""

    name: str
    version: str
    split: str | None = None
    host: str = "local"
    path: str
    hash: str | None = None
    hash_mode: str | None = None
    size: int | None = None
    checked_at: datetime | None = None


class Artifact(BaseModel):
    """
    A large file recorded by path, not copied.

    Checkpoints also carry the training ``step`` they were saved at and the
    ``metrics`` logged with them (for example ``{"val_loss": 1.92}``).
    """

    kind: str
    path: str
    host: str = "local"
    size: int | None = None
    step: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)


class UsageTotals(BaseModel):
    """Summed resource use of a run (from ``usage.jsonl``) or of a group of runs."""

    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    seconds: float = 0.0
    calls: int = 0


class ExecutorInfo(BaseModel):
    """
    How and where the run's process is supervised.

    ``host`` is the run's host name from the hub's ``environments.yaml``
    (None on the hub itself). ``gpus`` holds the GPU indices given to the run
    (its ``CUDA_VISIBLE_DEVICES``). ``slurm_job_id`` and ``node`` are set for
    SLURM runs. ``queue_position`` is the 1-based place in the host's queue
    while the run waits, else None.
    """

    type: str = "local"
    pid: int | None = None
    pid_create_time: float | None = None
    child_pid: int | None = None
    host: str | None = None
    gpus: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    slurm_job_id: str | None = None
    node: str | None = None
    queue_position: int | None = Field(default=None, ge=1)


class CostTotals(BaseModel):
    """
    What a run cost; stored as ``RunRecord.cost`` when the run ends.

    ``gpu_hours`` is wall time times the number of GPUs, ``gpu_usd`` prices
    them at the host's ``usd_per_gpu_hour``, ``api_usd`` is ``usage.usd``,
    and ``total_usd`` is ``gpu_usd + api_usd``. See ``hypothex.core.cost``.

    Examples
    --------
    >>> CostTotals(gpu_hours=3.0, gpu_usd=6.3, api_usd=0.375, total_usd=6.675).total_usd
    6.675
    """

    gpu_hours: float = 0.0
    gpu_usd: float = 0.0
    api_usd: float = 0.0
    total_usd: float = 0.0


class RunRecord(BaseModel):
    """All facts about one run; stored as ``run.yaml``."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    project: str
    task: str | None = None
    hypothesis: str = ""
    kind: RunKind = RunKind.FULL
    parent: str | None = None
    stage: str | None = None
    command: list[str]
    command_template: list[str]
    vars: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    cwd: str
    environment_id: str
    host: str
    executor: ExecutorInfo = Field(default_factory=ExecutorInfo)
    git: GitInfo = Field(default_factory=GitInfo)
    datasets: list[DatasetRef] = Field(default_factory=list)
    seed: int | None = None
    config_hash: str
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    exit_code: int | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    starred: bool = False
    archived: bool = False
    created_by: str = "human"
    usage: UsageTotals | None = None
    cost: CostTotals | None = None
    sweep_id: str | None = None
    gpus_requested: int = Field(default=0, ge=0)

    @property
    def command_display(self) -> str:
        """The command as one shell-quoted string."""
        return shlex.join(self.command)


class ScoreRecord(BaseModel):
    """One value of one metric version for one run; stored in ``scores.jsonl``."""

    metric: str
    version: str
    key: str
    value: float | None = None
    error: str | None = None
    source_hash: str | None = None
    created_at: datetime


def end_unstarted(status: RunStatus) -> Callable[[RunRecord], RunRecord]:
    """
    Build an ``update_run`` mutator that ends a run that never started.

    The run gets ``status`` and ``ended_at``, and gives back what it only held
    while it waited: its GPUs (``executor.gpus``) and its queue position. A run
    that is no longer ``queued`` (it started or already ended) is left as it is.

    Parameters
    ----------
    status : RunStatus
        The terminal status, e.g. ``failed`` (could not start) or ``killed``
        (removed from the queue).

    Returns
    -------
    callable
        Takes the current record and returns the ended one.

    Examples
    --------
    >>> ctx.update_run(run_id, "run.failed", end_unstarted(RunStatus.FAILED))  # doctest: +SKIP
    """

    def mutate(r: RunRecord) -> RunRecord:
        if r.status != RunStatus.QUEUED:
            return r
        executor = r.executor.model_copy(update={"gpus": [], "queue_position": None})
        return r.model_copy(
            update={"status": status, "ended_at": datetime.now(UTC), "executor": executor}
        )

    return mutate


class MetricPoint(BaseModel):
    """
    One step of a logged metric history; stored in ``metrics.jsonl``.

    ``value`` is finite: a ``NaN`` or infinite row (a diverged loss written by
    an old SDK) fails validation, so readers skip it.
    """

    name: str
    step: int
    value: float = Field(allow_inf_nan=False)
    t: float | None = None
