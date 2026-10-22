"""Typed table and chart authoring for agents and Python applications.

Examples
--------
>>> data = DataSource(rows=[{"model": "small", "accuracy": 0.9}])
>>> table = Table(title="Results", data=data)
>>> Dashboard(title="Report", panels=[table]).to_spec().panels[0].type
'table'
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from hypothex.core.config import TaskKind
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.views import (
    PanelData,
    PanelLayout,
    PanelSpec,
    RunFilter,
    Source,
    ViewSpec,
    check_view_name,
    save_view,
    validate_view_text,
    view_context,
)

__all__ = ["Chart", "Dashboard", "DataSource", "Encoding", "Table"]


class DataSource(BaseModel):
    """
    Read stored run data or embed JSON records computed by an agent.

    Parameters
    ----------
    source : str, optional
        One of runs, scores, metrics, predictions, samples, usage, traces, groups.
    rows : list of dict, optional
        Inline JSON records. Exactly one of source or rows is required. An empty
        list is valid. Limited to 2,000 rows and 1 MiB of serialized JSON.
    filter : dict, optional
        Exact row matches; list values match any listed value.

    Examples
    --------
    >>> DataSource(source="metrics", filter={"name": "loss"}).to_data().source
    'metrics'
    """

    model_config = ConfigDict(extra="forbid")

    source: Source | None = None
    rows: list[dict[str, JsonValue]] | None = None
    filter: dict[str, JsonValue] | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_data(cls, value: Any) -> Any:
        """Apply strict row validation before Pydantic can coerce JSON inputs."""
        if isinstance(value, dict):
            PanelData.model_validate(value)
        return value

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        """Require an unambiguous dataset, including explicit empty datasets."""
        if (self.source is None) == (self.rows is None):
            raise ValueError("provide exactly one of source or rows")
        return self

    def to_data(self, *, fields: list[str] | None = None) -> PanelData:
        """
        Build independent panel data, optionally selecting columns.

        Parameters
        ----------
        fields : list of str, optional
            Columns to project in order; omitted keeps all columns.

        Returns
        -------
        PanelData
            Validated copy suitable for a table or Vega-Lite panel.
        """
        return PanelData.model_validate({**self.model_dump(), "fields": fields})


class Encoding(BaseModel):
    """
    Map a data field to a Vega-Lite channel such as x, y, color, or tooltip.

    Parameters
    ----------
    field : str, optional
        Literal row key. Dots and brackets are escaped by default. Rename keys
        containing backslashes before using them in a typed encoding.
        May be omitted for aggregate='count'.
    type : str
        quantitative, nominal, ordinal, temporal, or geojson.
    aggregate : str, optional
        Vega-Lite aggregate, such as mean, sum, or count.
    title : str, optional
        Human-readable axis or legend title.
    nested : bool
        Set True to interpret field as a Vega nested property path.
    bin : bool, optional
        Bin a quantitative field.
    time_unit : str, optional
        Vega-Lite timeUnit, such as yearmonth.

    Examples
    --------
    >>> Encoding(field="params.lr", type="quantitative").to_dict()["field"]
    'params\\\\.lr'
    """

    model_config = ConfigDict(extra="forbid")

    field: str | None = None
    type: Literal["quantitative", "nominal", "ordinal", "temporal", "geojson"]
    aggregate: str | None = None
    title: str | None = None
    nested: bool = False
    bin: bool | None = None
    time_unit: str | None = None

    @model_validator(mode="after")
    def _field_or_count(self) -> Self:
        """Allow a fieldless count but reject accidentally empty encodings."""
        if self.field is not None and "\\" in self.field and not self.nested:
            raise ValueError("literal chart fields cannot contain backslashes; rename the row key")
        if self.field is None and self.aggregate != "count":
            raise ValueError("encoding requires a field unless aggregate is count")
        return self

    def to_dict(self) -> dict[str, Any]:
        """
        Produce a Vega-Lite encoding with literal field names preserved.

        Returns
        -------
        dict
            Vega-Lite field definition, with time_unit serialized as timeUnit.
        """
        result = self.model_dump(exclude_none=True, exclude={"nested", "time_unit"})
        if self.field is not None and not self.nested:
            result["field"] = "".join("\\" + c if c in "\\.[]" else c for c in self.field)
        if self.time_unit is not None:
            result["timeUnit"] = self.time_unit
        return result


class Table(BaseModel):
    """
    Display rows as a generic dashboard table.

    Parameters
    ----------
    title : str
        Panel heading.
    data : DataSource
        Stored source or inline records.
    columns : list of str, optional
        Selected columns in display order; omitted keeps all fields.
    layout : PanelLayout
        Grid position; defaults to the full 12-column width.

    Examples
    --------
    >>> Table(title="Empty", data=DataSource(rows=[]), columns=["score"]).to_panel().type
    'table'
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    data: DataSource
    columns: list[str] | None = None
    layout: PanelLayout = Field(default_factory=PanelLayout)

    def to_panel(self) -> PanelSpec:
        """
        Build an independent dashboard panel.

        Returns
        -------
        PanelSpec
            Table panel using the existing query and rendering pipeline.
        """
        return PanelSpec(
            type="table",
            title=self.title,
            data=self.data.to_data(fields=self.columns),
            layout=self.layout.model_copy(deep=True),
        )


