"""Inline records use the existing table and Vega-Lite validation/query paths."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml
from pydantic import ValidationError

from hypothex.core import views
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.panels import query_panel, query_view
from hypothex.core.views import (
    MAX_INLINE_BYTES,
    MAX_INLINE_DEPTH,
    MAX_INLINE_ROWS,
    PanelData,
    PanelSpec,
    RunFilter,
    ViewSpec,
    inline_row_fields,
    validate_view_text,
)


def _panel(
    rows: list[dict[str, Any]],
    *,
    type_: Literal["table", "vega_lite"] = "table",
    fields: list[str] | None = None,
    filter_: dict[str, Any] | None = None,
) -> PanelSpec:
    return PanelSpec(
        type=type_,
        title="Custom data",
        data=PanelData(rows=rows, fields=fields, filter=filter_),
        spec={"mark": "bar", "encoding": {"x": {"field": "name"}}}
        if type_ == "vega_lite"
        else None,
    )


def _validate(panel: PanelSpec) -> tuple[ViewSpec | None, list[views.ValidationIssue]]:
    text = yaml.safe_dump({"title": "Custom", "panels": [panel.model_dump(exclude_none=True)]})
    return validate_view_text(text, {"accuracy"}, {"runs": {"run_id", "unrelated"}})


@pytest.mark.parametrize("type_", ["table", "vega_lite"])
def test_inline_rows_filter_then_project_without_synthetic_keys(
    ctx: Context, toy_repo: Path, type_: Literal["table", "vega_lite"]
) -> None:
    ctx.register_project(toy_repo)
    rows = [{"name": "a", "score": 0.8, "keep": True}, {"name": "b", "score": 0.2}]
    panel = _panel(rows, type_=type_, fields=["score", "name"], filter_={"keep": True})
    view, issues = _validate(panel)
    assert view is not None and not issues
    result = query_panel(ctx, "toy", "toy-acc", panel, RunFilter(status=["failed"]))
    assert result.rows == [{"score": 0.8, "name": "a"}]
    assert list(result.rows[0]) == ["score", "name"]
    assert result.meta["source"] == "inline"
    assert result.meta["columns"] == ["score", "name"]
    assert result.meta["total"] == 1
    assert query_view(ctx, "toy", "toy-acc", view)[0] == result
    if type_ == "vega_lite":
        assert result.meta["spec"]["data"] == {"values": []}
        assert panel.spec is not None and "data" not in panel.spec


def test_inline_nested_json_is_detached_from_caller_and_results(
    ctx: Context, toy_repo: Path
) -> None:
    ctx.register_project(toy_repo)
    rows = [{"items": [None, True, 3, 0.5, "text", {"value": 4}], "empty": {}}]
    expected = copy.deepcopy(rows)
    panel = _panel(rows)
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == expected
    result.rows[0]["items"][-1]["value"] = 100
    assert rows == expected
    assert panel.data.rows == expected


@pytest.mark.parametrize("rows", [[], [{"name": "a"}]])
def test_empty_projection_is_valid_and_has_no_implicit_columns(
    ctx: Context, toy_repo: Path, rows: list[dict[str, Any]]
) -> None:
    ctx.register_project(toy_repo)
    result = query_panel(ctx, "toy", "toy-acc", _panel(rows, fields=[]))
    assert result.rows == ([{}] if rows else [])
    assert result.meta["columns"] == []


def test_empty_inline_rows_accept_explicit_schema_and_validate_filter(
    ctx: Context, toy_repo: Path
) -> None:
    ctx.register_project(toy_repo)
    panel = _panel([], fields=["name", "score"], filter_={"name": ["a", "b"]})
    assert inline_row_fields(panel.data) == {"name", "score"}
    _, issues = _validate(panel)
    assert not issues
    result = query_panel(ctx, "toy", "toy-acc", panel)
    assert result.rows == []
    assert result.meta == {"source": "inline", "total": 0, "columns": ["name", "score"]}
    assert inline_row_fields(PanelData(source="runs")) == set()


def test_union_of_inline_keys_supports_sparse_rows(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    panel = _panel([{"a": 1}, {"b": 2}], fields=["a", "b"])
    assert inline_row_fields(panel.data) == {"a", "b"}
    assert not _validate(panel)[1]
    assert query_panel(ctx, "toy", "toy-acc", panel).rows == [
        {"a": 1, "b": None},
        {"a": None, "b": 2},
    ]


@pytest.mark.parametrize("rows", [[{"name": "a"}], [{}], []])
def test_unknown_inline_filter_is_rejected_at_validation_and_query(
    ctx: Context, toy_repo: Path, rows: list[dict[str, Any]]
) -> None:
    ctx.register_project(toy_repo)
    panel = _panel(rows, filter_={"unrelated": 1})
    _, issues = _validate(panel)
    assert any(i.path == "panels[0].data.filter.unrelated" for i in issues)
    with pytest.raises(ConfigError, match="unknown filter key unrelated in inline"):
        query_panel(ctx, "toy", "toy-acc", panel)


@pytest.mark.parametrize("rows", [[{"score": 1}], [{}]])
def test_unknown_inline_projection_rejected_with_field_suggestion(
    ctx: Context, toy_repo: Path, rows: list[dict[str, Any]]
) -> None:
    ctx.register_project(toy_repo)
    panel = _panel(rows, fields=["scroe"])
    _, issues = _validate(panel)
    assert issues[0].path == "panels[0].data.fields[0]"
    if "score" in rows[0]:
        assert issues[0].suggestion == "score"
    with pytest.raises(ConfigError, match="unknown field scroe in inline"):
        query_panel(ctx, "toy", "toy-acc", panel)


def test_inline_name_filter_does_not_reference_task_metrics() -> None:
    panel = _panel([{"name": "unconfigured"}], filter_={"name": ["unconfigured"]})
    assert not _validate(panel)[1]


@pytest.mark.parametrize("rows", [[], [{"x": 1}]])
def test_source_and_rows_are_mutually_exclusive(rows: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        PanelData(source="runs", rows=rows)
    parsed, issues = validate_view_text(
        "title: Custom\npanels:\n- type: table\n  data: {source: runs, rows: []}\n", set(), {}
    )
    assert parsed is None and "mutually exclusive" in issues[0].message


def test_rows_rejected_for_other_panel_types() -> None:
    with pytest.raises(ValidationError, match="only to table and vega_lite"):
        PanelSpec(type="curves", data=PanelData(rows=[]))


def test_query_boundary_rejects_mutated_ambiguous_or_unsupported_data(ctx: Context) -> None:
    panel = _panel([])
    panel.data.source = "runs"
    with pytest.raises(ConfigError, match="mutually exclusive"):
        query_panel(ctx, "unused", "unused", panel)
    result = query_view(ctx, "unused", "unused", ViewSpec(title="x", panels=[panel]))
    assert "mutually exclusive" in result[0].meta["error"]
    panel.data.source = None
    panel.type = "markdown"
    with pytest.raises(ConfigError, match="only to table and vega_lite"):
        query_panel(ctx, "unused", "unused", panel)


@pytest.mark.parametrize("type_", ["table", "vega_lite"])
def test_source_or_rows_required_at_query_boundary(
    ctx: Context, toy_repo: Path, type_: Literal["table", "vega_lite"]
) -> None:
    ctx.register_project(toy_repo)
    panel = PanelSpec(type=type_, spec={"mark": "bar"})
    assert any("needs data.source or data.rows" in issue.message for issue in _validate(panel)[1])
    with pytest.raises(ConfigError, match="needs data.source or data.rows"):
        query_panel(ctx, "toy", "toy-acc", panel)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        Decimal("0.1"),
        datetime(2026, 1, 1),
        b"x",
        {1},
        (1,),
    ],
)
def test_inline_cells_require_strict_finite_json_values(value: Any) -> None:
    with pytest.raises(ValidationError, match="finite numbers|JSON-compatible"):
        PanelData.model_validate({"rows": [{"nested": {"value": [value]}}]})


def test_inline_rows_reject_nonobjects_nonstrings_and_cycles() -> None:
    for value in ({"a": 1}, [{1: "value"}], [1]):
        with pytest.raises(ValidationError, match="JSON objects|keys must be strings"):
            PanelData.model_validate({"rows": value})
    cyclic: dict[str, Any] = {}
    cyclic["cycle"] = cyclic
    with pytest.raises(ValidationError, match="cycles"):
        PanelData.model_validate({"rows": [cyclic]})


def test_inline_row_count_bound_and_shared_noncyclic_values() -> None:
    shared = {"value": 1}
    assert len(PanelData(rows=[shared] * MAX_INLINE_ROWS).rows or []) == MAX_INLINE_ROWS
    with pytest.raises(ValidationError, match="at most 2000"):
        PanelData(rows=[shared] * (MAX_INLINE_ROWS + 1))


def test_inline_serialized_byte_limit_counts_utf8_and_escaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [{'quoted"': ["雪", "\n", True, None, 1, 0.25]}]
    size = len(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    monkeypatch.setattr(views, "MAX_INLINE_BYTES", size)
    assert PanelData(rows=rows).rows == rows
    monkeypatch.setattr(views, "MAX_INLINE_BYTES", size - 1)
    with pytest.raises(ValidationError, match="serialized bytes"):
        PanelData(rows=rows)


def test_inline_large_payload_and_deep_nesting_rejected() -> None:
    with pytest.raises(ValidationError, match="serialized bytes"):
        PanelData(rows=[{"large": "x" * MAX_INLINE_BYTES}])
    nested: Any = 1
    for _ in range(MAX_INLINE_DEPTH):
        nested = [nested]
    with pytest.raises(ValidationError, match="nesting levels"):
        PanelData(rows=[{"nested": nested}])


def test_inline_mutation_cannot_bypass_query_limits(ctx: Context) -> None:
    panel = _panel([{"x": 1}])
    assert panel.data.rows is not None
    panel.data.rows[0]["x"] = float("nan")
    with pytest.raises(ConfigError, match="finite numbers"):
        query_panel(ctx, "unused", "unused", panel)


def test_inline_vega_uses_existing_external_resource_guard(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    panel = _panel([{"x": 1}], type_="vega_lite")
    panel.spec = {"mark": "bar", "layer": [{"data": {"url": "https://example.invalid/data"}}]}
    with pytest.raises(ConfigError, match="external resources"):
        query_panel(ctx, "toy", "toy-acc", panel)
