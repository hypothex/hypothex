import json
import os
import shutil
import time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hypothex.api.app import _run_view, create_app
from hypothex.cli.main import app as cli_app
from hypothex.core import queries as q
from hypothex.core import slurm
from hypothex.core.context import Context
from hypothex.core.control import repair_runs
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import read_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.overview import build_overview
from hypothex.core.panels import query_view
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.sweeps import load_sweep
from hypothex.core.views import ViewSpec, get_view
from hypothex.demo import (
    _SEEDERS,
    DEMO_EPOCH,
    DEMO_HOSTS_DIR,
    DEMO_SWEEP_ID,
    DEMO_TASKS,
    _fixed,
    _js_round,
    _mulberry32,
    _seed_demo,
    demo_hosts_running,
    seed_demo,
    seed_demo_hosts,
)
from hypothex.remote.config import load_hosts
from tests.api.envserver import wait_until

REFS = {
    "generic": "toy-classifier/toy-test",
    "training": "rxn-forward/uspto-forward-top1",
    "agent_eval": "retro-agents/retro-bench-200",
    "agent_iteration": "retro-agent/retro-bench-200",
    "system_bench": "route-search/route-api-latency",
}


@pytest.fixture(scope="module")
def demo_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One home seeded with every kind implemented so far (fixed anchor)."""
    home = tmp_path_factory.mktemp("demo")
    _seed_demo(home, list(_SEEDERS), DEMO_EPOCH)
    return home


@pytest.fixture
def dctx(demo_home: Path) -> Context:
    return Context.open(demo_home)


def _runs(ctx: Context, project: str) -> list[RunRecord]:
    """All runs of a project, oldest first."""
    runs = ctx.index.list_runs(project=project, include_archived=True, limit=None)
    return sorted(runs, key=lambda r: (r.created_at, r.run_id))


def _find(runs: list[RunRecord], seed: int | None = None, **params: str) -> RunRecord:
    """The one run with this seed and these params."""
    hits = [
        r
        for r in runs
        if (seed is None or r.seed == seed) and all(r.params.get(k) == v for k, v in params.items())
    ]
    assert len(hits) == 1, [r.run_id for r in hits]
    return hits[0]


def test_js_parity_helpers() -> None:
    # first three draws of mulberry32(20260927), printed by bun from the mockup's function
    draw = _mulberry32(20260927)
    assert [draw(), draw(), draw()] == [0.5817536343820393, 0.3177114331629127, 0.3009456454310566]
    assert _fixed(12.25, 1) == 12.3  # JS (12.25).toFixed(1) === "12.3"
    assert _js_round(-2.5) == -2 and _js_round(2.5) == 3  # JS Math.round


def test_generic_mirrors_ui_v4(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["generic"])
    assert board.kind == "generic"
    # ui-v4/data.js: SVM 166/180, rf 158/160/160 of 180, knn 156/180, logreg 149/180
    assert [row.primary.mean for row in board.rows if row.primary] == pytest.approx(
        [166 / 180, 478 / 540, 156 / 180, 149 / 180]
    )
    assert board.rows[1].primary is not None
    assert board.rows[1].primary.std == pytest.approx(0.006415002990995819)  # ui-v4 rf std
    assert [row.n for row in board.rows] == [3, 3, 3, 3]
    assert board.rows[0].identical_seeds and not board.rows[1].identical_seeds
    rf3, svm3 = board.rows[1].run_ids[2], board.rows[0].run_ids[2]
    diff = q.compare_examples(dctx, rf3, svm3, "accuracy")
    assert diff.fixed == [
        "test-0", "test-110", "test-116", "test-12", "test-156", "test-177", "test-21",
        "test-63", "test-83",
    ]  # fmt: skip
    assert diff.broken == ["test-137", "test-167", "test-30"]
    assert (diff.both_pass, diff.both_fail) == (157, 11)
    failed = [r for r in _runs(dctx, "toy-classifier") if r.status == RunStatus.FAILED]
    assert [(r.seed, r.exit_code, r.archived) for r in failed] == [
        (1, 2, True),
        (2, 2, True),
        (3, 2, True),
    ]
    stderr = q.read_log(dctx, failed[0].run_id, "stderr").text
    assert "invalid choice: 'svm'" in stderr
    assert "net +6/180" in q.show_run(dctx, svm3).notes


def test_same_anchor_gives_same_data(demo_home: Path, tmp_path: Path) -> None:
    _seed_demo(tmp_path / "again", list(_SEEDERS), DEMO_EPOCH)
    first, second = Context.open(demo_home), Context.open(tmp_path / "again")
    for kind in _SEEDERS:
        project = DEMO_TASKS[kind][0]
        a, b = _runs(first, project), _runs(second, project)
        assert [r.run_id for r in a] == [r.run_id for r in b]
        for ra, rb in zip(a, b, strict=True):
            assert ra.usage == rb.usage
            assert ra.artifacts == rb.artifacts
            da, db = first.run_dir(ra), second.run_dir(rb)
            written = ["scores.jsonl", "predictions/*.jsonl", "samples/*.jsonl", "traces/*.jsonl"]
            files = sorted(p.relative_to(da) for pattern in written for p in da.glob(pattern))
            assert files == sorted(
                p.relative_to(db) for pattern in written for p in db.glob(pattern)
            )
            for rel in files:
                assert (da / rel).read_bytes() == (db / rel).read_bytes(), rel
            pa = first.store.read_metric_points(project, ra.run_id)
            pb = second.store.read_metric_points(project, rb.run_id)
            assert [(p.name, p.step, p.value) for p in pa] == [
                (p.name, p.step, p.value) for p in pb
            ]


def test_refuses_existing_project_and_unknown_kind(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bad: list[Any] = ["generic", "nope"]
    with pytest.raises(ValueError, match="unknown demo kinds"):
        seed_demo(home, bad)
    assert not home.exists()
    assert seed_demo(home, ["generic", "generic"]) == {"generic": REFS["generic"]}
    ctx = Context.open(home)
    before = len(ctx.index.list_runs(include_archived=True, limit=None))
    with pytest.raises(StoreError, match="already exists"):
        seed_demo(home, ["generic"])
    assert len(ctx.index.list_runs(include_archived=True, limit=None)) == before


def test_training_mirrors_mockup(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["training"])
    assert board.kind == "training"
    # best-checkpoint test top-1 per run, from kinds/training/data.js (runs[i].best_top1)
    expected = {
        "aug": [0.909175, 0.906025],
        "lr1e-4": [0.893875, 0.8907, 0.889975],
        "base": [0.887675, 0.880425, 0.894],
    }
    runs = _runs(dctx, "rxn-forward")
    assert [dctx.find_record(row.run_ids[0]).params["config"] for row in board.rows] == [
        "aug",
        "lr1e-4",
        "base",
    ]
    for row, values in zip(board.rows, expected.values(), strict=True):
        assert row.n == len(values)
        assert row.primary is not None
        assert row.primary.mean == pytest.approx(sum(values) / len(values))
    base1 = _find(runs, 1, config="base")
    assert {(s.key, s.value) for s in dctx.store.read_scores("rxn-forward", base1.run_id)} == {
        ("value", 0.887675),
        ("final", 0.884575),
    }
    ckpts = [a for a in base1.artifacts if a.kind == "checkpoint"]
    assert [a.step for a in ckpts] == list(range(2000, 20001, 2000))
    best = max(ckpts, key=lambda a: a.metrics["val/top1"])
    assert (best.step, best.metrics["val/top1"]) == (12000, 0.8909)
    assert best.host == "gpu-a01" and best.path.endswith("/ckpt/step_012000.pt")
    spiky = _find(runs, 2, config="base")
    points = dctx.store.read_metric_points("rxn-forward", spiky.run_id)
    peak = max(p.value for p in points if p.name == "train/loss" and 9000 <= p.step < 9400)
    assert peak == 2.9667  # mockup event.peak of the diverged run
    killed = _find(runs, 3, config="aug")
    assert (killed.status, killed.exit_code) == (RunStatus.KILLED, 137)
    assert dctx.store.read_scores("rxn-forward", killed.run_id) == []
    names = {p.name for p in dctx.index.metric_points(base1.run_id)}
    assert names == {"train/loss", "val/top1", "val/loss", "lr", "sys/gpu_util", "sys/gpu_mem_gb"}
    live = _find(runs, config="lr2e-4")
    assert live.status == RunStatus.RUNNING and live.ended_at is None
    steps = [p.step for p in dctx.index.metric_points(live.run_id) if p.name == "train/loss"]
    assert max(steps) == 2350
    assert [a.step for a in dctx.store.read_artifacts("rxn-forward", live.run_id)] == [2000]


def test_running_demo_run_survives_repair(dctx: Context) -> None:
    assert repair_runs(dctx) == []
    live = dctx.index.list_runs(status=RunStatus.RUNNING, limit=None)
    assert len(live) == 1 and live[0].environment_id == "demo:gpu-a04"


def test_agent_eval_mirrors_mockup(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["agent_eval"])
    assert board.kind == "agent_eval"
    runs = _runs(dctx, "retro-agents")
    # solved targets and summed $ per config and seed, from kinds/agent_eval/data.js
    solved = {"mini": [84, 80, 80], "sonnet": [108, 120, 111], "scorer": [148, 141, 146]}
    solved["opus"] = [152, 147, 146]
    usd = {"mini": [3.0867, 3.0367, 3.6488], "sonnet": [44.257, 49.6265, 47.7672]}
    usd |= {"scorer": [33.5957, 38.1796, 33.5293], "opus": [108.2754, 106.1396, 117.8305]}
    loops = {"mini": [14, 16, 15], "sonnet": [30, 22, 34], "scorer": [8, 8, 5], "opus": [2, 7, 8]}
    for config, counts in solved.items():
        for seed, count in enumerate(counts, start=1):
            run = _find(runs, seed, config=config)
            scores = dctx.store.read_scores("retro-agents", run.run_id)
            assert [(s.metric, s.version, s.value) for s in scores] == [
                ("solved", "v2", count / 200)
            ]
            assert run.usage is not None
            assert run.usage.usd == pytest.approx(usd[config][seed - 1], abs=1e-6)
            assert run.usage.calls == 200
            rows = read_jsonl(dctx.run_dir(run) / "predictions" / "predictions.jsonl")
            categories = [r["meta"]["category"] for r in rows]
            assert categories.count("loop") == loops[config][seed - 1]
            assert categories.count(None) == count
    selected = _find(runs, 2, config="scorer")
    steps = read_jsonl(dctx.run_dir(selected) / "traces" / "T-014.jsonl")
    assert [s["turn"] for s in steps] == list(range(1, 14))
    assert steps[-1]["error"] == "loop: 3rd identical call"
    assert sum(s["tokens_in"] for s in steps) == 152670
    entry, task = q.resolve_task(dctx, REFS["agent_eval"])
    assert get_view(Path(entry.repo), entry.config, task, "cost-notes").title == "cost notes"


def test_agent_iteration_mirrors_mockup(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["agent_iteration"])
    assert board.kind == "agent_iteration"
    # solved targets per version (seeds 1-3), counted from the bitstrings in data.js
    counts = {
        "v1": [80, 80, 80], "v2": [85, 85, 85], "v3": [107, 107, 102], "v4": [111, 105, 115],
        "v5": [116, 126, 122], "v6": [110, 115, 110], "v7": [121, 120, 127],
        "v8": [129, 135, 134], "v9": [128, 136, 129],
    }  # fmt: skip
    runs = _runs(dctx, "retro-agent")
    means = {}
    for row in board.rows:
        version = dctx.find_record(row.run_ids[0]).params["version"]
        assert row.primary is not None
        means[version] = row.primary.mean
    assert means == pytest.approx({v: sum(c) / 600 for v, c in counts.items()})
    assert board.rows[0].label == "v8"  # agent_iteration labels are the version_param value
    detail = _find(runs, 2, version="v8")
    assert detail.usage is not None
    assert (detail.usage.usd, detail.usage.tokens_in) == (177.12, 61_100_000)
    assert detail.usage.seconds == 3 * 3600 - 2 * 60  # 15:06 to 18:04
    rows = {
        r["id"]: r for r in read_jsonl(dctx.run_dir(detail) / "predictions" / "predictions.jsonl")
    }
    assert rows["T-003"]["meta"] == {"category": "timeout", "steps": 29}
    assert rows["T-001"]["meta"] == {"category": None, "steps": 15}
    trace = read_jsonl(dctx.run_dir(detail) / "traces" / "T-035.jsonl")
    assert len(trace) == 11 and trace[-1]["tool"] == "submit" and trace[-1]["result"] == "solved"


def test_system_bench_mirrors_mockup(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["system_bench"])
    assert board.kind == "system_bench" and not board.higher_is_better
    runs = [r for r in _runs(dctx, "route-search") if r.status == RunStatus.FINISHED]
    # p95 (linear interpolation) over each run's Float32 latencies, computed by bun
    # from kinds/system_bench/data.js
    p95 = {
        ("baseline", 1): 234.31702575683593, ("baseline", 2): 230.59684829711915,
        ("baseline", 3): 234.89067153930665, ("cache", 1): 194.79916763305684,
        ("cache", 2): 197.24704971313494, ("cache", 3): 239.69444732666022,
        ("async", 1): 163.21131973266603, ("async", 2): 168.6949531555176,
        ("async", 3): 164.95999679565435,
    }  # fmt: skip
    errors = {("cache", 3): 4, ("async", 1): 3, ("async", 3): 1}
    for (version, rep), value in p95.items():
        run = _find(runs, rep, version=version)
        scores = {s.key: s.value for s in dctx.store.read_scores("route-search", run.run_id)}
        assert scores["p95"] == pytest.approx(value, abs=1e-9)
        assert scores["rate"] == errors.get((version, rep), 0) / 5000
        samples = read_jsonl(dctx.run_dir(run) / "samples" / "latency_ms.jsonl")
        assert len(samples) == 5000
        assert run.tags == (["baseline"] if version == "baseline" else [])
    # concurrency sweep on each third repeat (data.js SWEEP)
    cache3 = _find(runs, 3, version="cache")
    sweep = {
        p.step: p.value
        for p in dctx.store.read_metric_points("route-search", cache3.run_id)
        if p.name == "sweep/rps"
    }
    assert sweep == {
        1: 16.8,
        2: 34.4,
        4: 69.2,
        8: 137.2,
        16: 265.3,
        32: 429.2,
        64: 514.8,
        128: 522.9,
    }
    failed = [r for r in _runs(dctx, "route-search") if r.status == RunStatus.FAILED]
    assert len(failed) == 1 and failed[0].exit_code == 1
    assert failed[0].config_hash == cache3.config_hash
    assert cache3.created_at - failed[0].created_at == timedelta(seconds=10)


def test_seed_demo_is_fast_and_registers_every_kind(tmp_path: Path) -> None:
    start = time.perf_counter()
    refs = seed_demo(tmp_path / "home")
    assert time.perf_counter() - start < 10.0
    assert refs == REFS
    ctx = Context.open(tmp_path / "home")
    for kind, ref in refs.items():
        entry, task = q.resolve_task(ctx, ref)
        assert entry.config.tasks[task].kind == kind
        assert Path(entry.repo) == (tmp_path / "home" / "demo-repos" / entry.project).resolve()
    # the newest run (the one still training) starts 40 min before the current hour
    newest = max(r.created_at for r in ctx.index.list_runs(include_archived=True, limit=None))
    assert utcnow() - timedelta(minutes=101) <= newest <= utcnow()


def test_overview_of_demo(dctx: Context) -> None:
    summary = build_overview(dctx, since=DEMO_EPOCH - timedelta(hours=24))
    assert summary.counts == {
        "total": 45,
        "queued": 0,
        "running": 1,
        "finished": 40,
        "failed": 4,
        "killed": 0,
        "lost": 0,
        "archived": 7,
        "agent": 30,
        "human": 15,
    }
    assert [r.params["config"] for r in summary.running] == ["lr2e-4"]
    # the newest scored idea is a system_bench task: same phrasing as its task headline
    assert summary.headline == "1 running. async-worker p95 −29% vs baseline [−32, −26]"
    assert len(summary.failures) == 4 and all(f.retried_ok for f in summary.failures)
    assert [(p.project, p.runs, p.kind) for p in summary.projects] == [
        ("retro-agent", 27, "agent_iteration"),
        ("retro-agents", 12, "agent_eval"),
        ("route-search", 9, "system_bench"),
        ("rxn-forward", 8, "training"),
        ("toy-classifier", 12, "generic"),
    ]


def test_every_kind_overview_queries_cleanly(dctx: Context) -> None:
    # The preset names must match what the demo writes; the UI tests and screenshots use it.
    for kind, ref in REFS.items():
        entry, task = q.resolve_task(dctx, ref)
        view = get_view(Path(entry.repo), entry.config, task, "overview")
        results = {r.title: r for r in query_view(dctx, entry.project, task, view)}
        for title, result in results.items():
            assert "error" not in result.meta, (kind, title, result.meta.get("error"))
            if result.type != "markdown":
                assert result.rows, (kind, title)
        if kind == "training":
            assert {row["name"] for row in results["GPU"].rows} == {"sys/gpu_util"}
            assert results["Checkpoints"].meta["checkpoints"]
            curves = results["Curves"].meta
            assert curves["metrics"] == ["train/loss", "val/loss", "val/top1", "lr"]
            # one spike episode (base recipe seed 2, train and val loss) and one kill
            assert [e["label"] for e in curves["events"]] == ["spike 9k", "killed 14k"]
        if kind == "agent_iteration":
            solved = results["Solved by version"]
            assert solved.meta["x_type"] == "ordinal"
            assert [row["x"] for row in solved.rows] == [f"v{i}" for i in range(1, 10)]
            cost = results["$ per solved"]
            assert [row["x"] for row in cost.rows] == [f"v{i}" for i in range(1, 10)]
            # v1 (data.js): $74.28, $79.57, $75.70 for 80 solved targets in each seed
            assert cost.rows[0]["y"] == pytest.approx((74.28 + 79.57 + 75.70) / 240)
            # regressions (contract 1.6). Solved: no drop is outside the best earlier
            # version's CI (the largest, v6 0.558 vs v5 0.607, is inside v5's interval).
            assert not any(row["regression"] for row in solved.rows)
            # $ per solved is lower-is-better (usage.*), seed t-intervals over 3 seeds:
            # v3 is the cheapest (0.918, hi 1.004); v4..v9 all have y_lo above 1.004
            # (v4 1.127, v9 1.056), so each is flagged
            assert [row["regression"] for row in cost.rows] == [False] * 3 + [True] * 6
            # Changes: one row per version with only what changed (kinds/agent_iteration)
            changes = results["Changes"].rows
            assert [row["version"] for row in changes] == [f"v{i}" for i in range(1, 10)]
            assert [row["changes"] for row in changes[1:6]] == [
                "retries: 1 → 3",
                "tools: +stock_check; temperature: 0 → 0.6",
                "depth: 4 → 6",
                "model: gpt-4.1-mini → gpt-4.1",
                "prompt: react-1 → concise-2",
            ]
            assert changes[0]["changes"] == ""  # first version: nothing to compare with
            assert changes[0]["delta_prev"] is None
            assert changes[5]["delta_prev"] == pytest.approx(0.5583333 - 0.6066667, abs=1e-6)
        if kind == "system_bench":
            assert results["Latency"].rows[0]["n"] == 15_000  # 3 repeats x 5,000 requests
            errors = results["Error rate"].rows
            assert any(row["metric"] == "errors" and row["key"] == "rate" for row in errors)
            # percentile table: one distribution row per version, Δ vs the tag:baseline group
            table = results["Percentiles"]
            assert (table.type, table.meta["render"]) == ("distribution", "table")
            assert len(table.rows) == 3
            baseline = {row["group_id"]: row for row in table.rows}[table.meta["baseline"]]
            assert baseline["vs_baseline"] is None
            deltas = [row["vs_baseline"] for row in table.rows if row is not baseline]
            # 3 repeats on each side, so every percentile has a bootstrap interval
            assert all(lo is not None and lo <= hi for d in deltas for _, lo, hi in d.values())
            # async: repeat p95s 163-169 ms vs baseline 231-235 ms, about -29%
            assert min(d["p95"][0] for d in deltas) < -0.25
            # utilisation small multiples: one per config, its 3 repeats inside it
            util = results["Utilisation"]
            assert [g["label"] for g in util.meta["groups"]] == [
                "baseline",
                "cache-enabled",
                "async-worker",
            ]
            runs_per_group: dict[str, set[str]] = defaultdict(set)
            for row in util.rows:
                runs_per_group[row["group_id"]].add(row["run_id"])
            assert sorted(len(v) for v in runs_per_group.values()) == [3, 3, 3]
            # 9 finished runs: p95 for the spread
            assert len(results["Repeat spread"].rows) == 9
            # bars and points are named by config label, not group id
            names = {"baseline", "cache-enabled", "async-worker"}
            for title in ("Error rate", "Repeat spread"):
                assert {row["label"] for row in results[title].rows} == names
                assert results[title].meta["spec"]["encoding"]["y"]["field"] == "label"
        if kind == "agent_eval":
            failures = results["Failures"]
            assert failures.meta["spec"]["encoding"]["y"]["field"] == "label"
            assert {row["label"] for row in failures.rows} == {
                "Opus 5.5",
                "Sonnet 5 + scorer",
                "Sonnet 5",
                "gpt-5-mini",
            }


def test_existing_project_blocks_every_kind(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seed_demo(home, ["generic"])
    with pytest.raises(StoreError, match="toy-classifier"):
        seed_demo(home, ["system_bench", "generic"])
    assert not Context.open(home).layout.project_dir("route-search").exists()


def test_every_kind_run_view_queries_cleanly(dctx: Context) -> None:
    for kind, ref in REFS.items():
        entry, task = q.resolve_task(dctx, ref)
        finished = [
            r
            for r in _runs(dctx, entry.project)
            if r.status == RunStatus.FINISHED and not r.archived
        ]
        run_id = finished[-1].run_id
        # scoped to one run the way the UI's scopeToRun does; traces have their own section
        panels = [
            p.model_copy(update={"data": p.data.model_copy(update={"filter": {"run_id": run_id}})})
            for p in _run_view(kind)
            if p.type != "trace"
        ]
        results = query_view(dctx, entry.project, task, ViewSpec(title="run", panels=panels))
        for result in results:
            assert "error" not in result.meta, (kind, result.title, result.meta.get("error"))
        if kind == "system_bench":
            (latency,) = [r for r in results if r.type == "distribution"]
            assert [row["n"] for row in latency.rows] == [5000]
        if kind in ("agent_eval", "agent_iteration"):
            (tokens,) = [r for r in results if r.title == "tokens per turn"]
            assert tokens.meta["columns"] == ["turn", "tokens_in", "tokens_out", "seconds"]


runner = CliRunner()


@pytest.fixture(scope="module")
def hosts_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A hub home with the training demo and the fake hosts (seeded, not started)."""
    home = tmp_path_factory.mktemp("demo-hosts")
    seed_demo(home, ["training"])
    seed_demo_hosts(home)
    return home


