from typing import get_args

import pytest
from pydantic import ValidationError

from hypothex.core.config import TaskKind
from hypothex.core.errors import ConfigError
from hypothex.core.views import (
    PRESET_DIR,
    PanelData,
    PanelLayout,
    PanelSpec,
    RunFilter,
    ViewSpec,
    load_preset,
    resolve_view,
)

PRESET_TYPES = {
    "generic": ["stat_strip", "leaderboard"],
    "training": ["stat_strip", "leaderboard", "curves", "table", "vega_lite", "curves"],
    "agent_eval": ["stat_strip", "leaderboard", "scatter", "vega_lite", "grid", "trace"],
    "agent_iteration": ["stat_strip", "scatter", "scatter", "table", "grid", "leaderboard"],
    "system_bench": [
        "stat_strip",
        "leaderboard",
        "distribution",
        "curves",
        "distribution",
        "vega_lite",
        "curves",
        "vega_lite",
    ],
}


# ---- models, presets, resolve ----


def test_every_kind_has_a_preset_with_the_spec_panels() -> None:
    assert sorted(p.stem for p in PRESET_DIR.glob("*.yaml")) == sorted(get_args(TaskKind))
    for kind in get_args(TaskKind):
        view = load_preset(kind)
        assert view.title == "overview"
        assert view.from_ is None
        assert [p.type for p in view.panels] == PRESET_TYPES[kind]
        assert all(p.title for p in view.panels)
        assert all(1 <= p.layout.span <= 12 for p in view.panels)


def test_preset_details_match_spec() -> None:
    agent = {p.title: p for p in load_preset("agent_eval").panels}
    assert agent["Cost vs solved"].data.x == "usage.usd"
    assert agent["Cost vs solved"].pareto == {"x": "min", "y": "max"}
    assert agent["Failures"].data.source == "predictions"
    bench = {p.title: p for p in load_preset("system_bench").panels}
    assert bench["Latency"].scale == "log"
    assert bench["Latency"].data.source == "samples"
    assert bench["Latency"].data.metrics == ["latency_ms"]
    assert bench["Throughput vs concurrency"].data.metrics == ["sweep/rps"]
    assert bench["Utilisation"].data.metrics == ["gpu_pct", "cpu_pct"]
    training = {p.title: p for p in load_preset("training").panels}
    assert training["Curves"].data.step_metric == "step"
    assert training["Runs"].data.source == "runs"


def test_presets_cover_the_spec_items() -> None:
    # spec 8.4 items beyond the basics: GPU sparklines and checkpoints (training),
    # cost per success (agent_iteration), percentile table and repeat spread (system_bench)
    training = {p.title: p for p in load_preset("training").panels}
    gpu = training["GPU"]
    assert (gpu.data.source, gpu.data.filter) == ("metrics", {"name": "sys/gpu_util"})
    assert gpu.spec is not None and gpu.spec["encoding"]["row"]["field"] == "run_id"
    assert (training["Runs"].layout.row, gpu.layout.row) == (4, 4)  # sparklines beside the table
    assert training["Checkpoints"].type == "curves"
    assert training["Checkpoints"].data.metrics == ["val/top1"]
    assert training["Checkpoints"].data.group_by == "run"
    iteration = {p.title: p for p in load_preset("agent_iteration").panels}
    assert "Cost by version" not in iteration
    cost = iteration["$ per solved"]
    assert (cost.data.x, cost.data.y) == ("version", "usage.usd/solved")
    assert iteration["Changes"].data.fields == ["group_id", "version", "created_by", "created_at"]
    bench = {p.title: p for p in load_preset("system_bench").panels}
    percentiles = bench["Percentiles"]
    assert (percentiles.type, percentiles.render) == ("distribution", "table")
    assert percentiles.data.metrics == ["latency_ms"]
    assert bench["Latency"].render == "chart"
    solved = iteration["Solved by version"]
    assert (solved.type, solved.data.x) == ("scatter", "version")  # ordinal: regressions
    spread = bench["Repeat spread"]
    assert spread.data.filter == {"metric": "latency", "key": "p95"}
    assert spread.spec is not None
    assert {"calculate": "datum.vs_median > 0.1", "as": "flagged"} in spread.spec["transform"]


def test_load_preset_rejects_unknown_kind() -> None:
    with pytest.raises(ConfigError, match="no preset view for kind 'nope'"):
        load_preset("nope")  # ty: ignore[invalid-argument-type]


def test_view_spec_reads_and_writes_from_alias() -> None:
    view = ViewSpec.model_validate({"title": "mine", "from": "training"})
    assert view.from_ == "training"
    assert view.model_dump()["from"] == "training"
    assert ViewSpec(title="x", from_="generic").from_ == "generic"


def test_model_defaults_and_limits() -> None:
    panel = PanelSpec(type="leaderboard")
    assert panel.noise == ["seed", "test_set"]
    assert panel.layout == PanelLayout(span=12, row=None)
    assert panel.data == PanelData()
    assert panel.scale == "linear"
    assert panel.render == "chart"
    with pytest.raises(ValidationError):
        PanelSpec(type="distribution", render="pie")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValidationError):
        PanelLayout(span=13)
    with pytest.raises(ValidationError):
        PanelData.model_validate({"metrcs": ["acc"]})
    with pytest.raises(ValidationError):
        RunFilter.model_validate({"stauts": "finished"})


def test_run_filter_accepts_one_status_and_rejects_unknown() -> None:
    assert RunFilter.model_validate({"status": "finished"}).status == ["finished"]
    assert RunFilter.model_validate({"tags": "baseline"}).tags == ["baseline"]
    with pytest.raises(ValidationError, match="unknown status done"):
        RunFilter.model_validate({"status": ["finished", "done"]})


def test_resolve_view_replaces_same_title_and_appends_new() -> None:
    view = ViewSpec(
        title="mine",
        from_="generic",
        runs=RunFilter(status=["finished"]),
        panels=[
            PanelSpec(type="markdown", title="Note", text="hi"),
            PanelSpec(type="leaderboard", title="Leaderboard", noise=["seed"]),
        ],
    )
    resolved = resolve_view(view)
    assert [p.title for p in resolved.panels] == ["Summary", "Leaderboard", "Note"]
    assert resolved.panels[1].noise == ["seed"]
    assert resolved.title == "mine"
    assert resolved.from_ is None
    assert resolved.runs.status == ["finished"]
    assert resolve_view(resolved) == resolved


def test_resolve_view_without_from_is_unchanged() -> None:
    view = ViewSpec(title="plain", panels=[PanelSpec(type="markdown", title="a", text="x")])
    assert resolve_view(view) is view


def test_resolve_view_appends_untitled_panels() -> None:
    view = ViewSpec(title="m", from_="generic", panels=[PanelSpec(type="markdown", text="x")])
    assert [p.type for p in resolve_view(view).panels] == ["stat_strip", "leaderboard", "markdown"]
