"""Seed a Hypothex home with demo projects, one per task kind.

The demo mirrors the approved mockups in ``docs/mockups/kinds/*/data.js`` (and
``docs/mockups/ui-v4/data.js`` for the generic kind): the same seeded generators,
ported to Python, produce the same numbers. Every file is written through the
public store, ``Context``, and SDK APIs, so the demo home has the production
layout. ``seed_demo`` executes no training, metric worker, or Git commands.

Used by UI tests, Playwright, and docs screenshots.

``seed_demo_hosts`` adds two fake hosts (an 8-GPU SSH box and a SLURM cluster) as
separate homes under ``<home>/demo-hosts/``; ``demo_hosts_running`` (used by
``hx serve``) starts them and fills the GPU queue. Nothing reaches a real host.
The host demo uses an isolated Git repository so queued launches can pin its
configuration and fake training script without discovering an enclosing checkout.

Examples
--------
>>> import pathlib, tempfile
>>> from hypothex.demo import seed_demo
>>> seed_demo(pathlib.Path(tempfile.mkdtemp()), kinds=["generic"])
{'generic': 'toy-classifier/toy-test'}
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel

from hypothex.core.config import TaskKind, render_template
from hypothex.core.context import Context
from hypothex.core.cost import compute_cost
from hypothex.core.environment import load_descriptor
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.execution import process_alive
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import new_command_id, new_run_id, utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import (
    DatasetRef,
    ExecutorInfo,
    GitInfo,
    RunRecord,
    RunStatus,
    ScoreRecord,
)
from hypothex.core.seeds import config_hash, run_fingerprint
from hypothex.core.stats import quantile
from hypothex.core.store import sum_usage
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep, sweep_tag
from hypothex.core.views import save_view
from hypothex.remote.config import HostSpec, SlurmDefaults, load_hosts, save_hosts
from hypothex.remote.hub import CLAIMS_DIR
from hypothex.sdk import Run

KINDS: tuple[TaskKind, ...] = (
    "generic",
    "training",
    "agent_eval",
    "agent_iteration",
    "system_bench",
)
DEMO_EPOCH = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
"""The "now" of the mockups; demo timestamps keep their distance to it."""

DEMO_TASKS: dict[str, tuple[str, str]] = {
    "generic": ("toy-classifier", "toy-test"),
    "training": ("rxn-forward", "uspto-forward-top1"),
    "agent_eval": ("retro-agents", "retro-bench-200"),
    "agent_iteration": ("retro-agent", "retro-bench-200"),
    "system_bench": ("route-search", "route-api-latency"),
}

_M32 = 0xFFFFFFFF

_METRICS_PY = '''"""Metrics for the Hypothex demo projects."""

from hypothex.metrics import MetricResult


def accuracy(examples):
    per = {e.id: {"correct": e.prediction == e.reference} for e in examples}
    value = sum(v["correct"] for v in per.values()) / max(len(per), 1)
    return MetricResult(values={"value": value}, per_example=per)


def solved(examples):
    per = {e.id: {"solved": e.prediction is not None} for e in examples}
    value = sum(v["solved"] for v in per.values()) / max(len(per), 1)
    return MetricResult(values={"value": value}, per_example=per)


def harness(examples):
    raise RuntimeError("written by the benchmark harness; not computed from predictions")
'''


# --------------------------------------------------------------------- JS parity
def _mulberry32(seed: int) -> Callable[[], float]:
    """
    Return the mockups' seeded uniform generator (mulberry32).

    Parameters
    ----------
    seed : int
        32-bit seed.

    Returns
    -------
    callable
        Each call returns the next float in ``[0, 1)``, bit-identical to the
        JavaScript ``mulberry32`` in the mockups.

    Examples
    --------
    >>> round(_mulberry32(20260927)(), 6)
    0.581754
    """
    state = seed & _M32

    def draw() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & _M32
        t = ((state ^ (state >> 15)) * (state | 1)) & _M32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & _M32)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    return draw


def _gauss(draw: Callable[[], float]) -> float:
    """
    Draw a standard normal value with the Box-Muller transform, as the mockups do.

    Parameters
    ----------
    draw : callable
        Uniform generator from ``_mulberry32``.

    Returns
    -------
    float
    """
    u = 0.0
    while u == 0.0:
        u = draw()
    v = 0.0
    while v == 0.0:
        v = draw()
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * v)


def _js_round(x: float) -> int:
    """
    Round half up, like JavaScript ``Math.round``.

    Parameters
    ----------
    x : float
        Value to round.

    Returns
    -------
    int

    Examples
    --------
    >>> _js_round(2.5), _js_round(-2.5)
    (3, -2)
    """
    return math.floor(x + 0.5)


def _fixed(x: float, digits: int) -> float:
    """
    Round like JavaScript ``Number(x.toFixed(digits))``.

    Parameters
    ----------
    x : float
        Value to round.
    digits : int
        Decimal places.

    Returns
    -------
    float

    Examples
    --------
    >>> _fixed(12.25, 1)
    12.3
    """
    exact = Decimal(x).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(exact)


def _clamp(x: float, lo: float, hi: float) -> float:
    """
    Clamp ``x`` to ``[lo, hi]``.

    Parameters
    ----------
    x, lo, hi : float
        Value and bounds.

    Returns
    -------
    float
    """
    return max(lo, min(hi, x))


# --------------------------------------------------------------------- seeding helpers
@dataclass
class _RunSpec:
    """Everything needed to create one demo run record."""

    project: str
    task: str | None
    repo: Path
    hypothesis: str
    command_template: list[str]
    params: dict[str, str]
    seed: int | None
    created_at: datetime
    created_by: str
    host: str
    commit: str
    key: str
    branch: str = "main"
    tags: list[str] = field(default_factory=list)
    archived: bool = False
    datasets: list[DatasetRef] = field(default_factory=list)


class _Seeder:
    """
    Write demo projects and runs into one home.

    Parameters
    ----------
    ctx : Context
        Open context of the demo home.
    anchor : datetime
        Where ``DEMO_EPOCH`` lands; every mockup timestamp keeps its offset.
    """

    def __init__(self, ctx: Context, anchor: datetime) -> None:
        self.ctx = ctx
        self.shift = anchor - DEMO_EPOCH
        self.repos = ctx.layout.home / "demo-repos"

    def at(self, stamp: str) -> datetime:
        """
        Shift a mockup timestamp by the anchor offset.

        Parameters
        ----------
        stamp : str
            ISO timestamp, e.g. ``2026-09-26T14:02:11Z``.

        Returns
        -------
        datetime
            Aware UTC datetime.
        """
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")) + self.shift

    def project(self, config: dict[str, Any], files: dict[str, str]) -> Path:
        """
        Write a demo repo (``hypothex.yaml`` plus files) and register it.

        Parameters
        ----------
        config : dict
            Contents of ``hypothex.yaml``.
        files : dict of str to str
            Extra files, keyed by path relative to the repo.

        Returns
        -------
        Path
            The repo directory, ``<home>/demo-repos/<project>``.
        """
        repo = self.repos / config["project"]
        repo.mkdir(parents=True, exist_ok=True)
        atomic_write_text(repo / "hypothex.yaml", yaml.safe_dump(config, sort_keys=False))
        atomic_write_text(repo / "demo_metrics.py", _METRICS_PY)
        for rel, text in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(repo / rel, text)
        self.ctx.register_project(repo)
        return repo

    def start(self, spec: _RunSpec) -> tuple[RunRecord, Run]:
        """
        Create a running run and return it with an SDK handle to its folder.

        Parameters
        ----------
        spec : _RunSpec
            The run to create.

        Returns
        -------
        record : RunRecord
            The created record (status ``running``).
        run : Run
            SDK handle used to log metrics, predictions, samples, and traces.
        """
        seed = "" if spec.seed is None else str(spec.seed)
        digest = hashlib.sha256(f"{spec.project}|{spec.key}".encode()).hexdigest()[:4]
        run_id = new_run_id(spec.task, now=spec.created_at).rsplit("-", 1)[0] + f"-{digest}"
        fingerprint = run_fingerprint(
            command_template=spec.command_template,
            stage=None,
            user_config=None,
            params=spec.params,
            vars={},
        )
        record = RunRecord(
            run_id=run_id,
            project=spec.project,
            task=spec.task,
            hypothesis=spec.hypothesis,
            command=[arg.replace("{seed}", seed) for arg in spec.command_template],
            command_template=spec.command_template,
            params=spec.params,
            cwd=str(spec.repo),
            environment_id=f"demo:{spec.host}",
            host=spec.host,
            git=GitInfo(commit=spec.commit, branch=spec.branch),
            datasets=spec.datasets,
            seed=spec.seed,
            config_hash=config_hash(fingerprint),
            status=RunStatus.RUNNING,
            created_at=spec.created_at,
            started_at=spec.created_at,
            tags=spec.tags,
            archived=spec.archived,
            created_by=spec.created_by,
        )
        self.ctx.create_run(record)
        return record, Run(self.ctx.run_dir(record), run_id, spec.project)

    def per_example(self, record: RunRecord, ref: str, rows: dict[str, dict[str, Any]]) -> None:
        """
        Write per-example scores in the metric worker's format.

        Parameters
        ----------
        record : RunRecord
            Run the scores belong to.
        ref : str
            ``metric@version``.
        rows : dict
            Per-example fields keyed by example id.
        """
        path = self.ctx.run_dir(record) / "predictions" / f"scores.{ref}.jsonl"
        atomic_write_text(path, "".join(json.dumps({"id": k, **v}) + "\n" for k, v in rows.items()))

    def index_progress(self, record: RunRecord) -> None:
        """
        Index a still-running run's logged metric history (a bounded read).

        Parameters
        ----------
        record : RunRecord
            The running run.
        """
        points = self.ctx.store.read_metric_points_bounded(record.project, record.run_id)
        self.ctx.index.replace_metric_points(record.run_id, points)

    def finish(
        self,
        record: RunRecord,
        *,
        status: RunStatus,
        ended_at: datetime,
        exit_code: int,
        scores: Sequence[tuple[str, str, str, float]] = (),
        stderr: str = "",
    ) -> RunRecord:
        """
        Finalise a run the way ``execute_run`` does, then add its scores.

        Parameters
        ----------
        record : RunRecord
            The running run.
        status : RunStatus
            Final status.
        ended_at : datetime
            End time; also the scores' creation time.
        exit_code : int
            Process exit code.
        scores : sequence of (metric, version, key, value)
            Final scores to append.
        stderr : str
            Text for ``logs/stderr.log``.

        Returns
        -------
        RunRecord
            The final record.
        """
        run_dir = self.ctx.run_dir(record)
        if stderr:
            atomic_write_text(run_dir / "logs" / "stderr.log", stderr)
        self.index_progress(record)
        logged = self.ctx.store.read_artifacts(record.project, record.run_id)
        usage = sum_usage(self.ctx.store.read_usage(record.project, record.run_id))

        def mutate(r: RunRecord) -> RunRecord:
            return r.model_copy(
                update={
                    "status": status,
                    "ended_at": ended_at,
                    "exit_code": exit_code,
                    "artifacts": [*r.artifacts, *logged],
                    "usage": usage,
                }
            )

        final = self.ctx.update_run(
            record.run_id, f"run.{status.value}", mutate, {"exit_code": exit_code}
        )
        for metric, version, key, value in scores:
            self.ctx.add_score(
                final,
                ScoreRecord(
                    metric=metric, version=version, key=key, value=value, created_at=ended_at
                ),
            )
        return final


def _jsonl(rows: Iterable[dict[str, Any]]) -> str:
    """
    Serialise rows as JSON lines.

    Parameters
    ----------
    rows : iterable of dict
        Rows to write.

    Returns
    -------
    str
    """
    return "".join(json.dumps(r) + "\n" for r in rows)


def _task_config(
    project: str,
    task: str,
    *,
    kind: TaskKind,
    dataset: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
    primary: str,
    description: str,
    **extra: Any,
) -> dict[str, Any]:
    """
    Build a one-task ``hypothex.yaml`` body.

    Parameters
    ----------
    project, task : str
        Project and task names.
    kind : TaskKind
        Task kind.
    dataset : dict
        The dataset spec; it is named after the task.
    metrics : dict
        Metric specs by name.
    primary : str
        Primary metric reference.
    description : str
        Task description.
    **extra
        Additional task fields (``baseline``, ``version_param``).

    Returns
    -------
    dict
    """
    return {
        "project": project,
        "datasets": {task: dataset},
        "metrics": metrics,
        "tasks": {
            task: {
                "dataset": task,
                "split": "test",
                "metrics": list(metrics),
                "primary": primary,
                "description": description,
                "kind": kind,
                **extra,
            }
        },
    }


# --------------------------------------------------------------------- generic
# ui-v4/data.js: 180 test examples; rf seed 3 vs SVM: 9 fixed, 3 broken, 157 both
# pass, 11 both fail. Accuracies: logreg 149, knn 156, rf 158/160/160, SVM 166 of 180.
_GEN_FIXED = ("test-0", "test-110", "test-116", "test-12", "test-156", "test-177", "test-21")
_GEN_FIXED += ("test-63", "test-83")
_GEN_BROKEN = ("test-137", "test-167", "test-30")
_GEN_BOTH_FAIL = ("test-7", "test-14", "test-54", "test-62", "test-79", "test-81", "test-84")
_GEN_BOTH_FAIL += ("test-101", "test-122", "test-143", "test-171")
_GEN_RF = _GEN_BOTH_FAIL + _GEN_FIXED
_GEN_RF1 = _GEN_RF + ("test-40", "test-41")
_GEN_KNN = _GEN_BOTH_FAIL + _GEN_FIXED[:5]
_GEN_KNN += ("test-2", "test-5", "test-9", "test-17", "test-25", "test-33", "test-48", "test-66")
_GEN_LOGREG = _GEN_KNN + ("test-70", "test-88", "test-95", "test-104", "test-119", "test-133")
_GEN_LOGREG += ("test-150",)
_GEN_SVM_HYPOTHESIS = (
    "RBF-kernel SVM should beat RF/KNN/logreg because make_classification with "
    "n_clusters_per_class=1 makes smooth, roughly circular class clusters that a "
    "margin-based kernel model separates better than axis-aligned trees or a linear boundary"
)
_GEN_OLD, _GEN_NEW = (
    "2bbf5a3c81bfc657dea6d28bf0b3f057409602ad",
    "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
)
_GEN_ARGPARSE = (
    "usage: train_eval.py [-h] --model {logreg,rf,knn} [--seed SEED]\n"
    "train_eval.py: error: argument --model: invalid choice: 'svm' "
    "(choose from 'logreg', 'rf', 'knn')\n"
)
_GEN_NOTE = (
    "RBF SVM (C=10, gamma=scale) beats prior best (rf): accuracy 0.9222 (n=3) vs rf "
    "0.8852 +/- 0.0064 (n=3). Fixed 9 test examples rf got wrong, broke 3, net +6/180. "
    "SVM is deterministic here, so identical seeds are expected."
)


def _seed_generic(sd: _Seeder) -> None:
    """
    Seed ``toy-classifier/toy-test`` (kind ``generic``) from ``ui-v4/data.js``.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["generic"]
    ids = [f"test-{i}" for i in range(180)]
    refs = {ex: i % 3 for i, ex in enumerate(ids)}
    dataset = {"version": "v1", "path": "data/test.jsonl", "splits": {"test": "data/test.jsonl"}}
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="generic",
            dataset=dataset,
            metrics={"accuracy": {"version": "v1", "fn": "demo_metrics:accuracy"}},
            primary="accuracy",
            description="Classify the held-out test split.",
        ),
        {"data/test.jsonl": _jsonl({"id": ex, "reference": refs[ex]} for ex in ids)},
    )
    ref = DatasetRef(name=task, version="v1", split="test", path=str(repo / "data/test.jsonl"))

    def launch(
        model: str,
        seed: int,
        stamp: str,
        *,
        hypothesis: str,
        commit: str,
        by: str,
        key: str,
        tags: Sequence[str] = (),
        archived: bool = False,
    ) -> tuple[RunRecord, Run]:
        return sd.start(
            _RunSpec(
                project=project,
                task=task,
                repo=repo,
                hypothesis=hypothesis,
                command_template=["python", "train_eval.py", "--model", model, "--seed", "{seed}"],
                params={"model": model},
                seed=seed,
                created_at=sd.at(stamp),
                created_by=by,
                host="laptop",
                commit=commit,
                key=key,
                tags=list(tags),
                archived=archived,
                datasets=[ref],
            )
        )

    def scored(record: RunRecord, run: Run, wrong: Sequence[str]) -> RunRecord:
        miss = set(wrong)
        run.log_predictions(
            {
                "id": ex,
                "prediction": (refs[ex] + 1) % 3 if ex in miss else refs[ex],
                "reference": refs[ex],
            }
            for ex in ids
        )
        run.log({"train_accuracy": 1.0 - len(miss) / 360}, step=0)
        sd.per_example(record, "accuracy@v1", {ex: {"correct": ex not in miss} for ex in ids})
        return sd.finish(
            record,
            status=RunStatus.FINISHED,
            ended_at=record.created_at + timedelta(seconds=2),
            exit_code=0,
            scores=[("accuracy", "v1", "value", 1.0 - len(miss) / len(ids))],
        )

    baselines = (
        ("logreg", ("21:00:21", "21:00:23", "21:00:25"), (_GEN_LOGREG,) * 3),
        ("rf", ("21:00:28", "21:00:30", "21:00:32"), (_GEN_RF1, _GEN_RF, _GEN_RF)),
        ("knn", ("21:00:34", "21:00:36", "21:00:38"), (_GEN_KNN,) * 3),
    )
    for model, times, wrongs in baselines:
        for seed, (clock, wrong) in enumerate(zip(times, wrongs, strict=True), start=1):
            record, run = launch(
                model,
                seed,
                f"2026-09-26T{clock}Z",
                hypothesis=f"baseline {model}",
                commit=_GEN_OLD,
                by="human",
                key=f"{model}-{seed}",
            )
            scored(record, run, wrong)
    for seed, clock in enumerate(("21:01:58", "21:02:01", "21:02:02"), start=1):
        record, _ = launch(
            "svm",
            seed,
            f"2026-09-26T{clock}Z",
            hypothesis=_GEN_SVM_HYPOTHESIS,
            commit=_GEN_OLD,
            by="agent:acceptance",
            key=f"svm-failed-{seed}",
            archived=True,
        )
        sd.finish(
            record,
            status=RunStatus.FAILED,
            ended_at=record.created_at + timedelta(seconds=1),
            exit_code=2,
            stderr=_GEN_ARGPARSE,
        )
    for name, clock in (
        ("A", "21:02:41"),
        ("B", "21:02:43"),
        ("A2", "21:02:48"),
        ("B2", "21:02:50"),
    ):
        record, _ = launch(
            "rf",
            1,
            f"2026-09-26T{clock}Z",
            hypothesis=f"debug test {name}",
            commit=_GEN_NEW,
            by="agent:acceptance",
            key=f"debug-{name}",
            archived=True,
        )
        sd.finish(
            record,
            status=RunStatus.FINISHED,
            ended_at=record.created_at + timedelta(seconds=1),
            exit_code=0,
        )
    for seed, clock in enumerate(("21:03:02", "21:03:04", "21:03:06"), start=1):
        record, run = launch(
            "svm",
            seed,
            f"2026-09-26T{clock}Z",
            hypothesis=_GEN_SVM_HYPOTHESIS,
            commit=_GEN_NEW,
            by="agent:acceptance",
            key=f"svm-{seed}",
            tags=["best", "svm"] if seed == 3 else ["svm"],
        )
        final = scored(record, run, _GEN_BOTH_FAIL + _GEN_BROKEN)
        if seed == 3:
            sd.ctx.store.append_note(project, final.run_id, _GEN_NOTE, "agent:acceptance")


