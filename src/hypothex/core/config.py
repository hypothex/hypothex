"""Models and helpers for the per-project ``hypothex.yaml`` file."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hypothex.core.errors import ConfigError, TemplateError
from hypothex.core.fsutil import read_yaml

CONFIG_FILENAME = "hypothex.yaml"
BUILTIN_TEMPLATE_VARS = frozenset(
    {
        "run_id",
        "run_dir",
        "repo",
        "task",
        "seed",
        "config",
        "checkpoint",
        "dataset.name",
        "dataset.version",
        "dataset.path",
    }
)
NAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]*$"
VIEW_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
RESERVED_VIEW_NAMES = frozenset({"overview"})
TaskKind = Literal["generic", "training", "agent_eval", "agent_iteration", "system_bench"]
_FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")


def template_fields(template: str) -> set[str]:
    """
    Return the ``{name}`` fields used in a command template.

    Parameters
    ----------
    template : str
        Command template text.

    Returns
    -------
    set of str
        Field names referenced in the template.

    Examples
    --------
    >>> sorted(template_fields("run {run_dir} {dataset.path}"))
    ['dataset.path', 'run_dir']
    """
    return set(_FIELD.findall(template))


def template_var_hint(name: str) -> str:
    """
    Say how a caller gives a value for the template variable ``name``.

    Built-in variables name the option that sets them (``--seed``,
    ``--config``, ``--task``), with the API and MCP field where there is one;
    any other variable names ``--var`` and the ``vars`` (API) or
    ``template_vars`` (MCP) field.

    Parameters
    ----------
    name : str
        Template variable name, e.g. ``seed`` or ``beam``.

    Returns
    -------
    str
        Short hint, without the name.

    Examples
    --------
    >>> template_var_hint("seed")
    '--seed N; API/MCP: seed'
    >>> template_var_hint("beam")
    '--var beam=VALUE; API: vars, MCP: template_vars'
    """
    custom = f"--var {name}=VALUE; API: vars, MCP: template_vars"
    if name == "seed":
        return "--seed N; API/MCP: seed"
    if name == "config":
        return "--config PATH"
    if name == "checkpoint":
        return f"set by hx reinfer, or {custom}"
    if name == "task" or name.startswith("dataset."):
        return "--task NAME; API/MCP: task"
    return custom


def render_template(template: str, values: dict[str, str]) -> str:
    """
    Fill ``{name}`` fields in a template.

    Parameters
    ----------
    template : str
        Template text.
    values : dict of str to str
        Field values.

    Returns
    -------
    str
        Rendered text.

    Raises
    ------
    TemplateError
        If a field has no value; the message says how to set each one
        (``template_var_hint``).
    """
    missing = sorted(name for name in template_fields(template) if name not in values)
    if missing:
        hints = ", ".join(f"{name} ({template_var_hint(name)})" for name in missing)
        raise TemplateError(f"template variables without a value: {hints}")
    return _FIELD.sub(lambda m: values[m.group(1)], template)


def parse_metric_key(ref: str) -> tuple[str, str]:
    """
    Split ``metric/key`` into its parts; the key defaults to ``value``.

    Parameters
    ----------
    ref : str
        Metric reference, e.g. ``topk/k=1`` or ``acc``.

    Returns
    -------
    tuple of (str, str)
        Metric name and key.

    Examples
    --------
    >>> parse_metric_key("topk/k=1")
    ('topk', 'k=1')
    """
    name, sep, key = ref.partition("/")
    return name, (key if sep else "value")


def parse_metric_version(ref: str) -> tuple[str, str | None]:
    """
    Split ``metric@version`` into its parts.

    Parameters
    ----------
    ref : str
        Metric reference, e.g. ``topk@v2`` or ``topk``.

    Returns
    -------
    tuple of (str, str or None)
        Metric name and version (``None`` if unspecified).

    Examples
    --------
    >>> parse_metric_version("topk@v2")
    ('topk', 'v2')
    """
    name, sep, version = ref.partition("@")
    return name, (version if sep else None)


class _Strict(BaseModel):
    """Base model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class DatasetSpec(_Strict):
    """A named, versioned pointer to data on a host."""

    version: str
    path: str
    host: str = "local"
    description: str = ""
    splits: dict[str, str] = Field(default_factory=dict)
    id_field: str = "id"
    reference_field: str = "reference"

    def path_for(self, split: str | None) -> str:
        """
        Return the path of a split, or the main path when ``split`` is None.

        Parameters
        ----------
        split : str or None
            Split name, or ``None`` for the dataset's main path.

        Returns
        -------
        str
            Path of the requested split.

        Raises
        ------
        ConfigError
            If the split is not declared.
        """
        if split is None:
            return self.path
        if split not in self.splits:
            raise ConfigError(f"dataset has no split {split!r}")
        return self.splits[split]


