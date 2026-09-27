"""Pydantic models for everything stored in a run folder."""

from __future__ import annotations

import shlex
from datetime import datetime
from enum import StrEnum

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
    """How the run's process is supervised."""

    type: str = "local"
    pid: int | None = None
    pid_create_time: float | None = None
    child_pid: int | None = None


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


class MetricPoint(BaseModel):
    """One step of a logged metric history; stored in ``metrics.jsonl``."""

    name: str
    step: int
    value: float
    t: float | None = None
