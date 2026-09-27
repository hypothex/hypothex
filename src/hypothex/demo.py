"""Seed a Hypothex home with demo projects, one per task kind.

The demo mirrors the approved mockups in ``docs/mockups/kinds/*/data.js`` (and
``docs/mockups/ui-v4/data.js`` for the generic kind): the same seeded generators,
ported to Python, produce the same numbers. Every file is written through the
public store, ``Context``, and SDK APIs, so the demo home has the production
layout. Nothing is executed: no training, no metric worker, no git.

Used by UI tests, Playwright, and docs screenshots.

Examples
--------
>>> import pathlib, tempfile
>>> from hypothex.demo import seed_demo
>>> seed_demo(pathlib.Path(tempfile.mkdtemp()), kinds=["generic"])
{'generic': 'toy-classifier/toy-test'}
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

from hypothex.core.config import TaskKind
from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import new_run_id, utcnow
from hypothex.core.records import DatasetRef, GitInfo, RunRecord, RunStatus, ScoreRecord
from hypothex.core.seeds import config_hash, run_fingerprint
from hypothex.core.store import sum_usage
from hypothex.core.views import save_view
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
        Index a still-running run's logged metric history.

        Parameters
        ----------
        record : RunRecord
            The running run.
        """
        points = self.ctx.store.read_metric_points(record.project, record.run_id)
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


# --------------------------------------------------------------------- entry point
_SEEDERS: dict[str, Callable[[_Seeder], None]] = {
    "generic": _seed_generic,
    "training": _seed_training,
    "agent_eval": _seed_agent_eval,
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