class MetricSpec(_Strict):
    """A named, versioned scoring function in project code."""

    version: str
    fn: str = Field(pattern=r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
    higher_is_better: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    changelog: dict[str, str] = Field(default_factory=dict)
    unit: str = Field(default="", max_length=8)
    """Display unit (``ms``, ``$``, ``tokens``); empty: inferred from the name."""


class TaskSpec(_Strict):
    """
    Dataset + metrics + primary metric: the unit of comparison.

    ``kind`` picks the preset task view and run-detail layout; it never
    changes storage or evaluation. ``views`` holds inline view bodies
    (validated by ``hypothex.core.views``). ``baseline`` is a seed-group
    selector (``tag:<tag>`` or a group id) that ``system_bench`` compares
    against. ``version_param`` names the run param that orders
    ``agent_iteration`` groups.
    """

    dataset: str
    split: str | None = None
    metrics: list[str] = Field(min_length=1)
    primary: str
    description: str = ""
    kind: TaskKind = "generic"
    views: dict[str, dict[str, Any]] = Field(default_factory=dict)
    baseline: str | None = None
    version_param: str = Field(default="version", min_length=1)


class EnvSpec(_Strict):
    """How to run code in the project's environment."""

    setup: str | None = None
    python: list[str] | None = None


class ProjectConfig(_Strict):
    """Parsed ``hypothex.yaml``."""

    project: str = Field(pattern=NAME_PATTERN)
    description: str = ""
    datasets: dict[str, DatasetSpec] = Field(default_factory=dict)
    metrics: dict[str, MetricSpec] = Field(default_factory=dict)
    tasks: dict[str, TaskSpec] = Field(default_factory=dict)
    stages: dict[str, str] = Field(default_factory=dict)
    env: EnvSpec = Field(default_factory=EnvSpec)

    @model_validator(mode="after")
    def _check_references(self) -> ProjectConfig:
        """Cross-check task references to datasets, metrics, and splits."""
        errors: list[str] = []
        for name, task in self.tasks.items():
            if not re.match(NAME_PATTERN, name):
                errors.append(f"task name {name!r} must match {NAME_PATTERN}")
            dataset = self.datasets.get(task.dataset)
            if dataset is None:
                errors.append(f"task {name!r}: unknown dataset {task.dataset!r}")
            elif task.split is not None and task.split not in dataset.splits:
                errors.append(
                    f"task {name!r}: dataset {task.dataset!r} has no split {task.split!r}"
                )
            errors.extend(
                f"task {name!r}: unknown metric {m!r}"
                for m in task.metrics
                if m not in self.metrics
            )
            primary_metric, _ = parse_metric_key(task.primary)
            if primary_metric not in task.metrics:
                errors.append(f"task {name!r}: primary {task.primary!r} is not one of its metrics")
            for view in task.views:
                if not re.match(VIEW_NAME_PATTERN, view):
                    errors.append(
                        f"task {name!r}: view name {view!r} must match {VIEW_NAME_PATTERN}"
                    )
                elif view in RESERVED_VIEW_NAMES:
                    errors.append(f"task {name!r}: view name {view!r} is reserved for the preset")
        if errors:
            raise ValueError("; ".join(errors))
        return self


YAML_MAX_DEPTH = 64
YAML_MAX_EVENTS = 100_000
NO_VIEW_ANCHORS = "YAML anchors and aliases are not allowed in views"
YAML_CYCLE = "YAML aliases must not form a cycle"


class YamlScan(NamedTuple):
    """
    What ``scan_yaml`` found in a YAML text; lines are 1-based, None when absent.

    Attributes
    ----------
    problem : tuple of (str, int) or None
        ``(message, line)`` when the text nests deeper than ``YAML_MAX_DEPTH``
        or has more than ``YAML_MAX_EVENTS`` parser events; the scan stopped there.
    first_anchor : int or None
        Line of the first anchor or alias anywhere.
    views_anchor : int or None
        Line of the first anchor or alias at or under ``tasks.<task>.views``, with
        alias keys resolved to the scalar their anchor names.
    cycle : int or None
        Line of the first alias to a collection that is still open (one of its own
        ancestors), so the loaded value would contain itself.
    """

    problem: tuple[str, int] | None
    first_anchor: int | None
    views_anchor: int | None
    cycle: int | None


def _in_views(path: tuple[Any, ...]) -> bool:
    """Tell whether a key path is ``tasks.<task>.views`` or below it."""
    return len(path) >= 3 and path[0] == "tasks" and path[2] == "views"


def scan_yaml(text: str) -> YamlScan:
    """
    Pre-scan YAML text as a stream of parser events, before anything is built.

    ``yaml.compose`` and ``yaml.safe_load`` recurse once per nesting level, so a
    few hundred nested ``[`` raise ``RecursionError``. This scan keeps a depth
    counter instead and stops at the first collection deeper than
    ``YAML_MAX_DEPTH`` or the first event past ``YAML_MAX_EVENTS``. On the way it
    finds anchors and aliases: the first anywhere (view files allow none), the
    first at or under ``tasks.<task>.views`` (inline views allow none; a key
    written as an alias, ``*vk:``, is resolved to the scalar its anchor names),
    and the first alias to a collection that is still open (a cycle).

    Parameters
    ----------
    text : str
        YAML text.

    Returns
    -------
    YamlScan
        The first problem and the lines of interest.

    Raises
    ------
    yaml.YAMLError
        If the text is not valid YAML (up to where the scan stopped).

    Examples
    --------
    >>> scan_yaml("a: " + "[" * 70 + "]" * 70).problem
    ('YAML nested too deeply (over 64 levels)', 1)
    >>> scan_yaml("n: &k views\\ntasks:\\n  t:\\n    *k: {v: {title: x}}\\n").views_anchor
    4
    >>> scan_yaml("a: &a [1, *a]\\n").cycle
    1
    >>> scan_yaml("a: &a [1]\\nb: *a\\n")
    YamlScan(problem=None, first_anchor=1, views_anchor=None, cycle=None)
    """
    first_anchor: int | None = None
    views_anchor: int | None = None
    cycle: int | None = None
    scalars: dict[str, str] = {}  # anchor -> scalar value, to resolve alias keys
    # one frame per open collection: its key path, its anchor, and for a mapping
    # whether the next node is a key and the last key read
    frames: list[dict[str, Any]] = []
    for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader), start=1):
        line = event.start_mark.line + 1
        if count > YAML_MAX_EVENTS:
            too_large = (f"YAML too large (over {YAML_MAX_EVENTS} events)", line)
            return YamlScan(too_large, first_anchor, views_anchor, cycle)
        if isinstance(event, yaml.CollectionEndEvent):
            frames.pop()
            continue
        if not isinstance(event, yaml.NodeEvent):
            continue
        path: tuple[Any, ...] = ()
        if frames:
            top = frames[-1]
            if not top["mapping"]:
                path = (*top["path"], None)
            else:
                if top["key_next"]:
                    if isinstance(event, yaml.ScalarEvent):
                        top["key"] = event.value
                    elif isinstance(event, yaml.AliasEvent):
                        top["key"] = scalars.get(event.anchor or "")
                    else:
                        top["key"] = None
                top["key_next"] = not top["key_next"]
                path = (*top["path"], top["key"])
        if event.anchor is not None:
            if first_anchor is None:
                first_anchor = line
            if views_anchor is None and _in_views(path):
                views_anchor = line
            if isinstance(event, yaml.AliasEvent):
                if cycle is None and any(f["anchor"] == event.anchor for f in frames):
                    cycle = line
            elif isinstance(event, yaml.ScalarEvent):
                scalars[event.anchor] = event.value
        if isinstance(event, yaml.CollectionStartEvent):
            if len(frames) >= YAML_MAX_DEPTH:
                too_deep = (f"YAML nested too deeply (over {YAML_MAX_DEPTH} levels)", line)
                return YamlScan(too_deep, first_anchor, views_anchor, cycle)
            frames.append(
                {
                    "path": path,
                    "anchor": event.anchor,
                    "mapping": isinstance(event, yaml.MappingStartEvent),
                    "key_next": True,
                    "key": None,
                }
            )
    return YamlScan(None, first_anchor, views_anchor, cycle)


