import json
import math
import tracemalloc
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
from hypothex.core.records import (
    GitInfo,
    MetricPoint,
    RunRecord,
    RunStatus,
    ScoreRecord,
    UsageTotals,
)
from hypothex.core.store import safe_stem
from hypothex.core.thin import MAX_POINTS_PER_METRIC
from hypothex.core.views import (
    GROUP_FIELDS,
    MAX_PANEL_REFS,
    PanelData,
    PanelSpec,
    RunFilter,
    ViewSpec,
)
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


def _metrics(ctx: Context, rec: RunRecord, rows: list[dict[str, Any]]) -> None:
    """Write a run's ``metrics.jsonl`` and index it, as the end of the run does."""
    _jsonl(ctx.run_dir(rec) / "metrics.jsonl", rows)
    ctx.index.replace_metric_points(rec.run_id, ctx.store.read_metric_points("toy", rec.run_id))


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
    assert strip.meta == {"headline": board.headline, "unit": "", "value_format": "fraction"}
    assert (lb.meta["unit"], lb.meta["value_format"]) == ("", "fraction")


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
        {
            "run_id": "u1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": 4,
            "example_id": "ex-1",
            "usd": 0.25,
        }
    ]
    # the table draws the listed fields; rows keep run_id/group_id/label/seed too
    assert result.meta == {"source": "usage", "total": 1, "columns": ["example_id", "usd"]}


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
    assert result.rows == [
        {"run_id": "r1", "group_id": "aaaa@c1", "label": "group aaaa@c1", "seed": 2, "value": 0.75}
    ]
    assert result.meta == {"source": "scores", "total": 1, "columns": ["value"]}


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
    assert result.rows == [
        {
            "run_id": "a",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": 1,
            "status": "finished",
        }
    ]
    assert result.meta == {"source": "runs", "total": 1, "columns": ["status"]}
    everything = query_panel(ctx, "toy", "toy-acc", _panel("table", data={"source": "runs"}))
    assert [r["version"] for r in everything.rows][:2] == ["p10", "p9"]  # no fields: shown
    assert "columns" not in everything.meta  # no fields: every row key is a column