# --------------------------------------------------------------------- training
@dataclass(frozen=True)
class _TrainConfig:
    """One training config of the ``training`` mockup."""

    id: str
    name: str
    hypothesis: str
    lr: float
    sec_per_step: float
    created_by: str
    v: tuple[float, float, float, float]  # val top-1: inf, v0, tau, overfit
    vl: tuple[float, float, float, float]  # val loss: inf, l0, tau, overfit
    tl: tuple[float, float, float]  # train loss: inf, l0, tau
    util: float
    mem: float
    host: str
    commit: str


_TRAIN_CONFIGS = (
    _TrainConfig(
        "base", "base", "base recipe", 3e-4, 0.94, "shreyas",
        (0.8958, 0.62, 2500, 0.0060), (0.140, 0.46, 2300, 0.020), (0.074, 0.58, 2600),
        95, 61.4, "gpu-a01", "3d9e1a7",
    ),
    _TrainConfig(
        "lr1e-4", "lr 1e-4", "lr 1e-4 converges higher", 1e-4, 0.94, "agent:tuner",
        (0.8966, 0.62, 4300, 0.0), (0.143, 0.46, 4200, 0.0), (0.101, 0.58, 4600),
        95, 61.4, "gpu-a02", "b82f04c",
    ),
    _TrainConfig(
        "aug", "+aug", "+aug (SMILES randomisation) lifts top-1", 3e-4, 1.02, "agent:tuner",
        (0.9098, 0.60, 3100, 0.0), (0.121, 0.47, 3000, 0.0), (0.129, 0.61, 3200),
        86, 64.2, "gpu-a03", "b82f04c",
    ),
)  # fmt: skip
# Not in the mockup: one run still in progress, so the Overview has something running.
_TRAIN_RUNNING = _TrainConfig(
    "lr2e-4", "lr 2e-4", "+aug with lr 2e-4", 2e-4, 1.02, "agent:tuner",
    (0.9120, 0.60, 2800, 0.0), (0.118, 0.47, 2700, 0.0), (0.125, 0.61, 2900),
    86, 64.2, "gpu-a04", "b82f04c",
)  # fmt: skip
_STEPS, _VAL_EVERY, _CKPT_EVERY, _LOG_EVERY, _SYS_EVERY, _WARMUP = 20000, 500, 2000, 50, 100, 1000
_N_TEST, _SPIKE = 40000, 9000
_TRAIN_COMMAND = "python train.py --config configs/{config}.yaml --seed {{seed}}"


@dataclass
class _Curves:
    """Logged history of one training run."""

    train: list[tuple[int, float]]
    val: list[tuple[int, float, float]]
    lr: list[tuple[int, float]]
    sys: list[tuple[int, int, float]]
    ckpts: list[tuple[int, float, float]]
    best_step: int
    best_test: float
    final_test: float | None


def _lr_at(peak: float, step: int) -> float:
    """
    Learning rate with linear warmup, then cosine decay to 10% of peak.

    Parameters
    ----------
    peak : float
        Peak learning rate.
    step : int
        Optimiser step.

    Returns
    -------
    float
    """
    if step < _WARMUP:
        return peak * step / _WARMUP
    p = (step - _WARMUP) / (_STEPS - _WARMUP)
    return peak * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * p)))


def _training_curves(ci: int, c: _TrainConfig, seed: int, stop: int, diverged: bool) -> _Curves:
    """
    Port of the ``training`` mockup's per-run generator.

    Parameters
    ----------
    ci : int
        Config index (part of the RNG seed).
    c : _TrainConfig
        The config.
    seed : int
        Run seed (part of the RNG seed).
    stop : int
        Last step reached.
    diverged : bool
        Add the loss spike at step 9,000 and its lasting penalty.

    Returns
    -------
    _Curves
    """
    r = _mulberry32(1000 * (ci + 1) + seed * 41)
    off_v, off_vl, off_tl = _gauss(r) * 0.0014, _gauss(r) * 0.003, _gauss(r) * 0.003

    def pen(s: int) -> float:
        return math.exp(-(s - _SPIKE) / 520) if diverged and s >= _SPIKE else 0.0

    def pen_long(s: int) -> float:
        return 1 - math.exp(-(s - _SPIKE) / 900) if diverged and s >= _SPIKE else 0.0

    def r4(x: float) -> float:
        return _js_round(x * 1e4) / 1e4

    train = []
    for s in range(_LOG_EVERY, stop + 1, _LOG_EVERY):
        base = c.tl[0] + off_tl + (c.tl[1] - c.tl[0]) * math.exp(-s / c.tl[2])
        base += 2.75 * pen(s) + 0.052 * pen_long(s)
        train.append((s, r4(base * math.exp(_gauss(r) * 0.075))))
    val = []
    for s in range(_VAL_EVERY, stop + 1, _VAL_EVERY):
        x = s / _STEPS
        top1 = c.v[0] + off_v - (c.v[0] - c.v[1]) * math.exp(-s / c.v[2]) - c.v[3] * x * x * x
        loss = c.vl[0] + off_vl + (c.vl[1] - c.vl[0]) * math.exp(-s / c.vl[2]) + c.vl[3] * x * x * x
        top1 -= 0.45 * pen(s) + 0.029 * pen_long(s)
        loss += 0.95 * pen(s) + 0.058 * pen_long(s)
        val.append((s, r4(top1 + _gauss(r) * 0.0009), r4(loss * math.exp(_gauss(r) * 0.012))))
    lr = [(s, float(f"{_lr_at(c.lr, s):.3e}")) for s in range(0, stop + 1, _SYS_EVERY)]
    sys = []
    for s in range(_SYS_EVERY, stop + 1, _SYS_EVERY):
        eval_dip, ckpt_dip = s % _VAL_EVERY == 0, s % _CKPT_EVERY == 0
        u = c.util + _gauss(r) * 1.6
        if eval_dip:
            u = 38 + _gauss(r) * 4
        if ckpt_dip:
            u = 22 + _gauss(r) * 3
        m = c.mem * (s / 300) if s < 300 else c.mem + _gauss(r) * 0.15 + (1.8 if eval_dip else 0)
        sys.append((s, int(_clamp(_js_round(u), 0, 100)), _js_round(m * 10) / 10))
    gap = 0.0026 + _gauss(r) * 0.0006
    by_step = {s: (top1, loss) for s, top1, loss in val}
    ckpts = [(s, *by_step[s]) for s in range(_CKPT_EVERY, stop + 1, _CKPT_EVERY)]
    best = ckpts[0]
    for ck in ckpts[1:]:
        if ck[1] > best[1]:
            best = ck

    def test_of(v: float) -> float:
        return _js_round((v - gap) * _N_TEST) / _N_TEST

    final = test_of(val[-1][1]) if stop == _STEPS else None
    return _Curves(train, val, lr, sys, ckpts, best[0], test_of(best[1]), final)