def has_cycle(data: Any) -> bool:
    """
    Tell whether a loaded YAML value contains itself (a cycle made by aliases).

    An iterative depth-first walk, so depth never costs Python stack: a dict or
    list met again while it is still on the current path is a cycle. Containers
    already finished are not walked twice, so shared (non-cyclic) aliases cost
    linear time.

    Parameters
    ----------
    data : Any
        A value from ``yaml.safe_load``.

    Returns
    -------
    bool
        True if some dict or list contains itself.

    Examples
    --------
    >>> loop = {"a": 1}
    >>> loop["self"] = [loop]
    >>> shared = [1]
    >>> has_cycle(loop), has_cycle({"x": shared, "y": {"z": shared}})
    (True, False)
    """
    on_path: set[int] = set()
    done: set[int] = set()
    stack: list[tuple[Any, bool]] = [(data, False)]
    while stack:
        node, leaving = stack.pop()
        if leaving:
            on_path.discard(id(node))
            done.add(id(node))
            continue
        if not isinstance(node, dict | list) or id(node) in done:
            continue
        if id(node) in on_path:
            return True
        on_path.add(id(node))
        stack.append((node, True))
        children = node.values() if isinstance(node, dict) else node
        stack.extend((child, False) for child in children)
    return False


def load_project_config(repo: Path) -> ProjectConfig:
    """
    Load and validate ``<repo>/hypothex.yaml``.

    The text is pre-scanned first (``scan_yaml``): nesting deeper than
    ``YAML_MAX_DEPTH`` or more than ``YAML_MAX_EVENTS`` events, and any anchor or
    alias at or under ``tasks.<task>.views``, are errors with their line. After
    loading, a value that contains itself (``has_cycle``) is an error too.
    Anchors elsewhere stay allowed.

    Parameters
    ----------
    repo : Path
        Repository root directory.

    Returns
    -------
    ProjectConfig
        The parsed and validated project config.

    Raises
    ------
    ConfigError
        If the file is missing or invalid, too deep or too large, uses an anchor
        or alias in an inline view, or has aliases that form a cycle.
    """
    path = repo / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError(f"no {CONFIG_FILENAME} in {repo}; run `hx init` first")
    try:
        scan = scan_yaml(path.read_text(encoding="utf-8"))
        blocked = scan.problem is not None or scan.views_anchor is not None
        data = None if blocked else read_yaml(path)
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    line: int | None
    if scan.problem is not None:
        message, line = scan.problem
    elif scan.views_anchor is not None:
        message, line = NO_VIEW_ANCHORS, scan.views_anchor
    elif has_cycle(data):
        message, line = YAML_CYCLE, scan.cycle
    else:
        try:
            return ProjectConfig.model_validate(data)
        except (ValidationError, ValueError) as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    where = "" if line is None else f" (line {line})"
    raise ConfigError(f"{path}: {message}{where}")


