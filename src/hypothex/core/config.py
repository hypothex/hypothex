"""Models and helpers for the per-project ``hypothex.yaml`` file."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
        If a field has no value.
    """
    missing = sorted(name for name in template_fields(template) if name not in values)
    if missing:
        raise TemplateError(
            f"template variables without a value: {', '.join(missing)} "
            "(pass them with --var name=value)"
        )
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


class TaskSpec(_Strict):
    """Dataset + metrics + primary metric: the unit of comparison."""

    dataset: str
    split: str | None = None
    metrics: list[str] = Field(min_length=1)
    primary: str
    description: str = ""


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
        if errors:
            raise ValueError("; ".join(errors))
        return self


def load_project_config(repo: Path) -> ProjectConfig:
    """
    Load and validate ``<repo>/hypothex.yaml``.

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
        If the file is missing or invalid.
    """
    path = repo / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError(f"no {CONFIG_FILENAME} in {repo}; run `hx init` first")
    try:
        return ProjectConfig.model_validate(read_yaml(path))
    except (ValidationError, ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


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

stages:
  infer: python infer.py --out {{run_dir}}/predictions

env:
  python: [uv, run, python]
"""