class Chart(BaseModel):
    """
    Author a chart with typed encodings or a custom Vega-Lite specification.

    Parameters
    ----------
    title : str
        Panel heading.
    data : DataSource
        Stored source or inline records.
    mark : str, optional
        Vega-Lite mark, such as line, bar, point, area, or rect.
    encoding : dict, optional
        Channel names mapped to Encoding objects (lists for tooltip).
    spec : dict, optional
        Advanced Vega-Lite specification, exclusive with mark and encoding.
        Existing view validation rejects external resources and image marks.
        Panel rows replace root-level spec data; nested inline datasets remain available.
    layout : PanelLayout
        Grid position; defaults to full width.

    Examples
    --------
    >>> Chart(title="Count", data=DataSource(rows=[]), mark="bar",
    ...       encoding={"y": Encoding(type="quantitative", aggregate="count")}).to_panel().type
    'vega_lite'
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    data: DataSource
    mark: str | None = None
    encoding: dict[str, Encoding | list[Encoding]] | None = None
    spec: dict[str, Any] | None = None
    layout: PanelLayout = Field(default_factory=PanelLayout)

    @model_validator(mode="after")
    def _chart_definition(self) -> Self:
        """Reject conflicting or incomplete chart definitions."""
        if self.spec is not None:
            if self.mark is not None or self.encoding is not None:
                raise ValueError("spec is mutually exclusive with mark and encoding")
        elif self.mark is None or self.encoding is None:
            raise ValueError("provide spec or both mark and encoding")
        return self

    def to_panel(self) -> PanelSpec:
        """
        Build an independent Vega-Lite dashboard panel.

        Returns
        -------
        PanelSpec
            Chart panel; save or submit its view for contextual validation.
        """
        if self.spec is not None:
            from copy import deepcopy

            spec = deepcopy(self.spec)
        else:
            spec = {
                "mark": self.mark,
                "encoding": {
                    channel: [e.to_dict() for e in item]
                    if isinstance(item, list)
                    else item.to_dict()
                    for channel, item in (self.encoding or {}).items()
                },
            }
        return PanelSpec(
            type="vega_lite",
            title=self.title,
            data=self.data.to_data(),
            layout=self.layout.model_copy(deep=True),
            spec=spec,
        )


class Dashboard(BaseModel):
    """
    Compose and save a named task view from tables, charts, and existing panels.

    Parameters
    ----------
    title : str
        Dashboard title.
    panels : list
        Table, Chart, or existing PanelSpec objects in display order.
    preset : str, optional
        Task-kind preset whose panels precede these custom panels.
    runs : RunFilter
        Run selection for stored sources; inline rows are independent of runs.

    Examples
    --------
    >>> Dashboard(title="Report", panels=[]).to_spec().title
    'Report'
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    panels: list[Table | Chart | PanelSpec] = Field(default_factory=list)
    preset: TaskKind | None = None
    runs: RunFilter = Field(default_factory=RunFilter)

    def to_spec(self) -> ViewSpec:
        """
        Build an independent view using the standard Hypothex schema.

        Returns
        -------
        ViewSpec
            View definition, retaining any preset reference.
        """
        return ViewSpec(
            title=self.title,
            from_=self.preset,
            runs=self.runs.model_copy(deep=True),
            panels=[
                panel.model_copy(deep=True) if isinstance(panel, PanelSpec) else panel.to_panel()
                for panel in self.panels
            ],
        )

    def to_yaml(self) -> str:
        """
        Serialize for ``hx view add``, MCP ``add_view``, or the HTTP views API.

        Returns
        -------
        str
            YAML without aliases. Submission performs contextual validation.
        """
        return yaml.safe_dump(
            self.to_spec().model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=False,
        )

    def save(
        self, repo: str | Path, task: str, name: str, *, home: str | Path | None = None
    ) -> Path:
        """
        Validate and atomically create or replace a local repository view.

        Parameters
        ----------
        repo : str or Path
            Repository containing hypothex.yaml; registered in the selected home.
        task : str
            Existing task in that project.
        name : str
            View name, excluding the reserved overview name.
        home : str or Path, optional
            Hypothex home; omitted uses HYPOTHEX_HOME or the default home.

        Returns
        -------
        Path
            Written .hypothex/views/<task>/<name>.yaml file.

        Raises
        ------
        ConfigError
            Unknown task, invalid name, unsafe chart, or invalid data reference.

        Examples
        --------
        >>> dashboard.save("/path/to/project", "train", "agent-report")  # doctest: +SKIP
        """
        check_view_name(name)
        repo = Path(repo).resolve()
        ctx = Context.open(Path(home) if home is not None else None)
        entry = ctx.register_project(repo)
        if task not in entry.config.tasks:
            raise ConfigError(f"unknown task {task!r} in project {entry.project!r}")
        text = self.to_yaml()
        metrics, fields = view_context(ctx, entry.project, task)
        _, issues = validate_view_text(text, metrics, fields)
        if issues:
            raise ConfigError("; ".join(f"{issue.path}: {issue.message}" for issue in issues))
        return save_view(repo, task, name, text)