def _seed_training(sd: _Seeder) -> None:
    """
    Seed ``rxn-forward/uspto-forward-top1`` (kind ``training``).

    Nine runs mirror ``kinds/training/data.js``: base seed 2 diverges at step
    9,000, +aug seed 3 is killed at step 14,000. One extra run is still running.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["training"]
    dataset = {
        "version": "v2",
        "host": "nfs-01",
        "path": "/data/uspto-mit/v2",
        "splits": {"test": "/data/uspto-mit/v2/test.jsonl"},
    }
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="training",
            dataset=dataset,
            metrics={
                "top1": {
                    "version": "v1",
                    "fn": "demo_metrics:harness",
                    "changelog": {"v1": "exact-match top-1 on the 40,000-reaction test split"},
                }
            },
            primary="top1",
            description="Forward reaction prediction on USPTO-MIT; top-1 exact match.",
        ),
        {},
    )
    ref = DatasetRef(
        name=task, version="v2", split="test", host="nfs-01", path=dataset["splits"]["test"]
    )
    t0 = sd.at("2026-09-24T23:15:02Z")
    plan = [(ci, c, seed) for ci, c in enumerate(_TRAIN_CONFIGS) for seed in (1, 2, 3)]
    for k, (ci, c, seed) in enumerate([*plan, (3, _TRAIN_RUNNING, 1)]):
        running = c is _TRAIN_RUNNING
        killed = c.id == "aug" and seed == 3
        created = sd.at("2026-09-27T11:20:00Z") if running else t0 + timedelta(seconds=2 * k)
        stop = 2350 if running else 14000 if killed else _STEPS
        curves = _training_curves(ci, c, seed, stop, diverged=c.id == "base" and seed == 2)
        record, run = sd.start(
            _RunSpec(
                project=project,
                task=task,
                repo=repo,
                hypothesis=c.hypothesis,
                command_template=_TRAIN_COMMAND.format(config=c.id).split(),
                params={"config": c.id, "lr": f"{c.lr:g}"},
                seed=seed,
                created_at=created,
                created_by=c.created_by,
                host=c.host,
                commit=c.commit,
                key=f"{c.id}-{seed}",
                datasets=[ref],
            )
        )
        for s, value in curves.train:
            run.log({"train/loss": value}, step=s)
        for s, top1, loss in curves.val:
            run.log({"val/top1": top1, "val/loss": loss}, step=s)
        for s, value in curves.lr:
            run.log({"lr": value}, step=s)
        for s, util, mem in curves.sys:
            run.log({"sys/gpu_util": util, "sys/gpu_mem_gb": mem}, step=s)
        ckpt_dir = f"/scratch/shreyas/hx/{project}/runs/{record.run_id}/ckpt"
        for s, top1, loss in curves.ckpts:
            run.log_checkpoint(
                f"{ckpt_dir}/step_{s:06d}.pt",
                step=s,
                metrics={"val/top1": top1, "val/loss": loss},
                host=c.host,
            )
        if running:
            sd.index_progress(record)
            continue
        scores = [("top1", "v1", "value", curves.best_test)]
        if curves.final_test is not None:
            scores.append(("top1", "v1", "final", curves.final_test))
        sd.finish(
            record,
            status=RunStatus.KILLED if killed else RunStatus.FINISHED,
            ended_at=created + timedelta(seconds=stop * c.sec_per_step),
            exit_code=137 if killed else 0,
            scores=[] if killed else scores,
            stderr="preempted, SIGKILL\n" if killed else "",
        )


# --------------------------------------------------------------------- agent_eval
@dataclass(frozen=True)
class _AgentConfig:
    """One agent config of the ``agent_eval`` mockup."""

    id: str
    short: str
    model: str
    tools: str
    a: float  # skill
    pin: float  # $ per 1M input tokens
    pout: float  # $ per 1M output tokens
    c0: int  # base context per turn
    g: int  # context growth per turn
    out: int  # output tokens per turn
    lat: float  # model seconds per turn
    tc: float  # tool calls per turn
    fw: tuple[float, float, float, float, float]  # failure weights, in _FAILS order
    turn_k: float
    commit: str
    created_by: str


_AGENT_CONFIGS = (
    _AgentConfig("mini", "gpt-5-mini", "gpt-5-mini", "base", -0.75, 0.10, 1.6, 3100, 1150,
                 360, 1.9, 1.05, (0.10, 0.14, 0.34, 0.12, 0.30), 1.0, "4be19c2", "agent:sweep-7"),
    _AgentConfig("sonnet", "Sonnet 5", "claude-sonnet-5", "base", 0.25, 1.2, 15, 3300, 1000,
                 420, 3.4, 1.25, (0.26, 0.30, 0.10, 0.12, 0.22), 1.0, "4be19c2", "agent:sweep-7"),
    _AgentConfig("scorer", "Sonnet 5 + scorer", "claude-sonnet-5", "base + score_routes", 1.30,
                 1.2, 15, 3600, 820, 380, 3.3, 1.35, (0.30, 0.14, 0.08, 0.24, 0.24), 0.8,
                 "91ad07e", "mira"),
    _AgentConfig("opus", "Opus 5.5", "claude-opus-5-5", "base", 1.30, 2.0, 25, 3300, 1000, 880,
                 6.6, 1.3, (0.52, 0.12, 0.04, 0.10, 0.22), 1.0, "4be19c2", "agent:sweep-7"),
)  # fmt: skip
_FAILS = ("timeout", "loop", "invalid SMILES", "tool error", "gave up")
_AGENT_COMMAND = ["python", "-m", "retro_agents.bench", "--model"]
_CLASSES = (
    "kinase inhibitor", "macrolide", "peptidomimetic", "biaryl amide", "spiro-oxindole",
    "steroid", "nucleoside", "β-lactam", "sulfonamide", "indole alkaloid", "PROTAC linker",
    "fluoroquinolone",
)  # fmt: skip
# The trajectory of the selected attempt: tool, args, result, tokens in, tokens out, ms.
_AGENT_TRACE = (
    ("retro_expand", "target, top_k=8", "8 precursors, amide p .62", 4410, 512, 4820),
    ("check_stock", "ClC(=O)c1ccc(CN2CCN(C)CC2)cc1", "in stock", 5480, 188, 2710),
    ("check_stock", "Cc1ccc(N)cc1Nc1nccc(-c2cccnc2)n1", "not in stock", 6320, 204, 2640),
    ("retro_expand", "Cc1ccc(N)cc1Nc1nccc(…)n1", "6 precursors, nitro red. p .71", 7690, 466,
     4960),
    ("retro_expand", "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", "5 precursors, SNAr p .48", 9310,
     431, 5130),
    ("score_routes", "3 routes, depth 3", "best .71, route B", 10840, 352, 8870),
    ("check_stock", "Cc1ccc([N+](=O)[O-])cc1N", "in stock", 11720, 176, 2580),
    ("check_stock", "CN(C)/C=C/C(=O)c1cccnc1", "not in stock", 12460, 198, 2690),
    ("retro_expand", "CN(C)/C=C/C(=O)c1cccnc1", "4 precursors, DMF-DMA p .80", 13950, 402,
     4710),
    ("score_routes", "2 routes, depth 4", "tool error: timeout 8 s", 15210, 318, 11240),
    ("retro_expand", "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", "5 precursors, SNAr p .48", 16930,
     455, 5080),
    ("score_routes", "3 routes, depth 3", "best .71, route B", 18380, 341, 8790),
    ("retro_expand", "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", "loop: 3rd identical call", 19970,
     473, 4210),
)  # fmt: skip


@dataclass
class _Target:
    """One benchmark target."""

    id: str
    b: float  # difficulty
    depth: int
    cls: str


@dataclass
class _Attempt:
    """One attempt of one config and seed on one target."""

    solved: bool
    fail: str | None
    turns: int
    tool_calls: int
    tok_in: int
    tok_out: int
    cost: float
    wall: float


def _agent_eval_data() -> tuple[list[_Target], dict[tuple[str, int], list[_Attempt]], int]:
    """
    Port of the ``agent_eval`` mockup generator.

    Returns
    -------
    targets : list of _Target
        200 targets.
    attempts : dict
        Attempts keyed by ``(config id, seed)``, one per target.
    selected : int
        Index of the attempt whose trajectory is logged (Sonnet 5 + scorer, seed 2).
    """
    rnd = _mulberry32(20260927)

    def gauss() -> float:
        return _gauss(rnd)

    def pick(weights: list[float]) -> int:
        total = 0.0
        for w in weights:  # plain left-to-right sum, like Array.reduce
            total += w
        left = rnd() * total
        for i, w in enumerate(weights):
            left -= w
            if left <= 0:
                return i
        return len(weights) - 1

    targets = []
    for i in range(200):
        b = gauss() * 1.55
        depth = int(_clamp(_js_round(4.2 + b * 1.25 + gauss() * 0.9), 2, 11))
        cls = _CLASSES[math.floor(rnd() * len(_CLASSES))]
        targets.append(_Target(f"T-{i + 1:03d}", b, depth, cls))
    attempts: dict[tuple[str, int], list[_Attempt]] = {}
    for c in _AGENT_CONFIGS:
        for seed in (1, 2, 3):
            e = gauss() * 0.04
            rows = []
            for t in targets:
                p = 1 / (1 + math.exp(-(c.a + e - t.b)))
                solved = rnd() < p
                fail = None
                if solved:
                    turns = _js_round(
                        _clamp((3.5 + t.depth * 1.35) * c.turn_k + gauss() * 2.2, 3, 28)
                    )
                else:
                    w = list(c.fw)
                    if t.b > 1:
                        w[0] *= 1.6
                    fail = _FAILS[pick(w)]
                    if fail == "timeout":
                        turns = 30
                    elif fail == "loop":
                        turns = _js_round(_clamp(11 + gauss() * 3.5, 7, 26))
                    elif fail == "invalid SMILES":
                        turns = _js_round(_clamp(7 + gauss() * 2.5, 3, 16))
                    elif fail == "tool error":
                        turns = _js_round(_clamp(8 + gauss() * 3, 2, 20))
                    else:
                        turns = _js_round(_clamp(9 + gauss() * 3, 4, 20))
                noise = math.exp(gauss() * 0.12)
                tok_in = _js_round((turns * c.c0 + c.g * turns * (turns + 1) / 2) * noise)
                tok_out = _js_round(turns * c.out * math.exp(gauss() * 0.18))
                tool_calls = max(1, _js_round(turns * c.tc + gauss()))
                score_calls = _js_round(turns / 3) if c.id == "scorer" else 0
                wall = turns * c.lat * math.exp(gauss() * 0.15) + tool_calls * 0.55
                wall += score_calls * 6.8
                if fail == "timeout":
                    wall = min(300, max(wall, 150 + rnd() * 150))
                wall = min(wall, 300)
                cost = tok_in / 1e6 * c.pin + tok_out / 1e6 * c.pout
                cost, wall = _fixed(cost, 4), _fixed(wall, 1)
                rows.append(_Attempt(solved, fail, turns, tool_calls, tok_in, tok_out, cost, wall))
            attempts[(c.id, seed)] = rows
    selected = next(
        (
            i
            for i, t in enumerate(targets)
            if not attempts[("scorer", 2)][i].solved
            and attempts[("opus", 1)][i].solved
            and attempts[("opus", 2)][i].solved
            and 5 <= t.depth <= 7
        ),
        136,
    )
    scorer = next(c for c in _AGENT_CONFIGS if c.id == "scorer")
    tok_in = sum(step[3] for step in _AGENT_TRACE)
    tok_out = sum(step[4] for step in _AGENT_TRACE)
    attempts[("scorer", 2)][selected] = _Attempt(
        solved=False,
        fail="loop",
        turns=len(_AGENT_TRACE),
        tool_calls=len(_AGENT_TRACE),
        tok_in=tok_in,
        tok_out=tok_out,
        cost=_fixed((tok_in / 1e6) * scorer.pin + (tok_out / 1e6) * scorer.pout, 4),
        wall=_fixed(sum(step[5] for step in _AGENT_TRACE) / 1000, 1),
    )
    return targets, attempts, selected


_AGENT_EVAL_VIEW = """title: cost notes
from: agent_eval
panels:
  - type: markdown
    title: Note
    text: |
      Sonnet 5 + scorer: 0.725 solved@v2 vs 0.742 for Opus 5.5, at a third of the cost.
    layout: {span: 12}