def test_table_rows_carry_leaderboard_labels(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    _run(ctx, toy_repo, "c1", "cccc", minute=3, status=RunStatus.RUNNING, tags=["knn"])
    scores = _panel("table", data={"source": "scores", "fields": ["value"]})
    rows = query_panel(ctx, "toy", "toy-acc", scores).rows
    assert [(r["group_id"], r["label"]) for r in rows] == [
        ("aaaa@c1", "svm"),
        ("aaaa@c1", "svm"),
        ("bbbb@c1", "rf"),
    ]
    runs = query_panel(ctx, "toy", "toy-acc", _panel("table", data={"source": "runs"})).rows
    assert runs[-1]["label"] == "knn"  # not on the board: the same rule over its own runs


def test_agent_iteration_rows_are_labelled_by_version(ctx: Context, toy_repo: Path) -> None:
    _set_task(toy_repo, kind="agent_iteration")
    for rid, group, version, minute in [("a", "aaaa", "v1", 0), ("b", "bbbb", "v2", 1)]:
        rec = _run(
            ctx, toy_repo, rid, group, minute=minute, hypothesis="x", params={"version": version}
        )
        _score(ctx, rec, 0.5)
    _run(ctx, toy_repo, "c", "cccc", minute=2, status=RunStatus.RUNNING, params={"version": "v3"})
    table = _panel("table", data={"source": "runs", "fields": []})
    rows = query_panel(ctx, "toy", "toy-acc", table).rows
    assert [r["label"] for r in rows] == ["v1", "v2", "v3"]


def test_data_filter_matches_group_labels(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    panel = _panel("leaderboard", data={"filter": {"label": "rf"}})
    assert [r["group_id"] for r in query_panel(ctx, "toy", "toy-acc", panel).rows] == ["bbbb@c1"]
    table = _panel("table", data={"source": "runs", "fields": [], "filter": {"label": "svm"}})
    assert _ids(query_panel(ctx, "toy", "toy-acc", table)) == ["s1", "s2"]


def test_group_changes_lists_differing_params_else_the_commit_first_group_empty() -> None:
    def rec(commit: str | None, **params: str) -> RunRecord:
        return make_record(params=params, vars={"lr": "0.1"}, git=GitInfo(commit=commit))

    v1 = rec("aaaaaaa111", version="v1", model="sonnet-5", tools="search,expand")
    v2 = rec("bbbbbbb222", version="v2", model="opus-5.5", tools="search,expand,stock_check")
    assert panels.group_changes(None, v1, "version") == ""  # first group: nothing to compare
    assert (
        panels.group_changes(v1, v2, "version") == "model: sonnet-5 → opus-5.5; tools: +stock_check"
    )
    v3 = rec("ccccccc333", version="v3", model="opus-5.5", tools="search", depth="6")
    assert panels.group_changes(v2, v3, "version") == "tools: −expand −stock_check; depth: — → 6"
    v4 = rec("ddddddd444", version="v4", model="opus-5.5", tools="search")
    assert panels.group_changes(v3, v4, "version") == "depth: 6 → —"
    # the version param never counts as a change; nothing else differs -> the commit
    v5 = rec("eeeeeee555", version="v5", model="opus-5.5", tools="search")
    assert panels.group_changes(v4, v5, "version") == "eeeeeee"
    nogit = rec(None, version="v6", model="opus-5.5", tools="search")
    assert panels.group_changes(v4, nogit, "version") == ""


def test_groups_source_one_row_per_group_in_version_order(ctx: Context, toy_repo: Path) -> None:
    runs = [
        ("a1", "aaaa", "v10", 1, 0.9, 0, "c1"),
        ("a2", "aaaa", "v10", 2, 0.7, 1, "c1"),
        ("b1", "bbbb", "v9", 1, 0.6, 2, "c1"),
        ("b2", "bbbb", "v9", 2, 0.6, 3, "c1"),
        ("c1", "cccc", None, 1, None, 4, "c1"),  # no version param, not scored
    ]
    for rid, group, version, seed, value, minute, _ in runs:
        params = {"model": "m" + group[0]} | ({"version": version} if version else {})
        rec = _run(
            ctx,
            toy_repo,
            rid,
            group,
            minute=minute,
            seed=seed,
            params=params,
            created_by="human:x" if seed == 1 else "agent:y",
            hypothesis=f"try {group}",
        )
        if value is not None:
            _score(ctx, rec, value)
    panel = _panel("table", data={"source": "groups"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.meta == {"source": "groups", "total": 3}
    b, a, c = result.rows
    assert [r["version"] for r in result.rows] == [
        "v9",
        "v10",
        (T0 + timedelta(minutes=4)).strftime("%Y-%m-%d %H:%M:%S"),
    ]
    assert set(a) == set(GROUP_FIELDS)
    assert (a["group_id"], a["label"], a["run_id"], a["n"]) == ("aaaa@c1", "try aaaa", "a2", 2)
    assert (a["commit"], a["created_by"], a["hypothesis"]) == ("c1", "agent:y, human:x", "try aaaa")
    assert a["primary"] == pytest.approx(0.8)
    assert a["primary_lo"] < 0.8 < a["primary_hi"]  # seed t-interval (no per-example file)
    assert b["delta_prev"] is None and b["changes"] == ""  # first row: nothing to compare
    assert a["delta_prev"] == pytest.approx(0.2)
    assert a["changes"] == "model: mb → ma"
    assert (c["primary"], c["primary_lo"], c["delta_prev"]) == (None, None, None)
    # fields keep exactly the listed keys, in order; the filter reads the full row
    fields = ["version", "changes", "delta_prev", "n"]
    panel = _panel("table", data={"source": "groups", "fields": fields, "filter": {"n": 2}})
    rows = query_panel(ctx, "toy", "toy-acc", panel).rows
    assert [list(r) for r in rows] == [fields, fields]
    assert [r["version"] for r in rows] == ["v9", "v10"]


def test_iter_rows_refuses_the_task_level_groups_source(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    with pytest.raises(ConfigError, match="groups is a task-level source"):
        list(panels.iter_rows(ctx, [rec], "groups"))


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
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": None,
            "params.lr": "0.1",
        }
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
    _metrics(ctx, c1, loss + acc)
    _metrics(
        ctx,
        c2,
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
        {"run_id": "c1", "step": 22, "kind": "spike", "label": "spike 22"},
        {"run_id": "c2", "step": 4, "kind": "killed", "label": "killed 4"},
    ]
    assert result.meta["checkpoints"] == [
        {"run_id": "c1", "step": 10, "value": 0.5, "best": False},
        {"run_id": "c1", "step": 20, "value": 0.7, "best": True},
    ]
    assert result.meta["groups"] == [{"group_id": "aaaa@c1", "label": "baseline"}]
    assert result.meta["metrics"] == ["train/loss", "val/acc"]
    assert result.meta["x"] == "step"


def test_curves_nonfinite_markers_become_events(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "c1", seed=1)
    _metrics(
        ctx,
        rec,
        [{"name": "train/loss", "step": s, "value": 1.0} for s in range(5)],
    )
    _jsonl(
        ctx.run_dir(rec) / "metrics_nonfinite.jsonl",
        [
            {"name": "train/loss", "step": 9000, "value": "nan", "t": 1.0},
            {"name": "val/loss", "step": 9000, "value": "inf", "t": 1.0},  # same step: one event
            {"name": "other", "step": 3, "value": "-inf", "t": 1.0},  # not a shown metric
            {"name": "train/loss", "step": 4, "value": 1.0},  # malformed: skipped
        ],
    )
    panel = _panel("curves", data={"metrics": ["train/loss", "val/loss"]})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.meta["events"] == [
        {"run_id": "c1", "step": 9000, "kind": "nonfinite", "label": "NaN 9k"},
    ]
    # no metric list: every name counts
    result = query_panel(ctx, "toy", "toy-acc", _panel("curves"))
    assert [(e["step"], e["kind"]) for e in result.meta["events"]] == [
        (3, "nonfinite"),
        (9000, "nonfinite"),
    ]


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
    _metrics(
        ctx,
        rec,
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


def test_group_by_run_labels_each_repeat_of_its_config(ctx: Context, toy_repo: Path) -> None:
    for rid, group, minute in [("b1", "aaaa", 0), ("c1", "bbbb", 1), ("b2", "aaaa", 2)]:
        rec = _run(ctx, toy_repo, rid, group, minute=minute, hypothesis=f"h{group[0]}")
        _metrics(ctx, rec, [{"name": "gpu_pct", "step": 0, "value": 40}])
        _score(ctx, rec, 0.5)
    curves = _panel("curves", data={"metrics": ["gpu_pct"], "group_by": "run"})
    result = query_panel(ctx, "toy", "toy-acc", curves)
    assert result.meta["groups"] == [
        {"group_id": "b1", "label": "ha r1", "seed_group": "aaaa@c1", "repeat": 1},
        {"group_id": "c1", "label": "hb r1", "seed_group": "bbbb@c1", "repeat": 1},
        {"group_id": "b2", "label": "ha r2", "seed_group": "aaaa@c1", "repeat": 2},
    ]
    # other panels grouped by run get the same labels
    scatter = _panel("scatter", data={"x": "gpu_pct", "group_by": "run"})
    assert [r["label"] for r in query_panel(ctx, "toy", "toy-acc", scatter).rows] == [
        "ha r1",
        "hb r1",
        "ha r2",
    ]


def test_group_by_config_labels_follow_the_board_rule(ctx: Context, toy_repo: Path) -> None:
    # two configs of one sweep share a hypothesis: they get the vars that differ
    for rid, group, lr in [("a1", "aaaa", "1e-3"), ("b1", "bbbb", "1e-4")]:
        rec = _run(ctx, toy_repo, rid, group, hypothesis="lr sweep", vars={"lr": lr})
        _metrics(ctx, rec, [{"name": "gpu_pct", "step": 0, "value": 40}])
    curves = _panel("curves", data={"metrics": ["gpu_pct"], "group_by": "config"})
    groups = query_panel(ctx, "toy", "toy-acc", curves).meta["groups"]
    assert [g["label"] for g in groups] == ["lr sweep · lr 1e-3", "lr sweep · lr 1e-4"]


def test_checkpoints_use_the_step_metric_x(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "c1")
    _metrics(
        ctx,
        rec,
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


def test_curves_spike_episode_is_one_event_across_loss_metrics(
    ctx: Context, toy_repo: Path
) -> None:
    rec = _run(ctx, toy_repo, "c1", status=RunStatus.FAILED)
    steps = [s * 500 for s in range(40)]  # 0 .. 19,500

    def loss(name: str, spiked: set[int]) -> list[dict[str, Any]]:
        return [{"name": name, "step": s, "value": 9.0 if s in spiked else 1.0} for s in steps]

    # train loss spikes at 12k, 12.5k, 13k; val loss at 12.5k (inside the same episode);
    # a second train spike at 18k is its own event
    points = loss("train/loss", {12_000, 12_500, 13_000, 18_000}) + loss("val/loss", {12_500})
    _metrics(ctx, rec, points)
    result = query_panel(ctx, "toy", "toy-acc", _panel("curves", data={"group_by": "run"}))
    assert result.meta["events"] == [
        {"run_id": "c1", "step": 12_000, "kind": "spike", "label": "spike 12k"},
        {"run_id": "c1", "step": 18_000, "kind": "spike", "label": "spike 18k"},
        {"run_id": "c1", "step": 19_500, "kind": "failed", "label": "failed 20k"},
    ]


def test_short_step_labels() -> None:
    cases = {0: "0", 950: "950", 9000: "9k", 9500: "9.5k", 14_250: "14k", 1_250_000: "1.3M"}
    assert {x: panels.short_step(x) for x in cases} == cases
    assert panels.short_step(2.5) == "2.5"


# scatter --------------------------------------------------------------------------
def test_scatter_groups_intervals_and_pareto(ctx: Context, toy_repo: Path) -> None:
    for rid, group, hyp, usd, acc, minute in [
        ("s1", "aaaa", "svm", 0.1, 0.8, 0),
        ("s2", "aaaa", "svm", 0.3, 0.9, 1),
        ("f1", "bbbb", "rf", 0.05, 0.6, 2),
        ("g1", "cccc", "gbm", 0.5, 0.7, 3),
    ]:
        rec = _run(
            ctx, toy_repo, rid, group, minute=minute, hypothesis=hyp, usage=UsageTotals(usd=usd)
        )
        _score(ctx, rec, acc)
    panel = _panel(
        "scatter", data={"x": "usage.usd", "y": "accuracy"}, pareto={"x": "min", "y": "max"}
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    by_label = {r["label"]: r for r in result.rows}
    svm = by_label["svm"]
    # 95% t-interval, df=1: t = 12.706 (seeds._T_975); stdev([0.1, 0.3]) / sqrt(2) = 0.1
    assert svm["x"] == pytest.approx(0.2)
    assert svm["x_lo"] == pytest.approx(0.2 - 1.2706)
    assert svm["x_hi"] == pytest.approx(0.2 + 1.2706)
    # stdev([0.8, 0.9]) / sqrt(2) = 0.05 -> half-width 0.6353
    assert svm["y"] == pytest.approx(0.85)
    assert svm["y_lo"] == pytest.approx(0.85 - 0.6353)
    assert svm["y_hi"] == pytest.approx(0.85 + 0.6353)
    assert svm["seeds"] == [{"x": 0.1, "y": 0.8}, {"x": 0.3, "y": 0.9}]
    assert by_label["rf"]["x_lo"] is None and by_label["rf"]["y_hi"] is None
    # gbm (0.5, 0.7) is dominated by svm (0.2, 0.85): costlier and worse
    assert {r["label"]: r["pareto"] for r in result.rows} == {
        "svm": True,
        "rf": True,
        "gbm": False,
    }
    assert not any(r["regression"] for r in result.rows)  # quantitative x never regresses
    assert result.meta == {
        "x": "usage.usd",
        "y": "accuracy",
        "x_type": "quantitative",
        "scale": "linear",
        "pareto": {"x": "min", "y": "max"},
        "y_higher_is_better": True,
        "best_group": "aaaa@c1",  # svm, mean accuracy 0.85
        "x_unit": "$",
        "y_unit": "",
    }


def test_scatter_without_pareto_marks_nothing_and_skips_missing(
    ctx: Context, toy_repo: Path
) -> None:
    rec = _run(ctx, toy_repo, "s1", params={"lr": "0.1"})
    _score(ctx, rec, 0.5)
    _run(ctx, toy_repo, "s2", "bbbb", params={"lr": "0.2"})  # no score -> no y -> dropped
    panel = _panel("scatter", data={"x": "params.lr", "y": "accuracy"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert [(r["x"], r["y"], r["pareto"]) for r in result.rows] == [(0.1, 0.5, False)]


def test_scatter_reads_samples_aggregates_and_history(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1")
    _jsonl(ctx.run_dir(rec) / "samples" / "lat.jsonl", [{"value": v} for v in (1, 2, 3, 4)])
    _metrics(
        ctx,
        rec,
        [
            {"name": "val/loss", "step": 1, "value": 0.9},
            {"name": "val/loss", "step": 5, "value": 0.3},
        ],
    )
    panel = _panel("scatter", data={"x": "lat/p50", "y": "val/loss", "group_by": "run"})
    (row,) = query_panel(ctx, "toy", "toy-acc", panel).rows
    # numpy-linear p50 of [1, 2, 3, 4] = 2.5; history value = last step's value
    assert (row["group_id"], row["x"], row["y"]) == ("s1", 2.5, 0.3)
    mean_panel = _panel("scatter", data={"x": "lat", "y": "lat/max", "group_by": "run"})
    (row,) = query_panel(ctx, "toy", "toy-acc", mean_panel).rows
    assert (row["x"], row["y"]) == (2.5, 4.0)


def test_scatter_requires_x_and_defaults_y_to_primary(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=0.2))
    _score(ctx, rec, 0.5)
    with pytest.raises(ConfigError, match="needs data.x"):
        query_panel(ctx, "toy", "toy-acc", _panel("scatter", data={"y": "accuracy"}))
    result = query_panel(ctx, "toy", "toy-acc", _panel("scatter", data={"x": "usage.usd"}))
    assert [(r["x"], r["y"]) for r in result.rows] == [(0.2, 0.5)]
    assert (result.meta["y"], result.meta["x_type"]) == ("accuracy/value", "quantitative")


def test_scatter_bad_pareto_key_is_a_panel_error(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=0.2))
    _score(ctx, rec, 0.5)
    bad = _panel("scatter", data={"x": "usage.usd"}, pareto={"z": "min"})
    with pytest.raises(ConfigError, match="pareto keys are x and y"):
        query_panel(ctx, "toy", "toy-acc", bad)
    # the editor preview sends views that were not validated: one panel error, not a 500
    view = ViewSpec(title="v", panels=[bad, _panel("markdown", text="ok")])
    broken, notes = query_view(ctx, "toy", "toy-acc", view)
    assert (broken.rows, broken.meta) == ([], {"error": "pareto keys are x and y"})
    assert notes.meta == {"text": "ok"}


def test_non_finite_values_count_as_missing(ctx: Context, toy_repo: Path) -> None:
    a = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=0.1))
    nan_score = ScoreRecord(metric="accuracy", version="v1", key="value", value=0.0, created_at=T0)
    # json.dumps writes NaN; json.loads and pydantic read it back as float("nan")
    _jsonl(
        ctx.run_dir(a) / "scores.jsonl", [{**nan_score.model_dump(mode="json"), "value": math.nan}]
    )
    b = _run(ctx, toy_repo, "s2", "bbbb", minute=1, usage=UsageTotals(usd=0.2))
    _score(ctx, b, 0.5)
    _metrics(
        ctx,
        b,
        [
            {"name": "val/loss", "step": 1, "value": 0.4},
            {"name": "val/loss", "step": 2, "value": math.nan},
        ],
    )
    panel = _panel(
        "scatter",
        data={"x": "usage.usd", "y": "accuracy", "group_by": "run"},
        pareto={"x": "min", "y": "max"},
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # s1's NaN score is no value, so s1 is dropped instead of a null point on the front
    assert [(r["group_id"], r["x"], r["y"], r["pareto"]) for r in result.rows] == [
        ("s2", 0.2, 0.5, True)
    ]
    loss = _panel("scatter", data={"x": "usage.usd", "y": "val/loss", "group_by": "run"})
    # a NaN metric point is skipped when read (MetricPoint is finite): the last point is 0.4
    assert [(r["group_id"], r["y"]) for r in query_panel(ctx, "toy", "toy-acc", loss).rows] == [
        ("s2", 0.4)
    ]


def test_scatter_categorical_x_is_ordinal_in_natural_order(ctx: Context, toy_repo: Path) -> None:
    for rid, group, version, acc, minute in [
        ("a1", "aaaa", "v10", 0.9, 0),
        ("b1", "bbbb", "v9", 0.7, 1),
        ("b2", "bbbb", "v9", 0.8, 2),
    ]:
        rec = _run(ctx, toy_repo, rid, group, minute=minute, params={"version": version})
        _score(ctx, rec, acc)
    panel = _panel(
        "scatter", data={"x": "params.version", "y": "accuracy"}, pareto={"x": "min", "y": "max"}
    )
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # float("v9") fails, so x keeps the text; v9 sorts before v10 (natural order)
    assert [(r["x"], r["x_lo"], r["x_hi"]) for r in result.rows] == [
        ("v9", None, None),
        ("v10", None, None),
    ]
    assert [r["y"] for r in result.rows] == pytest.approx([0.75, 0.9])
    assert result.rows[0]["seeds"] == [{"x": "v9", "y": 0.7}, {"x": "v9", "y": 0.8}]
    assert not any(r["pareto"] for r in result.rows)  # no Pareto front on an ordinal axis
    assert result.meta["x_type"] == "ordinal"


def _version_series(ctx: Context, repo: Path, xs: list[str]) -> None:
    """
    Five seed groups in order, one per ``params.version`` value in ``xs``.

    Each group has 3 seeds whose accuracy and ``usage.usd`` are ``mean - 0.01``,
    ``mean``, ``mean + 0.01`` for means 0.50, 0.60, 0.70, 0.60, 0.68.
    """
    means = [0.50, 0.60, 0.70, 0.60, 0.68]
    for i, (x, mean) in enumerate(zip(xs, means, strict=True)):
        for j, step in enumerate((-0.01, 0.0, 0.01)):
            value = mean + step
            rec = _run(
                ctx,
                repo,
                f"r{i}{j}",
                f"aaa{i}",
                minute=3 * i + j,
                seed=j + 1,
                params={"version": x},
                usage=UsageTotals(usd=value),
            )
            _score(ctx, rec, value)


def test_scatter_flags_regressions_on_ordinal_x(ctx: Context, toy_repo: Path) -> None:
    _version_series(ctx, toy_repo, ["v1", "v2", "v3", "v4", "v5"])
    solved = query_panel(ctx, "toy", "toy-acc", _panel("scatter", data={"x": "params.version"}))
    assert solved.meta["x_type"] == "ordinal"
    # 3 seeds, stdev 0.01: 95% t half-width = 4.303 * 0.01 / sqrt(3) = 0.0248 (no test-set
    # interval: the runs have no per-example scores). Accuracy is higher-is-better.
    # Each version is compared with the one just before it.
    # v4: y_hi 0.6248 < previous (v3) y_lo 0.6752 -> regression.
    # v5: 0.68 improves on v4 (below v3, the best so far, but that does not count).
    assert [(r["x"], r["regression"]) for r in solved.rows] == [
        ("v1", False),
        ("v2", False),
        ("v3", False),
        ("v4", True),
        ("v5", False),
    ]
    assert solved.rows[3]["y_hi"] == pytest.approx(0.60 + 4.303 * 0.01 / math.sqrt(3))
    cost = _panel("scatter", data={"x": "params.version", "y": "usage.usd"})
    # usage is lower-is-better. v2 (y_lo 0.5752) and v3 (0.6752) cost more than the version
    # before (y_hi 0.5248, 0.6248); v4 (0.60) costs less than v3, so it is not flagged even
    # though it costs more than v1, the cheapest so far; v5 (y_lo 0.6552) > v4 y_hi 0.6248.
    assert [r["regression"] for r in query_panel(ctx, "toy", "toy-acc", cost).rows] == [
        False,
        True,
        True,
        False,
        True,
    ]


def test_scatter_quantitative_x_never_flags_regressions(ctx: Context, toy_repo: Path) -> None:
    # the same values as the ordinal series, but versions 1..5 are numbers
    _version_series(ctx, toy_repo, ["1", "2", "3", "4", "5"])
    result = query_panel(ctx, "toy", "toy-acc", _panel("scatter", data={"x": "params.version"}))
    assert result.meta["x_type"] == "quantitative"
    assert [r["x"] for r in result.rows] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert [r["regression"] for r in result.rows] == [False] * 5


def test_usage_per_solved_divides_by_solved_examples(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=3.0))
    _score(ctx, rec, 0.75)
    _jsonl(
        ctx.run_dir(rec) / "predictions" / "scores.accuracy@v1.jsonl",
        [{"id": f"ex-{i}", "correct": ok} for i, ok in enumerate([True, True, True, False])],
    )
    none = _run(ctx, toy_repo, "s2", "bbbb", minute=1, usage=UsageTotals(usd=2.0))
    _score(ctx, none, 0.0)
    _jsonl(
        ctx.run_dir(none) / "predictions" / "scores.accuracy@v1.jsonl",
        [{"id": "ex-0", "correct": False}],
    )
    panel = _panel("scatter", data={"x": "usage.usd", "y": "usage.usd/solved", "group_by": "run"})
    rows = query_panel(ctx, "toy", "toy-acc", panel).rows
    # s1: $3.00 over 3 solved examples = 1.0; s2 solved nothing, so it has no value (dropped)
    assert [(r["group_id"], r["x"], r["y"]) for r in rows] == [("s1", 3.0, 1.0)]
    bad = _panel("scatter", data={"x": "usage.usd/run"})
    with pytest.raises(ConfigError, match=r"usage\.<field>/solved or usage\.<field>/attempt"):
        query_panel(ctx, "toy", "toy-acc", bad)


def test_usage_per_attempt_divides_by_attempted_examples(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1", usage=UsageTotals(usd=3.0))
    _score(ctx, rec, 0.25)
    _jsonl(
        ctx.run_dir(rec) / "predictions" / "scores.accuracy@v1.jsonl",
        [{"id": f"ex-{i}", "correct": ok} for i, ok in enumerate([True, False, False, False])],
    )
    _score(ctx, _run(ctx, toy_repo, "s2", "bbbb", minute=1, usage=UsageTotals(usd=2.0)), 0.5)
    panel = _panel("scatter", data={"x": "usage.usd/attempt", "group_by": "run"}, scale="log")
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # s1: $3.00 over 4 attempted examples; s2 has no per-example rows, so no value (dropped)
    assert [(r["group_id"], r["x"]) for r in result.rows] == [("s1", 0.75)]
    assert (result.meta["x_unit"], result.meta["scale"]) == ("$", "log")


def test_metric_aggregate_keys_read_per_example_scores(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "s1")
    _jsonl(
        ctx.run_dir(rec) / "predictions" / "scores.accuracy@v1.jsonl",
        [{"id": f"ex-{i}", "len": v} for i, v in enumerate((4, 1, 3, 10))],
    )
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v1", key="p95", value=7.0, created_at=T0)
    )
    panel = _panel(
        "scatter", data={"x": "accuracy@v1/median", "y": "accuracy/max", "group_by": "run"}
    )
    (row,) = query_panel(ctx, "toy", "toy-acc", panel).rows
    # no "median"/"max" score: aggregate the per-example field (median 3.5, max 10)
    assert (row["x"], row["y"]) == (3.5, 10.0)
    stored = _panel(
        "scatter", data={"x": "accuracy/p95", "y": "accuracy@v1/mean", "group_by": "run"}
    )
    (row,) = query_panel(ctx, "toy", "toy-acc", stored).rows
    assert (row["x"], row["y"]) == (7.0, 4.5)  # a stored "p95" score wins


def test_stat_strip_with_metrics_summarises_selected_runs(ctx: Context, toy_repo: Path) -> None:
    _two_groups(ctx, toy_repo)
    panel = _panel("stat_strip", data={"metrics": ["accuracy@v1", "usage.usd"], "pick": "best"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == [
        {"label": "accuracy@v1", "value": "0.850", "unit": "", "tooltip": "Mean of 2 runs of svm"},
        {
            "label": "usage.usd",
            "value": "—",
            "unit": "",
            "tooltip": "No value in the 2 selected runs",
        },
    ]
    assert set(result.meta) == {"headline", "unit", "value_format"}


def test_stat_strip_metrics_use_units(ctx: Context, toy_repo: Path) -> None:
    for rid, usd, minute in [("a1", 0.5, 0), ("a2", 0.6, 1)]:
        rec = _run(ctx, toy_repo, rid, minute=minute, usage=UsageTotals(usd=usd, seconds=90.0))
        _jsonl(ctx.run_dir(rec) / "samples" / "latency_ms.jsonl", [{"value": 165.6}])
    refs = ["usage.usd", "latency_ms", "usage.seconds"]
    result = query_panel(ctx, "toy", "toy-acc", _panel("stat_strip", data={"metrics": refs}))
    assert [(r["value"], r["unit"]) for r in result.rows] == [
        ("$0.55", ""),  # dollars are a prefix
        ("166", "ms"),  # 3 significant figures, unit beside the value
        ("90", "s"),
    ]


def test_scatter_meta_carries_y_direction_and_best_group(ctx: Context, toy_repo: Path) -> None:
    for rid, group, usd, acc, minute in [("a1", "aaaa", 0.1, 0.8, 0), ("b1", "bbbb", 0.3, 0.9, 1)]:
        rec = _run(ctx, toy_repo, rid, group, minute=minute, usage=UsageTotals(usd=usd))
        _score(ctx, rec, acc)
        _metrics(ctx, rec, [{"name": "val/loss", "step": 1, "value": 1 - acc}])

    def meta(data: dict[str, str]) -> tuple[bool, str | None]:
        result = query_panel(ctx, "toy", "toy-acc", _panel("scatter", data=data))
        return result.meta["y_higher_is_better"], result.meta["best_group"]

    # no pareto settings anywhere: the best group still follows the y direction
    assert meta({"x": "usage.usd"}) == (True, "bbbb@c1")  # primary accuracy: 0.9 wins
    assert meta({"x": "accuracy", "y": "usage.usd"}) == (False, "aaaa@c1")  # $0.1 wins
    assert meta({"x": "usage.usd", "y": "val/loss"}) == (False, "bbbb@c1")  # loss 0.1 wins
    assert meta({"x": "usage.usd", "y": "nothing"}) == (True, None)  # no rows


def test_scatter_uses_the_test_interval_only_at_the_board_version(
    ctx: Context, toy_repo: Path
) -> None:
    for rid, seed, usd, old in [("s1", 1, 0.1, 0.4), ("s2", 2, 0.3, 0.6)]:
        rec = _run(ctx, toy_repo, rid, seed=seed, minute=seed, usage=UsageTotals(usd=usd))
        _score(ctx, rec, 0.75)  # accuracy@v1: the board's version
        ctx.add_score(
            rec, ScoreRecord(metric="accuracy", version="v0", key="value", value=old, created_at=T0)
        )
        _jsonl(
            ctx.run_dir(rec) / "predictions" / "scores.accuracy@v1.jsonl",
            [{"id": f"ex-{i}", "correct": ok} for i, ok in enumerate([True, True, True, False])],
        )
    for y in ("accuracy", "accuracy@v1"):
        (row,) = query_panel(
            ctx, "toy", "toy-acc", _panel("scatter", data={"x": "usage.usd", "y": y})
        ).rows
        # pooled 3 of 4 correct: statsmodels proportion_confint(3, 4, method="wilson")
        assert (row["y_lo"], row["y_hi"]) == pytest.approx(
            (0.30064184258240184, 0.9544127391902995)
        )
    old = _panel("scatter", data={"x": "usage.usd", "y": "accuracy@v0"})
    (row,) = query_panel(ctx, "toy", "toy-acc", old).rows
    # v0 is not the board's version: its own seed t-interval, 0.5 +- 12.706 * 0.1
    assert row["y"] == pytest.approx(0.5)
    assert (row["y_lo"], row["y_hi"]) == pytest.approx((0.5 - 1.2706, 0.5 + 1.2706))


def test_scatter_version_x_follows_version_param_then_creation_time(
    ctx: Context, toy_repo: Path
) -> None:
    for rid, group, params, acc, minute in [
        ("a", "aaaa", {"prompt_version": "p10"}, 0.7, 0),
        ("b", "bbbb", {"prompt_version": "p9"}, 0.6, 1),
        ("c", "cccc", {}, 0.5, 2),
        ("d", "dddd", {}, 0.4, 3),
    ]:
        rec = _run(ctx, toy_repo, rid, group, minute=minute, params=params)
        _score(ctx, rec, acc)
    t0, t1, t2, t3 = ((T0 + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S") for m in range(4))
    panel = _panel("scatter", data={"x": "version"})
    # default version_param "version": no run has it, so every group falls back to the
    # creation time of its first run (spec 8.4) instead of vanishing from the plot
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.meta["x_type"] == "ordinal"
    assert [r["x"] for r in result.rows] == [t0, t1, t2, t3]
    _set_task(toy_repo, version_param="prompt_version")
    result = query_panel(ctx, "toy", "toy-acc", panel)
    # params first in natural order (p9 before p10), then the fallback groups by time
    assert [(r["x"], r["y"]) for r in result.rows] == [
        ("p9", 0.6),
        ("p10", 0.7),
        (t2, 0.5),
        (t3, 0.4),
    ]


# distribution ----------------------------------------------------------------------
def test_distribution_quantiles_seeds_and_ecdf(ctx: Context, toy_repo: Path) -> None:
    d1 = _run(ctx, toy_repo, "d1", hypothesis="fast", minute=0)
    d2 = _run(ctx, toy_repo, "d2", hypothesis="fast", minute=1)
    e1 = _run(ctx, toy_repo, "e1", "bbbb", hypothesis="slow", minute=2)
    _jsonl(ctx.run_dir(d1) / "samples" / "latency_ms.jsonl", [{"value": v} for v in range(1, 101)])
    _jsonl(
        ctx.run_dir(d2) / "samples" / "latency_ms.jsonl", [{"value": v} for v in range(101, 201)]
    )
    _jsonl(ctx.run_dir(e1) / "samples" / "latency_ms.jsonl", [{"value": v} for v in range(1, 1001)])
    panel = _panel("distribution", data={"metrics": ["latency_ms"]}, scale="log")
    result = query_panel(ctx, "toy", "toy-acc", panel)
    fast, slow = result.rows
    # numpy "linear" quantile of 1..200: 1 + q * 199
    assert (fast["group_id"], fast["label"], fast["n"]) == ("aaaa@c1", "fast", 200)
    assert fast["p50"] == pytest.approx(100.5)
    assert fast["p95"] == pytest.approx(190.05)
    assert fast["p99"] == pytest.approx(198.01)
    # per seed: 1..100 -> 1 + q * 99; 101..200 -> 101 + q * 99
    assert fast["seeds"] == [
        {
            "run_id": "d1",
            "p50": pytest.approx(50.5),
            "p95": pytest.approx(95.05),
            "p99": pytest.approx(99.01),
        },
        {
            "run_id": "d2",
            "p50": pytest.approx(150.5),
            "p95": pytest.approx(195.05),
            "p99": pytest.approx(199.01),
        },
    ]
    assert slow["n"] == 1000
    assert len(slow["ecdf"]) <= 200  # downsampled
    assert slow["ecdf"][-1] == [1000.0, 1.0]
    xs = [p[0] for p in slow["ecdf"]]
    assert xs == sorted(xs)
    assert [r["vs_baseline"] for r in result.rows] == [None, None]  # no baseline configured
    assert result.meta == {
        "name": "latency_ms",
        "unit": "ms",
        "scale": "log",
        "render": "chart",
        "baseline": None,
    }


def _latency_groups(ctx: Context, repo: Path) -> None:
    """base: 3 repeats tagged baseline; fast: the same samples halved; one: a single repeat."""
    runs = [
        ("b1", "aaaa", "base", ["baseline"], [float(v) for v in range(1, 101)]),
        ("b2", "aaaa", "base", ["baseline"], [float(v) for v in range(11, 111)]),
        ("b3", "aaaa", "base", ["baseline"], [float(v) for v in range(21, 121)]),
        ("f1", "bbbb", "fast", [], [v / 2 for v in range(1, 101)]),
        ("f2", "bbbb", "fast", [], [v / 2 for v in range(11, 111)]),
        ("f3", "bbbb", "fast", [], [v / 2 for v in range(21, 121)]),
        ("c1", "cccc", "one", [], [0.8 * v for v in range(11, 111)]),
    ]
    for minute, (rid, group, hyp, tags, values) in enumerate(runs):
        rec = _run(ctx, repo, rid, group, minute=minute, hypothesis=hyp, tags=tags)
        _jsonl(ctx.run_dir(rec) / "samples" / "latency_ms.jsonl", [{"value": v} for v in values])


def test_distribution_vs_baseline_with_repeat_bootstrap(ctx: Context, toy_repo: Path) -> None:
    _latency_groups(ctx, toy_repo)
    _set_task(toy_repo, baseline="tag:baseline")
    panel = _panel("distribution", data={"metrics": ["latency_ms"]}, render="table")
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.meta == {
        "name": "latency_ms",
        "unit": "ms",
        "scale": "linear",
        "render": "table",
        "baseline": "aaaa@c1",
    }
    base, fast, one = result.rows
    assert base["vs_baseline"] is None  # the baseline row itself
    # pooled: base p50 60.5, p95 108.0, p99 117.01; fast is every sample halved -> -50%
    # per-seed p50: base [50.5, 60.5, 70.5], fast [25.25, 30.25, 35.25]; 1000 resamples
    # with random.Random(0) per percentile, 2.5th/97.5th percentile of
    # (mean(fast draw) - mean(base draw)) / mean(base draw)
    delta = fast["vs_baseline"]
    assert list(delta) == ["p50", "p95", "p99"]
    assert delta["p50"] == pytest.approx([-0.5, -0.5992555831265508, -0.38320140086109644])
    assert delta["p95"] == pytest.approx([-0.5, -0.5596747724899299, -0.43440294760377146])
    assert delta["p99"] == pytest.approx([-0.5, -0.5576319050226204, -0.43686312004044475])
    # one repeat: the change is known, the interval is not
    # pooled p50 48.4, p95 84.04, p99 87.208 vs 60.5, 108.0, 117.01
    assert one["vs_baseline"]["p50"][0] == pytest.approx(-0.2)
    assert one["vs_baseline"]["p95"][0] == pytest.approx(84.04 / 108.0 - 1)
    assert one["vs_baseline"]["p99"][0] == pytest.approx(87.208 / 117.01 - 1)
    assert [v[1:] for v in one["vs_baseline"].values()] == [[None, None]] * 3


def test_distribution_baseline_selectors(ctx: Context, toy_repo: Path) -> None:
    _latency_groups(ctx, toy_repo)
    panel = _panel("distribution", data={"metrics": ["latency_ms"]})

    def rows() -> list[dict[str, Any]]:
        return query_panel(ctx, "toy", "toy-acc", panel).rows

    assert [r["vs_baseline"] for r in rows()] == [None, None, None]  # no baseline
    _set_task(toy_repo, baseline="tag:nothing")
    assert [r["vs_baseline"] for r in rows()] == [None, None, None]  # no group matches
    _set_task(toy_repo, baseline="bbbb")  # a group_id prefix: fast is the baseline
    base, fast, one = rows()
    assert fast["vs_baseline"] is None
    assert base["vs_baseline"]["p50"][0] == pytest.approx(1.0)  # 60.5 vs 30.25
    assert one["vs_baseline"]["p99"][0] == pytest.approx(87.208 / 58.505 - 1)
    assert one["vs_baseline"]["p99"][1:] == [None, None]
    _set_task(toy_repo, baseline="sha256:cccc")  # a config hash: one is the baseline
    base, fast, one = rows()
    assert one["vs_baseline"] is None
    assert base["vs_baseline"]["p50"] == [pytest.approx(60.5 / 48.4 - 1), None, None]


def test_distribution_over_usage_field(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "u1")
    _jsonl(ctx.run_dir(rec) / "usage.jsonl", [{"seconds": s} for s in (1.0, 2.0, 3.0)])
    (row,) = query_panel(
        ctx, "toy", "toy-acc", _panel("distribution", data={"x": "usage.seconds"})
    ).rows
    assert (row["n"], row["p50"]) == (3, 2.0)


# grid ------------------------------------------------------------------------------
def test_grid_fraction_solved_and_difficulty_order(ctx: Context, toy_repo: Path) -> None:
    outcomes = {
        "a1": ("aaaa", "alpha", [True, False, True]),
        "a2": ("aaaa", "alpha", [True, False, False]),
        "b1": ("bbbb", "beta", [True, True, False]),
    }
    for minute, (rid, (group, hyp, solved)) in enumerate(outcomes.items()):
        rec = _run(ctx, toy_repo, rid, group, hypothesis=hyp, minute=minute)
        pred = ctx.run_dir(rec) / "predictions"
        _jsonl(pred / "predictions.jsonl", [{"id": f"ex-{i}", "prediction": 0} for i in range(3)])
        _jsonl(
            pred / "scores.accuracy@v1.jsonl",
            [{"id": f"ex-{i}", "correct": ok} for i, ok in enumerate(solved)],
        )
    result = query_panel(ctx, "toy", "toy-acc", _panel("grid"))
    # alpha: ex-0 2/2, ex-1 0/2, ex-2 1/2; beta: ex-0 1, ex-1 1, ex-2 0
    # item means: ex-0 1.0, ex-1 0.5, ex-2 0.25 -> hardest first
    assert result.meta["items"] == ["ex-2", "ex-1", "ex-0"]
    # group means: beta 2/3 > alpha 1/2
    assert result.meta["groups"] == [
        {"group_id": "bbbb@c1", "label": "beta"},
        {"group_id": "aaaa@c1", "label": "alpha"},
    ]
    assert result.meta["field"] == "accuracy@v1.correct"
    assert result.rows == [
        {"item_id": "ex-2", "group_id": "bbbb@c1", "value": 0.0},
        {"item_id": "ex-2", "group_id": "aaaa@c1", "value": 0.5},
        {"item_id": "ex-1", "group_id": "bbbb@c1", "value": 1.0},
        {"item_id": "ex-1", "group_id": "aaaa@c1", "value": 0.0},
        {"item_id": "ex-0", "group_id": "bbbb@c1", "value": 1.0},
        {"item_id": "ex-0", "group_id": "aaaa@c1", "value": 1.0},
    ]


def test_grid_uses_explicit_field_and_rejects_unknown_metric(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "a1")
    pred = ctx.run_dir(rec) / "predictions"
    _jsonl(pred / "predictions.jsonl", [{"id": "ex-0", "prediction": 0}])
    _jsonl(pred / "scores.accuracy@v1.jsonl", [{"id": "ex-0", "correct": True, "partial": 0}])
    panel = _panel("grid", data={"metrics": ["accuracy@v1"], "y": "partial"})
    assert query_panel(ctx, "toy", "toy-acc", panel).rows == [
        {"item_id": "ex-0", "group_id": "aaaa@c1", "value": 0.0}
    ]
    with pytest.raises(ConfigError, match="unknown metric 'nope'"):
        query_panel(ctx, "toy", "toy-acc", _panel("grid", data={"metrics": ["nope"]}))


# one view, shared data (PERF-F6, PERF-F3) --------------------------------------------
def test_query_view_builds_one_board_and_lists_runs_once(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i, group in enumerate(("aaaa", "bbbb")):
        _score(ctx, _run(ctx, toy_repo, f"r{i}", group, minute=i), 0.5 + i / 10)
    boards: list[int] = []
    real_board = panels._build_board

    def board_spy(*args: Any) -> Any:
        boards.append(1)
        return real_board(*args)

    lists: list[int] = []
    real_list = ctx.index.list_runs

    def list_spy(*args: Any, **kw: Any) -> Any:
        lists.append(1)
        return real_list(*args, **kw)

    monkeypatch.setattr(panels, "_build_board", board_spy)
    monkeypatch.setattr(ctx.index, "list_runs", list_spy)
    view = ViewSpec(
        title="v",
        panels=[
            _panel("stat_strip"),
            _panel("leaderboard"),
            _panel("table", data={"source": "runs", "fields": ["label"]}),
            _panel("curves", data={"metrics": ["train/loss"]}),
            _panel("scatter", data={"x": "params.lr"}),
        ],
    )
    strip, board, table, curves, _ = query_view(ctx, "toy", "toy-acc", view)
    assert "error" not in strip.meta and "error" not in curves.meta
    assert [row["label"] for row in table.rows] == [r["label"] for r in board.rows][::-1]
    assert (len(boards), len(lists)) == (1, 1)


def test_views_reuse_boards_across_requests_until_the_index_changes(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PERF-F1 handoff: a view board comes from leaderboard.cached_leaderboard, keyed
    # by the panel's run ids, so a narrowed panel gets its own board
    for i, group in enumerate(("aaaa", "bbbb")):
        _score(ctx, _run(ctx, toy_repo, f"r{i}", group, minute=i), 0.5 + i / 10)
    builds: list[int] = []
    real = panels.build_leaderboard

    def spy(*args: Any, **kw: Any) -> Any:
        builds.append(len(args[3]))
        return real(*args, **kw)

    monkeypatch.setattr(panels, "build_leaderboard", spy)
    view = ViewSpec(title="v", panels=[_panel("leaderboard")])
    (first,) = query_view(ctx, "toy", "toy-acc", view)
    (again,) = query_view(ctx, "toy", "toy-acc", view)
    assert builds == [2] and again.rows == first.rows
    narrowed = query_panel(ctx, "toy", "toy-acc", view.panels[0], RunFilter(created_by="nobody"))
    assert builds == [2, 0] and narrowed.rows == []
    _score(ctx, _run(ctx, toy_repo, "r2", "cccc", minute=2), 0.9)
    (later,) = query_view(ctx, "toy", "toy-acc", view)
    assert builds == [2, 0, 3] and len(later.rows) == 3


def test_view_reads_ended_runs_metrics_from_the_index_by_name(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _run(ctx, toy_repo, "r1")
    _metrics(
        ctx,
        rec,
        [
            {"name": name, "step": s, "value": float(s)}
            for s in range(3)
            for name in ("train/loss", "val/top1", "sys/gpu_util", "other")
        ],
    )

    def no_file(*_: Any) -> None:
        raise AssertionError("an ended run's metrics.jsonl was parsed")

    monkeypatch.setattr(ctx.store, "read_metric_points", no_file)
    monkeypatch.setattr(ctx.store, "read_metric_points_bounded", no_file)
    asked: list[frozenset[str] | None] = []
    real = ctx.index.metric_points_for

    def spy(run_ids: Any, names: Any = None) -> Any:
        asked.append(None if names is None else frozenset(names))
        return real(run_ids, names)

    monkeypatch.setattr(ctx.index, "metric_points_for", spy)
    view = ViewSpec(
        title="v",
        panels=[
            _panel("curves", data={"metrics": ["train/loss", "val/top1"]}),
            _panel(
                "vega_lite",
                data={"source": "metrics", "filter": {"name": "sys/gpu_util"}},
                spec={"mark": "line"},
            ),
            _panel("curves", title="again", data={"metrics": ["val/top1", "train/loss"]}),
        ],
    )
    curves, gpu, again = query_view(ctx, "toy", "toy-acc", view)
    assert curves.meta["metrics"] == ["train/loss", "val/top1"]
    assert len(curves.rows) == 6

    def key(row: dict[str, Any]) -> tuple[str, int]:
        return row["name"], row["step"]

    assert sorted(again.rows, key=key) == sorted(curves.rows, key=key)
    assert [(r["name"], r["step"]) for r in gpu.rows] == [("sys/gpu_util", s) for s in range(3)]
    # one query per name set; the second curves panel reuses the first one's points
    assert asked == [frozenset({"train/loss", "val/top1"}), frozenset({"sys/gpu_util"})]


def test_curves_thin_a_long_series_and_keep_its_spike(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", status=RunStatus.RUNNING)  # live: the full file is read
    n = 5000
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [{"name": "train/loss", "step": s, "value": 50.0 if s == 3001 else 1.0} for s in range(n)],
    )
    result = query_panel(ctx, "toy", "toy-acc", _panel("curves", data={"group_by": "run"}))
    steps = [row["step"] for row in result.rows]
    assert len(steps) == panels.CURVE_POINTS
    assert steps == sorted(steps)
    assert (steps[0], steps[-1]) == (0, n - 1)
    assert {"step": 3001, "value": 50.0} in [
        {"step": r["step"], "value": r["value"]} for r in result.rows
    ]
    assert result.meta["events"] == [
        {"run_id": "r1", "step": 3001, "kind": "spike", "label": "spike 3k"}
    ]


@pytest.mark.parametrize("limit", [None, 2, 17, 500])
def test_curves_requested_point_limit_preserves_metadata_and_axis(
    ctx: Context, toy_repo: Path, limit: int | None
) -> None:
    rec = _run(ctx, toy_repo, "r1", status=RunStatus.KILLED)
    _metrics(
        ctx,
        rec,
        [
            {"name": name, "step": step, "value": value}
            for step in range(600)
            for name, value in (
                ("train/loss", 50.0 if step == 301 else 1.0),
                ("val/acc", 0.5),
                ("epoch", step / 10),
            )
        ],
    )
    _jsonl(
        ctx.run_dir(rec) / "artifacts.jsonl",
        [{"kind": "checkpoint", "path": "/ck/100.pt", "step": 100, "metrics": {"val/acc": 0.5}}],
    )
    data = {"metrics": ["train/loss", "val/acc"], "step_metric": "epoch"}
    original = query_panel(ctx, "toy", "toy-acc", _panel("curves", data=data))
    result = query_panel(
        ctx, "toy", "toy-acc", _panel("curves", data={**data, "max_points": limit})
    )

    assert result.meta == original.meta
    assert {event["kind"] for event in result.meta["events"]} == {"spike", "killed"}
    assert len(result.meta["checkpoints"]) == 1
    assert {row["name"] for row in result.rows} == {"train/loss", "val/acc"}
    for name in data["metrics"]:
        rows = [row for row in result.rows if row["name"] == name]
        assert len(rows) == (500 if limit is None else limit)
        assert [rows[0]["step"], rows[-1]["step"]] == [0.0, 59.9]


def test_curves_empty_metric_selection_does_not_read_all_series(
    ctx: Context, toy_repo: Path
) -> None:
    rec = _run(ctx, toy_repo, "r1")
    _metrics(ctx, rec, [{"name": "loss", "step": 0, "value": 1.0}])
    result = query_panel(
        ctx, "toy", "toy-acc", _panel("curves", data={"metrics": [], "max_points": 2})
    )
    assert result.rows == []
    assert result.meta["metrics"] == []


def test_lttb_keeps_ends_peaks_and_short_series() -> None:
    xs = [float(i) for i in range(100)]
    ys = [0.0] * 100
    ys[37] = 5.0
    ys[80] = -4.0
    kept = panels.lttb(xs, ys, 10)
    assert len(kept) == 10
    assert kept == sorted(set(kept))
    assert (kept[0], kept[-1]) == (0, 99)
    assert {37, 80} <= set(kept)
    assert panels.lttb(xs[:10], ys[:10], 10) == list(range(10))
    assert panels.lttb(xs, ys, 2) == [0, 99]


def test_view_parses_a_live_runs_metrics_file_once_for_all_curves(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _run(ctx, toy_repo, "r1", status=RunStatus.RUNNING)
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [{"name": n, "step": 0, "value": 1.0} for n in ("train/loss", "lr", "sys/gpu_util")],
    )
    reads: list[str] = []
    real = ctx.store.read_metric_points_bounded

    def spy(project: str, run_id: str) -> Any:
        reads.append(run_id)
        return real(project, run_id)

    monkeypatch.setattr(ctx.store, "read_metric_points_bounded", spy)
    view = ViewSpec(
        title="v",
        panels=[
            _panel("curves", data={"metrics": ["train/loss"]}),
            _panel("curves", title="lr", data={"metrics": ["lr"]}),
            _panel(
                "vega_lite",
                data={"source": "metrics", "filter": {"name": ["sys/gpu_util"]}},
                spec={"mark": "line"},
            ),
        ],
    )
    loss, lr, gpu = query_view(ctx, "toy", "toy-acc", view)
    assert [r["name"] for r in (*loss.rows, *lr.rows)] == ["train/loss", "lr"]
    assert [r["name"] for r in gpu.rows] == ["sys/gpu_util"]
    assert reads == ["r1", "r1"]  # once for the curves panels, once for the vega_lite source


# denial of service: data or specs that must not fail or blow up a view ----------
def test_lttb_survives_values_near_the_float_limit() -> None:
    n = 1000
    big = [1.7e308] * n
    kept = panels.lttb(list(range(n)), big, 10)
    assert len(kept) == 10 and (kept[0], kept[-1]) == (0, n - 1)
    kept = panels.lttb(big, [1.0] * n, 10)
    assert len(kept) == 10 and kept == sorted(set(kept))


def test_curves_of_values_near_the_float_limit_do_not_fail_the_view(
    ctx: Context, toy_repo: Path
) -> None:
    rec = _run(ctx, toy_repo, "r1")
    _metrics(ctx, rec, [{"name": "loss", "step": s, "value": 1.7e308} for s in range(600)])
    view = ViewSpec(title="v", panels=[_panel("curves", data={"metrics": ["loss"]})])
    (curves,) = query_view(ctx, "toy", "toy-acc", view)
    assert "error" not in curves.meta
    assert len(curves.rows) == panels.CURVE_POINTS


def test_a_step_the_index_cannot_hold_is_skipped_not_a_failed_view(
    ctx: Context, toy_repo: Path
) -> None:
    from hypothex.core.index import rebuild_index

    done = _run(ctx, toy_repo, "r1")
    live = _run(ctx, toy_repo, "r2", minute=1, status=RunStatus.RUNNING)
    for rec in (done, live):
        _jsonl(
            ctx.run_dir(rec) / "metrics.jsonl",
            [
                {"name": "loss", "step": 0, "value": 1.0},
                {"name": "loss", "step": 2**63, "value": 1.0},
                {"name": "loss", "step": 10**400, "value": 1.0},
            ],
        )
    rebuild_index(ctx.index, ctx.store)  # r1's points are indexed by the first read
    view = ViewSpec(title="v", panels=[_panel("curves", data={"metrics": ["loss"]})])
    (curves,) = query_view(ctx, "toy", "toy-acc", view)
    assert sorted((r["run_id"], r["step"]) for r in curves.rows) == [("r1", 0), ("r2", 0)]


def test_curves_draw_a_repeated_metric_name_once(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    _metrics(ctx, rec, [{"name": "loss", "step": s, "value": 1.0} for s in range(10)])
    panel = _panel("curves", data={"metrics": ["loss"] * MAX_PANEL_REFS})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert len(result.rows) == 10
    assert result.meta["metrics"] == ["loss"]


def test_view_cache_keeps_a_bounded_history_of_each_live_run(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", status=RunStatus.RUNNING)
    n = 3 * MAX_POINTS_PER_METRIC
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [
            {"name": name, "step": s, "value": 50.0 if s == 2001 else 1.0}
            for s in range(n)
            for name in ("loss", "lr", "sys/gpu_util")
        ],
    )
    cache = panels._ViewCache()
    got = cache.metric_points(ctx, [rec], ["loss"])["r1"]
    held = cache.files["r1"]
    assert len(held) <= 3 * MAX_POINTS_PER_METRIC
    assert [p.step for p in got if p.value == 50.0] == [2001]  # the peak survives
    assert (got[0].step, got[-1].step) == (0, n - 1)


def test_scatter_of_a_history_metric_reads_the_points_once(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(30):
        rec = _run(ctx, toy_repo, f"r{i:02d}", f"g{i:03d}", minute=i)
        _metrics(ctx, rec, [{"name": "acc", "step": s, "value": float(i)} for s in range(3)])
    calls: list[int] = []
    real = panels._ViewCache.metric_points

    def spy(self: Any, ctx_: Context, runs: list[RunRecord], names: Any) -> Any:
        calls.append(len(runs))
        return real(self, ctx_, runs, names)

    monkeypatch.setattr(panels._ViewCache, "metric_points", spy)
    panel = _panel("scatter", data={"x": "acc", "y": "acc", "group_by": "run"})
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert len(result.rows) == 30
    assert calls == [30]  # one read for x and y of every run, not one scan per run


def test_a_view_of_a_huge_live_metrics_file_holds_a_bounded_history(
    ctx: Context, toy_repo: Path
) -> None:
    rec = _run(ctx, toy_repo, "r1", status=RunStatus.RUNNING)
    n = 30_000
    with (ctx.run_dir(rec) / "metrics.jsonl").open("w") as fh:
        for s in range(n):
            fh.write(json.dumps({"name": "loss", "step": s, "value": 1.0 / (s + 1)}) + "\n")
    view = ViewSpec(
        title="v",
        panels=[
            _panel("curves", data={"metrics": ["loss"]}),
            _panel("stat_strip", data={"metrics": ["loss"]}),
            _panel("vega_lite", data={"source": "metrics"}, spec={"mark": "line"}),
        ],
    )
    tracemalloc.start()
    try:
        curves, strip, table = query_view(ctx, "toy", "toy-acc", view)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    # parsing the whole file held all 30k points at once (~28 MiB)
    assert peak < 8 * 2**20, f"peak {peak / 2**20:.1f} MiB"
    assert curves.rows[-1]["step"] == n - 1
    assert strip.rows[0]["tooltip"].startswith("Mean of 1 run")
    assert len(table.rows) == MAX_POINTS_PER_METRIC


def test_stat_strip_reads_each_runs_samples_and_scores_once(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(4):
        rec = _run(ctx, toy_repo, f"r{i}", f"g{i:03d}", minute=i)
        _score(ctx, rec, 0.5 + i / 10)
        _jsonl(
            ctx.run_dir(rec) / "samples" / "lat.jsonl",
            [{"name": "lat", "value": float(v)} for v in range(10)],
        )
    counts = {"read_samples": 0, "read_scores": 0}
    for name in counts:
        real = getattr(ctx.store, name)

        def spy(project: str, run_id: str, _real: Any = real, _name: str = name) -> Any:
            counts[_name] += 1
            return _real(project, run_id)

        monkeypatch.setattr(ctx.store, name, spy)
    refs = ["accuracy", "lat", "lat/p50", "lat/max", "accuracy/median"] * 4
    view = ViewSpec(
        title="v",
        panels=[
            _panel("stat_strip", data={"metrics": refs}),
            _panel("scatter", data={"x": "lat/p50", "y": "accuracy", "group_by": "run"}),
        ],
    )
    strip, scatter = query_view(ctx, "toy", "toy-acc", view)
    assert [r["value"] for r in strip.rows[:5]] == ["0.650", "4.5", "4.5", "9", "—"]
    assert len(strip.rows) == len(refs)
    assert len(scatter.rows) == 4
    # once per run and panel (4 runs x 2 panels); it was once per run and reference
    assert counts == {"read_samples": 8, "read_scores": 8}


def test_stat_strip_reuses_primary_examples_for_cost_denominators(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _run(ctx, toy_repo, "cost", usage=UsageTotals(usd=10, seconds=20))
    _score(ctx, rec, 0.5)
    path = ctx.run_dir(rec) / "predictions" / "scores.accuracy@v1.jsonl"
    _jsonl(path, [{"id": 0, "accuracy": 1}, {"id": 1, "accuracy": 0}])
    reads: list[Path] = []
    original = panels.read_jsonl

    def read(file: Path) -> list[Any]:
        reads.append(file)
        return original(file)

    monkeypatch.setattr(panels, "read_jsonl", read)
    refs = [
        "usage.usd/solved",
        "usage.seconds/solved",
        "usage.usd/attempt",
        "usage.seconds/attempt",
        "accuracy/median",
    ]
    result = query_panel(ctx, "toy", "toy-acc", _panel("stat_strip", data={"metrics": refs}))
    assert len(result.rows) == len(refs)
    assert reads == [path]
