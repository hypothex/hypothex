"""Public agent authoring API and existing save/query transport integration."""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.panels import query_view
from hypothex.core.views import PanelSpec, get_view
from hypothex.mcp.server import put_view, query_task_view
from hypothex.visuals import Chart, Dashboard, DataSource, Encoding, Table
from tests.factories import seed_finished_run


def _dashboard() -> Dashboard:
    data = DataSource(rows=[{"model": "A", "score": 0.8}, {"model": "B", "score": 0.9}])
    return Dashboard(
        title="Agent report",
        panels=[
            Table(title="Results", data=data, columns=["model", "score"]),
            Chart(
                title="Scores",
                data=data,
                mark="bar",
                encoding={
                    "x": Encoding(field="model", type="nominal"),
                    "y": Encoding(field="score", type="quantitative"),
                    "tooltip": [
                        Encoding(field="model", type="nominal"),
                        Encoding(field="score", type="quantitative"),
                    ],
                },
            ),
        ],
    )


def test_authoring_roundtrip_and_independent_outputs() -> None:
    dashboard = _dashboard()
    view = dashboard.to_spec()
    assert [p.type for p in view.panels] == ["table", "vega_lite"]
    assert view.panels[0].data.fields == ["model", "score"]
    assert view.panels[1].spec["encoding"]["tooltip"][1]["field"] == "score"
    view.panels[0].data.rows[0]["score"] = 999
    view.panels[1].layout.span = 1
    fresh = dashboard.to_spec()
    assert fresh.panels[0].data.rows[0]["score"] == 0.8
    assert fresh.panels[1].layout.span == 12
    assert yaml.safe_load(dashboard.to_yaml()) == fresh.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert "&id" not in dashboard.to_yaml()


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"source": "runs", "rows": []},
        {"source": "bogus"},
        {"rows": [{"x": float("nan")}]},
        {"rows": [{1: "x"}]},
        {"rows": [{"x": (1, 2)}]},
    ],
)
def test_invalid_data(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        DataSource(**kwargs)


def test_datasource_projection_filter_and_copy() -> None:
    source = DataSource(rows=[{"x": {"a": [1]}, "keep": True}], filter={"keep": True})
    result = source.to_data(fields=["x"])
    assert result.fields == ["x"] and result.filter == {"keep": True}
    result.rows[0]["x"]["a"].append(2)
    assert source.rows[0]["x"] == {"a": [1]}
    assert DataSource(source="runs").to_data().source == "runs"
    assert DataSource(rows=[]).to_data().rows == []


def test_encodings_literal_nested_and_count() -> None:
    assert Encoding(field="params.lr[0]", type="quantitative").to_dict() == {
        "field": r"params\.lr\[0\]",
        "type": "quantitative",
    }
    assert Encoding(
        field="obj.value", type="temporal", nested=True, time_unit="yearmonth", title="Month"
    ).to_dict() == {
        "field": "obj.value",
        "type": "temporal",
        "timeUnit": "yearmonth",
        "title": "Month",
    }
    assert Encoding(type="quantitative", aggregate="count").to_dict() == {
        "type": "quantitative",
        "aggregate": "count",
    }
    with pytest.raises(ValidationError, match="cannot contain backslashes"):
        Encoding(field=r"back\slash", type="quantitative")
    with pytest.raises(ValidationError, match="requires a field"):
        Encoding(type="nominal")


@pytest.mark.parametrize(
    "definition",
    [{}, {"mark": "bar"}, {"encoding": {}}, {"spec": {"mark": "point"}, "mark": "bar"}],
)
def test_invalid_chart_definition(definition: dict) -> None:
    with pytest.raises(ValidationError):
        Chart(title="Bad", data=DataSource(rows=[]), **definition)


def test_advanced_spec_existing_panels_and_preset() -> None:
    chart = Chart(title="Layered", data=DataSource(rows=[]), spec={"layer": [{"mark": "point"}]})
    dashboard = Dashboard(
        title="Extended",
        preset="generic",
        panels=[
            PanelSpec(type="markdown", text="Analysis"),
            chart,
        ],
    )
    result = dashboard.to_spec()
    assert result.from_ == "generic"
    assert result.panels[0].text == "Analysis"
    result.panels[1].spec["layer"][0]["mark"] = "bar"
    assert chart.spec["layer"][0]["mark"] == "point"
    result.panels[0].text = "Changed"
    assert dashboard.to_spec().panels[0].text == "Analysis"


def test_save_query_and_replace(home: Path, toy_repo: Path) -> None:
    dashboard = _dashboard()
    path = dashboard.save(toy_repo, "toy-acc", "agent-report", home=home)
    assert path == toy_repo.resolve() / ".hypothex/views/toy-acc/agent-report.yaml"
    ctx = Context.open(home)
    entry = ctx.store.load_project("toy")
    view = get_view(toy_repo, entry.config, "toy-acc", "agent-report")
    results = query_view(ctx, "toy", "toy-acc", view)
    assert (
        results[0].rows
        == results[1].rows
        == [
            {"model": "A", "score": 0.8},
            {"model": "B", "score": 0.9},
        ]
    )
    assert results[0].meta["source"] == "inline"
    dashboard.title = "Revised"
    dashboard.save(toy_repo, "toy-acc", "agent-report", home=home)
    assert yaml.safe_load(path.read_text())["title"] == "Revised"


def test_save_validates_before_replacing(home: Path, toy_repo: Path) -> None:
    good = _dashboard()
    path = good.save(toy_repo, "toy-acc", "agent-report", home=home)
    original = path.read_text()
    bad = Dashboard(
        title="Unsafe",
        panels=[
            Chart(
                title="Unsafe",
                data=DataSource(rows=[]),
                spec={"mark": "point", "data": {"url": "https://example.com/data"}},
            )
        ],
    )
    with pytest.raises(ConfigError):
        bad.save(toy_repo, "toy-acc", "agent-report", home=home)
    assert path.read_text() == original
    with pytest.raises(ConfigError, match="unknown task"):
        good.save(toy_repo, "missing", "report", home=home)
    with pytest.raises(ConfigError, match="preset"):
        good.save(toy_repo, "toy-acc", "overview", home=home)
    bad_columns = Dashboard(
        title="Bad", panels=[Table(title="Bad", data=DataSource(rows=[{"a": 1}]), columns=["typo"])]
    )
    with pytest.raises(ConfigError):
        bad_columns.save(toy_repo, "toy-acc", "bad", home=home)
    assert not (path.parent / "bad.yaml").exists()


def test_stored_source_dashboard(ctx: Context, toy_repo: Path, home: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    dashboard = Dashboard(
        title="Runs",
        panels=[Table(title="Runs", data=DataSource(source="runs"), columns=["run_id"])],
    )
    dashboard.save(toy_repo, "toy-acc", "runs", home=home)
    result = query_view(ctx, "toy", "toy-acc", dashboard.to_spec())[0]
    assert result.rows[0]["run_id"] == "r1"


def test_http_put_get_query(home: Path, ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    base = "/api/v1/tasks/toy/toy-acc/views"
    with TestClient(
        create_app(home, background_repair=False), base_url="http://127.0.0.1:7777"
    ) as c:
        response = c.put(f"{base}/agent-report", json={"text": _dashboard().to_yaml()})
        assert response.status_code == 200, response.text
        assert c.get(f"{base}/agent-report").status_code == 200
        response = c.post(f"{base}/query", json={"name": "agent-report"})
        assert response.status_code == 200, response.text
        panels = response.json()["panels"]
        assert (
            panels[0]["rows"]
            == panels[1]["rows"]
            == [
                {"model": "A", "score": 0.8},
                {"model": "B", "score": 0.9},
            ]
        )
        response = c.post(
            f"{base}/query",
            json={
                "panel": {
                    "type": "table",
                    "data": {"rows": [], "source": "runs"},
                }
            },
        )
        assert response.status_code == 422


def test_mcp_put_query(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    saved = put_view(ctx, "toy-acc", "agent-report", _dashboard().to_yaml(), project="toy")
    assert saved["info"]["name"] == "agent-report"
    result = query_task_view(ctx, "toy-acc", name="agent-report", project="toy")
    assert result["panels"][0]["rows"][1] == {"model": "B", "score": 0.9}


def test_save_respects_whole_view_budget_without_replacing(home: Path, toy_repo: Path) -> None:
    from hypothex.core.views import MAX_INLINE_BYTES, MAX_INLINE_ROWS

    path = _dashboard().save(toy_repo, "toy-acc", "agent-report", home=home)
    original = path.read_text()
    rows = [{f"column{j}": 0 for j in range(25)} for _ in range(MAX_INLINE_ROWS)]
    assert len(json.dumps(rows, separators=(",", ":")).encode()) < MAX_INLINE_BYTES
    wide = Dashboard(title="Wide", panels=[Table(title="Wide", data=DataSource(rows=rows))])
    with pytest.raises(ConfigError, match="YAML too large"):
        wide.save(toy_repo, "toy-acc", "agent-report", home=home)
    assert path.read_text() == original
