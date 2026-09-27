"""Views: YAML dashboards of panels, the preset view of each task kind, and validation."""

from __future__ import annotations

import difflib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hypothex.core.config import YAML_CYCLE, TaskKind, has_cycle, scan_yaml
from hypothex.core.errors import ConfigError
from hypothex.core.records import RunStatus

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

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

ROW_KEYS = frozenset({"run_id", "group_id", "seed"})
FIELD_PREFIXES = ("usage.", "params.", "vars.")
VEGA_ROOT_KEYS = frozenset({"mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"})
VEGA_BLOCKED_KEYS = frozenset({"url", "href", "embedOptions"})
VERSION_REF = "version"
VEGA_MAX_DEPTH = 64
VEGA_MAX_NODES = 10_000
NO_ANCHORS = "YAML anchors and aliases are not allowed"

Loc = tuple[str | int, ...]


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


def _path(loc: Loc) -> str:
    """Format a location as ``panels[0].data.metrics[1]``."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out


def _node_at(root: yaml.Node, loc: Loc) -> yaml.Node:
    """
    Return the YAML node for ``loc``, or its deepest existing ancestor.

    For a mapping step the key node is returned, so an error points at the key's line.
    """
    node, found = root, root
    for part in loc:
        child: yaml.Node | None = None
        mark: yaml.Node | None = None
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if isinstance(key, yaml.ScalarNode) and key.value == str(part):
                    child, mark = value, key
                    break
        elif (
            isinstance(node, yaml.SequenceNode)
            and isinstance(part, int)
            and 0 <= part < len(node.value)
        ):
            child = mark = node.value[part]
        if child is None or mark is None:
            break
        node, found = child, mark
    return found


def _line(root: yaml.Node, loc: Loc) -> int:
    """Return the 1-based line of ``loc`` in the composed YAML."""
    return _node_at(root, loc).start_mark.line + 1


def _allowed_keys(loc: Loc) -> list[str]:
    """Return the keys a mapping at ``loc`` may have, or ``[]`` if unknown."""
    shape = tuple("#" if isinstance(p, int) else p for p in loc)
    models: dict[tuple[str, ...], type[BaseModel]] = {
        (): ViewSpec,
        ("runs",): RunFilter,
        ("panels", "#"): PanelSpec,
        ("panels", "#", "data"): PanelData,
        ("panels", "#", "layout"): PanelLayout,
    }
    model = models.get(shape)
    if model is None:
        return []
    return [field.alias or name for name, field in model.model_fields.items()]


def _closest(word: str, choices: list[str] | set[str]) -> str | None:
    """Return the closest choice to ``word`` (difflib), or None."""
    near = difflib.get_close_matches(word, sorted(choices), n=1)
    return near[0] if near else None


def _schema_issue(root: yaml.Node, err: ErrorDetails) -> ValidationIssue:
    """Turn one pydantic error into a ``ValidationIssue`` with line and suggestion."""
    loc: Loc = tuple(err["loc"])
    field = next((p for p in reversed(loc) if isinstance(p, str)), "value")
    suggestion: str | None = None
    if err["type"] == "extra_forbidden":
        message = f"unknown key {loc[-1]}"
        suggestion = _closest(str(loc[-1]), _allowed_keys(loc[:-1]))
    elif err["type"] == "literal_error":
        expected = re.findall(r"'([^']*)'", str(err.get("ctx", {}).get("expected", "")))
        suggestion = _closest(str(err["input"]), expected)
        message = f"unknown {field} {err['input']}"
        if suggestion is None:
            message += f"; expected one of {', '.join(expected)}"
    elif err["type"] == "missing":
        message = f"missing {field}"
    else:
        message = f"{field}: {err['msg'].removeprefix('Value error, ')}"
    return ValidationIssue(
        line=_line(root, loc), path=_path(loc), message=message, suggestion=suggestion
    )


def _metric_problem(
    ref: str, known_metrics: set[str], known_fields: dict[str, set[str]]
) -> tuple[str, str | None] | None:
    """
    Return ``(message, suggestion)`` if ``ref`` names an unknown metric, else None.

    A reference that is exactly a known name is valid before any split, so history
    metrics keep their ``/`` (``val/top1`` is not metric ``val`` with key ``top1``).
    """
    if ref in ("step", VERSION_REF) or ref.startswith(FIELD_PREFIXES):
        return None
    if ref in known_fields.get("runs", set()) or not known_metrics or ref in known_metrics:
        return None
    base = re.split(r"[@/]", ref, maxsplit=1)[0]
    if base in known_metrics:
        return None
    if "/" in ref and "@" not in ref:
        whole = _closest(ref, {m for m in known_metrics if "/" in m})
        if whole is not None:
            return f"unknown metric {ref}", whole
    near = _closest(base, known_metrics)
    return f"unknown metric {base}", (near + ref[len(base) :] if near else None)


def _example_field_problem(
    name: str, known_fields: dict[str, set[str]]
) -> tuple[str, str | None] | None:
    """
    Return ``(message, suggestion)`` if ``name`` is not a known per-example field.

    Per-example fields are the ``<field>`` of ``predictions`` keys
    ``<metric>@<version>.<field>``. Skipped when no such key is known.
    """
    fields = {
        key.rsplit(".", 1)[1]
        for key in known_fields.get("predictions", set())
        if "." in key and "@" in key.rsplit(".", 1)[0]
    }
    if not fields or name in fields:
        return None
    return f"unknown per-example field {name}", _closest(name, fields)


class _SpecTooBig(Exception):
    """Raised inside ``vega_spec_problems`` when a spec passes a size bound."""


def vega_spec_problems(spec: Any, at: Loc = ()) -> list[tuple[Loc, str]]:
    """
    Find what a Vega-Lite spec may not contain: external resources and images.

    Rows reach a ``vega_lite`` panel only inline, so every ``url`` (data, lookup
    sources, image marks), ``href`` (links), and ``embedOptions`` (vega-embed
    options, which can swap the loader) key is rejected at any depth, and so is
    every ``image`` mark. The walk is bounded: more than ``VEGA_MAX_DEPTH`` nested
    mappings and lists, or more than ``VEGA_MAX_NODES`` values, gives the single
    problem "too deep" or "too large" at ``at`` instead. A spec that contains
    itself (YAML aliases in ``hypothex.yaml``) is "too deep", not a
    ``RecursionError``.

    Parameters
    ----------
    spec : Any
        The spec, or a part of it.
    at : tuple of (str or int)
        Location of ``spec``; prefixed to every returned location.

    Returns
    -------
    list of tuple of (tuple, str)
        ``(location, message)`` per problem, in document order.

    Examples
    --------
    >>> vega_spec_problems({"layer": [{"mark": "point", "data": {"url": "x.csv"}}]})
    [(('layer', 0, 'data', 'url'), 'vega_lite spec must not load external resources (url)')]
    >>> vega_spec_problems({"mark": {"type": "image"}})
    [(('mark',), 'vega_lite image marks are not allowed')]
    >>> loop = {"mark": "point"}
    >>> loop["layer"] = [loop]
    >>> vega_spec_problems(loop, ("spec",))
    [(('spec',), 'vega_lite spec is too deep (over 64 levels)')]
    """
    found: list[tuple[Loc, str]] = []
    seen = 0

    def walk(node: Any, loc: Loc, level: int) -> None:
        nonlocal seen
        seen += 1
        if seen > VEGA_MAX_NODES:
            raise _SpecTooBig(f"vega_lite spec is too large (over {VEGA_MAX_NODES} values)")
        if isinstance(node, dict | list) and level > VEGA_MAX_DEPTH:
            raise _SpecTooBig(f"vega_lite spec is too deep (over {VEGA_MAX_DEPTH} levels)")
        if isinstance(node, dict):
            for key, value in node.items():
                here: Loc = (*loc, str(key))
                if key in VEGA_BLOCKED_KEYS:
                    found.append((here, f"vega_lite spec must not load external resources ({key})"))
                elif key == "mark" and (
                    value == "image" or (isinstance(value, dict) and value.get("type") == "image")
                ):
                    found.append((here, "vega_lite image marks are not allowed"))
                else:
                    walk(value, here, level + 1)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, (*loc, i), level + 1)

    try:
        walk(spec, at, 1)
    except _SpecTooBig as exc:
        return [(at, str(exc))]
    return found


def _panel_issues(
    panel: PanelSpec,
    at: Loc,
    known_metrics: set[str],
    known_fields: dict[str, set[str]],
) -> list[tuple[Loc, str, str | None]]:
    """Return ``(loc, message, suggestion)`` for one panel's semantic problems."""
    out: list[tuple[Loc, str, str | None]] = []
    data = panel.data
    refs: list[tuple[Loc, str]] = [
        ((*at, "data", "metrics", j), ref) for j, ref in enumerate(data.metrics or [])
    ]
    # a grid's data.y is a per-example field, checked below
    axes = ("x", "step_metric") if panel.type == "grid" else ("x", "y", "step_metric")
    refs += [((*at, "data", k), v) for k in axes if (v := getattr(data, k))]
    for loc, ref in refs:
        problem = _metric_problem(ref, known_metrics, known_fields)
        if problem is not None:
            out.append((loc, *problem))
    if panel.type == "grid" and data.y:
        problem = _example_field_problem(data.y, known_fields)
        if problem is not None:
            out.append(((*at, "data", "y"), *problem))
    if panel.type in ("table", "vega_lite") and data.source is None:
        out.append(((*at, "data"), f"{panel.type} needs data.source", None))
    known = known_fields.get(data.source, set()) if data.source else set()
    if known:
        allowed = known | ROW_KEYS | ({VERSION_REF} if data.source == "runs" else set())
        for j, name in enumerate(data.fields or []):
            if name not in allowed:
                out.append(
                    (
                        (*at, "data", "fields", j),
                        f"unknown field {name} in {data.source}",
                        _closest(name, allowed),
                    )
                )
    if panel.type == "scatter" and not data.x:
        out.append(((*at, "data"), "scatter needs data.x", None))
    if panel.type == "markdown" and not panel.text:
        out.append(((*at, "text"), "markdown needs text", None))
    if panel.type == "vega_lite" and not VEGA_ROOT_KEYS & set(panel.spec or {}):
        out.append(((*at, "spec"), "vega_lite spec needs mark, layer, or a composition", None))
    if panel.type == "vega_lite" and panel.spec:
        out += [(loc, msg, None) for loc, msg in vega_spec_problems(panel.spec, (*at, "spec"))]
    if panel.pareto and set(panel.pareto) - {"x", "y"}:
        out.append(((*at, "pareto"), "pareto keys are x and y", None))
    return out