"""


def _seed_agent_eval(sd: _Seeder) -> None:
    """
    Seed ``retro-agents/retro-bench-200`` (kind ``agent_eval``).

    Four configs x three seeds x 200 targets, from ``kinds/agent_eval/data.js``:
    per-example outcomes with failure categories, per-attempt usage, the
    trajectory of one failed attempt, and a custom view.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["agent_eval"]
    targets, attempts, selected = _agent_eval_data()
    dataset = {
        "version": "v2",
        "path": "data/targets.jsonl",
        "splits": {"test": "data/targets.jsonl"},
    }
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="agent_eval",
            dataset=dataset,
            metrics={
                "solved": {
                    "version": "v2",
                    "fn": "demo_metrics:solved",
                    "changelog": {"v2": "route must end in purchasable building blocks"},
                }
            },
            primary="solved",
            description="Valid route to purchasable stock within 30 turns and 300 s.",
        ),
        {
            "data/targets.jsonl": _jsonl(
                {"id": t.id, "reference": None, "depth": t.depth, "class": t.cls} for t in targets
            )
        },
    )
    save_view(repo, task, "cost-notes", _AGENT_EVAL_VIEW)
    ref = DatasetRef(name=task, version="v2", split="test", path=str(repo / dataset["path"]))
    for index, c in enumerate(_AGENT_CONFIGS):
        for seed in (1, 2, 3):
            clock = ("14:02", "14:19", "14:33")[seed - 1]
            created = sd.at(f"2026-09-26T{clock}:{index * 7 + 11:02d}Z")
            command = [*_AGENT_COMMAND, c.model, "--tools", c.tools, "--seed", "{seed}"]
            record, run = sd.start(
                _RunSpec(
                    project=project,
                    task=task,
                    repo=repo,
                    hypothesis=f"{c.short}, tools: {c.tools}",
                    command_template=command,
                    params={"config": c.id, "model": c.model, "tools": c.tools},
                    seed=seed,
                    created_at=created,
                    created_by=c.created_by,
                    host="evalbox-2",
                    commit=c.commit,
                    key=f"{c.id}-{seed}",
                    datasets=[ref],
                )
            )
            rows = attempts[(c.id, seed)]
            run.log_predictions(
                {
                    "id": t.id,
                    "prediction": "route" if a.solved else None,
                    "meta": {"category": a.fail, "difficulty": t.depth, "class": t.cls},
                }
                for t, a in zip(targets, rows, strict=True)
            )
            for t, a in zip(targets, rows, strict=True):
                run.log_usage(
                    tokens_in=a.tok_in,
                    tokens_out=a.tok_out,
                    usd=a.cost,
                    seconds=a.wall,
                    example_id=t.id,
                )
            if c.id == "scorer" and seed == 2:
                run.log_trace(
                    targets[selected].id,
                    (
                        {
                            "turn": turn,
                            "tool": tool,
                            "args": args,
                            "result": result,
                            "tokens_in": tok_in,
                            "tokens_out": tok_out,
                            "seconds": ms / 1000,
                            "error": result if turn == len(_AGENT_TRACE) else None,
                        }
                        for turn, (tool, args, result, tok_in, tok_out, ms) in enumerate(
                            _AGENT_TRACE, start=1
                        )
                    ),
                )
            sd.per_example(
                record,
                "solved@v2",
                {
                    t.id: {
                        "solved": a.solved,
                        "turns": a.turns,
                        "tool_calls": a.tool_calls,
                        "usd": a.cost,
                        "seconds": a.wall,
                    }
                    for t, a in zip(targets, rows, strict=True)
                },
            )
            wall = math.fsum(a.wall for a in rows)
            sd.finish(
                record,
                status=RunStatus.FINISHED,
                ended_at=created + timedelta(seconds=wall / 8),  # eight attempts in parallel
                exit_code=0,
                scores=[("solved", "v2", "value", sum(a.solved for a in rows) / len(rows))],
            )


# --------------------------------------------------------------------- agent_iteration
@dataclass(frozen=True)
class _Version:
    """One agent version of the ``agent_iteration`` mockup."""

    v: str
    at: str
    by: str
    change: str
    commit: str
    prompt: str
    model: str
    temperature: float
    depth: int
    budget: int
    retries: int
    tools: str  # comma-separated


@dataclass(frozen=True)
class _IterRun:
    """One run of the ``agent_iteration`` mockup; ``solved`` is 200 bits as hex."""

    v: str
    seed: int
    started_at: str
    ended_at: str
    cost_usd: float
    tokens_m: float
    tool_calls: int
    solved: str


