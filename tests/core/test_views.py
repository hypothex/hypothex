import json
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
    validate_view_text,
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


# ---- validate_view_text ----

KNOWN_METRICS = {"solved", "route_len", "solve_time", "tokens"}
KNOWN_FIELDS = {
    "predictions": {"id", "prediction", "reference", "meta.category", "solved@v2.solved"},
    "runs": {"status", "created_by", "params.depth", "usage.usd"},
}

# The route-quality view from docs/mockups/kinds/custom_view/data.js, minus its
# made-up "config" field. Line numbers below refer to this text.
ROUTE_QUALITY = """\
title: route quality
runs: {status: finished}
panels:
  - type: stat_strip
    title: Best config
    data:
      metrics:
        - solved@v2
        - route_len@v1/median
      pick: best
    layout: {span: 12, row: 1}
  - type: scatter
    title: Length vs time
    data:
      x: solve_time@v1/median
      y: route_len@v1/median
      group_by: config
    pareto: {x: min, y: min}
    layout: {span: 5, row: 2}
  - type: vega_lite
    title: Solved by depth
    data:
      source: predictions
      fields: [group_id, solved@v2.solved]
    spec:
      mark: rect
      encoding:
        x: {field: group_id}
    layout: {span: 8, row: 3}
  - type: markdown
    title: Note
    text: Critic gain is largest on 5+ step targets.
    layout: {span: 4, row: 3}
"""


def _check(text: str) -> tuple[ViewSpec | None, list[tuple[int | None, str, str, str | None]]]:
    view, issues = validate_view_text(text, KNOWN_METRICS, KNOWN_FIELDS)
    return view, [(i.line, i.path, i.message, i.suggestion) for i in issues]


def test_valid_view_has_no_issues() -> None:
    view, issues = _check(ROUTE_QUALITY)
    assert issues == []
    assert view is not None
    assert view.runs.status == ["finished"]
    assert [p.type for p in view.panels] == ["stat_strip", "scatter", "vega_lite", "markdown"]


def test_unknown_metric_names_line_and_suggests_nearest() -> None:
    text = ROUTE_QUALITY.replace("y: route_len@v1/median", "y: route_length@v1/median")
    view, issues = _check(text)
    assert view is not None
    assert issues == [
        (16, "panels[1].data.y", "unknown metric route_length", "route_len@v1/median")
    ]


def test_unknown_metric_in_list_and_without_near_match() -> None:
    text = ROUTE_QUALITY.replace("- solved@v2", "- zzz@v2")
    _, issues = _check(text)
    assert issues == [(8, "panels[0].data.metrics[0]", "unknown metric zzz", None)]


def test_field_refs_and_step_are_not_metrics() -> None:
    text = """\
title: t
panels:
  - type: scatter
    data: {x: usage.usd, y: params.depth}
  - type: curves
    data: {x: step, step_metric: step}
"""
    assert _check(text)[1] == []


def test_metric_checks_skip_when_nothing_is_known() -> None:
    text = "title: t\npanels:\n  - type: leaderboard\n    data: {y: anything@v9/p95}\n"
    view, issues = validate_view_text(text, set(), {})
    assert view is not None
    assert issues == []


def test_yaml_syntax_error_has_line() -> None:
    view, issues = _check("title: t\npanels:\n  - type: [leaderboard\n")
    assert view is None
    assert len(issues) == 1
    assert issues[0][0] == 4
    assert issues[0][2].startswith("YAML: ")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", (1, "", "a view is a mapping with title and panels", None)),
        ("- a\n- b\n", (1, "", "a view is a mapping with title and panels", None)),
        ("panels: []\n", (1, "title", "missing title", None)),
        (
            "title: t\npanels:\n  - type: leaderbord\n",
            (3, "panels[0].type", "unknown type leaderbord", "leaderboard"),
        ),
        (
            "title: t\npanels:\n  - type: leaderboard\n    data:\n      metrcs: [solved]\n",
            (5, "panels[0].data.metrcs", "unknown key metrcs", "metrics"),
        ),
        (
            "title: t\nruns: {stauts: finished}\n",
            (2, "runs.stauts", "unknown key stauts", "status"),
        ),
        (
            "title: t\nfrom: trainng\n",
            (2, "from", "unknown from trainng", "training"),
        ),
        (
            "title: t\npanels:\n  - type: grid\n    layout: {span: 20}\n",
            (
                4,
                "panels[0].layout.span",
                "span: Input should be less than or equal to 12",
                None,
            ),
        ),
        (
            "title: t\nruns: {status: done}\n",
            (
                2,
                "runs.status",
                "status: unknown status done; expected one of queued, running, finished, "
                "failed, killed, lost",
                None,
            ),
        ),
        ("title: t\npanels:\n  - title: no type\n", (3, "panels[0].type", "missing type", None)),
    ],
)
def test_schema_errors_have_line_path_and_suggestion(
    text: str, expected: tuple[int | None, str, str, str | None]
) -> None:
    view, issues = _check(text)
    assert view is None
    assert issues == [expected]