def _semantic_issues(
    view: ViewSpec,
    root: yaml.Node,
    known_metrics: set[str],
    known_fields: dict[str, set[str]],
) -> list[ValidationIssue]:
    """Check metric names, sources, fields, and per-type requirements of a parsed view."""
    found: list[tuple[Loc, str, str | None]] = []
    titles: set[str] = set()
    for i, panel in enumerate(view.panels):
        found += _panel_issues(panel, ("panels", i), known_metrics, known_fields)
        if panel.title in titles:
            found.append((("panels", i, "title"), f"duplicate panel title {panel.title}", None))
        if panel.title:
            titles.add(panel.title)
    return [
        ValidationIssue(line=_line(root, loc), path=_path(loc), message=msg, suggestion=fix)
        for loc, msg, fix in found
    ]


def validate_view_text(
    text: str, known_metrics: set[str], known_fields: dict[str, set[str]]
) -> tuple[ViewSpec | None, list[ValidationIssue]]:
    """
    Parse and check a view's YAML text.

    The text is pre-scanned before it is loaded (``config.scan_yaml``): nesting
    deeper than 64 levels, more than 100,000 parser events, and any YAML anchor
    or alias (a view could refer to itself) are schema errors with their line; a
    loaded value that contains itself (``config.has_cycle``) is one too. Schema
    errors (bad YAML, those guards, unknown keys, wrong types) return no view. Semantic
    problems (unknown metric or field, missing ``source``/``text``/``spec``,
    duplicate titles) return the parsed view plus issues, so a preview can still
    render; the view is valid only when the issue list is empty. Metric and field
    checks are skipped when the matching known set is empty (a task with no runs).

    Parameters
    ----------
    text : str
        View YAML.
    known_metrics : set of str
        Metric base names seen for the task (``view_context``).
    known_fields : dict of str to set of str
        Row fields per source seen for the task (``view_context``).

    Returns
    -------
    tuple of (ViewSpec or None, list of ValidationIssue)

    Examples
    --------
    >>> view, issues = validate_view_text("title: t\\npanels:\\n  - type: leaderbord\\n", set(), {})
    >>> view is None, issues[0].line, issues[0].suggestion
    (True, 3, 'leaderboard')
    """
    try:
        scan = scan_yaml(text)
        if scan.problem is not None:
            message, line = scan.problem
            return None, [ValidationIssue(line=line, path="", message=message)]
        if scan.first_anchor is not None:
            return None, [ValidationIssue(line=scan.first_anchor, path="", message=NO_ANCHORS)]
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark is not None else None
        return None, [ValidationIssue(line=line, path="", message=f"YAML: {exc.problem or exc}")]
    except yaml.YAMLError as exc:
        return None, [ValidationIssue(line=None, path="", message=f"YAML: {exc}")]
    if has_cycle(data):  # the shared guard; without aliases no cycle can form
        return None, [ValidationIssue(line=scan.cycle, path="", message=YAML_CYCLE)]
    if not isinstance(root, yaml.MappingNode):
        line = root.start_mark.line + 1 if root is not None else 1
        message = "a view is a mapping with title and panels"
        return None, [ValidationIssue(line=line, path="", message=message)]
    try:
        view = ViewSpec.model_validate(data)
    except ValidationError as exc:
        return None, [_schema_issue(root, err) for err in exc.errors()]
    return view, _semantic_issues(view, root, known_metrics, known_fields)
