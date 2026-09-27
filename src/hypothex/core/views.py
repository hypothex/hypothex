"""Views: YAML dashboards of panels, the preset view of each task kind, and validation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from hypothex.core.config import TaskKind
from hypothex.core.errors import ConfigError
from hypothex.core.records import RunStatus

PanelType = Literal[
    "stat_strip",
    "leaderboard",
    "curves",
    "scatter",
    "distribution",
    "grid",
    "table",
    "trace",
    "markdown",
    "vega_lite",
]
Source = Literal["runs", "scores", "metrics", "predictions", "samples", "usage", "traces"]
Noise = Literal["seed", "test_set"]

PRESET_DIR = Path(__file__).resolve().parent.parent / "views" / "presets"


class RunFilter(BaseModel):
    """
    Which runs a view shows; ``None`` means no filter on that field.

    ``status`` and ``tags`` accept one string or a list of strings.

    Examples
    --------
    >>> RunFilter.model_validate({"status": "finished"}).status
    ['finished']
    """

    model_config = ConfigDict(extra="forbid")

    status: list[str] | None = None
    tags: list[str] | None = None
    created_by: str | None = None
    since: datetime | None = None

    @field_validator("status", "tags", mode="before")
    @classmethod
    def _one_or_many(cls, value: Any) -> Any:
        """Wrap a single string into a one-item list."""
        return [value] if isinstance(value, str) else value

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: list[str] | None) -> list[str] | None:
        """Reject statuses that are not a ``RunStatus`` value."""
        allowed = [s.value for s in RunStatus]
        for item in value or []:
            if item not in allowed:
                raise ValueError(f"unknown status {item}; expected one of {', '.join(allowed)}")
        return value


class PanelLayout(BaseModel):
    """Where a panel sits on the 12-column grid."""

    model_config = ConfigDict(extra="forbid")

    span: int = Field(12, ge=1, le=12)
    row: int | None = Field(None, ge=1)


class PanelData(BaseModel):
    """What a panel reads; which keys matter depends on the panel type."""

    model_config = ConfigDict(extra="forbid")

    metrics: list[str] | None = None
    x: str | None = None
    y: str | None = None
    group_by: Literal["group", "config", "run", "seed"] | None = None
    filter: dict[str, Any] | None = None
    pick: Literal["best", "latest", "all"] | None = None
    source: Source | None = None
    fields: list[str] | None = None
    run_id: str | None = None
    example_id: str | None = None
    step_metric: str | None = None


def _default_noise() -> list[Noise]:
    """Return the default leaderboard noise kinds: both seed and test-set noise."""
    return ["seed", "test_set"]


class PanelSpec(BaseModel):
    """One panel of a view."""

    model_config = ConfigDict(extra="forbid")

    type: PanelType
    title: str = ""
    data: PanelData = Field(default_factory=PanelData)
    layout: PanelLayout = Field(default_factory=PanelLayout)
    noise: list[Noise] = Field(default_factory=_default_noise)
    pareto: dict[str, Literal["min", "max"]] | None = None
    spec: dict[str, Any] | None = None
    text: str | None = None
    scale: Literal["linear", "log"] = "linear"
    render: Literal["chart", "table"] = "chart"


class ViewSpec(BaseModel):
    """
    A view: a title, an optional preset to start from, a run filter, and panels.

    The YAML key ``from`` maps to the attribute ``from_``.

    Examples
    --------
    >>> ViewSpec.model_validate({"title": "mine", "from": "training"}).from_
    'training'
    """

    model_config = ConfigDict(
        extra="forbid", validate_by_name=True, validate_by_alias=True, serialize_by_alias=True
    )

    title: str
    from_: TaskKind | None = Field(None, alias="from")
    runs: RunFilter = Field(default_factory=RunFilter)
    panels: list[PanelSpec] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    """One problem in a view's YAML, with its 1-based line when known."""

    line: int | None
    path: str
    message: str
    suggestion: str | None = None


class ViewInfo(BaseModel):
    """A view as listed for a task."""

    name: str
    title: str
    origin: Literal["preset", "inline", "file"]
    path: str | None
    kind: TaskKind | None


def load_preset(kind: TaskKind) -> ViewSpec:
    """
    Load the preset view that ships with the package for a task kind.

    Parameters
    ----------
    kind : TaskKind
        Task kind, e.g. ``"training"``.

    Returns
    -------
    ViewSpec
        The preset view (it has no ``from``).

    Raises
    ------
    ConfigError
        If ``kind`` is not a task kind.

    Examples
    --------
    >>> [p.type for p in load_preset("generic").panels]
    ['stat_strip', 'leaderboard']
    """
    if kind not in get_args(TaskKind):
        raise ConfigError(f"no preset view for kind {kind!r}")
    text = (PRESET_DIR / f"{kind}.yaml").read_text(encoding="utf-8")
    return ViewSpec.model_validate(yaml.safe_load(text))


def resolve_view(view: ViewSpec) -> ViewSpec:
    """
    Apply ``from``: start from the preset panels, then merge the view's panels.

    A view panel whose non-empty title equals a preset panel's title replaces that
    panel in place; every other view panel is appended in order. The view's run
    filter wins unless it is empty, then the preset's is used. The result has no
    ``from``, so resolving twice gives the same view.

    Parameters
    ----------
    view : ViewSpec
        View as written.

    Returns
    -------
    ViewSpec
        The expanded view.

    Examples
    --------
    >>> note = PanelSpec(type="markdown", title="Note", text="hi")
    >>> [p.title for p in resolve_view(ViewSpec(title="m", from_="generic", panels=[note])).panels]
    ['Summary', 'Leaderboard', 'Note']
    """
    if view.from_ is None:
        return view
    base = load_preset(view.from_)
    panels = list(base.panels)
    position = {p.title: i for i, p in enumerate(panels) if p.title}
    for panel in view.panels:
        if panel.title and panel.title in position:
            panels[position[panel.title]] = panel
        else:
            panels.append(panel)
    runs = view.runs if view.runs != RunFilter() else base.runs
    return view.model_copy(update={"from_": None, "runs": runs, "panels": panels})