_ITER_VERSIONS = (
    _Version("v1", "2026-09-13T10:12:00Z", "human:shreyas", "baseline",
             "a031a64b9cbd2a8e81ebf150c9ab0804a710a6a6", "react-1", "gpt-4.1-mini", 0, 4, 40, 1,
             "template_search,route_score,smiles_validate"),
    _Version("v2", "2026-09-14T16:40:00Z", "human:shreyas", "retries 3",
             "6fa2cfdf2f93d4bd34398d373139b5abcfc9acc8", "react-1", "gpt-4.1-mini", 0, 4, 40, 3,
             "template_search,route_score,smiles_validate"),
    _Version("v3", "2026-09-16T11:05:00Z", "agent:iterate", "+stock_check",
             "13c824cb0b7b7d816c843bd761ddc1a4f19a7612", "react-1", "gpt-4.1-mini", 0.6, 4, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v4", "2026-09-17T19:22:00Z", "agent:iterate", "depth 6",
             "50cc29f312390a273e41162f8591d2d98004702a", "react-1", "gpt-4.1-mini", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v5", "2026-09-19T09:48:00Z", "human:shreyas", "gpt-4.1",
             "356483f8954521d87436e67efa04c7e31fc6cc58", "react-1", "gpt-4.1", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v6", "2026-09-21T14:15:00Z", "agent:iterate", "prompt rewrite",
             "e058f3e5a888d5352ee90a3b16e8c5980450b9b9", "concise-2", "gpt-4.1", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v7", "2026-09-22T10:31:00Z", "human:shreyas", "revert prompt",
             "8c02d161c42ce427c0eeb79c9a3956fae5a037f3", "react-1", "gpt-4.1", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check"),
    _Version("v8", "2026-09-24T15:02:00Z", "agent:iterate", "+conditions",
             "1d191070a618a3666e85659d92caba648413e751", "react-1", "gpt-4.1", 0.6, 6, 40, 3,
             "template_search,route_score,smiles_validate,stock_check,condition_predict"),
    _Version("v9", "2026-09-26T13:37:00Z", "agent:iterate", "budget 25",
             "bd4d8132a7bf094731e43e59dc7d747f440a8af3", "react-1", "gpt-4.1", 0.6, 6, 25, 3,
             "template_search,route_score,smiles_validate,stock_check,condition_predict"),
)  # fmt: skip
_ITER_RUNS = (
    _IterRun("v1", 1, "2026-09-13T10:12:00Z", "2026-09-13T12:37:00Z",
             74.28, 119.8, 2780, "50c977ef1695348448c90d5a48c0c50104245a18f4b9b0404e"),
    _IterRun("v1", 2, "2026-09-13T10:17:00Z", "2026-09-13T12:48:00Z",
             79.57, 128.3, 2820, "50c977ef1695348448c90d5a48c0c50104245a18f4b9b0404e"),
    _IterRun("v1", 3, "2026-09-13T10:22:00Z", "2026-09-13T13:11:00Z",
             75.7, 122.1, 2660, "50c977ef1695348448c90d5a48c0c50104245a18f4b9b0404e"),
    _IterRun("v2", 1, "2026-09-14T16:40:00Z", "2026-09-14T19:09:00Z",
             86.68, 139.8, 2640, "5ae177ee1794a48448690d5a40c0c409c425183854fdb4644e"),
    _IterRun("v2", 2, "2026-09-14T16:45:00Z", "2026-09-14T19:36:00Z",
             84.58, 136.4, 2720, "5ae177ee1794a48448690d5a40c0c409c425183854fdb4644e"),
    _IterRun("v2", 3, "2026-09-14T16:52:00Z", "2026-09-14T19:49:00Z",
             82.7, 133.4, 2800, "5ae177ee1794a48448690d5a40c0c409c425183854fdb4644e"),
    _IterRun("v3", 1, "2026-09-16T11:05:00Z", "2026-09-16T13:37:00Z",
             99.34, 160.2, 2820, "dcad77efc695f4c588d989da5cc0d509c6245a3f34ffb45c4e"),
    _IterRun("v3", 2, "2026-09-16T11:11:00Z", "2026-09-16T14:13:00Z",
             94.11, 151.8, 2800, "5cc9f7efc5f5f4c549c9185accc3950bd4241b7d74b7b0761e"),
    _IterRun("v3", 3, "2026-09-16T11:13:00Z", "2026-09-16T14:03:00Z",
             96.53, 155.7, 2780, "56c177efc4f5e4c548f9995a58c09209c6245a3c74bfb556ce"),
    _IterRun("v4", 1, "2026-09-17T19:22:00Z", "2026-09-17T22:09:00Z",
             126.26, 203.6, 3360, "dce977fdd4fcf1e549d9195a4ccadd0b94251a3d74bfb454ce"),
    _IterRun("v4", 2, "2026-09-17T19:26:00Z", "2026-09-17T21:33:00Z",
             119.08, 192.1, 3380, "588f77edc6f4e4e549c99a5a48c0d10b47241b7fb4bbb556ce"),
    _IterRun("v4", 3, "2026-09-17T19:34:00Z", "2026-09-17T22:38:00Z",
             130.13, 209.9, 3480, "dcfb77efd6f7f1e549e99b5a5cc8c50997249bbd34e3b4568e"),
    _IterRun("v5", 1, "2026-09-19T09:48:00Z", "2026-09-19T13:21:00Z",
             160.31, 55.3, 3380, "dcc377ef74f575e549f11bded8d0c50bd4241b3d34ffb57ece"),
    _IterRun("v5", 2, "2026-09-19T09:54:00Z", "2026-09-19T13:19:00Z",
             186.12, 64.2, 3320, "dceff7efc2f5fcc5c9e98d5e5cd6d58bc7249bfff4bf355676"),
    _IterRun("v5", 3, "2026-09-19T10:00:00Z", "2026-09-19T13:11:00Z",
             177.98, 61.4, 3420, "5cabffef74f5fcc549fd185a58d3d40bc7259bbe76bfb574fe"),
    _IterRun("v6", 1, "2026-09-21T14:15:00Z", "2026-09-21T17:35:00Z",
             178.2, 61.4, 3380, "dced77ef44f4e5c549f98dca48805509d6249a3f74fbb574fe"),
    _IterRun("v6", 2, "2026-09-21T14:21:00Z", "2026-09-21T18:02:00Z",
             180.95, 62.4, 3440, "dee9ffefc4d5f5c549d9195a4ccad50b67259a3ef4adb474ee"),
    _IterRun("v6", 3, "2026-09-21T14:25:00Z", "2026-09-21T17:53:00Z",
             181.19, 62.5, 3440, "dce9ffefe0d5a7c558fd9f5a4cc0841b46641a3ef4bdb07c4e"),
    _IterRun("v7", 1, "2026-09-22T10:31:00Z", "2026-09-22T13:11:00Z",
             168.62, 58.1, 3480, "5de7ffefc6f5f5e549c98b5e4cd8d48be4245b3eb4bfb57ece"),
    _IterRun("v7", 2, "2026-09-22T10:35:00Z", "2026-09-22T14:08:00Z",
             178.66, 61.6, 3420, "dcaf77efc6f5f5c5c9f91f5e58c8d58bd4259b3f94ef3176ce"),
    _IterRun("v7", 3, "2026-09-22T10:39:00Z", "2026-09-22T13:33:00Z",
             185.94, 64.1, 3300, "dceb7ffff6f5e7c549e91b5e5cd0d61bc620da7cf4ffb17ffe"),
    _IterRun("v8", 1, "2026-09-24T15:02:00Z", "2026-09-24T18:28:00Z",
             167.77, 57.9, 3260, "dcc377eff6bff5e549f99b5e58dbd58bf425db7e74bfb576ce"),
    _IterRun("v8", 2, "2026-09-24T15:06:00Z", "2026-09-24T18:04:00Z",
             177.12, 61.1, 3300, "dccd7ffff6f5fce549f91f5e58cbd58bd7259afffcffb576ee"),
    _IterRun("v8", 3, "2026-09-24T15:10:00Z", "2026-09-24T18:29:00Z",
             188.06, 64.8, 3280, "5efd7feff6f5e7e748e19f5e4c96d72bf5249b7ef4fffd76ee"),
    _IterRun("v9", 1, "2026-09-26T13:37:00Z", "2026-09-26T16:16:00Z",
             137.35, 47.4, 2260, "dcef7fefb7f5adc5c8f99fda58c5d58bf4259aff14bfb576ee"),
    _IterRun("v9", 2, "2026-09-26T13:41:00Z", "2026-09-26T16:51:00Z",
             148.21, 51.1, 2280, "d8efffefe6bde5e549f99f5a5cdadde9d424dbfff4bfbd76fe"),
    _IterRun("v9", 3, "2026-09-26T13:47:00Z", "2026-09-26T17:20:00Z",
             141.58, 48.8, 2320, "58cf7feff69de4e548f99b5e5cdad789d4a5dbfdf4ffb576ee"),
)  # fmt: skip
_ITER_DETAIL_FAILS = (
    "2T 6N 7B 10S 11B 14B 16S 36S 39N 44N 46N 54B 55N 59I 60N 62B 64B 66N 67S 69I 70S "
    "77S 78I 80N 81N 82S 88N 90S 95N 96N 98N 101N 102N 103N 106B 107N 109S 114N 116B "
    "118B 121S 122N 123N 125B 130N 132I 136N 137N 139I 140B 142B 145S 146N 149N 151I "
    "166N 167I 177N 180S 182S 184S 188B 191N 195N 199N"
)
_ITER_DETAIL_STEPS = (
    "15 14 29 8 17 10 19 40 15 14 11 40 10 12 40 12 21 7 7 14 9 19 10 7 7 8 13 14 16 "
    "19 16 11 7 8 11 15 24 15 10 12 7 10 9 9 23 23 14 14 8 10 12 19 14 16 40 17 22 11 "
    "15 8 11 23 40 16 40 15 22 13 21 4 12 17 16 17 9 9 8 12 8 17 18 21 17 9 11 8 15 9 "
    "19 20 10 13 8 16 15 18 15 10 15 18 13 19 18 13 17 12 40 10 9 20 22 16 9 13 10 13 "
    "40 19 40 11 8 19 19 22 17 40 10 8 15 14 12 9 9 13 18 12 17 15 8 7 40 16 40 17 7 "
    "22 21 15 10 19 8 5 17 17 16 12 14 10 13 15 14 14 16 15 14 10 14 6 11 14 8 13 14 "
    "8 14 14 11 15 17 21 17 13 13 11 13 12 18 18 40 11 5 12 10 14 12 14 10 14 14 14"
)
_ITER_TRACE: tuple[tuple[str, str, str, float, float], ...] = (
    ("template_search", "target", "12 templates", 12.4, 1.8),
    ("route_score", "amide disconnection", "0.81", 14.1, 0.9),
    ("stock_check", "OC(=O)c1ccc(F)cc1", "in stock", 15, 0.3),
    ("stock_check", "NC1CCN(Cc2ccc(OC)cc2)CC1", "not in stock", 15.9, 0.3),
    ("template_search", "NC1CCN(Cc2ccc(OC)cc2)CC1", "9 templates", 17.6, 1.6),
    ("route_score", "reductive amination", "0.77", 19, 0.8),
    ("stock_check", "COc1ccc(C=O)cc1", "in stock", 19.9, 0.3),
    ("stock_check", "CC(C)(C)OC(=O)NC1CCNCC1", "in stock", 20.8, 0.3),
    ("condition_predict", "reductive amination", "NaBH(OAc)3, DCE", 22.5, 1.2),
    ("condition_predict", "amide coupling", "HATU, DIPEA, DMF", 24.1, 1.1),
    ("submit", "route, depth 3", "solved", 25.3, 0.6),
)
_ITER_DETAIL = ("v8", 2)  # the run shown on the run page
_ITER_FAIL_CODES = {
    "T": "timeout",
    "N": "no route",
    "B": "budget hit",
    "S": "not in stock",
    "I": "invalid SMILES",
}


def _bits(solved_hex: str) -> list[bool]:
    """
    Decode 200 per-target outcomes from hex.

    Parameters
    ----------
    solved_hex : str
        50 hex digits; the most significant bit is target 1.

    Returns
    -------
    list of bool

    Examples
    --------
    >>> _bits("8" + "0" * 49)[:2]
    [True, False]
    """
    return [bit == "1" for bit in f"{int(solved_hex, 16):0200b}"]


def _seed_agent_iteration(sd: _Seeder) -> None:
    """
    Seed ``retro-agent/retro-bench-200`` (kind ``agent_iteration``).

    Nine versions x three seeds with the exact per-target outcomes, costs, and
    tokens of ``kinds/agent_iteration/data.js``; the v8 seed 2 run also has
    failure categories, step counts, and one trajectory.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["agent_iteration"]
    ids = [f"T-{i + 1:03d}" for i in range(200)]
    dataset = {
        "version": "v2",
        "host": "gpu-07",
        "path": "/data/retro-bench-200/targets.jsonl",
        "splits": {"test": "/data/retro-bench-200/targets.jsonl"},
    }
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="agent_iteration",
            dataset=dataset,
            metrics={"solved": {"version": "v2", "fn": "demo_metrics:solved"}},
            primary="solved",
            description="Route found and verified for each of 200 targets.",
            version_param="version",
        ),
        {},
    )
    ref = DatasetRef(
        name=task, version="v2", split="test", host="gpu-07", path=dataset["splits"]["test"]
    )
    fails = {
        ids[int(item[:-1])]: _ITER_FAIL_CODES[item[-1]]
        for item in "".join(_ITER_DETAIL_FAILS).split()
    }
    steps = [int(n) for n in "".join(_ITER_DETAIL_STEPS).split()]
    versions = {v.v: v for v in _ITER_VERSIONS}
    for spec in _ITER_RUNS:
        v = versions[spec.v]
        created = sd.at(spec.started_at)
        ended = sd.at(spec.ended_at)
        record, run = sd.start(
            _RunSpec(
                project=project,
                task=task,
                repo=repo,
                hypothesis=v.change,
                command_template=["python", "-m", "retro_agent.run", "--seed", "{seed}"],
                params={
                    "version": v.v,
                    "model": v.model,
                    "prompt": v.prompt,
                    "tools": v.tools,
                    "temperature": str(v.temperature),
                    "depth": str(v.depth),
                    "budget": str(v.budget),
                    "retries": str(v.retries),
                },
                seed=spec.seed,
                created_at=created,
                created_by=v.by,
                host="gpu-07",
                commit=v.commit,
                key=f"{v.v}-{spec.seed}",
                datasets=[ref],
            )
        )
        solved = _bits(spec.solved)
        detail = (spec.v, spec.seed) == _ITER_DETAIL
        run.log_predictions(
            {
                "id": ex,
                "prediction": "route" if ok else None,
                "meta": {"category": fails.get(ex), "steps": steps[i]} if detail else {},
            }
            for i, (ex, ok) in enumerate(zip(ids, solved, strict=True))
        )
        run.log_usage(
            tokens_in=round(spec.tokens_m * 1e6),
            usd=spec.cost_usd,
            seconds=(ended - created).total_seconds(),
        )
        run.log({"tool_calls": spec.tool_calls}, step=0)
        if detail:
            run.log_trace(
                ids[34],
                (
                    {
                        "turn": turn,
                        "tool": tool,
                        "args": args,
                        "result": result,
                        "tokens_in": round(k_tokens * 1000),
                        "tokens_out": 0,
                        "seconds": seconds,
                        "error": None,
                    }
                    for turn, (tool, args, result, k_tokens, seconds) in enumerate(
                        _ITER_TRACE, start=1
                    )
                ),
            )
        sd.per_example(
            record, "solved@v2", {ex: {"solved": ok} for ex, ok in zip(ids, solved, strict=True)}
        )
        sd.finish(
            record,
            status=RunStatus.FINISHED,
            ended_at=ended,
            exit_code=0,
            scores=[("solved", "v2", "value", sum(solved) / len(solved))],
        )


# --------------------------------------------------------------------- system_bench
def _f32(x: float) -> float:
    """
    Round to single precision, like storing into a JavaScript ``Float32Array``.

    Parameters
    ----------
    x : float
        Value to round.

    Returns
    -------
    float
    """
    return struct.unpack("f", struct.pack("f", x))[0]


_SB_REQUESTS, _SB_WARMUP, _SB_CONCURRENCY, _SB_TIMEOUT_MS = 5000, 200, 16, 1000
_SB_VERSIONS = {
    "baseline": ("baseline", "main", "a1b2c3d9e8f70615", "human", "main@a1b2"),
    "cache": ("cache-enabled", "feat/route-cache", "c7e41f02b6a95d38", "agent:bench", "LRU 50k"),
    "async": (
        "async-worker", "feat/async-worker", "9d03b5e4417ac2f0", "agent:bench",
        "4 workers, batch 8",
    ),
}  # fmt: skip
_SB_SERVER = {
    "baseline": "uvicorn app:app --workers 1",
    "cache": "uvicorn app:app --workers 1 --route-cache 50000",
    "async": "uvicorn app:app --workers 4 --batch 8",
}
_SB_ERR503 = {"baseline": 0.0, "cache": 0.0, "async": 0.0008}
_SB_GPU_PER_RPS = {"baseline": 0.372, "cache": 0.372, "async": 0.452}
_SB_CPU_BASE = {"baseline": 23, "cache": 16, "async": 31}
_SB_CPU_PER_RPS = {"baseline": 0.145, "cache": 0.062, "async": 0.178}
_SB_XMAX = {"baseline": 196, "cache": 520, "async": 312}
_SB_CONC = (1, 2, 4, 8, 16, 32, 64, 128)
_SB_COMMAND: str = (
    "python bench/load.py --url http://127.0.0.1:8080/v2/route -n 5000 -c 16 --warmup 200 "
    "--seed {seed}"
)
# version, repeat, created_at, drift, noisy neighbour (t0, t1, cpu steal %, slowdown)
_SB_RUNS: tuple[tuple[str, int, str, float, tuple[float, float, float, float] | None], ...] = (
    ("baseline", 1, "2026-09-27T09:12:04Z", 1.004, None),
    ("baseline", 2, "2026-09-27T09:14:12Z", 0.991, None),
    ("baseline", 3, "2026-09-27T09:16:20Z", 1.009, None),
    ("cache", 1, "2026-09-27T09:30:45Z", 0.996, None),
    ("cache", 2, "2026-09-27T09:32:33Z", 1.007, None),
    ("cache", 3, "2026-09-27T09:34:21Z", 1.002, (5.5, 12.0, 23, 2.1)),
    ("async", 1, "2026-09-27T09:50:10Z", 0.998, None),
    ("async", 2, "2026-09-27T09:51:58Z", 1.006, None),
    ("async", 3, "2026-09-27T09:53:46Z", 0.993, None),
)


@dataclass
class _Bench:
    """Raw samples and 1 Hz utilisation of one benchmark run."""

    t: list[float]
    lat: list[float]
    err: list[int]
    hit: list[bool]
    duration: float
    cpu: list[float]
    gpu: list[float]
    mem: list[float]
    steal: list[float]


def _lognormal(draw: Callable[[], float], median: float, sigma: float) -> float:
    """
    Draw a log-normal value with the given median.

    Parameters
    ----------
    draw : callable
        Uniform generator.
    median, sigma : float
        Median and log-scale spread.

    Returns
    -------
    float
    """
    return median * math.exp(sigma * _gauss(draw))


def _latency(vid: str, draw: Callable[[], float], t: float) -> tuple[float, bool]:
    """
    Draw one request latency (ms) and whether the route cache was hit.

    Parameters
    ----------
    vid : str
        Version id.
    draw : callable
        Uniform generator.
    t : float
        Seconds since measurement start (the cache warms up).

    Returns
    -------
    tuple of (float, bool)
    """
    if vid == "cache":
        if draw() < 0.66 - 0.28 * math.exp(-t / 2.5):
            return _lognormal(draw, 14, 0.35), True
        extra = 80 + 140 * draw() if draw() < 0.006 else 0
        return extra + _lognormal(draw, 124, 0.40), False
    if vid == "async":
        extra = 60 + 90 * draw() if draw() < 0.003 else 0
        return extra + _lognormal(draw, 104, 0.28), False
    extra = 80 + 140 * draw() if draw() < 0.006 else 0
    return extra + _lognormal(draw, 118, 0.40), False


def _simulate(
    vid: str, seed: int, drift: float, noisy: tuple[float, float, float, float] | None
) -> _Bench:
    """
    Port of the ``system_bench`` mockup's closed-loop load simulation.

    Parameters
    ----------
    vid : str
        Version id.
    seed : int
        RNG seed.
    drift : float
        Multiplier on every latency (run-to-run drift).
    noisy : tuple or None
        Noisy-neighbour window ``(t0, t1, steal, slowdown)``.

    Returns
    -------
    _Bench
    """
    r = _mulberry32(seed)
    free = [0.0] * _SB_CONCURRENCY
    t: list[float] = []
    lat: list[float] = []
    err: list[int] = []
    hit: list[bool] = []
    t_start = 0.0
    for i in range(_SB_REQUESTS + _SB_WARMUP):
        w = 0
        for j in range(1, _SB_CONCURRENCY):
            if free[j] < free[w]:
                w = j
        s = free[w]
        if i == _SB_WARMUP:
            t_start = s
        tm = s - t_start if i >= _SB_WARMUP else 0.0
        ms, h = _latency(vid, r, tm)
        ms *= drift
        if noisy is not None and noisy[0] <= tm <= noisy[1]:
            ms *= 1 + (noisy[3] - 1) * 0.55 if h else noisy[3] * (0.85 + 0.3 * r())
            if r() < 0.015:
                ms += 600 + 300 * r()
        e = 0
        if ms > _SB_TIMEOUT_MS:
            ms, e = float(_SB_TIMEOUT_MS), 1
        elif r() < _SB_ERR503[vid]:
            ms, e = 2 + 3 * r(), 2
        free[w] = s + ms / 1000 + 0.0004
        if i >= _SB_WARMUP:
            t.append(_f32(free[w] - t_start))
            lat.append(_f32(ms))
            err.append(e)
            hit.append(h)
    duration = max(t)
    r = _mulberry32(seed ^ 0x5BD1E995)
    n = math.ceil(duration)
    done, gpu_req = [0] * n, [0] * n
    for ti, h in zip(t, hit, strict=True):
        b = min(n - 1, math.floor(ti))
        done[b] += 1
        if not h:
            gpu_req[b] += 1
    cpu, gpu, mem, steal = [], [], [], []
    cached = 0
    for s in range(n):
        frac = max(0.2, duration - s) if s == n - 1 else 1
        rps, grps = done[s] / frac, gpu_req[s] / frac
        in_nn = noisy is not None and noisy[0] <= s + 0.5 <= noisy[1]
        if noisy is not None and in_nn:
            steal.append(_fixed(noisy[2] + 3 * _gauss(r), 1))
        else:
            steal.append(_fixed(0.3 + 0.25 * r(), 1))
        load = _SB_CPU_BASE[vid] + _SB_CPU_PER_RPS[vid] * rps + 1.6 * _gauss(r)
        cpu.append(_fixed(min(99, load + (9 if in_nn else 0)), 1))
        gpu.append(_fixed(min(99, _SB_GPU_PER_RPS[vid] * grps + 1.8 * _gauss(r)), 1))
        if vid == "cache":
            cached += gpu_req[s]
        base = 7.0 if vid == "async" else 6.1
        grown = cached * 0.00082 if vid == "cache" else 0
        mem.append(_fixed(base + grown + 0.04 * _gauss(r), 2))
    return _Bench(t, lat, err, hit, duration, cpu, gpu, mem, steal)


def _sweep(vid: str, vi: int, clean: list[_Bench]) -> list[tuple[int, float]]:
    """
    Port of the mockup's concurrency sweep: throughput (req/s) per concurrency.

    Parameters
    ----------
    vid : str
        Version id.
    vi : int
        Version index (RNG seed offset).
    clean : list of _Bench
        The version's repeats without a noisy neighbour; the curve passes
        through their mean throughput at concurrency 16.

    Returns
    -------
    list of (int, float)
    """
    r = _mulberry32(777 + vi)
    k = 3.2

    def throughput(c: int, r0: float) -> float:
        return 1 / math.pow(math.pow(r0 / c, k) + math.pow(1 / _SB_XMAX[vid], k), 1 / k)

    x16 = 0.0
    for b in clean:
        x16 += sum(1 for e in b.err if not e) / _fixed(b.duration, 2)
    x16 /= len(clean)
    lo, hi = 0.001, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if throughput(16, mid) > x16:
            lo = mid
        else:
            hi = mid
    r0 = (lo + hi) / 2
    return [
        (c, _fixed(x16 if c == 16 else throughput(c, r0) * (1 + 0.012 * _gauss(r)), 1))
        for c in _SB_CONC
    ]


def _seed_system_bench(sd: _Seeder) -> None:
    """
    Seed ``route-search/route-api-latency`` (kind ``system_bench``).

    Three versions x three repeats of 5,000 requests from
    ``kinds/system_bench/data.js``: raw latency samples, 1 Hz utilisation, a
    concurrency sweep on each third repeat, and one failed first attempt
    (server not ready) before cache repeat 3.

    Parameters
    ----------
    sd : _Seeder
        Target home.
    """
    project, task = DEMO_TASKS["system_bench"]
    dataset = {
        "version": "v1",
        "path": "bench/requests.jsonl",
        "splits": {"test": "bench/requests.jsonl"},
    }
    lower = {"higher_is_better": False, "fn": "demo_metrics:harness", "version": "v1"}
    repo = sd.project(
        _task_config(
            project,
            task,
            kind="system_bench",
            dataset=dataset,
            metrics={
                "latency": lower,
                "errors": lower,
                "throughput": {"version": "v1", "fn": "demo_metrics:harness"},
            },
            primary="latency/p95",
            description="POST /v2/route, 5,000 requests after 200 warm-up, concurrency 16.",
            baseline="tag:baseline",
        ),
        {"bench/requests.jsonl": _jsonl({"id": f"q{i}", "reference": None} for i in range(3))},
    )
    ref = DatasetRef(name=task, version="v1", split="test", path=str(repo / dataset["path"]))
    clean: dict[str, list[_Bench]] = {}  # repeats without a noisy neighbour
    for i, (vid, rep, stamp, drift, noisy) in enumerate(_SB_RUNS):
        bench = _simulate(vid, 9001 + i * 7919, drift, noisy)
        if noisy is None:
            clean.setdefault(vid, []).append(bench)
        name, branch, commit, by, note = _SB_VERSIONS[vid]
        created = sd.at(stamp)
        spec = _RunSpec(
            project=project,
            task=task,
            repo=repo,
            hypothesis=f"{name}: {note}",
            command_template=_SB_COMMAND.split(),
            params={"version": vid, "server": _SB_SERVER[vid], "concurrency": "16"},
            seed=rep,
            created_at=created,
            created_by=by,
            host="gpu-box-1",
            commit=commit,
            branch=branch,
            key=f"{vid}-{rep}",
            tags=["baseline"] if vid == "baseline" else [],
            datasets=[ref],
        )
        if noisy is not None:  # the first attempt died before the server came up
            first_try = replace(
                spec, created_at=created - timedelta(seconds=10), key=f"{vid}-{rep}-1"
            )
            failed, _ = sd.start(first_try)
            sd.finish(
                failed,
                status=RunStatus.FAILED,
                ended_at=failed.created_at + timedelta(seconds=2.1),
                exit_code=1,
                stderr="server not ready: connect :8080 refused\n",
            )
        record, run = sd.start(spec)
        run.log_samples("latency_ms", bench.lat)
        for s, values in enumerate(zip(bench.cpu, bench.gpu, bench.mem, bench.steal, strict=True)):
            cpu, gpu, mem, steal = values
            run.log({"cpu_pct": cpu, "gpu_pct": gpu, "mem_gb": mem, "steal_pct": steal}, step=s)
        per_second: dict[int, list[float]] = {}
        for ti, ms in zip(bench.t, bench.lat, strict=True):
            per_second.setdefault(math.floor(ti), []).append(ms)
        for s in sorted(per_second):
            run.log({"latency_p95_ms": quantile(per_second[s], 0.95)}, step=s)
        if rep == 3:  # the sweep ran after the third repeat
            for c, rps in _sweep(vid, list(_SB_VERSIONS).index(vid), clean[vid]):
                run.log({"sweep/rps": rps}, step=c)
        ok = sum(1 for e in bench.err if not e)
        duration = _fixed(bench.duration, 2)
        sd.finish(
            record,
            status=RunStatus.FINISHED,
            ended_at=created + timedelta(seconds=duration + 6.4),
            exit_code=0,
            scores=[
                ("latency", "v1", "p50", quantile(bench.lat, 0.50)),
                ("latency", "v1", "p95", quantile(bench.lat, 0.95)),
                ("latency", "v1", "p99", quantile(bench.lat, 0.99)),
                ("errors", "v1", "rate", (len(bench.err) - ok) / len(bench.err)),
                ("throughput", "v1", "rps", ok / duration),
            ],
        )


# --------------------------------------------------------------------- entry point
_SEEDERS: dict[str, Callable[[_Seeder], None]] = {
    "generic": _seed_generic,
    "training": _seed_training,
    "agent_eval": _seed_agent_eval,
    "agent_iteration": _seed_agent_iteration,
    "system_bench": _seed_system_bench,
}


def _seed_demo(home: Path, kinds: Iterable[str], anchor: datetime) -> dict[str, str]:
    """
    Seed the demo with every timestamp placed relative to ``anchor``.

    Parameters
    ----------
    home : Path
        Hypothex home to write into.
    kinds : iterable of str
        Task kinds to seed.
    anchor : datetime
        Where ``DEMO_EPOCH`` lands. The same anchor gives the same run ids and data.

    Returns
    -------
    dict of str to str
        ``{kind: "project/task"}`` in the order given.

    Raises
    ------
    ValueError
        For an unknown kind.
    StoreError
        If a demo project already exists in ``home`` (nothing is written).
    """
    wanted = list(dict.fromkeys(kinds))
    unknown = [k for k in wanted if k not in _SEEDERS]
    if unknown:
        raise ValueError(f"unknown demo kinds {unknown}; choose from {list(KINDS)}")
    ctx = Context.open(home)
    for kind in wanted:
        project = DEMO_TASKS[kind][0]
        if ctx.layout.project_dir(project).exists():
            raise StoreError(
                f"demo project {project!r} already exists in {ctx.layout.home}; "
                "seed the demo into an empty HYPOTHEX_HOME"
            )
    seeder = _Seeder(ctx, anchor)
    for kind in wanted:
        _SEEDERS[kind](seeder)
    return {kind: "/".join(DEMO_TASKS[kind]) for kind in wanted}


def seed_demo(home: Path, kinds: Iterable[TaskKind] = KINDS) -> dict[str, str]:
    """
    Write demo projects and runs for the given task kinds into ``home``.

    Timestamps keep the mockups' distance to ``DEMO_EPOCH`` but are moved so
    that ``DEMO_EPOCH`` falls on the current hour; the Overview's default 24-hour
    window therefore always shows recent runs. Within one hour the output is
    identical; the numbers never change.

    Parameters
    ----------
    home : Path
        Hypothex home (created if missing). Demo repos go to ``<home>/demo-repos/``.
    kinds : iterable of TaskKind
        Which kinds to seed; default all five.

    Returns
    -------
    dict of str to str
        ``{kind: "project/task"}``.

    Raises
    ------
    ValueError
        For an unknown kind.
    StoreError
        If a demo project already exists in ``home``.

    Examples
    --------
    >>> import pathlib, tempfile
    >>> seed_demo(pathlib.Path(tempfile.mkdtemp()), kinds=["generic"])
    {'generic': 'toy-classifier/toy-test'}
    """
    anchor = utcnow().replace(minute=0, second=0, microsecond=0)
    return _seed_demo(home, kinds, anchor)


# --------------------------------------------------------------------- fake hosts
DEMO_HOSTS_DIR = "demo-hosts"
DEMO_HOSTS_FILE = "hosts.json"
DEMO_SWEEP_ID = "s-7f3a"
DEMO_SLEEP_ENV = "HX_DEMO_SLEEP"
_LIVE_RUNS_FILE = "live-runs.json"  # in <home>/demo-hosts: the run ids `hx serve` launched
_PLACEHOLDER_URL = "http://127.0.0.1:9"  # `hx serve` rewrites it when it starts the hosts
_DEMO_GPU_RATE = 1.10
_DEMO_SLURM_RATE = 0.50
_SWEEP_HYPOTHESIS = "lr x beam: find the best beam width for each learning rate"
_SWEEP_COMMAND = [
    "python", "train.py", "--config", "configs/aug.yaml",
    "--lr", "{lr}", "--beam", "{beam}", "--seed", "{seed}",
]  # fmt: skip
_LONG_COMMAND = [
    "python", "train.py", "--config", "configs/aug.yaml", "--steps", "40000", "--seed", "{seed}",
]  # fmt: skip
_SWEEP_LRS = ("1e-4", "3e-4", "1e-3")
_SWEEP_BEAMS = ("1", "5", "10")
# phase2/data.js `grid`: per (lr, beam), seeds 1..3 as (state, top-1). "f" finished and
# "x" failed are seeded on gpu1; "r" and "q" are launched live by `hx serve`.
_SWEEP_GRID: dict[tuple[str, str], tuple[tuple[str, float | None], ...]] = {
    ("1e-4", "1"): (("f", 0.8917), ("f", 0.8931), ("f", 0.8915)),
    ("1e-4", "5"): (("f", 0.8979), ("f", 0.8992), ("f", 0.8990)),
    ("1e-4", "10"): (("f", 0.8996), ("r", None), ("q", None)),
    ("3e-4", "1"): (("f", 0.9046), ("f", 0.9031), ("f", 0.9052)),
    ("3e-4", "5"): (("f", 0.9101), ("f", 0.9117), ("f", 0.9106)),
    ("3e-4", "10"): (("f", 0.9118), ("f", 0.9130), ("f", 0.9115)),
    ("1e-3", "1"): (("f", 0.8806), ("f", 0.8829), ("q", None)),
    ("1e-3", "5"): (("f", 0.8871), ("r", None), ("q", None)),
    ("1e-3", "10"): (("f", 0.8880), ("r", None), ("x", None)),
}
_TRAIN_PY = '''"""Demo stand-in for train.py: sleeps so the run stays running."""
import os
import time

time.sleep(float(os.environ.get("HX_DEMO_SLEEP", "900")))
'''
# demo stand-ins: `.jobs` holds queued jobs as `id|comment` (they stay PENDING, nothing
# runs); `scancel` moves a job to `.cancelled`, which `sacct` reports as CANCELLED. The
# lock waits at most 5 s, so a lock left by a killed script never blocks the demo.
_FAKE_SLURM_LOCK = (
    'd="$(dirname "$0")"\n'
    "i=0\n"
    'while ! mkdir "$d/.lock" 2>/dev/null && [ "$i" -lt 100 ]; do i=$((i + 1)); sleep 0.05; done\n'
    "trap 'rmdir \"$d/.lock\"' EXIT\n"
)
_FAKE_SLURM = {
    "sbatch": (
        "#!/bin/sh\n"
        "# demo stand-in: queue the job (it stays PENDING), print its id, run nothing\n"
        + _FAKE_SLURM_LOCK
        + 'comment=""\n'
        'for a in "$@"; do case "$a" in --comment=*) comment="${a#--comment=}";; esac; done\n'
        'n=$(cat "$d/.jobid" 2>/dev/null || echo 48213000)\n'
        "n=$((n + 1))\n"
        'echo "$n" > "$d/.jobid"\n'
        'echo "$n|$comment" >> "$d/.jobs"\n'
        'echo "$n"\n'
    ),
    "squeue": (
        "#!/bin/sh\n"
        "# demo stand-in: every queued job is PENDING on no node\n"
        'd="$(dirname "$0")"\n'
        '[ -f "$d/.jobs" ] || exit 0\n'
        "while IFS='|' read -r id comment; do\n"
        '  case "$*" in *%k*) echo "$id|PENDING||$comment";; *) echo "$id|PENDING|";; esac\n'
        'done < "$d/.jobs"\n'
    ),
    "sacct": (
        "#!/bin/sh\n"
        "# demo stand-in: only cancelled jobs have accounting records\n"
        'd="$(dirname "$0")"\n'
        '[ -f "$d/.cancelled" ] || exit 0\n'
        'row="CANCELLED by 0|0:0|None assigned"\n'
        "while IFS='|' read -r id comment; do\n"
        '  case "$*" in *Comment*) echo "$id|$row|$comment";; *) echo "$id|$row";; esac\n'
        'done < "$d/.cancelled"\n'
    ),
    "scancel": (
        "#!/bin/sh\n"
        "# demo stand-in: a queued job leaves the queue as CANCELLED; others are ignored\n"
        + _FAKE_SLURM_LOCK
        + 'for a in "$@"; do case "$a" in -*) ;; *) id="$a";; esac; done\n'
        'job=$(grep "^$id|" "$d/.jobs" 2>/dev/null) || exit 0\n'
        'grep -v "^$id|" "$d/.jobs" > "$d/.jobs.new"\n'
        'mv "$d/.jobs.new" "$d/.jobs"\n'
        'echo "$job" >> "$d/.cancelled"\n'
    ),
    "scontrol": (
        "#!/bin/sh\n# demo stand-in: accounting keeps job comments\n"
        'echo "AccountingStoreFlags    = job_comment"\n'
    ),
}


class _DemoHost(BaseModel):
    """One fake host, as listed in ``<home>/demo-hosts/hosts.json``."""

    name: str
    kind: str
    home: str
    repo: str
    fake_gpus: str | None = None
    bin: str | None = None


def _fake_gpu_rows() -> list[dict[str, Any]]:
    """
    Eight A100s for gpu1; GPUs 3 and 7 are busy with other users' processes.

    Returns
    -------
    list of dict
        ``GpuInfo`` objects as JSON.
    """
    outside = {3: (63.0, 33600), 7: (9.0, 14700)}
    return [
        {
            "index": i,
            "name": "NVIDIA A100 80GB",
            "util": outside.get(i, (0.0, 0))[0],
            "mem_used_mb": outside.get(i, (0.0, 0))[1],
            "mem_total_mb": 81920,
            "external": i in outside,
            "run_id": None,
        }
        for i in range(8)
    ]


def _demo_host_home(root: Path, name: str, hub_repo: Path) -> tuple[Context, Path]:
    """
    Create a fake host's home (labelled ``name``) with a copy of the demo repo.

    Parameters
    ----------
    root : Path
        ``<hub home>/demo-hosts``.
    name : str
        Host name; also the environment label.
    hub_repo : Path
        The hub's demo repo to copy (plus a sleeping ``train.py``).

    Returns
    -------
    tuple of (Context, Path)
        The host's context and its checkout.
    """
    home = root / name
    ctx = Context.open(home)
    identity = json.loads(ctx.layout.environment_json.read_text(encoding="utf-8"))
    identity["label"] = name
    atomic_write_text(ctx.layout.environment_json, json.dumps(identity, indent=2))
    ctx = Context.open(home)
    repo = home / "repos" / hub_repo.name
    shutil.copytree(hub_repo, repo)
    atomic_write_text(repo / "train.py", _TRAIN_PY)
    ctx.register_project(repo)
    return ctx, repo


def _host_run(
    ctx: Context,
    *,
    repo: Path,
    host: str,
    kind: str,
    command_template: list[str],
    params: dict[str, str],
    seed: int,
    created_at: datetime,
    minutes: int,
    status: RunStatus,
    exit_code: int | None,
    hypothesis: str,
    created_by: str,
    rate: float,
    sweep_id: str | None = None,
    sweep_owner: str = "",
    end_reason: str | None = None,
    slurm_job: str | None = None,
    node: str | None = None,
) -> RunRecord:
    """
    Create one finished-state run on a fake host (2 GPUs, cost filled in).

    Returns
    -------
    RunRecord
        The created record.
    """
    project, task = DEMO_TASKS["training"]
    digest = hashlib.sha256(f"{host}|{sorted(params.items())}|{seed}".encode()).hexdigest()[:4]
    run_id = new_run_id(task, now=created_at).rsplit("-", 1)[0] + f"-{digest}"
    values = {**params, "seed": str(seed)}
    fingerprint = run_fingerprint(
        command_template=command_template,
        stage=None,
        user_config=None,
        params=params,
        vars=params,
    )
    record = RunRecord(
        run_id=run_id,
        project=project,
        task=task,
        hypothesis=hypothesis,
        command=[render_template(part, values) for part in command_template],
        command_template=list(command_template),
        vars=dict(params),
        params=dict(params),
        cwd=str(repo),
        environment_id=ctx.descriptor.environment_id,
        host=host,
        executor=ExecutorInfo(type=kind, host=host, gpus=[0, 1], slurm_job_id=slurm_job, node=node),
        git=GitInfo(commit="b82f04c", branch="main"),
        seed=seed,
        config_hash=config_hash(fingerprint),
        status=status,
        created_at=created_at,
        started_at=created_at,
        ended_at=created_at + timedelta(minutes=minutes),
        end_reason=end_reason,
        exit_code=exit_code,
        tags=[sweep_tag(sweep_owner, sweep_id)] if sweep_id else [],
        created_by=created_by,
        sweep_id=sweep_id,
        gpus_requested=2,
    )
    return ctx.create_run(record.model_copy(update={"cost": compute_cost(record, rate)}))


def _score(ctx: Context, record: RunRecord, value: float) -> None:
    ctx.add_score(
        record,
        ScoreRecord(
            metric="top1",
            version="v1",
            key="value",
            value=value,
            created_at=record.ended_at or record.created_at,
        ),
    )


def _seed_gpu1_sweep(ctx: Context, repo: Path, anchor: datetime, owner: str) -> list[str]:
    """Seed the sweep's finished and failed cells on gpu1 (tagged for ``owner``, the hub)."""
    start = anchor - timedelta(hours=5, minutes=20)
    run_ids: list[str] = []
    for (lr, beam), runs in _SWEEP_GRID.items():
        for seed, (state, score) in enumerate(runs, 1):
            if state not in ("f", "x"):
                continue
            failed = state == "x"
            record = _host_run(
                ctx,
                repo=repo,
                host="gpu1",
                kind="ssh",
                command_template=_SWEEP_COMMAND,
                params={"lr": lr, "beam": beam},
                seed=seed,
                created_at=start + timedelta(minutes=4 * len(run_ids)),
                minutes=7 if failed else 48,
                status=RunStatus.FAILED if failed else RunStatus.FINISHED,
                exit_code=1 if failed else 0,
                hypothesis=_SWEEP_HYPOTHESIS,
                created_by="agent:tuner",
                rate=_DEMO_GPU_RATE,
                sweep_id=DEMO_SWEEP_ID,
                sweep_owner=owner,
            )
            if failed:
                atomic_write_text(
                    ctx.run_dir(record) / "logs" / "stderr.log", "loss is NaN at step 3100\n"
                )
            if score is not None:
                _score(ctx, record, score)
            run_ids.append(record.run_id)
    return run_ids


def _seed_cluster_runs(ctx: Context, repo: Path, anchor: datetime) -> list[str]:
    """Seed two SLURM runs on cluster: one finished, one lost to a node failure."""
    common: dict[str, Any] = {
        "repo": repo,
        "host": "cluster",
        "kind": "slurm",
        "command_template": _LONG_COMMAND,
        "params": {},
        "hypothesis": "40k steps lifts +aug past 0.915 top-1",
        "created_by": "human:shreyas",
        "rate": _DEMO_SLURM_RATE,
    }
    done = _host_run(
        ctx,
        seed=1,
        created_at=anchor - timedelta(hours=13),
        minutes=470,
        status=RunStatus.FINISHED,
        exit_code=0,
        slurm_job="48213077",
        node="r209u14n01",
        **common,
    )
    _score(ctx, done, 0.9142)
    lost = _host_run(
        ctx,
        seed=2,
        created_at=anchor - timedelta(hours=12, minutes=40),
        minutes=52,
        status=RunStatus.LOST,
        exit_code=None,
        end_reason="SLURM ended job 48211932 with NODE_FAIL on r208u06n02; no exit record",
        slurm_job="48211932",
        node="r208u06n02",
        **common,
    )
    atomic_write_text(
        ctx.run_dir(lost) / "logs" / "stderr.log",
        "slurmstepd: error: *** JOB 48211932 ON r208u06n02 CANCELLED DUE TO NODE FAILURE ***\n",
    )
    return [done.run_id, lost.run_id]


def seed_demo_hosts(home: Path) -> dict[str, str]:
    """
    Seed two fake hosts and a sweep next to the training demo.

    ``gpu1`` (SSH kind, 8 fake A100s, $1.10/GPU-hour) holds 21 seeded runs of the
    ``lr x beam`` sweep ``s-7f3a``; ``cluster`` (SLURM kind, $0.50/GPU-hour) holds a
    finished and a lost run. The hub gets ``route: url`` entries for both and the
    sweep spec; ``hx serve`` starts the hosts (``demo_hosts_running``).
    The generated training repository and both host copies share an initial Git
    commit containing their configuration and fake training script.

    Parameters
    ----------
    home : Path
        The hub's home; must already hold the training demo.

    Returns
    -------
    dict of str to str
        ``{"gpu1": <home>, "cluster": <home>, "sweep": "rxn-forward/s-7f3a"}``.

    Raises
    ------
    ConfigError
        If the training demo is missing or its registered repository is not the
        generated demo directory.
    StoreError
        If the fake hosts already exist.

    Examples
    --------
    >>> import pathlib, tempfile
    >>> home = pathlib.Path(tempfile.mkdtemp())
    >>> _ = seed_demo(home, kinds=["training"])
    >>> sorted(seed_demo_hosts(home))
    ['cluster', 'gpu1', 'sweep']
    """
    home = home.expanduser().resolve()
    hub = Context.open(home)
    project, task = DEMO_TASKS["training"]
    try:
        entry = hub.store.load_project(project)
    except StoreError as exc:
        raise ConfigError(
            f"--with-hosts needs the training demo ({project}); add --kinds training"
        ) from exc
    root = home / DEMO_HOSTS_DIR
    if root.exists():
        raise StoreError(f"demo hosts already exist in {root}; seed into an empty HYPOTHEX_HOME")
    repo = Path(entry.repo)
    if repo.resolve() != (home / "demo-repos" / project).resolve():
        raise ConfigError("--with-hosts requires the generated training demo repository")
    atomic_write_text(repo / "train.py", _TRAIN_PY)
    # A demo home may be nested in a source checkout (the browser fixture is).
    # Give it its own history before copying so hub pins exist on both fake hosts.
    git = [
        "git", "-C", str(repo), "-c", "core.hooksPath=/dev/null",
        "-c", "commit.gpgSign=false", "-c", "user.name=Hypothex demo",
        "-c", "user.email=demo@hypothex.invalid",
    ]  # fmt: skip
    for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "Seed fake host demo"]):
        subprocess.run([*git, *args], check=True, capture_output=True)
    anchor = utcnow().replace(minute=0, second=0, microsecond=0)
    gpu_ctx, gpu_repo = _demo_host_home(root, "gpu1", repo)
    slurm_ctx, slurm_repo = _demo_host_home(root, "cluster", repo)
    fake_gpus = root / "gpu1-gpus.json"
    atomic_write_text(fake_gpus, json.dumps(_fake_gpu_rows(), indent=2))
    bin_dir = root / "cluster-bin"
    for name, text in _FAKE_SLURM.items():
        atomic_write_text(bin_dir / name, text)
        (bin_dir / name).chmod(0o755)
    owner = hub.descriptor.environment_id  # the hub owns the sweep: its tag names the hub
    _seed_gpu1_sweep(gpu_ctx, gpu_repo, anchor, owner)  # tagged: the sweep's members
    _seed_cluster_runs(slurm_ctx, slurm_repo, anchor)
    save_sweep(
        hub.layout,
        SweepSpec(
            id=DEMO_SWEEP_ID,
            project=project,
            task=task,
            host="gpu1",
            grid=[
                SweepParam(name="lr", values=list(_SWEEP_LRS)),
                SweepParam(name="beam", values=list(_SWEEP_BEAMS)),
            ],
            random=None,
            seeds=[1, 2, 3],
            command_template=list(_SWEEP_COMMAND),
            created_by="agent:tuner",
            created_at=anchor - timedelta(hours=5, minutes=20),
        ),
    )
    hosts = load_hosts(hub.layout)
    environments = {
        **hosts.environments,
        "gpu1": HostSpec(
            route="url",
            url=_PLACEHOLDER_URL,
            kind="ssh",
            usd_per_gpu_hour=_DEMO_GPU_RATE,
            projects={project: str(gpu_repo)},
        ),
        "cluster": HostSpec(
            route="url",
            url=_PLACEHOLDER_URL,
            kind="slurm",
            usd_per_gpu_hour=_DEMO_SLURM_RATE,
            slurm=SlurmDefaults(partition="gpu", time="08:00:00", gpus=2),
            projects={project: str(slurm_repo)},
        ),
    }
    save_hosts(hub.layout, hosts.model_copy(update={"environments": environments}))
    marker = [
        _DemoHost(
            name="gpu1",
            kind="ssh",
            home=str(gpu_ctx.layout.home),
            repo=str(gpu_repo),
            fake_gpus=str(fake_gpus),
        ),
        _DemoHost(
            name="cluster",
            kind="slurm",
            home=str(slurm_ctx.layout.home),
            repo=str(slurm_repo),
            bin=str(bin_dir),
        ),
    ]
    atomic_write_text(
        root / DEMO_HOSTS_FILE, json.dumps([h.model_dump() for h in marker], indent=2)
    )
    return {
        "gpu1": str(gpu_ctx.layout.home),
        "cluster": str(slurm_ctx.layout.home),
        "sweep": f"{project}/{DEMO_SWEEP_ID}",
    }