def test_literal_without_near_match_lists_choices() -> None:
    _, issues = _check("title: t\npanels:\n  - type: leaderboard\n    scale: zzz\n")
    assert issues == [
        (4, "panels[0].scale", "unknown scale zzz; expected one of linear, log", None)
    ]


@pytest.mark.parametrize(
    ("panel", "expected"),
    [
        ("  - type: table\n", (3, "panels[0].data", "table needs data.source", None)),
        (
            "  - type: table\n    data: {source: runs, fields: [stauts]}\n",
            (4, "panels[0].data.fields[0]", "unknown field stauts in runs", "status"),
        ),
        ("  - type: markdown\n", (3, "panels[0].text", "markdown needs text", None)),
        (
            "  - type: vega_lite\n    data: {source: runs}\n    spec: {encoding: {}}\n",
            (5, "panels[0].spec", "vega_lite spec needs mark, layer, or a composition", None),
        ),
        ("  - type: scatter\n", (3, "panels[0].data", "scatter needs data.x", None)),
        (
            "  - type: scatter\n    data: {x: usage.usd}\n    pareto: {z: min}\n",
            (5, "panels[0].pareto", "pareto keys are x and y", None),
        ),
    ],
)
def test_panel_requirements(panel: str, expected: tuple[int, str, str, str | None]) -> None:
    view, issues = _check("title: t\npanels:\n" + panel)
    assert view is not None
    assert issues == [expected]


def test_fields_accept_row_keys_and_skip_unknown_sources() -> None:
    text = """\
title: t
panels:
  - type: table
    data: {source: runs, fields: [run_id, group_id, seed, usage.usd]}
  - type: table
    data: {source: traces, fields: [anything]}
"""
    assert _check(text)[1] == []


def test_duplicate_panel_titles() -> None:
    text = """\
title: t
panels:
  - type: leaderboard
    title: A
  - type: grid
    title: A
"""
    assert _check(text)[1] == [(6, "panels[1].title", "duplicate panel title A", None)]


def test_every_preset_file_validates_clean() -> None:
    for kind in get_args(TaskKind):
        text = (PRESET_DIR / f"{kind}.yaml").read_text(encoding="utf-8")
        view, issues = validate_view_text(text, set(), {})
        assert issues == [], kind
        assert view == load_preset(kind)


def test_issues_serialise_for_the_api() -> None:
    _, issues = validate_view_text("title: t\npanels:\n  - type: pie\n", set(), {})
    dumped = json.loads(issues[0].model_dump_json())
    assert dumped["line"] == 3
    assert dumped["path"] == "panels[0].type"
    assert dumped["message"].startswith("unknown type pie; expected one of stat_strip")
    assert dumped["suggestion"] is None


def test_known_metric_names_with_slashes_are_not_split() -> None:
    # history metrics keep their "/" (records.MetricPoint.name): val/top1 is not metric "val"
    metrics = {"accuracy", "val/top1", "sys/gpu_util"}
    fields = {"runs": {"status", "created_by"}}
    text = """\
title: t
panels:
  - type: curves
    data: {metrics: [val/top1, sys/gpu_util], y: val/top1}
  - type: scatter
    data: {x: version, y: val/top1}
  - type: table
    data: {source: runs, fields: [group_id, version, status]}
"""
    view, issues = validate_view_text(text, metrics, fields)
    assert view is not None and issues == []
    typo = text.replace("y: val/top1}", "y: val/topp1}", 1)  # the curves panel's y
    _, issues = validate_view_text(typo, metrics, fields)
    assert [(i.line, i.path, i.message, i.suggestion) for i in issues] == [
        (4, "panels[0].data.y", "unknown metric val/topp1", "val/top1")
    ]


