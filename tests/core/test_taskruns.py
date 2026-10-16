import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypothex.core import naming
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import key_higher_is_better
from hypothex.core.overview import build_overview
from hypothex.core.records import (
    CostTotals,
    GitInfo,
    MetricPoint,
    RunRecord,
    RunStatus,
    ScoreRecord,
)
from hypothex.core.taskruns import derived_names, latest_scores, run_names, task_runs
from tests.factories import make_record

T0 = utcnow()


def _run(
    ctx: Context, repo: Path, run_id: str, group: str, *, minute: int = 0, **kw: Any
) -> RunRecord:
    """A finished toy-acc run in seed group ``<group>@c1``."""
    ctx.register_project(repo)
    fields: dict[str, Any] = {
        "task": "toy-acc",
        "status": RunStatus.FINISHED,
        "config_hash": f"sha256:{group}",
        "git": GitInfo(commit="c1"),
        "created_at": T0 + timedelta(minutes=minute),
        "cwd": str(repo),
        "environment_id": ctx.descriptor.environment_id,
    }
    fields.update(kw)
    return ctx.create_run(make_record(run_id, project="toy", **fields))


def _scored(ctx: Context, rec: RunRecord, right: int, *, version: str = "v1") -> None:
    """Score ``rec`` ``right``/4 on accuracy with the matching per-example rows."""
    rows = [{"id": f"ex-{i}", "correct": i < right} for i in range(4)]
    path = ctx.run_dir(rec) / "predictions" / f"scores.accuracy@{version}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    score = ScoreRecord(
        metric="accuracy", version=version, key="value", value=right / 4, created_at=utcnow()
    )
    ctx.add_score(rec, score)


def test_runs_are_named_by_what_differs_and_renames_win(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "a", "aaaa", params={"lr": "1e-3", "db": "v3"})
    b = _run(ctx, toy_repo, "b", "bbbb", minute=1, params={"lr": "3e-4", "db": "v3"})
    q.rename_run(ctx, b.run_id, "small lr")
    out = task_runs(ctx, "toy-acc")
    by_id = {r.run_id: r for r in out.runs}
    assert out.varying_keys == ["lr"]
    assert (by_id["a"].name, by_id["a"].derived_name, by_id["a"].renamed) == (
        "lr 1e-3",
        "lr 1e-3",
        False,
    )
    assert (by_id["b"].name, by_id["b"].derived_name, by_id["b"].renamed) == (
        "small lr",
        "lr 3e-4",
        True,
    )
    assert by_id["a"].params == {"lr": "1e-3", "db": "v3"}
    assert by_id["a"].commit == "c1"
    assert run_names(ctx, "toy", "toy-acc") == {"a": "lr 1e-3", "b": "small lr"}
    assert [r.run_id for r in out.runs] == ["b", "a"]  # newest first


def test_groups_reuse_the_leaderboard_statistics(ctx: Context, toy_repo: Path) -> None:
    for i, right in enumerate([3, 3]):
        _scored(ctx, _run(ctx, toy_repo, f"a{i}", "aaaa", minute=i, seed=i), right)
    _scored(ctx, _run(ctx, toy_repo, "b0", "bbbb", minute=2, seed=0), 1)
    _run(ctx, toy_repo, "live", "cccc", minute=3, status=RunStatus.RUNNING)
    board = q.get_leaderboard(ctx, "toy-acc")
    out = task_runs(ctx, "toy-acc")
    assert [g.group_id for g in out.groups] == ["aaaa@c1", "bbbb@c1", "cccc@c1"]
    best, other, live = out.groups
    row = board.rows[0]
    assert (best.primary, best.test_interval, best.n) == (row.primary, row.test_interval, 2)
    assert best.is_best and not other.is_best and not live.is_best
    assert best.scores == {"accuracy/value": 0.75} and best.seed_values == [0.75, 0.75]
    assert other.vs_best == board.rows[1].vs_best
    assert other.within_noise_of_best is (board.rows[1].within_noise_of_best is True)
    assert live.run_ids == ["live"] and live.n == 1
    assert (live.primary, live.test_interval, live.vs_best) == (None, None, None)
    assert {r.run_id: r.primary for r in out.runs} == {
        "a0": 0.75,
        "a1": 0.75,
        "b0": 0.25,
        "live": None,
    }


