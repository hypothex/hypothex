import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypothex.core import panels
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.ids import utcnow
from hypothex.core.panels import PanelResult, query_panel, query_view
from hypothex.core.records import GitInfo, MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.store import safe_stem
from hypothex.core.views import PanelData, PanelSpec, RunFilter, ViewSpec
from tests.factories import make_record

T0 = utcnow()


def _run(
    ctx: Context, repo: Path, run_id: str, group: str = "aaaa", *, minute: int = 0, **kw: Any
) -> RunRecord:
    """Create a finished toy-acc run in seed group ``<group>@c1``."""
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


def _score(ctx: Context, rec: RunRecord, value: float) -> None:
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v1", key="value", value=value, created_at=T0)
    )


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _panel(type_: str, **kw: Any) -> PanelSpec:
    data = kw.pop("data", {})
    return PanelSpec.model_validate({"type": type_, "title": "p", "data": data, **kw})


def _ids(result: PanelResult) -> list[str]:
    return [row["run_id"] for row in result.rows]


def _set_task(repo: Path, **fields: Any) -> None:
    """Change toy-acc's entry in ``hypothex.yaml``; every query re-reads the config."""
    path = repo / "hypothex.yaml"
    config = yaml.safe_load(path.read_text())
    config["tasks"]["toy-acc"].update(fields)
    path.write_text(yaml.safe_dump(config, sort_keys=False))


# markdown, stat strip, leaderboard ----------------------------------------------
def test_markdown_panel(ctx: Context) -> None:
    result = query_panel(ctx, "nope", "nope", _panel("markdown", text="**hi**"))
    assert result == PanelResult(type="markdown", title="p", rows=[], meta={"text": "**hi**"})


def _two_groups(ctx: Context, repo: Path) -> None:
    for rid, group, seed, value, minute in [
        ("s1", "aaaa", 1, 0.8, 0),
        ("s2", "aaaa", 2, 0.9, 1),
        ("f1", "bbbb", 1, 0.6, 2),
    ]:
        rec = _run(
            ctx,
            repo,
            rid,
            group,
            seed=seed,
            minute=minute,
            hypothesis="svm" if group == "aaaa" else "rf",
            params={"model": "svm" if group == "aaaa" else "rf"},
        )
        _score(ctx, rec, value)