def find_repo_root(start: Path) -> Path:
    """
    Walk up from ``start`` to the first directory holding ``hypothex.yaml``.

    Parameters
    ----------
    start : Path
        Directory to start searching from.

    Returns
    -------
    Path
        The repository root.

    Raises
    ------
    ConfigError
        If none is found.
    """
    here = start.resolve()
    for directory in [here, *here.parents]:
        if (directory / CONFIG_FILENAME).is_file():
            return directory
    raise ConfigError(f"no {CONFIG_FILENAME} found in {start} or any parent directory")


def starter_config(project: str) -> str:
    """
    Return the text of a commented starter ``hypothex.yaml``.

    Parameters
    ----------
    project : str
        Project name to embed in the starter file.

    Returns
    -------
    str
        Starter ``hypothex.yaml`` file contents.
    """
    return f"""# Hypothex project file. Docs: https://github.com/hypothex/hypothex
project: {project}
description: ""

datasets:
  example:
    version: v1
    path: data/test.jsonl          # relative to the repo, or absolute
    splits: {{test: data/test.jsonl}}

metrics:
  accuracy:
    version: v1
    fn: my_package.metrics:accuracy  # module:function in this repo
    higher_is_better: true

tasks:
  example-test:
    dataset: example
    split: test
    metrics: [accuracy]
    primary: accuracy
    kind: generic                    # or training, agent_eval, agent_iteration, system_bench

stages:
  infer: python infer.py --out {{run_dir}}/predictions

env:
  python: [uv, run, python]
"""