def test_seed_demo_hosts_writes_hosts_runs_and_the_sweep(hosts_home: Path) -> None:
    hub = Context.open(hosts_home)
    hosts = load_hosts(hub.layout).environments
    assert set(hosts) == {"gpu1", "cluster"}
    assert (hosts["gpu1"].route, hosts["gpu1"].kind, hosts["cluster"].kind) == (
        "url",
        "ssh",
        "slurm",
    )
    assert hosts["cluster"].slurm is not None and hosts["cluster"].slurm.partition == "gpu"
    assert hosts["gpu1"].usd_per_gpu_hour == 1.10
    gpu_repo = Path(hosts["gpu1"].projects["rxn-forward"])
    assert (gpu_repo / "train.py").is_file() and (gpu_repo / "hypothex.yaml").is_file()
    gpu = Context.open(hosts_home / DEMO_HOSTS_DIR / "gpu1")
    assert gpu.descriptor.label == "gpu1"
    runs = gpu.index.list_runs(limit=None)
    assert Counter(r.status for r in runs) == {RunStatus.FINISHED: 20, RunStatus.FAILED: 1}
    assert {r.sweep_id for r in runs} == {DEMO_SWEEP_ID}
    best = next(r for r in runs if r.params == {"lr": "3e-4", "beam": "10"} and r.seed == 2)
    assert best.command == [
        "python", "train.py", "--config", "configs/aug.yaml",
        "--lr", "3e-4", "--beam", "10", "--seed", "2",
    ]  # fmt: skip
    assert best.executor.gpus == [0, 1] and best.cost is not None
    assert best.cost.gpu_hours == pytest.approx(1.6)
    assert best.cost.gpu_usd == pytest.approx(1.76)
    assert gpu.store.read_scores("rxn-forward", best.run_id)[0].value == 0.9130
    cluster = Context.open(hosts_home / DEMO_HOSTS_DIR / "cluster")
    lost = next(r for r in cluster.index.list_runs(limit=None) if r.status == RunStatus.LOST)
    assert (lost.executor.slurm_job_id, lost.executor.node) == ("48211932", "r208u06n02")
    spec = load_sweep(hub.layout, "rxn-forward", DEMO_SWEEP_ID)
    assert spec.host == "gpu1" and spec.seeds == [1, 2, 3]
    tag = f"sweep:{hub.descriptor.environment_id[:8]}:{DEMO_SWEEP_ID}"  # the hub owns it
    members = gpu.index.list_runs(tag=tag, include_archived=True, limit=None)
    assert len(members) == 21
    assert [p.name for p in spec.grid] == ["lr", "beam"]
    gpus = json.loads((hosts_home / DEMO_HOSTS_DIR / "gpu1-gpus.json").read_text())
    assert len(gpus) == 8 and [g["index"] for g in gpus if g["external"]] == [3, 7]