def test_grid_y_is_a_per_example_field() -> None:
    fields = {"predictions": {"id", "accuracy@v1.correct", "accuracy@v1.partial", "meta.category"}}
    text = "title: t\npanels:\n  - type: grid\n    data: {metrics: [accuracy@v1], y: partial}\n"
    assert validate_view_text(text, {"accuracy"}, fields)[1] == []
    typo = text.replace("partial", "partal")
    _, issues = validate_view_text(typo, {"accuracy"}, fields)
    assert [(i.line, i.path, i.message, i.suggestion) for i in issues] == [
        (4, "panels[0].data.y", "unknown per-example field partal", "partial")
    ]
    assert validate_view_text(typo, {"accuracy"}, {})[1] == []  # nothing known: skipped


def test_vega_lite_external_resources_are_rejected_at_any_depth() -> None:
    text = """\
title: t
panels:
  - type: vega_lite
    data: {source: runs}
    spec:
      layer:
        - mark: point
          data: {url: "https://example.com/x.json"}
        - mark: {type: image}
          encoding:
            url: {field: run_id}
            href: {field: run_id}
      transform:
        - lookup: run_id
          from: {data: {url: data/other.csv}, key: run_id, fields: [x]}
      usermeta: {embedOptions: {loader: {baseURL: "https://example.com/"}}}
"""
    view, issues = validate_view_text(text, set(), {})
    assert view is not None  # a semantic problem: the preview may render, Save may not
    external = "vega_lite spec must not load external resources"
    assert [(i.line, i.path, i.message) for i in issues] == [
        (8, "panels[0].spec.layer[0].data.url", f"{external} (url)"),
        (9, "panels[0].spec.layer[1].mark", "vega_lite image marks are not allowed"),
        (11, "panels[0].spec.layer[1].encoding.url", f"{external} (url)"),
        (12, "panels[0].spec.layer[1].encoding.href", f"{external} (href)"),
        (15, "panels[0].spec.transform[0].from.data.url", f"{external} (url)"),
        (16, "panels[0].spec.usermeta.embedOptions", f"{external} (embedOptions)"),
    ]


NO_ANCHORS = "YAML anchors and aliases are not allowed"
# regression: the spec refers to itself; loading it used to raise RecursionError
RECURSIVE_VIEW = """\
title: t
panels:
  - type: vega_lite
    data: {source: runs}
    spec: &s {mark: point, layer: [*s]}
"""


def test_yaml_anchors_and_aliases_are_rejected_with_their_line() -> None:
    assert _check(RECURSIVE_VIEW) == (None, [(5, "", NO_ANCHORS, None)])
    shared = """\
title: t
panels:
  - type: markdown
    title: A
    text: &note shared text
  - type: markdown
    title: B
    text: *note
"""
    assert _check(shared) == (None, [(5, "", NO_ANCHORS, None)])
    merge = "title: t\npanels:\n  - type: grid\n    layout:\n      <<: *wide\n"
    assert _check(merge) == (None, [(5, "", NO_ANCHORS, None)])  # alias with no anchor


def _vega_view(spec: str) -> str:
    return (
        "title: t\npanels:\n  - type: vega_lite\n    data: {source: runs}\n"
        f"    spec: {{mark: point, extra: {spec}}}\n"
    )


def test_deep_or_huge_yaml_is_rejected_before_it_is_loaded() -> None:
    # regression: 600 nested lists (no alias) raised RecursionError inside yaml.compose
    deep = (None, [(5, "", "YAML nested too deeply (over 64 levels)", None)])
    assert _check(_vega_view("[" * 600 + "]" * 600)) == deep
    # 60 nested mappings under the spec: 64 levels in the whole document, the limit
    view, issues = validate_view_text(_vega_view("{a: " * 60 + "1" + "}" * 60), set(), {})
    assert view is not None and issues == []
    assert _check(_vega_view("{a: " * 61 + "1" + "}" * 61)) == deep
    huge = _vega_view("[" + ", ".join(["0"] * 100_000) + "]")
    assert _check(huge) == (None, [(5, "", "YAML too large (over 100000 events)", None)])


def test_vega_lite_spec_size_is_bounded() -> None:
    wide = _vega_view("[" + ", ".join(["0"] * 10_000) + "]")
    view, issues = validate_view_text(wide, set(), {})
    assert view is not None
    assert [(i.line, i.path, i.message) for i in issues] == [
        (5, "panels[0].spec", "vega_lite spec is too large (over 10000 values)")
    ]