def test_run_scores_keep_the_newest_value_of_the_current_version(
    ctx: Context, toy_repo: Path
) -> None:
    rec = _run(ctx, toy_repo, "r1", "aaaa")
    _scored(ctx, rec, 1, version="v0")  # an old version is never shown
    _scored(ctx, rec, 2)
    _scored(ctx, rec, 3)
    failed = ScoreRecord(
        metric="accuracy", version="v1", key="value", error="boom", created_at=utcnow()
    )
    ctx.add_score(rec, failed)  # an error never replaces the last value
    out = task_runs(ctx, "toy-acc")
    assert out.runs[0].scores == {"accuracy/value": 0.75}
    assert out.score_keys == ["accuracy/value"]
    assert out.metric_versions == {"accuracy": "v1"}


def test_latest_scores_skips_non_finite_values() -> None:
    def score(value: float, minute: int) -> ScoreRecord:
        at = T0 + timedelta(minutes=minute)
        return ScoreRecord(metric="acc", version="v1", key="value", value=value, created_at=at)

    good = score(0.5, 0)
    assert latest_scores([good, score(float("inf"), 1), score(float("nan"), 2)], {"acc": "v1"}) == {
        "acc/value": 0.5
    }
    assert latest_scores([score(float("nan"), 0)], {"acc": "v1"}) == {}


def test_archived_runs_only_on_request_and_names_stay(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "a", "aaaa", params={"lr": "1"})
    _run(ctx, toy_repo, "b", "bbbb", minute=1, params={"lr": "2"}, archived=True)
    hidden = task_runs(ctx, "toy-acc")
    shown = task_runs(ctx, "toy-acc", archived=True)
    assert [r.run_id for r in hidden.runs] == ["a"]
    assert {r.run_id for r in shown.runs} == {"a", "b"}
    assert hidden.runs[0].name == "lr 1"  # derived over every run, the archived one too
    assert [g.group_id for g in hidden.groups] == ["aaaa@c1"]


def test_metric_names_come_from_the_index_and_live_files(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "done", "aaaa")
    ctx.index.replace_metric_points("done", [MetricPoint(name="train/loss", step=0, value=1.0)])
    live = _run(ctx, toy_repo, "live", "bbbb", minute=1, status=RunStatus.RUNNING)
    append_jsonl(ctx.run_dir(live) / "metrics.jsonl", {"name": "val/acc", "step": 1, "value": 0.5})
    assert task_runs(ctx, "toy-acc").metric_names == ["train/loss", "val/acc"]


def test_cost_and_key_parts(ctx: Context, toy_repo: Path) -> None:
    cfg_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["tasks"]["toy-acc"]["score_keys"] = "{dataset}.{metric}"
    cfg_path.write_text(yaml.safe_dump(cfg))
    cost = CostTotals(gpu_hours=2.0, gpu_usd=4.0, total_usd=4.5, gpu_pricing_complete=True)
    _run(ctx, toy_repo, "paid", "aaaa", cost=cost)
    _run(ctx, toy_repo, "queued", "bbbb", minute=1, status=RunStatus.QUEUED)
    out = task_runs(ctx, "toy-acc")
    by_id = {r.run_id: r for r in out.runs}
    assert (by_id["paid"].gpu_hours, by_id["paid"].cost_usd) == (2.0, 4.5)
    assert (by_id["queued"].gpu_hours, by_id["queued"].cost_usd) == (None, None)
    assert by_id["queued"].progress is None
    assert out.key_parts == ["dataset", "metric"]