def test_seed_demo_hosts_refuses_twice_and_needs_training(hosts_home: Path, tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="demo hosts already exist"):
        seed_demo_hosts(hosts_home)
    other = tmp_path / "other"
    seed_demo(other, ["generic"])
    with pytest.raises(ConfigError, match="--kinds training"):
        seed_demo_hosts(other)


def test_fake_slurm_keeps_a_submitted_job_pending_until_scancel(
    hosts_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty fake squeue made every new demo SLURM launch `lost` within a minute.
    bin_dir = tmp_path / "bin"
    shutil.copytree(hosts_home / DEMO_HOSTS_DIR / "cluster-bin", bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    first = slurm.submit("#!/bin/sh\n", tmp_path, comment="hx-a")
    second = slurm.submit("#!/bin/sh\n", tmp_path, comment="hx-b")
    assert int(second) == int(first) + 1
    jobs = slurm.poll([first, second])
    assert {j: (s.state, s.node) for j, s in jobs.items()} == {
        first: ("PENDING", None),
        second: ("PENDING", None),
    }
    assert slurm.comment_accounting(refresh=True)
    found, known = slurm.find_submitted("hx-b")
    assert known and found is not None and (found.job_id, found.state) == (second, "PENDING")
    slurm.cancel(first)
    after = slurm.poll([first, second])
    assert after[first].state == "CANCELLED" and slurm.is_finished(after[first])
    assert after[second].state == "PENDING"
    gone, known = slurm.find_submitted("hx-a")
    assert known and gone is not None and gone.state == "CANCELLED"
    slurm.cancel("48211932")  # a job the fake never queued: scancel says nothing
    assert slurm.poll(["48211932"]) == {}


def test_demo_hosts_running_does_nothing_without_the_marker(tmp_path: Path) -> None:
    with demo_hosts_running(tmp_path) as started:
        assert started == []


def test_cli_demo_with_hosts(home: Path) -> None:
    result = runner.invoke(
        cli_app, ["demo", "--kinds", "training", "--with-hosts", "--json"], catch_exceptions=False
    )
    out = json.loads(result.stdout)
    assert out["training"] == "rxn-forward/uspto-forward-top1"
    assert set(out["hosts"]) == {"gpu1", "cluster", "sweep"}
    with pytest.raises(ConfigError, match="--kinds training"):
        runner.invoke(
            cli_app,
            ["--home", str(home.parent / "other"), "demo", "--kinds", "generic", "--with-hosts"],
            catch_exceptions=False,
        )


def test_demo_hosts_serve_connected_hosts_a_queue_and_a_sweep(tmp_path: Path) -> None:
    home = tmp_path / "hub"
    seed_demo(home, ["training"])
    seed_demo_hosts(home)
    with demo_hosts_running(home) as started:
        assert len(started) == 6
        app = create_app(home, background_repair=False)
        with TestClient(app, base_url="http://127.0.0.1:7777") as client:

            def rows() -> dict[str, dict]:
                return {r["name"]: r for r in client.get("/api/v1/hosts").json()}

            wait_until(
                lambda: (
                    {n: r["state"]["state"] for n, r in rows().items()}
                    == {"local": "connected", "gpu1": "connected", "cluster": "connected"}
                ),
                timeout=60,
            )
            current = rows()
            assert len(current["gpu1"]["gpus"]) == 8
            assert current["cluster"]["slurm"] == {
                "pending": 0,
                "running": 0,
                "comment_accounting": True,
            }
            wait_until(lambda: rows()["gpu1"]["queue"] == 3, timeout=60)

            def summary() -> dict:
                return client.get(f"/api/v1/sweeps/rxn-forward/{DEMO_SWEEP_ID}").json()

            # 21 seeded + 6 live runs, all tagged for the hub, members once mirrored
            wait_until(lambda: summary()["counts"]["total"] == 27, timeout=60)
            assert set(started) <= set(summary()["run_ids"])


def test_sigterm_to_hx_serve_stops_the_demo_hosts(tmp_path: Path) -> None:
    # a real SIGTERM to a real `hx serve`: uvicorn re-raises it after its shutdown,
    # so the cleanup must run in the app's lifespan, not in a `with` around uvicorn
    import os
    import signal
    import subprocess
    import sys

    from hypothex.core.execution import process_alive

    home = tmp_path / "hub"
    seed_demo(home, ["training"])
    seed_demo_hosts(home)
    log = (tmp_path / "serve.log").open("wb")
    hub = subprocess.Popen(
        [sys.executable, "-m", "hypothex.cli.main", "--home", str(home), "serve", "--port", "0"],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        files = [
            home / DEMO_HOSTS_DIR / name / "serve" / "server.json" for name in ("gpu1", "cluster")
        ]

        def host_pids() -> list[int]:
            pids = []
            for path in files:
                try:
                    pids.append(json.loads(path.read_text())["pid"])
                except (OSError, ValueError, KeyError):
                    return []
            return pids

        hub_file = home / "serve" / "server.json"
        wait_until(lambda: len(host_pids()) == 2 and hub_file.is_file(), timeout=90)
        pids = host_pids()
        assert all(process_alive(pid, None) for pid in pids)
        hub.send_signal(signal.SIGTERM)
        assert hub.wait(timeout=90) in (-signal.SIGTERM, 0)
        wait_until(lambda: not any(process_alive(pid, None) for pid in pids), timeout=30)
        assert not hub_file.exists()
    finally:
        if hub.poll() is None:
            hub.kill()
            hub.wait()
        for pid in host_pids():
            if process_alive(pid, None):
                os.kill(pid, signal.SIGKILL)
        log.close()


def test_demo_host_keeps_a_live_owners_server_file(tmp_path: Path) -> None:
    # one server per home: a server.json of a live process is never removed, so the
    # fake host's own `hx serve` refuses to start and the hub start fails loudly
    import os
    import socket

    home = tmp_path / "hub"
    seed_demo(home, ["training"])
    seed_demo_hosts(home)
    server_file = home / DEMO_HOSTS_DIR / "gpu1" / "serve" / "server.json"
    server_file.parent.mkdir(parents=True, exist_ok=True)
    owner = {"pid": os.getpid(), "port": 9, "hostname": socket.gethostname()}
    server_file.write_text(json.dumps(owner))
    with (
        pytest.raises(StoreError, match=r"demo host gpu1 exited(?s:.*)is alive"),
        demo_hosts_running(home, ready_timeout=60),
    ):
        pass
    assert json.loads(server_file.read_text()) == owner


def _mirrored_demo_session(home: Path) -> list[str]:
    """Start the fake hosts and the hub; wait until the 6 live runs are sweep members."""
    with demo_hosts_running(home) as started:
        assert len(started) == 6
        app = create_app(home, background_repair=False)
        with TestClient(app, base_url="http://127.0.0.1:7777") as client:

            def summary() -> dict[str, Any]:
                return client.get(f"/api/v1/sweeps/rxn-forward/{DEMO_SWEEP_ID}").json()

            wait_until(lambda: set(started) <= set(summary()["run_ids"]), timeout=90)
            current = summary()
            assert current["counts"]["total"] == 27
            for cell in current["cells"]:
                seeds = [r["seed"] for r in cell["runs"]]
                assert len(seeds) == len(set(seeds)), cell
    return started


def test_restarting_the_demo_hosts_keeps_the_sweep_at_27(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hypothex.demo as demo

    home = tmp_path / "hub"
    seed_demo(home, ["training"])
    seed_demo_hosts(home)
    gpu_home = home / DEMO_HOSTS_DIR / "gpu1"
    # first start: its exit leaves the stopped live runs (as a crash would)
    with monkeypatch.context() as patch:
        patch.setattr(demo, "_forget_live_runs", lambda home, host: None)
        first = _mirrored_demo_session(home)
    assert all(Context.open(gpu_home).index.get_run(r) is not None for r in first)
    # the next start forgets them on gpu1 and in the hub, then launches 6 new runs
    second = _mirrored_demo_session(home)
    assert not set(first) & set(second)
    for root in (gpu_home, home):
        ctx = Context.open(root)
        for run_id in first + second:  # a clean exit forgets the second start's runs too
            assert ctx.index.get_run(run_id) is None
            assert not ctx.layout.run_dir("rxn-forward", run_id).exists()
    assert len(Context.open(gpu_home).index.list_runs(limit=None)) == 21


def test_demo_hosts_run_in_their_own_session(tmp_path: Path) -> None:
    # Ctrl-C reaches the whole foreground process group; the fake hosts must not get
    # it, so the hub can still stop their runs before it terminates them
    import os

    import hypothex.demo as demo

    home = tmp_path / "hub"
    seed_demo(home, ["training"])
    seed_demo_hosts(home)
    marker = home / DEMO_HOSTS_DIR / demo.DEMO_HOSTS_FILE
    host = next(
        demo._DemoHost.model_validate(h)
        for h in json.loads(marker.read_text())
        if h["name"] == "cluster"
    )
    proc = demo._start_demo_host(host)
    try:
        demo._wait_demo_host(host, proc, 60)
        assert os.getsid(proc.pid) != os.getsid(0)
        assert os.getpgid(proc.pid) != os.getpgid(0)
    finally:
        proc.terminate()
        proc.wait(timeout=15)


def test_runs_launched_before_a_failed_launch_are_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    import hypothex.demo as demo

    home = tmp_path / "hub"
    seed_demo(home, ["training"])
    seed_demo_hosts(home)
    real_post = httpx.post
    launched: list[str] = []

    def flaky_post(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        if url.endswith("/api/v1/runs"):
            if launched:
                raise httpx.ReadTimeout("injected")
            resp = real_post(url, *args, **kwargs)
            launched.append(resp.json()["run_id"])
            return resp
        return real_post(url, *args, **kwargs)

    stopped: list[str] = []
    real_stop = demo._stop_runs

    def record_stop(url: str, run_ids: list[str]) -> None:
        stopped.extend(run_ids)
        real_stop(url, run_ids)

    monkeypatch.setattr(httpx, "post", flaky_post)
    monkeypatch.setattr(demo, "_stop_runs", record_stop)
    with pytest.raises(httpx.ReadTimeout), demo_hosts_running(home):
        pass
    assert len(launched) == 1
    assert stopped == launched


def _gpu_host(tmp_path: Path) -> Any:
    import hypothex.demo as demo

    return demo._DemoHost(
        name="gpu1", kind="ssh", home=str(tmp_path / "gpu1"), repo=str(tmp_path), fake_gpus="x"
    )


def test_live_run_launch_fails_loudly_on_an_error_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    import hypothex.demo as demo

    def error_get(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        body = {"error": "store busy", "type": "StoreError"}
        return httpx.Response(503, json=body, request=httpx.Request("GET", url))

    def no_post(*args: Any, **kwargs: Any) -> httpx.Response:
        raise AssertionError("no run may be launched")

    monkeypatch.setattr(httpx, "get", error_get)
    monkeypatch.setattr(httpx, "post", no_post)
    host = _gpu_host(tmp_path)
    with pytest.raises(httpx.HTTPStatusError):
        demo._launch_live_runs(tmp_path / "hub", [host], {"gpu1": "http://gpu1"}, [])


def test_live_run_launch_and_stop_send_command_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    import hypothex.demo as demo

    home = tmp_path / "hub"
    Context.open(home)
    (home / DEMO_HOSTS_DIR).mkdir()
    bodies: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def empty_get(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json=[], request=httpx.Request("GET", url))

    def record_post(url: str, *args: Any, json: dict[str, Any], **kwargs: Any) -> httpx.Response:
        bodies[url.rsplit("/", 1)[-1]].append(json)
        answer = {"run_id": f"r{len(bodies['runs'])}"}
        return httpx.Response(200, json=answer, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "get", empty_get)
    monkeypatch.setattr(httpx, "post", record_post)
    run_ids: list[str] = []
    demo._launch_live_runs(home, [_gpu_host(tmp_path)], {"gpu1": "http://gpu1"}, run_ids)
    first = [b["command_id"] for b in bodies.pop("runs")]
    assert len(first) == len(set(first)) == len(run_ids) == 6
    demo._launch_live_runs(home, [_gpu_host(tmp_path)], {"gpu1": "http://gpu1"}, [])
    assert not set(first) & {b["command_id"] for b in bodies.pop("runs")}  # a new start
    demo._stop_runs("http://gpu1", run_ids)
    stops = [b["command_id"] for b in bodies["stop"]]
    assert len(stops) == len(set(stops)) == 6