def test_leaderboard_and_stat_strip_match_task_leaderboard(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    board = q.get_leaderboard(ctx, "toy/toy-acc")

    lb = query_panel(ctx, "toy", "toy-acc", _panel("leaderboard", noise=["seed"]))
    assert [r["group_id"] for r in lb.rows] == ["aaaa@c1", "bbbb@c1"]
    assert lb.rows == [row.model_dump(mode="json") for row in board.rows]
    assert lb.rows[0]["primary"]["mean"] == pytest.approx(0.85)
    assert lb.rows[0]["label"] == "svm"
    assert lb.meta["primary"] == "accuracy/value"
    assert lb.meta["noise"] == ["seed"]
    assert lb.meta["headline"] == board.headline

    strip = query_panel(ctx, "toy", "toy-acc", _panel("stat_strip"))
    assert strip.rows == board.stat_strip
    assert strip.meta == {"headline": board.headline}


def test_data_filter_selects_runs_by_flattened_fields(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    panel = _panel("leaderboard", data={"filter": {"params.model": "rf"}})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert [r["group_id"] for r in result.rows] == ["bbbb@c1"]


# run selection -------------------------------------------------------------------
def test_run_filter_status_tags_created_by_since(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "a", minute=0, tags=["baseline", "x"])
    _run(ctx, toy_repo, "b", minute=1, status=RunStatus.FAILED, created_by="agent:claude")
    _run(ctx, toy_repo, "c", minute=2, created_by="agent:claude", tags=["x"])
    _run(ctx, toy_repo, "d", minute=3, archived=True)
    table = _panel("table", data={"source": "runs", "fields": []})

    def ids(flt: RunFilter | None) -> list[str]:
        return _ids(query_panel(ctx, "toy", "toy-acc", table, flt))

    assert ids(None) == ["a", "b", "c"]  # oldest first, archived hidden
    assert ids(RunFilter(status=["finished"])) == ["a", "c"]
    assert ids(RunFilter(tags=["x"])) == ["a", "c"]
    assert ids(RunFilter(tags=["baseline", "x"])) == ["a"]
    assert ids(RunFilter(created_by="agent:claude")) == ["b", "c"]
    since_naive = (T0 + timedelta(minutes=1)).replace(tzinfo=None)
    assert ids(RunFilter(since=since_naive)) == ["b", "c"]


def test_pick_latest_and_best(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    table = {"source": "runs", "fields": []}
    latest = query_panel(ctx, "toy", "toy-acc", _panel("table", data={**table, "pick": "latest"}))
    assert _ids(latest) == ["s2", "f1"]
    best = query_panel(ctx, "toy", "toy-acc", _panel("table", data={**table, "pick": "best"}))
    assert _ids(best) == ["s1", "s2"]
    everything = query_panel(ctx, "toy", "toy-acc", _panel("table", data={**table, "pick": "all"}))
    assert _ids(everything) == ["s1", "s2", "f1"]


def test_unknown_task_raises(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    with pytest.raises(ConfigError, match="unknown task 'nope'"):
        query_panel(ctx, "toy", "nope", _panel("leaderboard"))


# table and vega-lite --------------------------------------------------------------
def test_table_source_fields_and_row_filter(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "u1", seed=4)
    _jsonl(
        ctx.run_dir(rec) / "usage.jsonl",
        [{"example_id": "ex-0", "usd": 0.5}, {"example_id": "ex-1", "usd": 0.25}],
    )
    panel = _panel(
        "table",
        data={"source": "usage", "fields": ["example_id", "usd"], "filter": {"example_id": "ex-1"}},
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == [
        {"run_id": "u1", "group_id": "aaaa@c1", "seed": 4, "example_id": "ex-1", "usd": 0.25}
    ]
    assert result.meta == {"source": "usage", "total": 1}


def test_table_filters_full_rows_before_projecting(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", seed=2)
    _score(ctx, rec, 0.75)
    ctx.add_score(
        rec, ScoreRecord(metric="broken", version="v1", key="value", value=0.5, created_at=T0)
    )
    # the filter reads "metric", which the table does not show
    panel = _panel(
        "table",
        data={"source": "scores", "fields": ["value"], "filter": {"metric": "accuracy"}},
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == [{"run_id": "r1", "group_id": "aaaa@c1", "seed": 2, "value": 0.75}]
    assert result.meta == {"source": "scores", "total": 1}


def test_runs_table_version_field(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "a", minute=0, params={"version": "v2", "prompt_version": "p7"})
    _run(ctx, toy_repo, "b", "bbbb", minute=1)  # no version param: its group's first run time
    _run(ctx, toy_repo, "c", "bbbb", minute=2)
    panel = _panel("table", data={"source": "runs", "fields": ["version"]})
    first_b = (T0 + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    rows = query_panel(ctx, "toy", "toy-acc", panel).rows
    assert [(r["run_id"], r["version"]) for r in rows] == [
        ("a", "v2"),
        ("b", first_b),
        ("c", first_b),
    ]
    _set_task(toy_repo, version_param="prompt_version")
    rows = query_panel(ctx, "toy", "toy-acc", panel).rows
    assert [r["version"] for r in rows] == ["p7", first_b, first_b]


def test_runs_table_filters_on_version_it_does_not_show(ctx: Context, toy_repo: Path) -> None:
    # regression: `version` was added only when `fields` listed it, so this matched nothing
    _run(ctx, toy_repo, "a", minute=0, seed=1, params={"version": "p10"})
    _run(ctx, toy_repo, "b", "bbbb", minute=1, seed=1, params={"version": "p9"})
    _run(ctx, toy_repo, "c", "cccc", minute=2, seed=1)  # no param: a creation time
    panel = _panel(
        "table", data={"source": "runs", "fields": ["status"], "filter": {"version": "p10"}}
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == [{"run_id": "a", "group_id": "aaaa@c1", "seed": 1, "status": "finished"}]
    assert result.meta == {"source": "runs", "total": 1}
    everything = query_panel(ctx, "toy", "toy-acc", _panel("table", data={"source": "runs"}))
    assert [r["version"] for r in everything.rows][:2] == ["p10", "p9"]  # no fields: shown


def test_table_truncates_large_sources(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panels, "MAX_TABLE_ROWS", 2)
    rec = _run(ctx, toy_repo, "u1")
    _jsonl(ctx.run_dir(rec) / "samples" / "lat.jsonl", [{"value": v} for v in range(5)])
    result = query_panel(ctx, "toy", "toy-acc", _panel("table", data={"source": "samples"}))
    assert [r["value"] for r in result.rows] == [0.0, 1.0]
    assert result.meta["total"] == 5
    assert result.meta["warnings"] == ["showing the first 2 of 5 rows"]


def test_vega_lite_spec_has_empty_values(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "r1", params={"lr": "0.1"})
    spec = {
        "mark": "point",
        "data": {"url": "https://example.com/x.json"},
        "encoding": {"x": {"field": "params.lr", "type": "quantitative"}},
    }
    panel = _panel("vega_lite", spec=spec, data={"source": "runs", "fields": ["params.lr"]})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.meta["spec"] == {
        "mark": "point",
        "data": {"values": []},
        "encoding": {"x": {"field": "params.lr", "type": "quantitative"}},
    }
    assert panel.spec is not None and panel.spec["data"] == {"url": "https://example.com/x.json"}
    assert result.rows == [
        {"run_id": "r1", "group_id": "aaaa@c1", "seed": None, "params.lr": "0.1"}
    ]


def test_vega_lite_nested_external_data_is_a_panel_error(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "r1")
    spec = {
        "layer": [
            {"mark": "point"},
            {"mark": "line", "data": {"url": "https://example.com/x.json"}},
        ]
    }
    panel = _panel("vega_lite", spec=spec, data={"source": "runs"})
    with pytest.raises(ConfigError, match=r"resources \(url\) at spec\.layer\.1\.data\.url"):
        query_panel(ctx, "toy", "toy-acc", panel)
    # views that were never validated (inline, editor preview): one panel error, not a 500
    (result,) = query_view(ctx, "toy", "toy-acc", ViewSpec(title="v", panels=[panel]))
    assert result.rows == []
    assert result.meta["error"].startswith("vega_lite spec must not load external resources")


# trace --------------------------------------------------------------------------
def _write_trace(ctx: Context, rec: RunRecord, example_id: str, fail: bool) -> None:
    steps = [
        {
            "turn": 1,
            "tool": "search",
            "args": {"q": "x"},
            "result": "ok",
            "tokens_in": 10,
            "tokens_out": 5,
            "seconds": 0.5,
        },
        {
            "turn": 2,
            "tool": "edit",
            "args": {},
            "result": None,
            "tokens_in": 3,
            "tokens_out": 1,
            "seconds": 0.25,
            "error": "patch failed" if fail else None,
        },
    ]
    _jsonl(ctx.run_dir(rec) / "traces" / f"{safe_stem(example_id)}.jsonl", steps)


def test_trace_panel_for_explicit_run_and_example(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "t1")
    _write_trace(ctx, rec, "ex/1", fail=True)
    panel = _panel("trace", data={"run_id": "t1", "example_id": "ex/1"})
    result = query_panel(ctx, "toy", "any-task", panel)
    assert result.rows == [
        {
            "turn": 1,
            "tool": "search",
            "args": {"q": "x"},
            "result": "ok",
            "tokens_in": 10,
            "tokens_out": 5,
            "seconds": 0.5,
            "error": None,
        },
        {
            "turn": 2,
            "tool": "edit",
            "args": {},
            "result": None,
            "tokens_in": 3,
            "tokens_out": 1,
            "seconds": 0.25,
            "error": "patch failed",
        },
    ]
    assert result.meta == {"run_id": "t1", "example_id": "ex/1", "failed_turn": 2}


def test_trace_panel_missing_example_warns(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "t1")
    panel = _panel("trace", data={"run_id": "t1", "example_id": "nope"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == []
    assert result.meta["failed_turn"] is None
    assert result.meta["warnings"] == ["no trace for example 'nope' in run t1"]


def test_trace_panel_picks_latest_run_and_failing_example(ctx: Context, toy_repo: Path) -> None:
    old = _run(ctx, toy_repo, "t1", minute=0)
    new = _run(ctx, toy_repo, "t2", minute=1)
    _run(ctx, toy_repo, "t3", minute=2)  # no traces
    _write_trace(ctx, old, "ex-9", fail=True)
    _write_trace(ctx, new, "ex-a", fail=False)
    _write_trace(ctx, new, "ex-b", fail=True)
    result = query_panel(ctx, "toy", "toy-acc", _panel("trace"))
    assert result.meta == {"run_id": "t2", "example_id": "ex-b", "failed_turn": 2}


def test_trace_panel_without_traces(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "t1")
    result = query_panel(ctx, "toy", "toy-acc", _panel("trace"))
    assert result.rows == []
    assert result.meta["warnings"] == ["no run in this view has traces"]


# views ------------------------------------------------------------------------------
def test_query_view_applies_run_filter_and_isolates_errors(ctx: Context, toy_repo: Path) -> None:
    _run(ctx, toy_repo, "a", minute=0)
    _run(ctx, toy_repo, "b", minute=1, status=RunStatus.FAILED)
    view = ViewSpec(
        title="v",
        runs=RunFilter(status=["finished"]),
        panels=[
            PanelSpec(type="markdown", title="notes", text="hi"),
            PanelSpec(type="trace", title="bad", data=PanelData(run_id="missing")),
            PanelSpec(type="table", title="runs", data=PanelData(source="runs", fields=[])),
        ],
    )
    notes, bad, runs = query_view(ctx, "toy", "toy-acc", view)
    assert notes.meta == {"text": "hi"}
    assert (bad.type, bad.title, bad.rows) == ("trace", "bad", [])
    assert "missing" in bad.meta["error"]
    assert _ids(runs) == ["a"]


# curves --------------------------------------------------------------------------
def test_curves_rows_spikes_kills_and_checkpoints(ctx: Context, toy_repo: Path) -> None:
    c1 = _run(ctx, toy_repo, "c1", seed=1, hypothesis="baseline")
    c2 = _run(ctx, toy_repo, "c2", seed=2, minute=1, status=RunStatus.KILLED)
    loss = [{"name": "train/loss", "step": s, "value": 6.0 if s == 22 else 1.0} for s in range(25)]
    acc = [{"name": "val/acc", "step": s, "value": 100.0 if s == 10 else 0.5} for s in range(25)]
    _jsonl(ctx.run_dir(c1) / "metrics.jsonl", loss + acc)
    _jsonl(
        ctx.run_dir(c2) / "metrics.jsonl",
        [{"name": "train/loss", "step": s, "value": 1.0} for s in range(5)],
    )
    _jsonl(
        ctx.run_dir(c1) / "artifacts.jsonl",
        [
            {"kind": "checkpoint", "path": "/ck/10.pt", "step": 10, "metrics": {"val/acc": 0.5}},
            {"kind": "checkpoint", "path": "/ck/20.pt", "step": 20, "metrics": {"val/acc": 0.7}},
            {"kind": "model", "path": "/final.pt"},
        ],
    )
    panel = _panel("curves", data={"metrics": ["train/loss", "val/acc"]})
    result = query_panel(ctx, "toy", "toy-acc", panel)

    assert len(result.rows) == 55  # c1: 25 + 25 points, c2: 5 points
    assert result.rows[22] == {
        "run_id": "c1",
        "group_id": "aaaa@c1",
        "seed": 1,
        "name": "train/loss",
        "step": 22,
        "value": 6.0,
    }
    # step 22: 6.0 > 5 x median(previous 20 values = 1.0); val/acc jumps are ignored (no "loss")
    assert result.meta["events"] == [
        {"run_id": "c1", "step": 22, "kind": "spike"},
        {"run_id": "c2", "step": 4, "kind": "killed"},
    ]
    assert result.meta["checkpoints"] == [
        {"run_id": "c1", "step": 10, "value": 0.5, "best": False},
        {"run_id": "c1", "step": 20, "value": 0.7, "best": True},
    ]
    assert result.meta["groups"] == [{"group_id": "aaaa@c1", "label": "baseline"}]
    assert result.meta["metrics"] == ["train/loss", "val/acc"]
    assert result.meta["x"] == "step"


def test_curves_loss_checkpoint_best_is_minimum(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "c1")
    _jsonl(
        ctx.run_dir(rec) / "artifacts.jsonl",
        [
            {"kind": "checkpoint", "path": "/a", "step": 1, "metrics": {"val/loss": 0.9}},
            {"kind": "checkpoint", "path": "/b", "step": 2, "metrics": {"val/loss": 0.4}},
            {"kind": "checkpoint", "path": "/c", "step": 3, "metrics": {"val/loss": 0.6}},
        ],
    )
    result = query_panel(ctx, "toy", "toy-acc", _panel("curves"))
    assert [c["best"] for c in result.meta["checkpoints"]] == [False, True, False]


def test_curves_step_metric_and_group_by_run(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "c1", seed=1)
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [{"name": "epoch", "step": s, "value": s // 2} for s in range(4)]
        + [{"name": "val/acc", "step": s, "value": 0.1 * s} for s in (0, 2, 3, 9)],
    )
    panel = _panel(
        "curves", data={"metrics": ["val/acc"], "step_metric": "epoch", "group_by": "run"}
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # step 9 has no epoch value, so it is dropped
    assert [(r["step"], r["value"]) for r in result.rows] == [
        (0, 0.0),
        (1, pytest.approx(0.2)),
        (1, pytest.approx(0.30000000000000004)),
    ]
    assert {r["group_id"] for r in result.rows} == {"c1"}
    assert result.meta["x"] == "epoch"


def test_checkpoints_use_the_step_metric_x(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "c1")
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [{"name": "epoch", "step": s, "value": s // 100} for s in (0, 100, 200, 300)]
        + [{"name": "val/acc", "step": s, "value": 0.1 * s / 100} for s in (100, 200, 300)],
    )
    _jsonl(
        ctx.run_dir(rec) / "artifacts.jsonl",
        [
            {"kind": "checkpoint", "path": "/a", "step": 100, "metrics": {"val/acc": 0.1}},
            {"kind": "checkpoint", "path": "/b", "step": 300, "metrics": {"val/acc": 0.3}},
            {"kind": "checkpoint", "path": "/c", "step": 250, "metrics": {"val/acc": 0.9}},
        ],
    )
    panel = _panel("curves", data={"metrics": ["val/acc"], "step_metric": "epoch"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert [r["step"] for r in result.rows] == [1, 2, 3]
    # training steps 100 and 300 are epochs 1 and 3; step 250 has no epoch value: dropped
    assert result.meta["checkpoints"] == [
        {"run_id": "c1", "step": 1, "value": 0.1, "best": False},
        {"run_id": "c1", "step": 3, "value": 0.3, "best": True},
    ]


def test_spike_detection_rules() -> None:
    def pts(values: list[float]) -> list[MetricPoint]:
        return [MetricPoint(name="loss", step=i, value=v) for i, v in enumerate(values)]

    assert panels._spikes(pts([1.0, 5.0, 5.1])) == []  # median(1, 5) = 3 -> 5.1 < 15
    assert panels._spikes(pts([1.0, 5.1])) == [1]
    assert panels._spikes(pts([1.0, 5.0])) == []  # not strictly greater than 5x
    assert panels._spikes(pts([0.0, 3.0])) == [1]  # 3 > 5 x median(0) = 0 (contract rule)
    assert panels._spikes(pts([0.0, 0.0, 0.0])) == []  # 0 > 0 is false
    # only the previous 20 values count: median(20 x 3.0) = 3 -> 16 > 15 is a spike,
    # although the median of the whole history (21 x 10.0, 20 x 3.0) would be 10
    assert panels._spikes(pts([10.0] * 21 + [3.0] * 20 + [16.0])) == [41]