def _start_demo_host(host: _DemoHost) -> subprocess.Popen[bytes]:
    """Start ``hx serve --kind <kind> --port 0 --no-auth`` for one fake host."""
    env = {
        k: v for k, v in os.environ.items() if k not in ("HYPOTHEX_FAKE_GPUS", "HYPOTHEX_HUB_URL")
    }
    env["HYPOTHEX_HOME"] = host.home
    path = [str(Path(sys.executable).parent), env.get("PATH", "")]
    if host.bin:
        path.insert(0, host.bin)
    env["PATH"] = os.pathsep.join(path)
    if host.fake_gpus:
        env["HYPOTHEX_FAKE_GPUS"] = host.fake_gpus
    serve_dir = Path(host.home) / "serve"
    serve_dir.mkdir(parents=True, exist_ok=True)
    # server.json stays: a live owner of this home makes the child refuse (one server per home)
    # --no-auth: the hub reaches these fake hosts by `route: url`, which carries no token
    argv = [
        sys.executable, "-m", "hypothex.cli.main", "--home", host.home,
        "serve", "--host", "127.0.0.1", "--port", "0", "--kind", host.kind, "--no-auth",
    ]  # fmt: skip
    # own session: Ctrl-C on `hx serve` must not reach these hosts before the hub stops their runs
    with (serve_dir / "demo-host.log").open("ab") as log:
        return subprocess.Popen(
            argv,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _wait_demo_host(host: _DemoHost, proc: subprocess.Popen[bytes], timeout: float) -> str:
    """Wait for a fake host's ``server.json`` and descriptor; return its URL."""
    serve_dir = Path(host.home) / "serve"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log = serve_dir / "demo-host.log"
            tail = (
                log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.is_file() else ""
            )
            raise StoreError(f"demo host {host.name} exited with {proc.returncode}:\n{tail}")
        with contextlib.suppress(OSError, ValueError, KeyError, httpx.HTTPError):
            info = json.loads((serve_dir / "server.json").read_text(encoding="utf-8"))
            if info["pid"] == proc.pid:
                url = f"http://127.0.0.1:{info['port']}"
                resp = httpx.get(f"{url}/.well-known/hypothex/environment", timeout=2)
                if resp.status_code == 200:
                    return url
        time.sleep(0.1)
    raise StoreError(f"demo host {host.name} did not start in {timeout:.0f}s")


def _point_hub_at(home: Path, urls: dict[str, str]) -> None:
    """Rewrite the fake hosts' URLs in the hub's ``environments.yaml``."""
    layout = Layout(home.expanduser().resolve())
    hosts = load_hosts(layout)
    environments = {
        n: s.model_copy(update={"url": urls[n]}) if n in urls else s
        for n, s in hosts.environments.items()
    }
    save_hosts(layout, hosts.model_copy(update={"environments": environments}))


def _launch_live_runs(
    home: Path, hosts: list[_DemoHost], urls: dict[str, str], run_ids: list[str]
) -> None:
    """
    Launch the sweep's running and queued cells on gpu1 (unless it already has active runs).

    Running cells go first, so the FIFO scheduler gives them the 6 free GPUs. Each
    launched id is appended to ``run_ids`` at once, so the caller can stop the runs
    that started even when a later launch fails.
    """
    gpu = next(h for h in hosts if h.fake_gpus)
    url = urls[gpu.name]
    active: list[Any] = []
    for status in ("queued", "running"):
        listed = httpx.get(f"{url}/api/v1/runs", params={"status": status}, timeout=30)
        listed.raise_for_status()  # an error body must not read as "active runs"
        active.extend(listed.json())
    if active:
        return
    project, task = DEMO_TASKS["training"]
    hub_id = load_descriptor(Layout(home.expanduser().resolve())).environment_id
    tag = sweep_tag(hub_id, DEMO_SWEEP_ID)  # the hub owns the sweep
    cells = [
        (lr, beam, seed, state)
        for (lr, beam), runs in _SWEEP_GRID.items()
        for seed, (state, _) in enumerate(runs, 1)
        if state in ("r", "q")
    ]
    cells.sort(key=lambda cell: cell[3] != "r")
    # one command id per cell of this start; a later start (after the forget) gets new
    # ones, so a receipt never hands back a run that was deleted
    start = new_command_id()
    for lr, beam, seed, _ in cells:
        params = {"lr": lr, "beam": beam}
        resp = httpx.post(
            f"{url}/api/v1/runs",
            json={
                "command_id": f"demo-{start}-lr{lr}-beam{beam}-seed{seed}",
                "repo": gpu.repo,
                "task": task,
                "command": _SWEEP_COMMAND,
                "hypothesis": _SWEEP_HYPOTHESIS,
                "seed": seed,
                "params": params,
                "vars": params,
                "tags": [tag],
                "gpus": 2,
                "queue": True,
                "sweep_id": DEMO_SWEEP_ID,
                "created_by": "agent:tuner",
            },
            timeout=120,
        )
        if resp.status_code >= 400:
            raise StoreError(f"demo host {gpu.name} refused a run: {resp.text[:300]}")
        run_ids.append(resp.json()["run_id"])
        # recorded run by run, so even a start cut short is forgotten next time
        atomic_write_text(home / DEMO_HOSTS_DIR / _LIVE_RUNS_FILE, json.dumps(run_ids))
    # tagged for the hub: it counts them once they are mirrored


def _serving(host: _DemoHost) -> bool:
    """True when the ``server.json`` in the fake host's home names a live process."""
    try:
        info = json.loads((Path(host.home) / "serve" / "server.json").read_text(encoding="utf-8"))
        return process_alive(int(info["pid"]), None)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _forget_live_runs(home: Path, gpu: _DemoHost) -> None:
    """
    Delete the live runs that a start launched, on gpu1 and in the hub's mirror.

    The demo then holds only its seeded runs again, so each start of ``hx serve``
    shows the mockup's 27 sweep members (21 seeded + 6 live), never more. The ids
    come from ``<home>/demo-hosts/live-runs.json``. Nothing is deleted while a
    server still owns the gpu1 home: its own start then fails loudly instead.
    """
    path = home / DEMO_HOSTS_DIR / _LIVE_RUNS_FILE
    if not path.is_file() or _serving(gpu):
        return
    run_ids = [str(r) for r in json.loads(path.read_text(encoding="utf-8"))]
    project, _ = DEMO_TASKS["training"]
    for root in (Path(gpu.home), home):  # gpu1 first: the hub never mirrors them back
        ctx = Context.open(root)
        for run_id in run_ids:
            shutil.rmtree(ctx.layout.run_dir(project, run_id), ignore_errors=True)
            (ctx.layout.store / CLAIMS_DIR / f"{run_id}.json").unlink(missing_ok=True)
            ctx.index.delete_run(run_id)
    path.unlink()


def _stop_runs(url: str, run_ids: list[str]) -> None:
    """Stop the live demo runs (best effort, in parallel)."""

    def stop(run_id: str) -> None:
        with contextlib.suppress(httpx.HTTPError):
            httpx.post(
                f"{url}/api/v1/runs/{run_id}/stop",
                json={"created_by": "demo", "command_id": f"demo-stop-{run_id}"},
                timeout=60,
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(stop, run_ids))


@contextmanager
def demo_hosts_running(home: Path, *, ready_timeout: float = 60.0) -> Iterator[list[str]]:
    """
    Run the fake hosts of ``hx demo --with-hosts`` while the hub runs.

    Without ``<home>/demo-hosts/hosts.json`` this does nothing. Otherwise it starts
    one ``hx serve --kind ...`` process per fake host (gpu1 with fake GPUs, cluster
    with fake SLURM commands on ``PATH``), points the hub's ``environments.yaml`` at
    their ports, and, when gpu1 has no active runs, launches the sweep's 3 running
    and 3 queued cells there. On exit it stops those runs and the processes, then
    deletes the runs (on gpu1 and in the hub), so every start shows the same 27
    sweep members; a start first deletes any that an unclean exit left behind.
    A fake host whose home a live server already owns fails to start
    (``StoreError`` with the end of its log): one server per home.

    Parameters
    ----------
    home : Path
        The hub's home.
    ready_timeout : float
        Seconds to wait for each fake host.

    Yields
    ------
    list of str
        Run ids launched on gpu1 (empty when gpu1 already had active runs).

    Raises
    ------
    StoreError
        If a fake host exits (for example, a live server owns its home) or does
        not start in ``ready_timeout`` seconds.
    """
    marker = home / DEMO_HOSTS_DIR / DEMO_HOSTS_FILE
    if not marker.is_file():
        yield []
        return
    hosts = [_DemoHost.model_validate(h) for h in json.loads(marker.read_text(encoding="utf-8"))]
    gpu = next((h for h in hosts if h.fake_gpus), None)
    if gpu is not None:
        _forget_live_runs(home, gpu)  # left by a start that did not exit cleanly
    procs: list[subprocess.Popen[bytes]] = []
    urls: dict[str, str] = {}
    started: list[str] = []
    try:
        for host in hosts:
            procs.append(_start_demo_host(host))
        for host, proc in zip(hosts, procs, strict=True):
            urls[host.name] = _wait_demo_host(host, proc, ready_timeout)
        _point_hub_at(home, urls)
        _launch_live_runs(home, hosts, urls, started)
        yield started
    finally:
        if gpu is not None and gpu.name in urls and started:
            _stop_runs(urls[gpu.name], started)
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if gpu is not None and procs:
            _forget_live_runs(home, gpu)