def test_each_score_key_carries_its_own_direction(ctx: Context, toy_repo: Path) -> None:
    # a system_bench-like task: lower-is-better latency primary, higher-is-better throughput
    cfg_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["metrics"]["latency"] = {
        "version": "v1",
        "fn": "toymetrics:accuracy",
        "higher_is_better": False,
    }
    cfg["metrics"]["throughput"] = {"version": "v1", "fn": "toymetrics:accuracy"}
    cfg["tasks"]["toy-acc"].update(
        kind="system_bench", metrics=["latency", "throughput"], primary="latency/p95"
    )
    cfg_path.write_text(yaml.safe_dump(cfg))
    rec = _run(ctx, toy_repo, "r1", "aaaa")
    scored = [("latency", "p95", 41.0), ("throughput", "rps", 900.0), ("throughput", "p99", 7.0)]
    for metric, key, value in scored:
        score = ScoreRecord(metric=metric, version="v1", key=key, value=value, created_at=T0)
        ctx.add_score(rec, score)
    out = task_runs(ctx, "toy-acc")
    assert out.higher_is_better is False
    assert out.key_higher_is_better == {
        "latency/p95": False,
        "throughput/p99": False,
        "throughput/rps": True,
    }


def test_key_direction_follows_the_leaderboard_rule(ctx: Context, toy_repo: Path) -> None:
    cfg_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["metrics"]["speed"] = {"version": "v1", "fn": "toymetrics:accuracy"}
    cfg["tasks"]["toy-acc"].update(kind="system_bench", metrics=["speed"], primary="speed/p95")
    cfg_path.write_text(yaml.safe_dump(cfg))
    ctx.register_project(toy_repo)
    entry, _ = q.resolve_task(ctx, "toy-acc")
    config = entry.config
    spec = config.tasks["toy-acc"]
    # a system_bench percentile is lower-is-better, the primary's and every other one
    assert key_higher_is_better(config, spec, "speed/p95") is False
    assert key_higher_is_better(config, spec, "speed/p50") is False
    assert key_higher_is_better(config, spec, "speed/p99") is False
    # any other key: its metric's own direction
    assert key_higher_is_better(config, spec, "speed/rps") is True


def test_groups_with_the_same_params_on_two_commits_get_distinct_names(
    ctx: Context, toy_repo: Path
) -> None:
    _run(ctx, toy_repo, "a", "aaaa", params={"lr": "3e-4"}, git=GitInfo(commit="aaaaaaa1111"))
    _run(
        ctx,
        toy_repo,
        "b",
        "aaaa",
        minute=1,
        params={"lr": "3e-4"},
        git=GitInfo(commit="bbbbbbb2222"),
    )
    _run(
        ctx,
        toy_repo,
        "c",
        "cccc",
        minute=2,
        params={"lr": "1e-3"},
        git=GitInfo(commit="bbbbbbb2222"),
    )
    names = sorted(g.name for g in task_runs(ctx, "toy-acc").groups)
    assert names == ["lr 1e-3", "lr 3e-4 · @aaaaaaa", "lr 3e-4 · @bbbbbbb"]
    q.rename_run(ctx, "a", "first try")
    names = sorted(g.name for g in task_runs(ctx, "toy-acc").groups)
    assert names == ["first try", "lr 1e-3", "lr 3e-4"]  # no clash left


def test_derived_names_are_memoised_until_the_index_changes(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(ctx, toy_repo, "a", "aaaa", params={"lr": "1e-3"})
    _run(ctx, toy_repo, "b", "bbbb", minute=1, params={"lr": "3e-4"}, status=RunStatus.RUNNING)
    calls: list[int] = []
    real = naming.derive_names

    def counting(runs: Any) -> dict[str, str]:
        calls.append(len(runs))
        return real(runs)

    for module in ("hypothex.core.taskruns", "hypothex.core.overview", "hypothex.core.panels"):
        monkeypatch.setattr(f"{module}.derive_names", counting, raising=False)
    first = derived_names(ctx, "toy", "toy-acc")
    assert first == {"a": "lr 1e-3", "b": "lr 3e-4"}
    first["a"] = "changed by a caller"
    # the same index generation: no new derivation from any caller, and a copy each time
    assert derived_names(ctx, "toy", "toy-acc") == {"a": "lr 1e-3", "b": "lr 3e-4"}
    task_runs(ctx, "toy-acc")
    run_names(ctx, "toy", "toy-acc")
    build_overview(ctx)
    build_overview(ctx)
    assert calls == [2]
    # a write bumps the generation: the next call derives again
    _run(ctx, toy_repo, "c", "cccc", minute=2, params={"lr": "1e-2"})
    assert derived_names(ctx, "toy", "toy-acc")["c"] == "lr 1e-2"
    assert calls == [2, 3]
