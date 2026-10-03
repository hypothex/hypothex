# Hypothex Phase 1a (Core Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Hypothex engine for one machine (the Mac environment): project file, run folders, rebuildable index, event log, local execution, dataset fingerprints, versioned metrics with re-evaluation, seed-grouped leaderboards, and all agent interfaces (Python SDK, `hx` CLI with `--json`, HTTP + WebSocket API, MCP server, skill file), proven end to end on a toy project.

**Architecture:** Files are the source of truth (`~/.hypothex/store/<project>/runs/<run_id>/`). Every state change goes through `Context.update_run`, which, under a per-run file lock, writes `run.yaml`, appends an event to the environment's SQLite event log, and upserts the SQLite index. Metrics run in the project's own Python environment through a worker subprocess (`python -m hypothex.eval_worker`). CLI, API, and MCP are thin layers over `hypothex.core`.

**Tech Stack:** Python ≥ 3.11, uv, hatchling, pydantic 2, PyYAML, SQLAlchemy 2 (SQLite, WAL), Typer, FastAPI + uvicorn, psutil, xxhash, official `mcp` SDK (FastMCP), pytest, ruff, ty, Sphinx + sphinx-rtd-theme + numpydoc. Toy example uses scikit-learn.

**Spec:** `docs/superpowers/specs/2026-09-26-hypothex-design.md` (read sections 2–7, 10–13 before starting).

## Global Constraints

- Python `>=3.11`. Package manager **uv** only (`uv add`, `uv run`, `uv sync`). Lint/format **ruff** (line length 100). Types **ty**. Tests **pytest** in `tests/` mirroring `src/`.
- Package name `hypothex`, import `hypothex`, CLI entry point `hx`, version `0.1.0.dev0`, license `Apache-2.0` (matches the published 0.0.1 placeholder).
- Every public function/method has type annotations and a numpydoc docstring (summary + Parameters/Returns where there are any).
- Home directory: `~/.hypothex`, overridable with env `HYPOTHEX_HOME`. Layout: `store/`, `index.db`, `events.db`, `environment.json`, `dataset_cache.json`.
- Files first. The index must always be rebuildable from files (`hx reindex`). All `run.yaml` writes are atomic (temp + `os.replace`) and happen under the per-run lock.
- Old scores are never overwritten or deleted; re-evaluation appends.
- Every CLI command supports `--json` (stable output = pydantic `model_dump(mode="json")`).
- API binds `127.0.0.1:7777` by default. No auth in phase 1a.
- Environment `protocol_version` = `1`.
- Limits: git diff capture ≤ 5 MB; full dataset hash for files ≤ 2 GB, else manifest mode with 4 MB head/tail samples; log tail = last 5,000 lines / 8 MiB; ≤ 1,000 indexed points per metric name per run.
- Environment capture uses an allow-list of env vars only. Never capture secrets.
- If env `HYPOTHEX_AGENT` is set, a run without a hypothesis is rejected.
- Metric references: `name@version` selects a version; `name/key` selects a value key; key defaults to `value`.
- Git commands in tests pass `-c user.email=t@t -c user.name=t` so CI needs no git config.

## Review Focus

1. **A crash mid-append leaves a partial last line in a JSONL file.** Readers must skip it and keep going, not crash. (Task 1: `test_read_jsonl_skips_partial_last_line`.)
2. **The command is missing, exits non-zero, gets Ctrl-C/SIGTERM, or its supervisor dies.** The run must end as `failed` / `killed` / `lost` with an exit code where known, and never stay `running` forever. (Tasks 11–12: `test_missing_command_fails_before_run_dir`, `test_failing_command_is_failed`, `test_stop_run_kills_background_run`, `test_repair_marks_dead_running_as_lost`.)
3. **A task run produces no predictions.** It is `finished`, has no scores, and is listed as `unscored` on the leaderboard; re-eval skips it with the reason "no predictions". (Tasks 10–11: `test_reeval_skips_run_without_predictions`, `test_task_run_without_predictions_finishes_unscored`.)
4. **A metric function raises on one run.** It records an error score row, other metrics still score, and the leaderboard ignores error rows. (Tasks 9–10: `test_failing_metric_records_error_and_others_score`, `test_leaderboard_ignores_error_scores`.)
5. **`hypothex.yaml` changes after runs exist (a task is removed, the repo is not a git repo, the repo moves).** Old runs still show with all their paths; evaluation against a removed task fails with a clear message; non-git repos run with empty git info. (Tasks 10–11, 13: `test_evaluate_removed_task_is_clear_error`, `test_non_git_repo_runs`, `test_show_run_paths_children_and_removed_task`.)

---

## File Structure

```
pyproject.toml                         # package, deps, ruff/pytest config, `hx` entry point
src/hypothex/
  __init__.py                          # public SDK re-exports
  _version.py                          # __version__
  metrics.py                           # Example, MetricResult, normalize_result (public contract)
  sdk.py                               # current(), seed(), Run, NoopRun
  eval_worker.py                       # runs inside project env: evaluate / describe
  core/
    __init__.py
    errors.py                          # HypothexError hierarchy
    layout.py                          # Layout, default_home
    ids.py                             # new_run_id, new_command_id, utcnow
    fsutil.py                          # atomic writes, yaml/jsonl io, notes
    config.py                          # hypothex.yaml models, templates, metric refs
    records.py                         # RunRecord, ScoreRecord, MetricPoint, enums
    store.py                           # RunStore (files), ProjectEntry, run_lock
    events.py                          # EventLog (SQLite): events + idempotent command receipts
    environment.py                     # EnvironmentDescriptor
    index.py                           # SQLAlchemy index, rebuild/repair
    gitinfo.py                         # git info, diff, worktrees
    envcapture.py                      # system/package/GPU capture
    datasets.py                        # fingerprints, cache, drift check, overlap
    evalrunner.py                      # host side of eval worker subprocess
    seeds.py                           # run fingerprint, config_hash, Stats, intervals
    leaderboard.py                     # Leaderboard building
    context.py                         # Context: open, find_record, update_run, add_score
    evaluation.py                      # evaluate_run, reeval, validate_project
    execution.py                       # RunRequest, prepare_run, execute_run
    control.py                         # launch_run, stop_run, rerun, reinfer, repair_runs
    supervisor.py                      # `python -m hypothex.core.supervisor <run_id>`
    queries.py                         # read models + curation
  cli/
    __init__.py
    main.py                            # Typer app, `cli()` entry
  api/
    __init__.py
    app.py                             # FastAPI app, WebSocket event stream
  mcp/
    __init__.py
    server.py                          # FastMCP tools
skills/hypothex/SKILL.md               # agent skill
examples/toy-classifier/               # E2E example project
docs/                                  # Sphinx
.github/workflows/ci.yml
tests/                                 # mirrors src
```

---

### Task 1: Package scaffold, errors, layout, ids, file utilities

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/hypothex/__init__.py`, `src/hypothex/_version.py`, `src/hypothex/core/__init__.py`, `src/hypothex/core/errors.py`, `src/hypothex/core/layout.py`, `src/hypothex/core/ids.py`, `src/hypothex/core/fsutil.py`
- Test: `tests/__init__.py`, `tests/core/__init__.py`, `tests/core/test_fsutil.py`, `tests/core/test_layout_ids.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `hypothex.core.errors`: `HypothexError(Exception)`, `ConfigError(HypothexError)`, `TemplateError(ConfigError)`, `StoreError(HypothexError)`, `RunNotFoundError(StoreError)`, `RunError(HypothexError)`, `EvalError(HypothexError)`, `NoPredictionsError(EvalError)`, `GitError(HypothexError)`.
  - `hypothex.core.layout`: `default_home() -> Path`; `Layout(home: Path)` with properties `store, index_db, events_db, environment_json, dataset_cache` and methods `project_dir(project) -> Path`, `runs_dir(project) -> Path`, `run_dir(project, run_id) -> Path`, `worktrees_dir(project) -> Path`, `ensure() -> None`.
  - `hypothex.core.ids`: `utcnow() -> datetime`, `new_run_id(task: str | None, now: datetime | None = None) -> str`, `new_command_id() -> str`.
  - `hypothex.core.fsutil`: `atomic_write_text(path, text) -> None`, `write_yaml(path, data: dict) -> None`, `read_yaml(path) -> dict`, `append_jsonl(path, obj: dict) -> None`, `read_jsonl(path) -> list[dict]`, `append_note_file(path, text, author, now=None) -> None`.

- [ ] **Step 1: Create the project files**

`pyproject.toml`:

```toml
[project]
name = "hypothex"
version = "0.1.0.dev0"
description = "Experiment tracker and control panel for AI researchers and their agents."
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
authors = [{ name = "Shreyas Vinaya Sathyanarayana", email = "shreyas.college@gmail.com" }]
dependencies = [
  "pydantic>=2.8",
  "pyyaml>=6.0",
  "typer>=0.12",
  "click>=8.2",
  "sqlalchemy>=2.0",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "psutil>=6.0",
  "xxhash>=3.4",
  "mcp>=1.10",
  "httpx>=0.27",
]

[project.urls]
Homepage = "https://github.com/hypothex/hypothex"

[project.scripts]
hx = "hypothex.cli.main:cli"

[dependency-groups]
dev = [
  "pytest>=8.3",
  "ruff>=0.6",
  "ty",
  "scikit-learn>=1.5",
  "sphinx>=8.0",
  "sphinx-rtd-theme>=3.0",
  "numpydoc>=1.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/hypothex"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
dist/
docs/_build/
.pytest_cache/
.ruff_cache/
examples/toy-classifier/data/
```

`src/hypothex/_version.py`:

```python
"""Package version."""

__version__ = "0.1.0.dev0"
```

`src/hypothex/__init__.py` (Task 14 extends this):

```python
"""Hypothex: experiment tracker and control panel for AI researchers and their agents."""

from hypothex._version import __version__

__all__ = ["__version__"]
```

`src/hypothex/core/__init__.py`, `tests/__init__.py`, `tests/core/__init__.py`: empty files.

`src/hypothex/core/errors.py`:

```python
"""Exception hierarchy for Hypothex."""


class HypothexError(Exception):
    """Base class for all expected Hypothex errors."""


class ConfigError(HypothexError):
    """``hypothex.yaml`` is missing or invalid."""


class TemplateError(ConfigError):
    """A command template cannot be rendered."""


class StoreError(HypothexError):
    """The file store is inconsistent or an entry is missing."""


class RunNotFoundError(StoreError):
    """No run with the given id exists."""


class RunError(HypothexError):
    """A run cannot be created, started, or controlled."""


class EvalError(HypothexError):
    """Evaluation of a run failed."""


class NoPredictionsError(EvalError):
    """The run has no ``predictions/predictions.jsonl`` file."""


class GitError(HypothexError):
    """A git operation failed."""
```

Run: `uv sync`
Expected: creates `.venv`, installs deps, exit 0.

- [ ] **Step 2: Write the failing tests**

`tests/core/test_fsutil.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_text,
    read_jsonl,
    read_yaml,
    write_yaml,
)


def test_atomic_write_replaces_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "a" / "file.txt"
    atomic_write_text(target, "one")
    atomic_write_text(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in target.parent.iterdir()] == ["file.txt"]


def test_read_jsonl_skips_partial_last_line(tmp_path: Path) -> None:
    path = tmp_path / "m.jsonl"
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"a": 2})
    with path.open("a") as fh:
        fh.write('{"a": 3')  # simulated crash mid-write
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_read_jsonl_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_yaml_roundtrip_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    write_yaml(path, {"b": 1, "a": [1, 2]})
    assert read_yaml(path) == {"b": 1, "a": [1, 2]}
    path.write_text("")
    assert read_yaml(path) == {}
    path.write_text("- 1\n- 2\n")
    with pytest.raises(ValueError, match="mapping"):
        read_yaml(path)


def test_append_note_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    when = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    append_note_file(path, "first", "alice", now=when)
    append_note_file(path, "second", "agent:claude", now=when)
    text = path.read_text()
    assert "## 2026-09-26T12:00:00+00:00 — alice" in text
    assert text.index("first") < text.index("second")
```

`tests/core/test_layout_ids.py`:

```python
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hypothex.core.ids import new_command_id, new_run_id
from hypothex.core.layout import Layout, default_home


def test_default_home_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HYPOTHEX_HOME", str(tmp_path / "h"))
    assert default_home() == tmp_path / "h"


def test_layout_paths(tmp_path: Path) -> None:
    lay = Layout(tmp_path)
    assert lay.run_dir("p", "r") == tmp_path / "store" / "p" / "runs" / "r"
    assert lay.worktrees_dir("p") == tmp_path / "store" / "p" / "worktrees"
    assert lay.index_db == tmp_path / "index.db"
    lay.ensure()
    assert lay.store.is_dir()


def test_new_run_id_format_and_uniqueness() -> None:
    when = datetime(2026, 9, 26, 14, 32, 5, tzinfo=UTC)
    rid = new_run_id("USPTO 50k Top-K!", now=when)
    assert re.fullmatch(r"20260926-143205-uspto-50k-top-k-[0-9a-f]{4}", rid)
    assert new_run_id(None, now=when).split("-")[2] == "explore"
    assert len({new_run_id("t", now=when) for _ in range(50)}) > 40
    assert re.fullmatch(r"[0-9a-f]{16}", new_command_id())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/core -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.fsutil'`.

- [ ] **Step 4: Implement layout, ids, fsutil**

`src/hypothex/core/layout.py`:

```python
"""Filesystem layout of a Hypothex home directory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_home() -> Path:
    """
    Return the Hypothex home directory.

    Returns
    -------
    Path
        ``$HYPOTHEX_HOME`` if set, else ``~/.hypothex``.
    """
    return Path(os.environ.get("HYPOTHEX_HOME", str(Path.home() / ".hypothex"))).expanduser()


@dataclass(frozen=True)
class Layout:
    """
    Paths inside one Hypothex home directory.

    Parameters
    ----------
    home : Path
        Root directory, e.g. ``~/.hypothex``.
    """

    home: Path

    @property
    def store(self) -> Path:
        """Directory holding all project and run folders."""
        return self.home / "store"

    @property
    def index_db(self) -> Path:
        """SQLite index path."""
        return self.home / "index.db"

    @property
    def events_db(self) -> Path:
        """SQLite event log path."""
        return self.home / "events.db"

    @property
    def environment_json(self) -> Path:
        """Stable environment identity file."""
        return self.home / "environment.json"

    @property
    def dataset_cache(self) -> Path:
        """Dataset fingerprint cache file."""
        return self.home / "dataset_cache.json"

    def project_dir(self, project: str) -> Path:
        """Return the folder for one project."""
        return self.store / project

    def runs_dir(self, project: str) -> Path:
        """Return the folder holding a project's runs."""
        return self.project_dir(project) / "runs"

    def run_dir(self, project: str, run_id: str) -> Path:
        """Return the folder of one run."""
        return self.runs_dir(project) / run_id

    def worktrees_dir(self, project: str) -> Path:
        """Return the folder holding git worktrees created for reruns."""
        return self.project_dir(project) / "worktrees"

    def ensure(self) -> None:
        """Create the home and store directories if missing."""
        self.store.mkdir(parents=True, exist_ok=True)
```

`src/hypothex/core/ids.py`:

```python
"""Identifier and clock helpers."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

_SLUG = re.compile(r"[^a-z0-9]+")


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def new_run_id(task: str | None, now: datetime | None = None) -> str:
    """
    Create a sortable, human-readable run id.

    Parameters
    ----------
    task : str or None
        Task name used as a slug; ``None`` gives ``explore``.
    now : datetime, optional
        Timestamp to embed (UTC). Defaults to now.

    Returns
    -------
    str
        ``YYYYMMDD-HHMMSS-<slug>-<4 hex>``.

    Examples
    --------
    >>> new_run_id("toy-test").count("-") >= 3
    True
    """
    stamp = (now or utcnow()).strftime("%Y%m%d-%H%M%S")
    slug = _SLUG.sub("-", (task or "explore").lower()).strip("-")[:16].strip("-") or "run"
    return f"{stamp}-{slug}-{secrets.token_hex(2)}"


def new_command_id() -> str:
    """Return a random id used to make commands idempotent."""
    return secrets.token_hex(8)
```

`src/hypothex/core/fsutil.py`:

```python
"""Small, crash-safe file helpers."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from hypothex.core.ids import utcnow


def atomic_write_text(path: Path, text: str) -> None:
    """
    Write text so readers never see a partial file.

    Parameters
    ----------
    path : Path
        Destination file. Parent directories are created.
    text : str
        Full file content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write a mapping as YAML, keeping key order."""
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def read_yaml(path: Path) -> dict[str, Any]:
    """
    Read a YAML file whose top level is a mapping.

    Returns
    -------
    dict
        Parsed mapping; ``{}`` for an empty file.

    Raises
    ------
    ValueError
        If the top level is not a mapping.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    """Append one JSON object as a line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, default=str, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    Read a JSONL file, skipping blank, malformed, and partial lines.

    Returns
    -------
    list of dict
        Parsed objects; ``[]`` if the file does not exist.
    """
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def append_note_file(path: Path, text: str, author: str, now: datetime | None = None) -> None:
    """
    Append a timestamped note section to a Markdown file.

    Parameters
    ----------
    path : Path
        ``notes.md`` path.
    text : str
        Note body (Markdown).
    author : str
        Who wrote it, e.g. ``human`` or ``agent:claude``.
    now : datetime, optional
        Timestamp; defaults to now.
    """
    stamp = (now or utcnow()).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## {stamp} — {author}\n\n{text.strip()}\n")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core -v && uv run ruff check . && uv run ruff format --check .`
Expected: all PASS, ruff clean (run `uv run ruff format .` first if format check fails).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src tests
git commit -m "feat: package scaffold, layout, ids, crash-safe file helpers"
```

---

### Task 2: Project file (`hypothex.yaml`) models and templates

**Files:**
- Create: `src/hypothex/core/config.py`
- Test: `tests/core/test_config.py`

**Interfaces:**
- Consumes: `hypothex.core.errors.ConfigError, TemplateError`; `hypothex.core.fsutil.read_yaml`.
- Produces (`hypothex.core.config`):
  - `CONFIG_FILENAME = "hypothex.yaml"`, `BUILTIN_TEMPLATE_VARS: frozenset[str]`.
  - `template_fields(template: str) -> set[str]`, `render_template(template: str, values: dict[str, str]) -> str`.
  - `parse_metric_key(ref: str) -> tuple[str, str]` (`"topk/k=1"` → `("topk","k=1")`, `"acc"` → `("acc","value")`).
  - `parse_metric_version(ref: str) -> tuple[str, str | None]` (`"topk@v2"` → `("topk","v2")`).
  - Models: `DatasetSpec(version, path, host="local", description, splits: dict[str,str], id_field="id", reference_field="reference")` with `path_for(split: str | None) -> str`; `MetricSpec(version, fn, higher_is_better=True, params: dict, changelog: dict)`; `TaskSpec(dataset, split=None, metrics: list[str], primary, description)`; `EnvSpec(setup=None, python: list[str] | None=None)`; `ProjectConfig(project, description, datasets, metrics, tasks, stages: dict[str,str], env)`.
  - `load_project_config(repo: Path) -> ProjectConfig`, `find_repo_root(start: Path) -> Path`, `starter_config(project: str) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_config.py`:

```python
from pathlib import Path

import pytest

from hypothex.core.config import (
    CONFIG_FILENAME,
    find_repo_root,
    load_project_config,
    parse_metric_key,
    parse_metric_version,
    render_template,
    starter_config,
    template_fields,
)
from hypothex.core.errors import ConfigError, TemplateError

VALID = """
project: deepretro
datasets:
  uspto50k:
    version: v1
    path: data/test.jsonl
    splits: {train: data/train.jsonl, test: data/test.jsonl}
metrics:
  topk:
    version: v2
    fn: deepretro.eval:topk
    params: {k: [1, 5]}
tasks:
  uspto-topk:
    dataset: uspto50k
    split: test
    metrics: [topk]
    primary: topk/k=1
stages:
  infer: python infer.py --ckpt {checkpoint} --out {run_dir}/predictions --beam {beam}
"""


def _write(tmp_path: Path, text: str) -> Path:
    (tmp_path / CONFIG_FILENAME).write_text(text)
    return tmp_path


def test_valid_config_loads(tmp_path: Path) -> None:
    cfg = load_project_config(_write(tmp_path, VALID))
    assert cfg.project == "deepretro"
    assert cfg.metrics["topk"].version == "v2"
    assert cfg.datasets["uspto50k"].path_for("test") == "data/test.jsonl"
    assert cfg.datasets["uspto50k"].path_for(None) == "data/test.jsonl"
    with pytest.raises(ConfigError, match="no split"):
        cfg.datasets["uspto50k"].path_for("valid")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("dataset: uspto50k", "dataset: missing", "unknown dataset"),
        ("metrics: [topk]", "metrics: [nope]", "unknown metric"),
        ("primary: topk/k=1", "primary: other/k=1", "primary"),
        ("split: test", "split: valid", "no split"),
        ("project: deepretro", "project: Deep Retro", "project"),
    ],
)
def test_invalid_configs_raise(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_project_config(_write(tmp_path, VALID.replace(old, new)))


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="extra"):
        load_project_config(_write(tmp_path, VALID + "\nbogus: 1\n"))


def test_missing_file_mentions_init(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="hx init"):
        load_project_config(tmp_path)


def test_templates() -> None:
    tpl = "python x.py --out {run_dir}/p --data {dataset.path} --beam {beam}"
    assert template_fields(tpl) == {"run_dir", "dataset.path", "beam"}
    out = render_template(tpl, {"run_dir": "/r", "dataset.path": "/d", "beam": "5"})
    assert out == "python x.py --out /r/p --data /d --beam 5"
    with pytest.raises(TemplateError, match="beam"):
        render_template(tpl, {"run_dir": "/r", "dataset.path": "/d"})


def test_metric_ref_parsing() -> None:
    assert parse_metric_key("topk/k=1") == ("topk", "k=1")
    assert parse_metric_key("acc") == ("acc", "value")
    assert parse_metric_version("topk@v2") == ("topk", "v2")
    assert parse_metric_version("topk") == ("topk", None)


def test_find_repo_root_walks_up(tmp_path: Path) -> None:
    _write(tmp_path, VALID)
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert find_repo_root(deep) == tmp_path.resolve()
    with pytest.raises(ConfigError):
        find_repo_root(Path("/"))


def test_starter_config_is_valid(tmp_path: Path) -> None:
    cfg = load_project_config(_write(tmp_path, starter_config("my-proj")))
    assert cfg.project == "my-proj"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.config'`.

- [ ] **Step 3: Implement `config.py`**

```python
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

    Examples
    --------
    >>> parse_metric_version("topk@v2")
    ('topk', 'v2')
    """
    name, sep, version = ref.partition("@")
    return name, (version if sep else None)


class _Strict(BaseModel):
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
        errors: list[str] = []
        for name, task in self.tasks.items():
            if not re.match(NAME_PATTERN, name):
                errors.append(f"task name {name!r} must match {NAME_PATTERN}")
            dataset = self.datasets.get(task.dataset)
            if dataset is None:
                errors.append(f"task {name!r}: unknown dataset {task.dataset!r}")
            elif task.split is not None and task.split not in dataset.splits:
                errors.append(f"task {name!r}: dataset {task.dataset!r} has no split {task.split!r}")
            errors.extend(
                f"task {name!r}: unknown metric {m!r}" for m in task.metrics if m not in self.metrics
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
    """Return the text of a commented starter ``hypothex.yaml``."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_config.py -v`
Expected: PASS. (Pydantic's message for forbidden keys contains "Extra inputs are not permitted" — the `match="extra"` test is case-sensitive; if it fails, change the test to `match="(?i)extra"`.)

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/config.py tests/core/test_config.py
git commit -m "feat: hypothex.yaml models, templates, metric refs"
```

---

### Task 3: Run records and the file store

**Files:**
- Create: `src/hypothex/core/records.py`, `src/hypothex/core/store.py`
- Create: `tests/factories.py` (shared test helpers; later tasks add to it)
- Test: `tests/core/test_store.py`

**Interfaces:**
- Consumes: Task 1 (`Layout`, `fsutil`, `utcnow`, errors), Task 2 (`ProjectConfig`).
- Produces:
  - `hypothex.core.records`: `RunStatus(StrEnum)` = `queued|running|finished|failed|killed|lost`; `ACTIVE_STATUSES`, `TERMINAL_STATUSES` (frozensets); `RunKind(StrEnum)` = `full|infer`; models `GitInfo(repo, commit, branch, dirty)`, `DatasetRef(name, version, split, host, path, hash, hash_mode, size, checked_at)`, `Artifact(kind, path, host="local", size)`, `ExecutorInfo(type="local", pid, pid_create_time, child_pid)`, `RunRecord(...)` (fields below), `ScoreRecord(metric, version, key, value, error, source_hash, created_at)`, `MetricPoint(name, step, value, t)`.
  - `tests/factories.py`: `make_record(run_id="r1", project="toy", **overrides) -> RunRecord`.
  - `hypothex.core.store`: `ProjectEntry(project, repo, config, registered_at)`; `run_lock(run_dir: Path) -> ContextManager[None]`; `RunStore(layout)` with `register_project(config, repo) -> ProjectEntry`, `load_project(project) -> ProjectEntry`, `list_projects() -> list[ProjectEntry]`, `create_run(record) -> Path`, `write_record(record) -> None`, `read_record(project, run_id) -> RunRecord`, `iter_records(project=None) -> Iterator[RunRecord]`, `list_run_ids() -> dict[str, str]` (run_id → project), `find_project_of(run_id) -> str`, `append_score(project, run_id, score) -> None`, `read_scores(project, run_id) -> list[ScoreRecord]`, `read_metric_points(project, run_id) -> list[MetricPoint]`, `read_artifacts(project, run_id) -> list[Artifact]`, `append_note(project, run_id, text, author) -> None`, `read_notes(project, run_id) -> str`, `metric_hashes(project) -> dict[str, str]`, `save_metric_hashes(project, hashes) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/factories.py`:

```python
"""Shared builders for tests."""

from __future__ import annotations

from typing import Any

from hypothex.core.ids import utcnow
from hypothex.core.records import RunRecord, RunStatus


def make_record(run_id: str = "r1", project: str = "toy", **overrides: Any) -> RunRecord:
    """Build a valid RunRecord with sensible defaults."""
    base: dict[str, Any] = {
        "run_id": run_id,
        "project": project,
        "task": "t",
        "command": ["echo", "hi"],
        "command_template": ["echo", "hi"],
        "cwd": "/tmp",
        "environment_id": "env1",
        "host": "mac",
        "config_hash": "sha256:abc",
        "status": RunStatus.QUEUED,
        "created_at": utcnow(),
    }
    base.update(overrides)
    return RunRecord.model_validate(base)
```

`tests/core/test_store.py`:

```python
from pathlib import Path

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import RunNotFoundError, StoreError
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import ScoreRecord
from hypothex.core.store import RunStore
from tests.factories import make_record


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    layout = Layout(tmp_path)
    layout.ensure()
    return RunStore(layout)


def test_register_and_load_project(store: RunStore, tmp_path: Path) -> None:
    cfg = ProjectConfig(project="toy")
    entry = store.register_project(cfg, tmp_path)
    assert entry.repo == str(tmp_path.resolve())
    assert store.load_project("toy").config.project == "toy"
    assert [e.project for e in store.list_projects()] == ["toy"]
    with pytest.raises(StoreError, match="unknown project"):
        store.load_project("nope")


def test_create_read_and_duplicate(store: RunStore) -> None:
    record = make_record()
    run_dir = store.create_run(record)
    for sub in ("logs", "predictions", "env"):
        assert (run_dir / sub).is_dir()
    assert store.read_record("toy", "r1") == record
    with pytest.raises(StoreError, match="exists"):
        store.create_run(record)


def test_iter_records_skips_broken_dirs(store: RunStore) -> None:
    store.create_run(make_record("r1"))
    store.create_run(make_record("r2"))
    (store.layout.runs_dir("toy") / "empty").mkdir()
    (store.layout.run_dir("toy", "r2") / "run.yaml").write_text("{not: [valid")
    assert [r.run_id for r in store.iter_records()] == ["r1"]
    assert store.list_run_ids() == {"r1": "toy", "r2": "toy"}


def test_find_project_of(store: RunStore) -> None:
    store.create_run(make_record("r9", project="other"))
    assert store.find_project_of("r9") == "other"
    with pytest.raises(RunNotFoundError):
        store.find_project_of("missing")


def test_scores_points_artifacts_notes(store: RunStore) -> None:
    store.create_run(make_record())
    run_dir = store.layout.run_dir("toy", "r1")
    score = ScoreRecord(metric="acc", version="v1", key="value", value=0.5, created_at=utcnow())
    store.append_score("toy", "r1", score)
    assert store.read_scores("toy", "r1") == [score]
    append_jsonl(run_dir / "metrics.jsonl", {"name": "loss", "step": 0, "value": 1.5, "t": 1.0})
    append_jsonl(run_dir / "metrics.jsonl", {"name": "loss", "value": "bad"})
    assert [p.value for p in store.read_metric_points("toy", "r1")] == [1.5]
    append_jsonl(run_dir / "artifacts.jsonl", {"kind": "checkpoint", "path": "/m.pt"})
    assert store.read_artifacts("toy", "r1")[0].kind == "checkpoint"
    store.append_note("toy", "r1", "looks good", "alice")
    assert "looks good" in store.read_notes("toy", "r1")


def test_metric_hashes_roundtrip(store: RunStore) -> None:
    assert store.metric_hashes("toy") == {}
    store.save_metric_hashes("toy", {"acc@v1": "sha256:1"})
    assert store.metric_hashes("toy") == {"acc@v1": "sha256:1"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.records'`.

- [ ] **Step 3: Implement `records.py`**

```python
"""Pydantic models for everything stored in a run folder."""

from __future__ import annotations

import shlex
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    """Lifecycle state of a run."""

    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    KILLED = "killed"
    LOST = "lost"


ACTIVE_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})
TERMINAL_STATUSES = frozenset(
    {RunStatus.FINISHED, RunStatus.FAILED, RunStatus.KILLED, RunStatus.LOST}
)


class RunKind(StrEnum):
    """What a run executes."""

    FULL = "full"
    INFER = "infer"


class GitInfo(BaseModel):
    """Git state of the working copy a run was launched from."""

    repo: str | None = None
    commit: str | None = None
    branch: str | None = None
    dirty: bool = False


class DatasetRef(BaseModel):
    """The exact dataset a run used, with its fingerprint at launch."""

    name: str
    version: str
    split: str | None = None
    host: str = "local"
    path: str
    hash: str | None = None
    hash_mode: str | None = None
    size: int | None = None
    checked_at: datetime | None = None


class Artifact(BaseModel):
    """A large file recorded by path, not copied."""

    kind: str
    path: str
    host: str = "local"
    size: int | None = None


class ExecutorInfo(BaseModel):
    """How the run's process is supervised."""

    type: str = "local"
    pid: int | None = None
    pid_create_time: float | None = None
    child_pid: int | None = None


class RunRecord(BaseModel):
    """All facts about one run; stored as ``run.yaml``."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    project: str
    task: str | None = None
    hypothesis: str = ""
    kind: RunKind = RunKind.FULL
    parent: str | None = None
    stage: str | None = None
    command: list[str]
    command_template: list[str]
    vars: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    cwd: str
    environment_id: str
    host: str
    executor: ExecutorInfo = Field(default_factory=ExecutorInfo)
    git: GitInfo = Field(default_factory=GitInfo)
    datasets: list[DatasetRef] = Field(default_factory=list)
    seed: int | None = None
    config_hash: str
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    exit_code: int | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    starred: bool = False
    archived: bool = False
    created_by: str = "human"

    @property
    def command_display(self) -> str:
        """The command as one shell-quoted string."""
        return shlex.join(self.command)


class ScoreRecord(BaseModel):
    """One value of one metric version for one run; stored in ``scores.jsonl``."""

    metric: str
    version: str
    key: str
    value: float | None = None
    error: str | None = None
    source_hash: str | None = None
    created_at: datetime


class MetricPoint(BaseModel):
    """One step of a logged metric history; stored in ``metrics.jsonl``."""

    name: str
    step: int
    value: float
    t: float | None = None
```

- [ ] **Step 4: Implement `store.py`**

```python
"""The file store: projects and run folders are the source of truth."""

from __future__ import annotations

import fcntl
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import RunNotFoundError, StoreError
from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_text,
    read_jsonl,
    read_yaml,
    write_yaml,
)
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import Artifact, MetricPoint, RunRecord, ScoreRecord

log = logging.getLogger(__name__)
_M = TypeVar("_M", bound=BaseModel)

RUN_SUBDIRS = ("logs", "predictions", "env")


class ProjectEntry(BaseModel):
    """A registered project: its repo path and a snapshot of its config."""

    project: str
    repo: str
    config: ProjectConfig
    registered_at: datetime


@contextmanager
def run_lock(run_dir: Path) -> Iterator[None]:
    """
    Hold an exclusive, cross-process lock on one run folder.

    Parameters
    ----------
    run_dir : Path
        The run folder; ``.lock`` is created inside it.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / ".lock").open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class RunStore:
    """
    Read and write projects and runs under ``<home>/store``.

    Parameters
    ----------
    layout : Layout
        Home directory layout.
    """

    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    # projects -----------------------------------------------------------
    def _project_file(self, project: str) -> Path:
        return self.layout.project_dir(project) / "project.json"

    def register_project(self, config: ProjectConfig, repo: Path) -> ProjectEntry:
        """
        Record (or refresh) a project's repo path and config snapshot.

        Returns
        -------
        ProjectEntry
            The stored entry. The latest registration wins.
        """
        entry = ProjectEntry(
            project=config.project,
            repo=str(repo.resolve()),
            config=config,
            registered_at=utcnow(),
        )
        atomic_write_text(self._project_file(config.project), entry.model_dump_json(indent=2))
        return entry

    def load_project(self, project: str) -> ProjectEntry:
        """Load a registered project or raise ``StoreError``."""
        path = self._project_file(project)
        if not path.is_file():
            raise StoreError(f"unknown project {project!r}")
        return ProjectEntry.model_validate_json(path.read_text(encoding="utf-8"))

    def list_projects(self) -> list[ProjectEntry]:
        """Return all registered projects, sorted by name."""
        if not self.layout.store.is_dir():
            return []
        entries = []
        for path in sorted(self.layout.store.glob("*/project.json")):
            try:
                entries.append(ProjectEntry.model_validate_json(path.read_text(encoding="utf-8")))
            except ValidationError:
                log.warning("skipping unreadable project file %s", path)
        return entries

    # runs ---------------------------------------------------------------
    def create_run(self, record: RunRecord) -> Path:
        """
        Create a new run folder and its ``run.yaml``.

        Raises
        ------
        StoreError
            If the run folder already exists.
        """
        run_dir = self.layout.run_dir(record.project, record.run_id)
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise StoreError(f"run folder already exists: {run_dir}") from exc
        for sub in RUN_SUBDIRS:
            (run_dir / sub).mkdir()
        self.write_record(record)
        return run_dir

    def write_record(self, record: RunRecord) -> None:
        """Atomically write ``run.yaml``. Callers must hold ``run_lock``."""
        path = self.layout.run_dir(record.project, record.run_id) / "run.yaml"
        write_yaml(path, record.model_dump(mode="json"))

    def read_record(self, project: str, run_id: str) -> RunRecord:
        """Read ``run.yaml`` or raise ``RunNotFoundError``."""
        path = self.layout.run_dir(project, run_id) / "run.yaml"
        if not path.is_file():
            raise RunNotFoundError(f"no run {run_id!r} in project {project!r}")
        return RunRecord.model_validate(read_yaml(path))

    def iter_records(self, project: str | None = None) -> Iterator[RunRecord]:
        """Yield every readable run record; unreadable folders are logged and skipped."""
        if project is not None:
            projects = [project]
        elif self.layout.store.is_dir():
            projects = sorted(p.name for p in self.layout.store.iterdir() if p.is_dir())
        else:
            projects = []
        for name in projects:
            runs_dir = self.layout.runs_dir(name)
            if not runs_dir.is_dir():
                continue
            for run_dir in sorted(runs_dir.iterdir()):
                path = run_dir / "run.yaml"
                if not path.is_file():
                    continue
                try:
                    yield RunRecord.model_validate(read_yaml(path))
                except Exception:  # noqa: BLE001 - a corrupt file must not stop listing
                    log.warning("skipping unreadable run file %s", path)

    def list_run_ids(self) -> dict[str, str]:
        """Map every run id that has a ``run.yaml`` to its project."""
        found: dict[str, str] = {}
        for path in self.layout.store.glob("*/runs/*/run.yaml"):
            found[path.parent.name] = path.parent.parent.parent.name
        return found

    def find_project_of(self, run_id: str) -> str:
        """Return the project owning ``run_id`` or raise ``RunNotFoundError``."""
        for path in self.layout.store.glob(f"*/runs/{run_id}/run.yaml"):
            return path.parent.parent.parent.name
        raise RunNotFoundError(f"no run {run_id!r}")

    # run contents ---------------------------------------------------------
    def append_score(self, project: str, run_id: str, score: ScoreRecord) -> None:
        """Append one score to ``scores.jsonl``."""
        append_jsonl(self.layout.run_dir(project, run_id) / "scores.jsonl",
                     score.model_dump(mode="json"))

    def read_scores(self, project: str, run_id: str) -> list[ScoreRecord]:
        """Read all scores, oldest first, skipping malformed rows."""
        return _parse_rows(ScoreRecord, self.layout.run_dir(project, run_id) / "scores.jsonl")

    def read_metric_points(self, project: str, run_id: str) -> list[MetricPoint]:
        """Read the logged metric history, skipping malformed rows."""
        return _parse_rows(MetricPoint, self.layout.run_dir(project, run_id) / "metrics.jsonl")

    def read_artifacts(self, project: str, run_id: str) -> list[Artifact]:
        """Read artifacts logged by the SDK."""
        return _parse_rows(Artifact, self.layout.run_dir(project, run_id) / "artifacts.jsonl")

    def append_note(self, project: str, run_id: str, text: str, author: str) -> None:
        """Append a note to the run's ``notes.md``."""
        append_note_file(self.layout.run_dir(project, run_id) / "notes.md", text, author)

    def read_notes(self, project: str, run_id: str) -> str:
        """Return the run's notes, or an empty string."""
        path = self.layout.run_dir(project, run_id) / "notes.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    # metric source hashes ----------------------------------------------------
    def metric_hashes(self, project: str) -> dict[str, str]:
        """Return first-seen source hashes keyed by ``name@version``."""
        path = self.layout.project_dir(project) / "metric_hashes.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def save_metric_hashes(self, project: str, hashes: dict[str, str]) -> None:
        """Persist metric source hashes."""
        atomic_write_text(self.layout.project_dir(project) / "metric_hashes.json",
                          json.dumps(hashes, indent=2, sort_keys=True))


def _parse_rows(model: type[_M], path: Path) -> list[_M]:
    rows: list[_M] = []
    for raw in read_jsonl(path):
        try:
            rows.append(model.model_validate(raw))
        except ValidationError:
            continue
    return rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_store.py -v && uv run ruff check src tests`
Expected: PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/records.py src/hypothex/core/store.py tests/factories.py tests/core/test_store.py
git commit -m "feat: run records and file store with per-run lock"
```

---
### Task 4: Event log, idempotent commands, environment descriptor

**Files:**
- Create: `src/hypothex/core/events.py`, `src/hypothex/core/environment.py`
- Test: `tests/core/test_events.py`

**Interfaces:**
- Consumes: Task 1 (`Layout`, `utcnow`, `atomic_write_text`), `hypothex._version.__version__`.
- Produces:
  - `hypothex.core.events`: `Event(sequence: int, type: str, project: str | None, run_id: str | None, payload: dict, created_at: datetime)`; `CommandTimeoutError(RuntimeError)`; `EventLog(path: Path)` with `append(type_: str, *, project=None, run_id=None, payload=None) -> Event`, `since(after_sequence: int, limit: int = 1000) -> list[Event]`, `last_sequence() -> int`, `run_once(command_id: str | None, fn: Callable[[], dict]) -> dict`.
  - `hypothex.core.environment`: `PROTOCOL_VERSION = 1`, `CAPABILITIES: tuple[str, ...]`, `EnvironmentDescriptor(environment_id, label, kind, os, arch, hostname, hx_version, protocol_version, gpus, capabilities)`, `count_gpus() -> int`, `load_descriptor(layout: Layout) -> EnvironmentDescriptor`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_events.py`:

```python
import threading
import time
from pathlib import Path

import pytest

from hypothex.core.environment import PROTOCOL_VERSION, load_descriptor
from hypothex.core.events import EventLog
from hypothex.core.layout import Layout


def test_append_and_since(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.db")
    a = log.append("run.created", project="p", run_id="r1", payload={"status": "queued"})
    b = log.append("run.started", project="p", run_id="r1")
    assert b.sequence == a.sequence + 1
    assert [e.type for e in log.since(0)] == ["run.created", "run.started"]
    assert [e.sequence for e in log.since(a.sequence)] == [b.sequence]
    assert log.last_sequence() == b.sequence
    assert log.since(0)[0].payload == {"status": "queued"}


def test_two_handles_share_one_log(tmp_path: Path) -> None:
    one = EventLog(tmp_path / "e.db")
    two = EventLog(tmp_path / "e.db")
    one.append("x")
    assert [e.type for e in two.since(0)] == ["x"]


def test_run_once_is_idempotent(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")
    calls: list[int] = []

    def fn() -> dict:
        calls.append(1)
        return {"run_id": f"r{len(calls)}"}

    assert log.run_once("cmd-1", fn) == {"run_id": "r1"}
    assert log.run_once("cmd-1", fn) == {"run_id": "r1"}
    assert log.run_once(None, fn) == {"run_id": "r2"}
    assert len(calls) == 2


def test_run_once_releases_claim_on_failure(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")

    def boom() -> dict:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        log.run_once("c", boom)
    assert log.run_once("c", lambda: {"ok": True}) == {"ok": True}


def test_run_once_concurrent_same_command_runs_once(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")
    calls: list[int] = []
    results: list[dict] = []

    def slow() -> dict:
        calls.append(1)
        time.sleep(0.3)
        return {"n": len(calls)}

    threads = [
        threading.Thread(target=lambda: results.append(log.run_once("same", slow)))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert results == [{"n": 1}] * 4


def test_descriptor_is_stable(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    layout.ensure()
    first = load_descriptor(layout)
    second = load_descriptor(layout)
    assert first.environment_id == second.environment_id
    assert len(first.environment_id) == 32
    assert first.protocol_version == PROTOCOL_VERSION == 1
    assert first.kind == "local"
    assert "reeval" in first.capabilities
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.events'`.

- [ ] **Step 3: Implement `events.py`**

```python
"""Per-environment event log and idempotent command receipts (SQLite)."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hypothex.core.ids import utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  project TEXT,
  run_id TEXT,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
  command_id TEXT PRIMARY KEY,
  result TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""
_PENDING = "__pending__"


class Event(BaseModel):
    """One entry of the event log."""

    sequence: int
    type: str
    project: str | None = None
    run_id: str | None = None
    payload: dict[str, Any]
    created_at: datetime


class CommandTimeoutError(RuntimeError):
    """A duplicate command waited too long for the first one to finish."""


class EventLog:
    """
    Append-only event log with monotonically increasing sequence numbers.

    Safe to use from several processes at once (SQLite WAL + busy timeout).

    Parameters
    ----------
    path : Path
        SQLite file, e.g. ``~/.hypothex/events.db``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def append(
        self,
        type_: str,
        *,
        project: str | None = None,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        """
        Append one event.

        Returns
        -------
        Event
            The stored event with its sequence number.
        """
        now = utcnow()
        body = payload or {}
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO events(type, project, run_id, payload, created_at) VALUES (?,?,?,?,?)",
                (type_, project, run_id, json.dumps(body, default=str), now.isoformat()),
            )
            sequence = int(cur.lastrowid or 0)
        return Event(sequence=sequence, type=type_, project=project, run_id=run_id,
                     payload=json.loads(json.dumps(body, default=str)), created_at=now)

    def since(self, after_sequence: int, limit: int = 1000) -> list[Event]:
        """Return events with ``sequence > after_sequence`` in order."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE sequence > ? ORDER BY sequence LIMIT ?",
                (after_sequence, limit),
            ).fetchall()
        return [
            Event(sequence=r["sequence"], type=r["type"], project=r["project"],
                  run_id=r["run_id"], payload=json.loads(r["payload"]),
                  created_at=datetime.fromisoformat(r["created_at"]))
            for r in rows
        ]

    def last_sequence(self) -> int:
        """Return the highest sequence number, or 0 when empty."""
        with self._conn() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM events").fetchone()[0])

    def run_once(self, command_id: str | None, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """
        Run ``fn`` at most once per ``command_id`` and return its stored result.

        A second caller with the same id waits for the first result. If ``fn``
        raises, the claim is released so the command can be retried.

        Parameters
        ----------
        command_id : str or None
            Client-generated id; ``None`` disables idempotency.
        fn : callable
            Work to do; must return a JSON-serialisable dict.

        Returns
        -------
        dict
            Result of the first successful call.
        """
        if command_id is None:
            return fn()
        with self._conn() as conn:
            claimed = conn.execute(
                "INSERT OR IGNORE INTO receipts(command_id, result, created_at) VALUES (?,?,?)",
                (command_id, _PENDING, utcnow().isoformat()),
            ).rowcount == 1
        if not claimed:
            return self._wait_for_result(command_id)
        try:
            result = fn()
        except BaseException:
            with self._conn() as conn:
                conn.execute("DELETE FROM receipts WHERE command_id = ?", (command_id,))
            raise
        with self._conn() as conn:
            conn.execute("UPDATE receipts SET result = ? WHERE command_id = ?",
                         (json.dumps(result, default=str), command_id))
        return json.loads(json.dumps(result, default=str))

    def _wait_for_result(self, command_id: str, timeout: float = 60.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._conn() as conn:
                row = conn.execute("SELECT result FROM receipts WHERE command_id = ?",
                                   (command_id,)).fetchone()
            if row is None:
                raise CommandTimeoutError(f"command {command_id} failed in another caller; retry")
            if row["result"] != _PENDING:
                return json.loads(row["result"])
            time.sleep(0.05)
        raise CommandTimeoutError(f"command {command_id} is still running after {timeout}s")
```

Note on the concurrent test: all four threads return the JSON round-tripped result, so the first caller's `{"n": 1}` equals the waiters' `{"n": 1}`.

- [ ] **Step 4: Implement `environment.py`**

```python
"""Identity and capabilities of this Hypothex environment."""

from __future__ import annotations

import json
import platform
import socket
import subprocess
import uuid

from pydantic import BaseModel

from hypothex._version import __version__
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.layout import Layout

PROTOCOL_VERSION = 1
CAPABILITIES = ("run", "launch", "stop", "rerun", "reinfer", "reeval", "events-ws")


class EnvironmentDescriptor(BaseModel):
    """What ``GET /.well-known/hypothex/environment`` returns."""

    environment_id: str
    label: str
    kind: str = "local"
    os: str
    arch: str
    hostname: str
    hx_version: str
    protocol_version: int
    gpus: int
    capabilities: list[str]


def count_gpus() -> int:
    """Return the number of NVIDIA GPUs visible to ``nvidia-smi``, or 0."""
    try:
        out = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if out.returncode != 0:
        return 0
    return sum(1 for line in out.stdout.splitlines() if line.startswith("GPU "))


def load_descriptor(layout: Layout) -> EnvironmentDescriptor:
    """
    Load this environment's descriptor, creating a stable id on first use.

    Parameters
    ----------
    layout : Layout
        Home layout; the id lives in ``environment.json``.

    Returns
    -------
    EnvironmentDescriptor
        Descriptor with the persisted id and label and live system facts.
    """
    path = layout.environment_json
    if path.is_file():
        identity = json.loads(path.read_text(encoding="utf-8"))
    else:
        identity = {"environment_id": uuid.uuid4().hex, "label": socket.gethostname()}
        atomic_write_text(path, json.dumps(identity, indent=2))
    return EnvironmentDescriptor(
        environment_id=identity["environment_id"],
        label=identity["label"],
        os=platform.system().lower(),
        arch=platform.machine(),
        hostname=socket.gethostname(),
        hx_version=__version__,
        protocol_version=PROTOCOL_VERSION,
        gpus=count_gpus(),
        capabilities=list(CAPABILITIES),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_events.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/events.py src/hypothex/core/environment.py tests/core/test_events.py
git commit -m "feat: event log with idempotent command receipts and environment descriptor"
```

---

### Task 5: Rebuildable SQLite index

**Files:**
- Create: `src/hypothex/core/index.py`
- Test: `tests/core/test_index.py`

**Interfaces:**
- Consumes: Task 3 (`RunRecord`, `RunStatus`, `ScoreRecord`, `MetricPoint`, `ProjectEntry`, `RunStore`), `tests/factories.make_record`.
- Produces (`hypothex.core.index`):
  - `SCHEMA_VERSION = 1`, `MAX_POINTS_PER_METRIC = 1000`, `downsample(points, limit=MAX_POINTS_PER_METRIC) -> list[MetricPoint]`.
  - `Index(path: Path, store: RunStore | None = None)` (audit 2026-10-04: `store` lets `metric_points` read a run's points that a rebuild skipped; `rebuilt_schema` now means "new file or old schema: rebuild before use", and an old index is left intact until `rebuild_index` replaces it; extra methods `schema_version() -> str | None`, `generation() -> int`, `child_run_ids(run_id) -> list[str]`, `count_runs(...) -> int`, `list_runs(..., before=(created_at, run_id))`, `metric_points_for(run_ids, names=None) -> dict[str, list[MetricPoint]]`, `mark_scores_stale(run_id)`, `stale_score_runs() -> list[str]`) with attribute `rebuilt_schema: bool` and methods `clear()`, `upsert_project(entry)`, `list_projects() -> list[ProjectEntry]`, `get_project(name) -> ProjectEntry | None`, `upsert_run(record)`, `get_run(run_id) -> RunRecord | None`, `list_runs(*, project=None, task=None, status=None, tag=None, include_archived=False, limit: int | None = 500) -> list[RunRecord]` (newest first), `run_ids() -> set[str]`, `add_score(run_id, score)`, `replace_scores(run_id, scores)`, `scores_for(run_ids) -> dict[str, list[ScoreRecord]]` (oldest first per run), `replace_metric_points(run_id, points)`, `metric_points(run_id) -> list[MetricPoint]`.
  - `index_run(index, store, record) -> None`, `rebuild_index(index, store) -> int`, `repair_index_gaps(index, store) -> list[str]`. Audit 2026-10-04: `rebuild_index` is atomic (it fills `<index>.tmp`, then one write transaction catches up the runs written meanwhile and replaces every table; mirror cursors are kept; metric points are read lazily); `rebuild_index_if_stale(index, store) -> int | None` (used by `Context.open`; one rebuild across processes); `index_generation(ctx) -> int` (grows on every write of indexed data, in the same transaction); `repair_stale_scores(index, store) -> list[str]` (used by `Context.open`: re-indexes the scores of runs whose `Context.add_score` was cut short).

- [ ] **Step 1: Write the failing tests**

`tests/core/test_index.py`:

```python
import sqlite3
from pathlib import Path

from hypothex.core.config import ProjectConfig
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.index import Index, downsample, rebuild_index, repair_index_gaps
from hypothex.core.layout import Layout
from hypothex.core.records import MetricPoint, RunStatus, ScoreRecord
from hypothex.core.store import RunStore
from tests.factories import make_record


def test_upsert_and_filters(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.upsert_run(make_record("r1", task="a", tags=["x"]))
    idx.upsert_run(make_record("r2", task="b", archived=True))
    idx.upsert_run(make_record("r3", status=RunStatus.FINISHED))
    assert {r.run_id for r in idx.list_runs()} == {"r1", "r3"}
    assert len(idx.list_runs(include_archived=True)) == 3
    assert [r.run_id for r in idx.list_runs(task="a")] == ["r1"]
    assert [r.run_id for r in idx.list_runs(tag="x")] == ["r1"]
    assert [r.run_id for r in idx.list_runs(status=RunStatus.FINISHED)] == ["r3"]
    got = idx.get_run("r2")
    assert got is not None and got.archived
    assert idx.get_run("zz") is None


def test_upsert_run_replaces_tags(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.upsert_run(make_record("r1", tags=["old"]))
    idx.upsert_run(make_record("r1", tags=["new"]))
    assert idx.list_runs(tag="old") == []
    assert [r.run_id for r in idx.list_runs(tag="new")] == ["r1"]


def test_scores_roundtrip(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    s1 = ScoreRecord(metric="acc", version="v1", key="value", value=0.5, created_at=utcnow())
    s2 = ScoreRecord(metric="acc", version="v2", key="value", value=0.6, created_at=utcnow())
    idx.add_score("r1", s1)
    idx.add_score("r1", s2)
    assert idx.scores_for(["r1", "r2"]) == {"r1": [s1, s2]}
    idx.replace_scores("r1", [s2])
    assert idx.scores_for(["r1"]) == {"r1": [s2]}


def test_downsample_keeps_last_point_and_limit() -> None:
    points = [MetricPoint(name="loss", step=i, value=float(i)) for i in range(2500)]
    points.append(MetricPoint(name="acc", step=0, value=1.0))
    out = downsample(points, limit=1000)
    loss = [p for p in out if p.name == "loss"]
    assert len(loss) <= 1000
    assert loss[-1].step == 2499
    assert [p.name for p in out].count("acc") == 1


def test_schema_version_mismatch_triggers_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "i.db"
    assert Index(path).rebuilt_schema  # fresh file
    assert not Index(path).rebuilt_schema
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    assert Index(path).rebuilt_schema


def _seeded_store(tmp_path: Path) -> RunStore:
    layout = Layout(tmp_path / "home")
    layout.ensure()
    store = RunStore(layout)
    store.register_project(ProjectConfig(project="toy"), tmp_path)
    for rid in ("r1", "r2"):
        store.create_run(make_record(rid, status=RunStatus.FINISHED, tags=["t"]))
        store.append_score("toy", rid, ScoreRecord(metric="acc", version="v1", key="value",
                                                    value=0.5, created_at=utcnow()))
        append_jsonl(layout.run_dir("toy", rid) / "metrics.jsonl",
                     {"name": "loss", "step": 0, "value": 1.0})
    return store


def test_rebuild_matches_live_index(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    live = Index(tmp_path / "live.db")
    for entry in store.list_projects():
        live.upsert_project(entry)
    for record in store.iter_records():
        live.upsert_run(record)
        live.replace_scores(record.run_id, store.read_scores(record.project, record.run_id))
        live.replace_metric_points(record.run_id,
                                   store.read_metric_points(record.project, record.run_id))
    rebuilt = Index(tmp_path / "rebuilt.db")
    assert rebuild_index(rebuilt, store) == 2
    assert live.list_runs() == rebuilt.list_runs()
    assert live.scores_for(["r1", "r2"]) == rebuilt.scores_for(["r1", "r2"])
    assert live.metric_points("r1") == rebuilt.metric_points("r1")
    assert [p.project for p in rebuilt.list_projects()] == ["toy"]


def test_repair_index_gaps(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    idx = Index(tmp_path / "i.db")
    assert repair_index_gaps(idx, store) == ["r1", "r2"]
    assert repair_index_gaps(idx, store) == []
    assert idx.get_project("toy") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_index.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.index'`.

- [ ] **Step 3: Implement `index.py`**

```python
"""Rebuildable SQLite index over the file store."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine, delete, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from hypothex.core.records import MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.store import ProjectEntry, RunStore

SCHEMA_VERSION = 1
MAX_POINTS_PER_METRIC = 1000


class Base(DeclarativeBase):
    """Declarative base for index tables."""


class MetaRow(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


class ProjectRow(Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    repo: Mapped[str] = mapped_column(String)
    entry_json: Mapped[str] = mapped_column(Text)


class DatasetRow(Base):
    __tablename__ = "datasets"
    project: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String)
    host: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)


class MetricRow(Base):
    __tablename__ = "metrics"
    project: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String)
    fn: Mapped[str] = mapped_column(String)
    higher_is_better: Mapped[bool] = mapped_column(Boolean)


class TaskRow(Base):
    __tablename__ = "tasks"
    project: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    dataset: Mapped[str] = mapped_column(String)
    split: Mapped[str | None] = mapped_column(String, nullable=True)
    primary: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[str] = mapped_column(Text)


class RunRow(Base):
    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    project: Mapped[str] = mapped_column(String, index=True)
    task: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[str] = mapped_column(String, index=True)  # ISO-8601 UTC sorts correctly
    config_hash: Mapped[str] = mapped_column(String)
    commit: Mapped[str | None] = mapped_column(String, nullable=True)
    environment_id: Mapped[str] = mapped_column(String)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    record_json: Mapped[str] = mapped_column(Text)


class RunTagRow(Base):
    __tablename__ = "run_tags"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True, index=True)


class ScoreRow(Base):
    __tablename__ = "scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    record_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String)


class MetricPointRow(Base):
    __tablename__ = "metric_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    step: Mapped[int] = mapped_column(Integer)
    value: Mapped[float] = mapped_column(Float)
    t: Mapped[float | None] = mapped_column(Float, nullable=True)


_DATA_TABLES = (ProjectRow, DatasetRow, MetricRow, TaskRow, RunRow, RunTagRow, ScoreRow,
                MetricPointRow)


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def downsample(points: list[MetricPoint], limit: int = MAX_POINTS_PER_METRIC) -> list[MetricPoint]:
    """
    Keep at most ``limit`` evenly spaced points per metric name, always keeping the last.

    Parameters
    ----------
    points : list of MetricPoint
        Full history.
    limit : int
        Maximum points per name.

    Returns
    -------
    list of MetricPoint
        Downsampled points grouped by name, ordered by step.
    """
    by_name: dict[str, list[MetricPoint]] = defaultdict(list)
    for point in points:
        by_name[point.name].append(point)
    out: list[MetricPoint] = []
    for name in sorted(by_name):
        series = sorted(by_name[name], key=lambda p: p.step)
        if len(series) > limit:
            kept = series[:: math.ceil(len(series) / limit)]
            if kept[-1] is not series[-1]:
                kept = kept[: limit - 1] + [series[-1]]
            series = kept
        out.extend(series)
    return out


class Index:
    """
    SQLite index used for fast listing and filtering.

    The index is disposable: when ``SCHEMA_VERSION`` changes it is recreated
    empty and ``rebuilt_schema`` is True so the caller rebuilds it from files.

    Parameters
    ----------
    path : Path
        SQLite file path.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10}
        )
        event.listen(self.engine, "connect", _sqlite_pragmas)
        self.rebuilt_schema = self._ensure_schema()

    def _ensure_schema(self) -> bool:
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            row = session.get(MetaRow, "schema_version")
            if row is not None and row.value == str(SCHEMA_VERSION):
                return False
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session, session.begin():
            session.add(MetaRow(key="schema_version", value=str(SCHEMA_VERSION)))
        return True

    def clear(self) -> None:
        """Delete all indexed data (keeps the schema)."""
        with Session(self.engine) as session, session.begin():
            for model in _DATA_TABLES:
                session.execute(delete(model))

    # projects -----------------------------------------------------------------
    def upsert_project(self, entry: ProjectEntry) -> None:
        """Index a project and its datasets, metrics, and tasks."""
        cfg = entry.config
        with Session(self.engine) as session, session.begin():
            session.merge(ProjectRow(name=entry.project, repo=entry.repo,
                                     entry_json=entry.model_dump_json()))
            for model in (DatasetRow, MetricRow, TaskRow):
                session.execute(delete(model).where(model.project == entry.project))
            session.add_all(
                DatasetRow(project=entry.project, name=n, version=d.version, host=d.host,
                           path=d.path)
                for n, d in cfg.datasets.items()
            )
            session.add_all(
                MetricRow(project=entry.project, name=n, version=m.version, fn=m.fn,
                          higher_is_better=m.higher_is_better)
                for n, m in cfg.metrics.items()
            )
            session.add_all(
                TaskRow(project=entry.project, name=n, dataset=t.dataset, split=t.split,
                        primary=t.primary, metrics_json=json.dumps(t.metrics))
                for n, t in cfg.tasks.items()
            )

    def list_projects(self) -> list[ProjectEntry]:
        """Return indexed projects sorted by name."""
        with Session(self.engine) as session:
            rows = session.scalars(select(ProjectRow.entry_json).order_by(ProjectRow.name))
            return [ProjectEntry.model_validate_json(r) for r in rows]

    def get_project(self, name: str) -> ProjectEntry | None:
        """Return one indexed project or None."""
        with Session(self.engine) as session:
            row = session.get(ProjectRow, name)
            return ProjectEntry.model_validate_json(row.entry_json) if row else None

    # runs ---------------------------------------------------------------------
    def upsert_run(self, record: RunRecord) -> None:
        """Insert or replace one run and its tags."""
        with Session(self.engine) as session, session.begin():
            session.merge(RunRow(
                run_id=record.run_id, project=record.project, task=record.task,
                status=record.status.value, created_at=record.created_at.isoformat(),
                config_hash=record.config_hash, commit=record.git.commit,
                environment_id=record.environment_id, archived=record.archived,
                starred=record.starred, record_json=record.model_dump_json(),
            ))
            session.execute(delete(RunTagRow).where(RunTagRow.run_id == record.run_id))
            session.add_all(RunTagRow(run_id=record.run_id, tag=t) for t in sorted(set(record.tags)))

    def get_run(self, run_id: str) -> RunRecord | None:
        """Return one indexed run or None."""
        with Session(self.engine) as session:
            row = session.get(RunRow, run_id)
            return RunRecord.model_validate_json(row.record_json) if row else None

    def list_runs(
        self,
        *,
        project: str | None = None,
        task: str | None = None,
        status: RunStatus | str | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        limit: int | None = 500,
    ) -> list[RunRecord]:
        """
        List runs, newest first.

        Parameters
        ----------
        project, task, status, tag : optional
            Filters; ``None`` means no filter.
        include_archived : bool
            Include archived runs.
        limit : int or None
            Maximum rows; ``None`` for all.

        Returns
        -------
        list of RunRecord
        """
        stmt = select(RunRow.record_json).order_by(RunRow.created_at.desc(), RunRow.run_id.desc())
        if project is not None:
            stmt = stmt.where(RunRow.project == project)
        if task is not None:
            stmt = stmt.where(RunRow.task == task)
        if status is not None:
            stmt = stmt.where(RunRow.status == str(status))
        if tag is not None:
            stmt = stmt.join(RunTagRow, RunTagRow.run_id == RunRow.run_id).where(RunTagRow.tag == tag)
        if not include_archived:
            stmt = stmt.where(RunRow.archived.is_(False))
        if limit is not None:
            stmt = stmt.limit(limit)
        with Session(self.engine) as session:
            return [RunRecord.model_validate_json(j) for j in session.scalars(stmt)]

    def run_ids(self) -> set[str]:
        """Return all indexed run ids."""
        with Session(self.engine) as session:
            return set(session.scalars(select(RunRow.run_id)))

    # scores -------------------------------------------------------------------
    def add_score(self, run_id: str, score: ScoreRecord) -> None:
        """Index one score."""
        with Session(self.engine) as session, session.begin():
            session.add(ScoreRow(run_id=run_id, record_json=score.model_dump_json(),
                                 created_at=score.created_at.isoformat()))

    def replace_scores(self, run_id: str, scores: list[ScoreRecord]) -> None:
        """Replace all indexed scores of one run."""
        with Session(self.engine) as session, session.begin():
            session.execute(delete(ScoreRow).where(ScoreRow.run_id == run_id))
            session.add_all(ScoreRow(run_id=run_id, record_json=s.model_dump_json(),
                                     created_at=s.created_at.isoformat()) for s in scores)

    def scores_for(self, run_ids: Iterable[str]) -> dict[str, list[ScoreRecord]]:
        """Return scores per run, oldest first; runs without scores are omitted."""
        ids = list(dict.fromkeys(run_ids))
        out: dict[str, list[ScoreRecord]] = {}
        with Session(self.engine) as session:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                stmt = (select(ScoreRow.run_id, ScoreRow.record_json)
                        .where(ScoreRow.run_id.in_(chunk))
                        .order_by(ScoreRow.created_at, ScoreRow.id))
                for run_id, blob in session.execute(stmt):
                    out.setdefault(run_id, []).append(ScoreRecord.model_validate_json(blob))
        return out

    # metric points ------------------------------------------------------------
    def replace_metric_points(self, run_id: str, points: list[MetricPoint]) -> None:
        """Replace one run's indexed (downsampled) metric history."""
        with Session(self.engine) as session, session.begin():
            session.execute(delete(MetricPointRow).where(MetricPointRow.run_id == run_id))
            session.add_all(MetricPointRow(run_id=run_id, name=p.name, step=p.step, value=p.value,
                                           t=p.t) for p in downsample(points))

    def metric_points(self, run_id: str) -> list[MetricPoint]:
        """Return one run's indexed metric history ordered by name then step."""
        stmt = (select(MetricPointRow).where(MetricPointRow.run_id == run_id)
                .order_by(MetricPointRow.name, MetricPointRow.step))
        with Session(self.engine) as session:
            return [MetricPoint(name=r.name, step=r.step, value=r.value, t=r.t)
                    for r in session.scalars(stmt)]


def index_run(index: Index, store: RunStore, record: RunRecord) -> None:
    """Index a run, its scores, and its metric points from files."""
    index.upsert_run(record)
    index.replace_scores(record.run_id, store.read_scores(record.project, record.run_id))
    index.replace_metric_points(record.run_id,
                                store.read_metric_points(record.project, record.run_id))


def rebuild_index(index: Index, store: RunStore) -> int:
    """
    Rebuild the whole index from files.

    Returns
    -------
    int
        Number of runs indexed.
    """
    index.clear()
    for entry in store.list_projects():
        index.upsert_project(entry)
    count = 0
    for record in store.iter_records():
        index_run(index, store, record)
        count += 1
    return count


def repair_index_gaps(index: Index, store: RunStore) -> list[str]:
    """
    Index projects and run folders that have no index row yet.

    Returns
    -------
    list of str
        Run ids that were added, sorted.
    """
    for entry in store.list_projects():
        if index.get_project(entry.project) is None:
            index.upsert_project(entry)
    on_disk = store.list_run_ids()
    missing = sorted(set(on_disk) - index.run_ids())
    added: list[str] = []
    for run_id in missing:
        try:
            record = store.read_record(on_disk[run_id], run_id)
        except Exception:  # noqa: BLE001 - unreadable folders are skipped, not fatal
            continue
        index_run(index, store, record)
        added.append(run_id)
    return added
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_index.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/index.py tests/core/test_index.py
git commit -m "feat: rebuildable SQLite index with gap repair"
```

---

### Task 6: Git info, worktrees, and environment capture

**Files:**
- Create: `src/hypothex/core/gitinfo.py`, `src/hypothex/core/envcapture.py`
- Modify: `tests/factories.py` (add git helpers)
- Test: `tests/core/test_gitinfo.py`, `tests/core/test_envcapture.py`

**Interfaces:**
- Consumes: Task 1 (`GitError`, `atomic_write_text`), Task 3 (`GitInfo`).
- Produces:
  - `hypothex.core.gitinfo`: `DIFF_LIMIT_BYTES = 5 * 1024 * 1024`; `DiffCapture(diff: str | None, stat: str, too_large: bool)` (dataclass); `git_info(path: Path) -> GitInfo`; `head_commit(path) -> str | None`; `capture_diff(path, limit=DIFF_LIMIT_BYTES) -> DiffCapture`; `commit_exists(repo, commit) -> bool`; `create_worktree(repo, commit, dest, diff) -> Path`.
  - `hypothex.core.envcapture`: `ENV_ALLOWLIST: tuple[str, ...]`; `capture_env(repo: Path, env_dir: Path, python_cmd: list[str]) -> None`.
  - `tests/factories.py`: `git(repo: Path, *args: str) -> str`, `init_git_repo(repo: Path) -> str` (returns first commit sha).

- [ ] **Step 1: Add git helpers to `tests/factories.py`**

Append:

```python
import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` with a fixed identity; return stdout."""
    out = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def init_git_repo(repo: Path) -> str:
    """Init a repo, commit everything in it, and return the commit sha."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    return git(repo, "rev-parse", "HEAD")
```

(Move the `import subprocess` / `from pathlib import Path` lines to the top import block of the file.)

- [ ] **Step 2: Write the failing tests**

`tests/core/test_gitinfo.py`:

```python
from pathlib import Path

import pytest

from hypothex.core.errors import GitError
from hypothex.core.gitinfo import capture_diff, create_worktree, git_info, head_commit
from tests.factories import git, init_git_repo


def test_git_info_clean_and_dirty(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    sha = init_git_repo(repo)
    info = git_info(repo)
    assert info.commit == sha and info.branch == "main" and not info.dirty
    (repo / "a.txt").write_text("two\n")
    assert git_info(repo).dirty
    assert head_commit(repo) == sha


def test_non_git_directory_gives_empty_info(tmp_path: Path) -> None:
    info = git_info(tmp_path)
    assert info.commit is None and info.branch is None and not info.dirty
    assert capture_diff(tmp_path).diff is None


def test_capture_diff_and_size_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    init_git_repo(repo)
    assert capture_diff(repo).diff is None
    (repo / "a.txt").write_text("two\n")
    cap = capture_diff(repo)
    assert cap.diff is not None and "+two" in cap.diff and "a.txt" in cap.stat
    big = capture_diff(repo, limit=10)
    assert big.diff is None and big.too_large


def test_create_worktree_applies_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    sha = init_git_repo(repo)
    (repo / "a.txt").write_text("patched\n")
    diff = capture_diff(repo).diff
    git(repo, "checkout", "--", "a.txt")
    (repo / "a.txt").write_text("later\n")
    git(repo, "commit", "-qam", "later")
    wt = create_worktree(repo, sha, tmp_path / "wt", diff)
    assert (wt / "a.txt").read_text() == "patched\n"
    assert head_commit(wt) == sha


def test_create_worktree_missing_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    with pytest.raises(GitError, match="not found"):
        create_worktree(repo, "0" * 40, tmp_path / "wt", None)
```

`tests/core/test_envcapture.py`:

```python
import json
import sys
from pathlib import Path

import pytest

from hypothex.core.envcapture import capture_env


def test_capture_env_writes_system_and_allowlisted_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_text("lock")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("SECRET_TOKEN", "do-not-store")
    env_dir = tmp_path / "env"
    capture_env(repo, env_dir, [sys.executable])
    system = json.loads((env_dir / "system.json").read_text())
    assert system["project_python"].startswith("Python 3")
    env_vars = json.loads((env_dir / "env_vars.json").read_text())
    assert env_vars == {"CUDA_VISIBLE_DEVICES": "0,1"}
    assert (env_dir / "uv.lock").read_text() == "lock"
    assert "do-not-store" not in "".join(p.read_text() for p in env_dir.iterdir())


def test_capture_env_survives_missing_python(tmp_path: Path) -> None:
    capture_env(tmp_path, tmp_path / "env", ["/nonexistent/python"])
    system = json.loads((tmp_path / "env" / "system.json").read_text())
    assert system["project_python"] is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_gitinfo.py tests/core/test_envcapture.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.gitinfo'`.

- [ ] **Step 4: Implement `gitinfo.py`**

```python
"""Read git state and build worktrees for exact reruns."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from hypothex.core.errors import GitError
from hypothex.core.records import GitInfo

DIFF_LIMIT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class DiffCapture:
    """Uncommitted changes at launch time."""

    diff: str | None
    stat: str
    too_large: bool


def _git(path: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                              input=input_text, check=False)
    except FileNotFoundError as exc:
        raise GitError("git is not installed") from exc


def head_commit(path: Path) -> str | None:
    """Return the HEAD commit sha, or None outside a git repo."""
    out = _git(path, "rev-parse", "HEAD")
    return out.stdout.strip() if out.returncode == 0 else None


def git_info(path: Path) -> GitInfo:
    """
    Describe the git state of ``path``.

    Returns
    -------
    GitInfo
        Empty (all None) when ``path`` is not inside a git repo.
    """
    commit = head_commit(path)
    if commit is None:
        return GitInfo()
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or None
    remote = _git(path, "remote", "get-url", "origin")
    dirty = bool(_git(path, "status", "--porcelain").stdout.strip())
    return GitInfo(
        repo=remote.stdout.strip() if remote.returncode == 0 else None,
        commit=commit,
        branch=branch,
        dirty=dirty,
    )


def capture_diff(path: Path, limit: int = DIFF_LIMIT_BYTES) -> DiffCapture:
    """
    Capture ``git diff HEAD`` (tracked files only).

    Parameters
    ----------
    path : Path
        Directory inside the repo.
    limit : int
        Maximum diff size in bytes; larger diffs are not stored.

    Returns
    -------
    DiffCapture
        ``diff`` is None when clean, not a repo, or too large.
    """
    out = _git(path, "diff", "HEAD", "--binary")
    if out.returncode != 0:
        return DiffCapture(diff=None, stat="", too_large=False)
    stat = _git(path, "diff", "HEAD", "--stat").stdout
    if len(out.stdout.encode("utf-8")) > limit:
        return DiffCapture(diff=None, stat=stat, too_large=True)
    return DiffCapture(diff=out.stdout or None, stat=stat, too_large=False)


def commit_exists(repo: Path, commit: str) -> bool:
    """Return True if ``commit`` exists in ``repo``."""
    return _git(repo, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def create_worktree(repo: Path, commit: str, dest: Path, diff: str | None) -> Path:
    """
    Check out ``commit`` into a new detached worktree and apply ``diff``.

    Raises
    ------
    GitError
        If the commit is missing or the diff does not apply.
    """
    if not commit_exists(repo, commit):
        raise GitError(f"commit {commit} not found in {repo}; it may have been rebased away")
    dest.parent.mkdir(parents=True, exist_ok=True)
    added = _git(repo, "worktree", "add", "--detach", str(dest), commit)
    if added.returncode != 0:
        raise GitError(f"git worktree add failed: {added.stderr.strip()}")
    if diff:
        applied = _git(dest, "apply", "--whitespace=nowarn", "-", input_text=diff)
        if applied.returncode != 0:
            raise GitError(f"could not apply the saved diff: {applied.stderr.strip()}")
    return dest
```

- [ ] **Step 5: Implement `envcapture.py`**

```python
"""Capture the software and hardware environment of a run."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

from hypothex.core.fsutil import atomic_write_text

ENV_ALLOWLIST = (
    "CUDA_VISIBLE_DEVICES",
    "CUBLAS_WORKSPACE_CONFIG",
    "HF_HUB_OFFLINE",
    "OMP_NUM_THREADS",
    "PYTHONHASHSEED",
    "SLURM_JOB_ID",
    "SLURM_JOB_NODELIST",
    "TRANSFORMERS_OFFLINE",
)


def _run(cmd: list[str], timeout: float = 30) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout + out.stderr).strip() if out.returncode == 0 else None


def capture_env(repo: Path, env_dir: Path, python_cmd: list[str]) -> None:
    """
    Write ``system.json``, ``env_vars.json``, packages, and GPU info into ``env_dir``.

    Every probe is best effort: a missing tool never fails the run.

    Parameters
    ----------
    repo : Path
        Project repo (``uv.lock`` is copied from here when present).
    env_dir : Path
        Destination folder.
    python_cmd : list of str
        How to invoke the project's Python, e.g. ``["uv", "run", "python"]``.
    """
    env_dir.mkdir(parents=True, exist_ok=True)
    system = {
        "hx_python": platform.python_version(),
        "project_python": _run([*python_cmd, "--version"]),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "hostname": socket.gethostname(),
        "cpu_count": os.cpu_count(),
    }
    atomic_write_text(env_dir / "system.json", json.dumps(system, indent=2))
    env_vars = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    atomic_write_text(env_dir / "env_vars.json", json.dumps(env_vars, indent=2))
    lock = repo / "uv.lock"
    if lock.is_file():
        shutil.copy2(lock, env_dir / "uv.lock")
    else:
        freeze = _run([*python_cmd, "-m", "pip", "freeze"])
        if freeze:
            atomic_write_text(env_dir / "requirements.txt", freeze + "\n")
    gpus = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv"])
    if gpus:
        atomic_write_text(env_dir / "nvidia-smi.csv", gpus + "\n")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_gitinfo.py tests/core/test_envcapture.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hypothex/core/gitinfo.py src/hypothex/core/envcapture.py tests/factories.py tests/core/test_gitinfo.py tests/core/test_envcapture.py
git commit -m "feat: git state, worktrees for reruns, environment capture"
```

---

### Task 7: Dataset fingerprints, drift check, split overlap

**Files:**
- Create: `src/hypothex/core/datasets.py`
- Test: `tests/core/test_datasets.py`

**Interfaces:**
- Consumes: Task 1 (`atomic_write_text`, `utcnow`, `read_jsonl`), Task 2 (`DatasetSpec`), Task 3 (`DatasetRef`, `RunRecord`).
- Produces (`hypothex.core.datasets`):
  - `FULL_HASH_LIMIT = 2 * 1024**3`, `SAMPLE_BYTES = 4 * 1024**2`.
  - `Fingerprint(hash: str, mode: Literal["full","manifest"], size: int)`; `fingerprint(path: Path, full_limit: int = FULL_HASH_LIMIT) -> Fingerprint` (raises `FileNotFoundError`).
  - `FingerprintCache(path: Path)` with `fingerprint(path: Path) -> Fingerprint`.
  - `resolve_dataset_path(repo: Path, raw: str) -> Path`.
  - `dataset_ref(name, spec, split, repo, cache, local_label) -> DatasetRef` (hash_mode `full|manifest|missing|remote-unchecked`).
  - `DatasetDrift(run_id, project, dataset, path, recorded_hash, current_hash, status)` with status `ok|changed|missing|unchecked`; `check_runs(records, cache) -> list[DatasetDrift]`.
  - `OverlapReport(dataset, pairs: dict[str, int], examples: dict[str, list[str]])`; `overlap(name, spec, repo, key_field=None, max_examples=20) -> OverlapReport`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_datasets.py`:

```python
import json
from pathlib import Path

import pytest

from hypothex.core import datasets as ds
from hypothex.core.config import DatasetSpec
from hypothex.core.records import DatasetRef
from tests.factories import make_record


def test_full_hash_stable_and_content_sensitive(tmp_path: Path) -> None:
    f = tmp_path / "d.jsonl"
    f.write_text("a\nb\n")
    first = ds.fingerprint(f)
    assert first.mode == "full" and first.size == 4 and first.hash.startswith("xxh3:")
    assert ds.fingerprint(f) == first
    f.write_text("a\nc\n")
    assert ds.fingerprint(f).hash != first.hash


def test_manifest_mode_for_big_files_and_dirs(tmp_path: Path) -> None:
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * 100)
    assert ds.fingerprint(f, full_limit=10).mode == "manifest"
    d = tmp_path / "dir"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("1")
    (d / "sub" / "b.txt").write_text("2")
    first = ds.fingerprint(d)
    assert first.mode == "manifest" and first.size == 2
    (d / "sub" / "b.txt").write_text("22")
    assert ds.fingerprint(d).hash != first.hash


def test_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ds.fingerprint(tmp_path / "nope")


def test_cache_avoids_rehash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "d.txt"
    f.write_text("abc")
    cache = ds.FingerprintCache(tmp_path / "cache.json")
    calls: list[Path] = []
    real = ds._hash_file_full

    def counting(path: Path) -> str:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(ds, "_hash_file_full", counting)
    cache.fingerprint(f)
    ds.FingerprintCache(tmp_path / "cache.json").fingerprint(f)  # reloads from disk
    assert len(calls) == 1


def test_dataset_ref_modes(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "t.jsonl").write_text("{}\n")
    cache = ds.FingerprintCache(tmp_path / "c.json")
    spec = DatasetSpec(version="v1", path="data/t.jsonl")
    ref = ds.dataset_ref("d", spec, None, tmp_path, cache, "mac")
    assert ref.hash_mode == "full" and ref.path == str(tmp_path / "data" / "t.jsonl")
    missing = ds.dataset_ref("d", DatasetSpec(version="v1", path="nope.jsonl"), None, tmp_path,
                             cache, "mac")
    assert missing.hash is None and missing.hash_mode == "missing"
    remote = ds.dataset_ref("d", DatasetSpec(version="v1", path="/x", host="gpu1"), None,
                            tmp_path, cache, "mac")
    assert remote.hash_mode == "remote-unchecked"


def test_check_runs_detects_change(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text("a\n")
    cache = ds.FingerprintCache(tmp_path / "c.json")
    fp = cache.fingerprint(f)
    ref = DatasetRef(name="d", version="v1", path=str(f), hash=fp.hash, hash_mode=fp.mode)
    record = make_record("r1", datasets=[ref])
    assert [d.status for d in ds.check_runs([record], cache)] == ["ok"]
    f.write_text("bb\n")  # different size, so the cache cannot hit by mtime resolution luck
    assert [d.status for d in ds.check_runs([record], cache)] == ["changed"]
    f.unlink()
    assert [d.status for d in ds.check_runs([record], cache)] == ["missing"]


def test_overlap_counts_shared_examples(tmp_path: Path) -> None:
    rows = {"train": ["a", "b", "c"], "test": ["c", "d"], "valid": ["d"]}
    splits = {}
    for split, keys in rows.items():
        path = tmp_path / f"{split}.jsonl"
        path.write_text("".join(json.dumps({"smiles": k, "y": 1}) + "\n" for k in keys))
        splits[split] = str(path)
    spec = DatasetSpec(version="v1", path=splits["test"], splits=splits)
    report = ds.overlap("d", spec, tmp_path, key_field="smiles")
    assert report.pairs == {"test/train": 1, "test/valid": 1, "train/valid": 0}
    assert report.examples["test/train"] == ["c"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_datasets.py -v`
Expected: FAIL with `ImportError` (no `datasets` module).

- [ ] **Step 3: Implement `datasets.py`**

```python
"""Dataset fingerprints, drift detection, and split-overlap checks."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import xxhash
from pydantic import BaseModel

from hypothex.core.config import DatasetSpec
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import utcnow
from hypothex.core.records import DatasetRef, RunRecord

FULL_HASH_LIMIT = 2 * 1024**3
SAMPLE_BYTES = 4 * 1024**2
_CHUNK = 1024 * 1024


class Fingerprint(BaseModel):
    """Content fingerprint of a file or directory."""

    hash: str
    mode: Literal["full", "manifest"]
    size: int


def _hash_file_full(path: Path) -> str:
    h = xxhash.xxh3_128()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _hash_file_sample(path: Path, size: int) -> str:
    h = xxhash.xxh3_128()
    with path.open("rb") as fh:
        h.update(fh.read(SAMPLE_BYTES))
        if size > SAMPLE_BYTES:
            fh.seek(max(size - SAMPLE_BYTES, SAMPLE_BYTES))
            h.update(fh.read(SAMPLE_BYTES))
    return h.hexdigest()


def fingerprint(path: Path, full_limit: int = FULL_HASH_LIMIT) -> Fingerprint:
    """
    Fingerprint a dataset file or directory.

    Files up to ``full_limit`` bytes get a full content hash. Larger files and
    directories get a manifest hash over (relative path, size, mtime, head+tail sample).

    Parameters
    ----------
    path : Path
        File or directory.
    full_limit : int
        Size limit for full hashing.

    Returns
    -------
    Fingerprint

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> p = pathlib.Path(tempfile.mkdtemp()) / "x.txt"; _ = p.write_text("hi")
    >>> fingerprint(p).mode
    'full'
    """
    if path.is_file():
        size = path.stat().st_size
        if size <= full_limit:
            return Fingerprint(hash="xxh3:" + _hash_file_full(path), mode="full", size=size)
        files, base = [path], path.parent
    elif path.is_dir():
        files, base = sorted(p for p in path.rglob("*") if p.is_file()), path
    else:
        raise FileNotFoundError(path)
    h = xxhash.xxh3_128()
    total = 0
    for f in files:
        st = f.stat()
        total += st.st_size
        rel = f.relative_to(base).as_posix()
        sample = _hash_file_sample(f, st.st_size)
        h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\0{sample}\n".encode())
    return Fingerprint(hash="xxh3m:" + h.hexdigest(), mode="manifest", size=total)


class FingerprintCache:
    """
    Cache file fingerprints keyed by (path, size, mtime).

    Directories are always re-fingerprinted (their manifest hash is cheap).

    Parameters
    ----------
    path : Path
        JSON cache file.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict] = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        )

    def fingerprint(self, path: Path) -> Fingerprint:
        """Return a cached fingerprint when the file is unchanged, else compute and store it."""
        resolved = path.resolve()
        if not resolved.is_file():
            return fingerprint(resolved)
        st = resolved.stat()
        key = str(resolved)
        hit = self._data.get(key)
        if hit and hit["size"] == st.st_size and hit["mtime_ns"] == st.st_mtime_ns:
            return Fingerprint.model_validate(hit["fingerprint"])
        fp = fingerprint(resolved)
        self._data[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
                           "fingerprint": fp.model_dump()}
        atomic_write_text(self.path, json.dumps(self._data))
        return fp


def resolve_dataset_path(repo: Path, raw: str) -> Path:
    """Resolve a dataset path relative to the repo unless it is absolute."""
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (repo / p)


def dataset_ref(
    name: str,
    spec: DatasetSpec,
    split: str | None,
    repo: Path,
    cache: FingerprintCache,
    local_label: str,
) -> DatasetRef:
    """
    Build the ``DatasetRef`` a run records at launch.

    Parameters
    ----------
    name : str
        Dataset name from ``hypothex.yaml``.
    spec : DatasetSpec
        Dataset spec.
    split : str or None
        Split used by the task.
    repo : Path
        Project repo (for relative paths).
    cache : FingerprintCache
        Fingerprint cache.
    local_label : str
        This environment's label; datasets on other hosts are not hashed.

    Returns
    -------
    DatasetRef
        ``hash_mode`` is ``full``/``manifest``, ``missing`` if the path does not
        exist, or ``remote-unchecked`` for other hosts.
    """
    raw = spec.path_for(split)
    base = {"name": name, "version": spec.version, "split": split}
    if spec.host not in ("local", local_label):
        return DatasetRef(**base, host=spec.host, path=raw, hash_mode="remote-unchecked")
    path = resolve_dataset_path(repo, raw)
    try:
        fp = cache.fingerprint(path)
    except FileNotFoundError:
        return DatasetRef(**base, path=str(path), hash_mode="missing")
    return DatasetRef(**base, path=str(path), hash=fp.hash, hash_mode=fp.mode, size=fp.size,
                      checked_at=utcnow())


class DatasetDrift(BaseModel):
    """Result of re-checking one dataset of one run."""

    run_id: str
    project: str
    dataset: str
    path: str
    recorded_hash: str | None
    current_hash: str | None
    status: Literal["ok", "changed", "missing", "unchecked"]


def check_runs(records: Iterable[RunRecord], cache: FingerprintCache) -> list[DatasetDrift]:
    """
    Re-fingerprint every local dataset used by ``records``.

    Returns
    -------
    list of DatasetDrift
        One entry per (run, dataset).
    """
    out: list[DatasetDrift] = []
    for record in records:
        for ref in record.datasets:
            base = {"run_id": record.run_id, "project": record.project, "dataset": ref.name,
                    "path": ref.path, "recorded_hash": ref.hash}
            if ref.hash is None or ref.host != "local":
                out.append(DatasetDrift(**base, current_hash=None, status="unchecked"))
                continue
            try:
                current = cache.fingerprint(Path(ref.path)).hash
            except FileNotFoundError:
                out.append(DatasetDrift(**base, current_hash=None, status="missing"))
                continue
            status = "ok" if current == ref.hash else "changed"
            out.append(DatasetDrift(**base, current_hash=current, status=status))
    return out


class OverlapReport(BaseModel):
    """Examples shared between dataset splits."""

    dataset: str
    pairs: dict[str, int]
    examples: dict[str, list[str]]


def _split_keys(path: Path, key_field: str | None) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if key_field is None:
            keys.add(line)
            continue
        try:
            keys.add(str(json.loads(line)[key_field]))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return keys


def overlap(
    name: str,
    spec: DatasetSpec,
    repo: Path,
    key_field: str | None = None,
    max_examples: int = 20,
) -> OverlapReport:
    """
    Count examples shared between every pair of declared splits.

    Parameters
    ----------
    name : str
        Dataset name.
    spec : DatasetSpec
        Spec with ``splits``.
    repo : Path
        Project repo for relative paths.
    key_field : str, optional
        JSON field identifying an example; default compares whole lines.
    max_examples : int
        Shared keys listed per pair.

    Returns
    -------
    OverlapReport
    """
    keys = {split: _split_keys(resolve_dataset_path(repo, p), key_field)
            for split, p in spec.splits.items()}
    pairs: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for a, b in itertools.combinations(sorted(keys), 2):
        shared = keys[a] & keys[b]
        pairs[f"{a}/{b}"] = len(shared)
        examples[f"{a}/{b}"] = sorted(shared)[:max_examples]
    return OverlapReport(dataset=name, pairs=pairs, examples=examples)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_datasets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/datasets.py tests/core/test_datasets.py
git commit -m "feat: dataset fingerprints, drift check, split overlap"
```

---
### Task 8: Metric contract, eval worker, and worker runner

**Files:**
- Create: `src/hypothex/metrics.py`, `src/hypothex/eval_worker.py`, `src/hypothex/core/evalrunner.py`
- Modify: `tests/factories.py` (add toy project writer)
- Test: `tests/test_eval_worker.py`

**Interfaces:**
- Consumes: Task 1 (`EvalError`, `read_jsonl`, `atomic_write_text`), Task 2 (`ProjectConfig`), Task 6 (`init_git_repo` in factories).
- Produces:
  - `hypothex.metrics`: `Example(id: str, prediction: Any, reference: Any = None, meta: dict = {})` (frozen dataclass); `MetricResult(values: dict[str, float], per_example: dict[str, dict[str, Any]] = {})` (dataclass); `normalize_result(raw: object) -> MetricResult`.
  - `hypothex.eval_worker`: `load_examples(run_dir, dataset) -> list[Example]`, `evaluate(request) -> dict`, `describe(request) -> dict`, `main(argv=None) -> int`. Evaluate result: `{"n_examples": int, "results": [{"name","version","values","error","source_hash"}]}`. Describe result: `{"metrics": {name: {"importable","error","source_hash"}}}`. Per-example scores go to `predictions/scores.<name>@<version>.jsonl` as `{"id": ..., **fields}`.
  - `hypothex.core.evalrunner`: `default_python_cmd(repo: Path, config: ProjectConfig) -> list[str]`, `run_worker(action: str, request: dict, python_cmd: list[str], cwd: Path, timeout: float | None = None) -> dict`.
  - `tests/factories.py`: `TOY_METRICS`, `TOY_INFER` (str), `PREDS_075: list[dict]` (scores accuracy 0.75 on the toy data), `write_toy_project(repo: Path, *, accuracy_version: str = "v1", use_git: bool = True) -> Path`.

- [ ] **Step 1: Add the toy project writer to `tests/factories.py`**

Add `import json`, `import shlex`, `import sys`, `import yaml` to the imports, then append:

```python
TOY_METRICS = '''\
from hypothex.metrics import MetricResult


def accuracy(examples):
    per = {e.id: {"correct": e.prediction == e.reference} for e in examples}
    value = sum(v["correct"] for v in per.values()) / max(len(per), 1)
    return MetricResult(values={"value": value}, per_example=per)


def broken(examples):
    raise RuntimeError("boom")
'''

TOY_INFER = '''\
import json
import os
import sys
from pathlib import Path

run_dir = Path(os.environ["HYPOTHEX_RUN_DIR"])
ckpt = sys.argv[sys.argv.index("--ckpt") + 1]
with (run_dir / "predictions" / "predictions.jsonl").open("w") as fh:
    for i in range(4):
        fh.write(json.dumps({"id": f"ex-{i}", "prediction": i % 2}) + "\\n")
print("inferred with", ckpt)
'''

# references are [0, 1, 0, 0]; these predictions are [0, 1, 0, 1] -> accuracy 0.75
PREDS_075 = [{"id": f"ex-{i}", "prediction": i % 2} for i in range(4)]


def write_toy_project(repo: Path, *, accuracy_version: str = "v1", use_git: bool = True) -> Path:
    """Write a tiny Hypothex project (data, metrics, infer stage) and optionally git-init it."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "data").mkdir(exist_ok=True)
    refs = [0, 1, 0, 0]
    (repo / "data" / "test.jsonl").write_text(
        "".join(json.dumps({"id": f"ex-{i}", "reference": r}) + "\n" for i, r in enumerate(refs))
    )
    config = {
        "project": "toy",
        "datasets": {
            "toyset": {"version": "v1", "path": "data/test.jsonl",
                       "splits": {"test": "data/test.jsonl"}},
        },
        "metrics": {
            "accuracy": {"version": accuracy_version, "fn": "toymetrics:accuracy"},
            "broken": {"version": "v1", "fn": "toymetrics:broken"},
        },
        "tasks": {
            "toy-acc": {"dataset": "toyset", "split": "test", "metrics": ["accuracy"],
                        "primary": "accuracy"},
            "toy-broken": {"dataset": "toyset", "split": "test",
                           "metrics": ["accuracy", "broken"], "primary": "accuracy"},
        },
        "stages": {"infer": f"{shlex.quote(sys.executable)} infer.py --ckpt {{checkpoint}}"},
        "env": {"python": [sys.executable]},
    }
    (repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (repo / "toymetrics.py").write_text(TOY_METRICS)
    (repo / "infer.py").write_text(TOY_INFER)
    if use_git and not (repo / ".git").exists():
        init_git_repo(repo)
    return repo
```

- [ ] **Step 2: Write the failing tests**

`tests/test_eval_worker.py`:

```python
import json
import sys
from pathlib import Path

import pytest

from hypothex.core.errors import EvalError
from hypothex.core.evalrunner import run_worker
from hypothex.core.fsutil import read_jsonl
from hypothex.metrics import MetricResult, normalize_result
from tests.factories import write_toy_project


def _run_dir(tmp_path: Path, rows: list[dict]) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "predictions").mkdir(parents=True)
    (run_dir / "predictions" / "predictions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )
    return run_dir


def _request(repo: Path, run_dir: Path, metrics: list[str]) -> dict:
    fns = {"accuracy": "toymetrics:accuracy", "broken": "toymetrics:broken"}
    return {
        "repo": str(repo),
        "run_dir": str(run_dir),
        "dataset": {"path": str(repo / "data" / "test.jsonl"), "id_field": "id",
                    "reference_field": "reference"},
        "metrics": [{"name": m, "version": "v1", "fn": fns[m], "params": {}} for m in metrics],
    }


def test_normalize_result_variants() -> None:
    res = MetricResult(values={"a": 1.0})
    assert normalize_result(res) is res
    assert normalize_result(0.5).values == {"value": 0.5}
    assert normalize_result({"k=1": 1}).values == {"k=1": 1.0}
    for bad in ("x", True, {"a": "b"}):
        with pytest.raises(TypeError):
            normalize_result(bad)


def test_evaluate_scores_and_writes_per_example(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    run_dir = _run_dir(tmp_path, [{"id": "ex-0", "prediction": 0}, {"id": "ex-1", "prediction": 0}])
    out = run_worker("evaluate", _request(repo, run_dir, ["accuracy", "broken"]),
                     [sys.executable], cwd=repo)
    acc, broken = out["results"]
    assert out["n_examples"] == 2
    assert acc["values"] == {"value": 0.5} and acc["error"] is None
    assert acc["source_hash"].startswith("sha256:")
    assert "boom" in broken["error"] and broken["values"] == {}
    per = read_jsonl(run_dir / "predictions" / "scores.accuracy@v1.jsonl")
    assert {r["id"]: r["correct"] for r in per} == {"ex-0": True, "ex-1": False}


def test_inline_reference_wins_over_dataset(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    run_dir = _run_dir(tmp_path, [{"id": "ex-1", "prediction": 5, "reference": 5}])
    out = run_worker("evaluate", _request(repo, run_dir, ["accuracy"]), [sys.executable], cwd=repo)
    assert out["results"][0]["values"] == {"value": 1.0}


def test_missing_predictions_is_eval_error(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    with pytest.raises(EvalError, match="no predictions"):
        run_worker("evaluate", _request(repo, run_dir, ["accuracy"]), [sys.executable], cwd=repo)


def test_describe_reports_import_errors(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    request = {"repo": str(repo), "metrics": [
        {"name": "accuracy", "fn": "toymetrics:accuracy"},
        {"name": "gone", "fn": "nomodule:fn"},
    ]}
    out = run_worker("describe", request, [sys.executable], cwd=repo)["metrics"]
    assert out["accuracy"]["importable"] and out["accuracy"]["source_hash"]
    assert not out["gone"]["importable"] and "nomodule" in out["gone"]["error"]


def test_missing_python_is_eval_error(tmp_path: Path) -> None:
    with pytest.raises(EvalError, match="could not start"):
        run_worker("describe", {"repo": str(tmp_path), "metrics": []},
                   ["/nonexistent/python"], cwd=tmp_path)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.evalrunner'`.

- [ ] **Step 4: Implement `metrics.py`**

```python
"""Public contract for metric functions.

A metric function lives in project code and has this shape::

    from hypothex import Example, MetricResult

    def accuracy(examples: list[Example], **params) -> MetricResult | float | dict[str, float]:
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real
from typing import Any


@dataclass(frozen=True)
class Example:
    """
    One prediction joined with its reference.

    Parameters
    ----------
    id : str
        Example id (from the predictions file).
    prediction : Any
        Model output.
    reference : Any
        Gold answer (inline in the predictions row, or joined from the dataset).
    meta : dict
        Extra fields from the predictions row.
    """

    id: str
    prediction: Any
    reference: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricResult:
    """
    What a metric function returns.

    Parameters
    ----------
    values : dict of str to float
        One or more values, e.g. ``{"k=1": 0.61, "k=5": 0.83}``. Use ``"value"``
        for single-valued metrics.
    per_example : dict of str to dict
        Optional per-example details keyed by example id, e.g.
        ``{"ex-3": {"correct": False}}``. Shown in the example browser.

    Examples
    --------
    >>> MetricResult(values={"value": 0.75}).values["value"]
    0.75
    """

    values: dict[str, float]
    per_example: dict[str, dict[str, Any]] = field(default_factory=dict)


def _is_number(x: object) -> bool:
    return isinstance(x, Real) and not isinstance(x, bool)


def normalize_result(raw: object) -> MetricResult:
    """
    Convert a metric function's return value into a ``MetricResult``.

    Parameters
    ----------
    raw : MetricResult, float, or dict of str to float

    Returns
    -------
    MetricResult

    Raises
    ------
    TypeError
        For any other type.

    Examples
    --------
    >>> normalize_result(0.5).values
    {'value': 0.5}
    """
    if isinstance(raw, MetricResult):
        return raw
    if _is_number(raw):
        return MetricResult(values={"value": float(raw)})  # type: ignore[arg-type]
    if isinstance(raw, dict) and raw and all(_is_number(v) for v in raw.values()):
        return MetricResult(values={str(k): float(v) for k, v in raw.items()})
    raise TypeError(f"metric returned {type(raw).__name__}; expected MetricResult, number, or dict")
```

- [ ] **Step 5: Implement `eval_worker.py`**

```python
"""Run metric functions inside a project's own Python environment.

Hypothex invokes this module as::

    python -m hypothex.eval_worker {evaluate|describe} --request REQ.json --out OUT.json

It must be importable in the project's environment, so it only uses the standard
library and light ``hypothex`` modules.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from hypothex.core.fsutil import atomic_write_text, read_jsonl
from hypothex.metrics import Example, normalize_result


def import_fn(ref: str) -> Any:
    """Import ``module:function``."""
    module_name, _, attr = ref.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def source_hash(fn: Any) -> str | None:
    """Return a short sha256 of the function's source, or None if unavailable."""
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return None
    return "sha256:" + hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


def load_examples(run_dir: Path, dataset: dict[str, Any] | None) -> list[Example]:
    """
    Load predictions and join references from the dataset when rows lack them.

    Raises
    ------
    FileNotFoundError
        If ``predictions/predictions.jsonl`` is missing.
    """
    path = run_dir / "predictions" / "predictions.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"no predictions at {path}")
    rows = [r for r in read_jsonl(path) if "id" in r]
    refs: dict[str, Any] = {}
    if dataset and any("reference" not in r for r in rows):
        id_field, ref_field = dataset["id_field"], dataset["reference_field"]
        for row in read_jsonl(Path(dataset["path"])):
            if id_field in row:
                refs[str(row[id_field])] = row.get(ref_field)
    return [
        Example(
            id=str(r["id"]),
            prediction=r.get("prediction"),
            reference=r["reference"] if "reference" in r else refs.get(str(r["id"])),
            meta=r.get("meta") or {},
        )
        for r in rows
    ]


def evaluate(request: dict[str, Any]) -> dict[str, Any]:
    """Run each requested metric; one metric failing does not stop the others."""
    sys.path.insert(0, request["repo"])
    run_dir = Path(request["run_dir"])
    examples = load_examples(run_dir, request.get("dataset"))
    results: list[dict[str, Any]] = []
    for m in request["metrics"]:
        entry: dict[str, Any] = {"name": m["name"], "version": m["version"], "values": {},
                                 "error": None, "source_hash": None}
        try:
            fn = import_fn(m["fn"])
            entry["source_hash"] = source_hash(fn)
            result = normalize_result(fn(examples, **m.get("params", {})))
            entry["values"] = result.values
            if result.per_example:
                out = run_dir / "predictions" / f"scores.{m['name']}@{m['version']}.jsonl"
                atomic_write_text(out, "".join(
                    json.dumps({"id": k, **v}, default=str) + "\n"
                    for k, v in result.per_example.items()
                ))
        except Exception:  # noqa: BLE001 - reported per metric
            entry["error"] = traceback.format_exc(limit=5)
        results.append(entry)
    return {"n_examples": len(examples), "results": results}


def describe(request: dict[str, Any]) -> dict[str, Any]:
    """Check that each metric imports and return its source hash."""
    sys.path.insert(0, request["repo"])
    out: dict[str, Any] = {}
    for m in request["metrics"]:
        try:
            fn = import_fn(m["fn"])
            out[m["name"]] = {"importable": True, "error": None, "source_hash": source_hash(fn)}
        except Exception as exc:  # noqa: BLE001
            out[m["name"]] = {"importable": False, "error": f"{type(exc).__name__}: {exc}",
                              "source_hash": None}
    return {"metrics": out}


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; writes the result JSON to ``--out``."""
    parser = argparse.ArgumentParser(prog="hypothex.eval_worker")
    parser.add_argument("action", choices=["evaluate", "describe"])
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    try:
        result = evaluate(request) if args.action == "evaluate" else describe(request)
    except Exception:  # noqa: BLE001
        result = {"fatal": traceback.format_exc(limit=5)}
    Path(args.out).write_text(json.dumps(result, default=str), encoding="utf-8")
    return 2 if "fatal" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Implement `core/evalrunner.py`**

```python
"""Host side of the metric worker subprocess."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import EvalError


def default_python_cmd(repo: Path, config: ProjectConfig) -> list[str]:
    """
    Return the command that runs Python in the project's environment.

    Returns
    -------
    list of str
        ``env.python`` from ``hypothex.yaml`` if set, else
        ``["uv", "run", "--project", <repo>, "python"]``.
    """
    if config.env.python:
        return list(config.env.python)
    return ["uv", "run", "--project", str(repo), "python"]


def run_worker(
    action: str,
    request: dict[str, Any],
    python_cmd: list[str],
    cwd: Path,
    timeout: float | None = None,
) -> dict[str, Any]:
    """
    Run ``hypothex.eval_worker`` in the project environment and return its result.

    Parameters
    ----------
    action : {"evaluate", "describe"}
    request : dict
        Worker request (see ``hypothex.eval_worker``).
    python_cmd : list of str
        Project Python command.
    cwd : Path
        Working directory (the repo).
    timeout : float, optional
        Seconds before giving up.

    Raises
    ------
    EvalError
        If the worker cannot start, produces no result, or reports a fatal error.
    """
    with tempfile.TemporaryDirectory(prefix="hx-eval-") as tmp:
        req = Path(tmp) / "request.json"
        out = Path(tmp) / "result.json"
        req.write_text(json.dumps(request, default=str), encoding="utf-8")
        cmd = [*python_cmd, "-m", "hypothex.eval_worker", action, "--request", str(req),
               "--out", str(out)]
        try:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EvalError(f"could not start the metric worker with {python_cmd!r}: {exc}") from exc
        if not out.is_file():
            raise EvalError(
                f"metric worker exited {proc.returncode} without a result; is hypothex installed "
                f"in the project environment? stderr: {proc.stderr[-2000:]}"
            )
        result = json.loads(out.read_text(encoding="utf-8"))
    if "fatal" in result:
        raise EvalError(result["fatal"])
    return result
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_worker.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/hypothex/metrics.py src/hypothex/eval_worker.py src/hypothex/core/evalrunner.py tests/factories.py tests/test_eval_worker.py
git commit -m "feat: metric contract and eval worker running in the project environment"
```

---

### Task 9: Seed groups and leaderboards

**Files:**
- Create: `src/hypothex/core/seeds.py`, `src/hypothex/core/leaderboard.py`
- Test: `tests/core/test_seeds.py`, `tests/core/test_leaderboard.py`

**Interfaces:**
- Consumes: Task 2 (`ProjectConfig`, `parse_metric_key`), Task 3 (`RunRecord`, `RunStatus`, `ScoreRecord`, `GitInfo`).
- Produces:
  - `hypothex.core.seeds`: `run_fingerprint(*, command_template: list[str], stage: str | None, user_config: dict | None, params: dict[str, str], vars: dict[str, str]) -> dict`; `config_hash(data: dict) -> str` (drops top-level `seed`, returns `sha256:<16 hex>`); `Stats(mean, std, n, ci_low, ci_high)`; `t_critical(df: int) -> float`; `summarize(values: list[float]) -> Stats`; `intervals_overlap(a: Stats, b: Stats) -> bool | None`.
  - `hypothex.core.leaderboard`: `LeaderboardRow(group_id, run_ids, latest_run_id, hypothesis, commit, config_hash, n, scores: dict[str, Stats], primary: Stats | None, single_seed, within_noise_of_best: bool | None)`; `Leaderboard(project, task, primary, higher_is_better, metric_versions: dict[str, str], rows, needs_reeval: list[str], unscored: list[str])`; `build_leaderboard(project, task, config, runs, scores, versions=None) -> Leaderboard`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_seeds.py`:

```python
import math

import pytest

from hypothex.core.seeds import config_hash, intervals_overlap, run_fingerprint, summarize


def test_config_hash_ignores_seed_and_key_order() -> None:
    assert config_hash({"lr": 1, "seed": 1}) == config_hash({"seed": 2, "lr": 1})
    assert config_hash({"lr": 1}) != config_hash({"lr": 2})
    assert config_hash({"a": 1}).startswith("sha256:")


def test_run_fingerprint_drops_seed_everywhere() -> None:
    a = run_fingerprint(command_template=["python", "t.py", "--seed", "{seed}"], stage=None,
                        user_config={"lr": 0.1, "seed": 1}, params={"seed": "1"}, vars={})
    b = run_fingerprint(command_template=["python", "t.py", "--seed", "{seed}"], stage=None,
                        user_config={"lr": 0.1, "seed": 7}, params={"seed": "7"}, vars={})
    assert config_hash(a) == config_hash(b)


def test_summarize_single_and_many() -> None:
    one = summarize([0.5])
    assert (one.mean, one.std, one.n, one.ci_low, one.ci_high) == (0.5, 0.0, 1, None, None)
    three = summarize([1.0, 2.0, 3.0])
    assert three.mean == 2.0 and three.std == 1.0 and three.n == 3
    half = 4.303 / math.sqrt(3)
    assert three.ci_low == pytest.approx(2.0 - half)
    assert three.ci_high == pytest.approx(2.0 + half)


def test_intervals_overlap() -> None:
    a = summarize([0.80, 0.82, 0.81])
    b = summarize([0.805, 0.815, 0.81])
    c = summarize([0.70, 0.71, 0.69])
    assert intervals_overlap(a, b) is True
    assert intervals_overlap(a, c) is False
    assert intervals_overlap(a, summarize([0.9])) is None
```

`tests/core/test_leaderboard.py`:

```python
from datetime import timedelta

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import build_leaderboard
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord
from tests.factories import make_record

CFG = ProjectConfig.model_validate({
    "project": "toy",
    "datasets": {"d": {"version": "v1", "path": "x"}},
    "metrics": {
        "acc": {"version": "v2", "fn": "m:acc"},
        "loss": {"version": "v1", "fn": "m:loss", "higher_is_better": False},
    },
    "tasks": {
        "t": {"dataset": "d", "metrics": ["acc"], "primary": "acc"},
        "tl": {"dataset": "d", "metrics": ["loss"], "primary": "loss"},
    },
})
T0 = utcnow()


def run(rid: str, group: str, *, task: str = "t", status: RunStatus = RunStatus.FINISHED,
        archived: bool = False, minute: int = 0) -> RunRecord:
    return make_record(rid, task=task, status=status, archived=archived,
                       config_hash=f"sha256:{group}", git=GitInfo(commit="c1"),
                       created_at=T0 + timedelta(minutes=minute))


def score(metric: str, value: float | None, version: str = "v2",
          error: str | None = None) -> ScoreRecord:
    return ScoreRecord(metric=metric, version=version, key="value", value=value, error=error,
                       created_at=utcnow())


def test_groups_sorts_and_flags() -> None:
    runs, scores = [], {}
    for i, v in enumerate([0.80, 0.82, 0.81]):
        runs.append(run(f"a{i}", "a", minute=i))
        scores[f"a{i}"] = [score("acc", v)]
    for i, v in enumerate([0.800, 0.805, 0.810]):  # mean 0.805, CI overlaps group a
        runs.append(run(f"b{i}", "b"))
        scores[f"b{i}"] = [score("acc", v)]
    for i, v in enumerate([0.70, 0.71, 0.69]):
        runs.append(run(f"c{i}", "c"))
        scores[f"c{i}"] = [score("acc", v)]
    runs += [run("stale", "d"), run("none", "e"), run("fail", "f", status=RunStatus.FAILED),
             run("arch", "g", archived=True)]
    scores["stale"] = [score("acc", 0.99, version="v1")]
    scores["fail"] = [score("acc", 1.0)]
    scores["arch"] = [score("acc", 1.0)]

    board = build_leaderboard("toy", "t", CFG, runs, scores)

    assert board.metric_versions == {"acc": "v2"} and board.primary == "acc/value"
    assert [r.config_hash for r in board.rows] == ["sha256:a", "sha256:b", "sha256:c"]
    best, second, third = board.rows
    assert best.n == 3 and best.latest_run_id == "a2" and not best.single_seed
    assert best.scores["acc/value"].mean == pytest.approx(0.81)
    assert second.within_noise_of_best is True
    assert third.within_noise_of_best is False
    assert board.needs_reeval == ["stale"]
    assert board.unscored == ["none"]


def test_lower_is_better() -> None:
    runs = [run("x", "x", task="tl"), run("y", "y", task="tl")]
    scores = {"x": [score("loss", 0.2, version="v1")], "y": [score("loss", 0.1, version="v1")]}
    board = build_leaderboard("toy", "tl", CFG, runs, scores)
    assert [r.run_ids for r in board.rows] == [["y"], ["x"]]
    assert board.rows[0].single_seed and board.rows[1].within_noise_of_best is None


def test_leaderboard_ignores_error_scores() -> None:
    runs = [run("ok", "a"), run("err", "b")]
    scores = {"ok": [score("acc", 0.5)], "err": [score("acc", None, error="Traceback...")]}
    board = build_leaderboard("toy", "t", CFG, runs, scores)
    assert [r.run_ids for r in board.rows] == [["ok"]]
    assert board.unscored == ["err"]


def test_version_override_and_latest_score_wins() -> None:
    runs = [run("r", "a")]
    scores = {"r": [score("acc", 0.1, version="v1"), score("acc", 0.3, version="v1")]}
    board = build_leaderboard("toy", "t", CFG, runs, scores, versions={"acc": "v1"})
    assert board.rows[0].scores["acc/value"].mean == 0.3
    assert board.metric_versions == {"acc": "v1"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_seeds.py tests/core/test_leaderboard.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `seeds.py`**

```python
"""Seed-invariant run fingerprints and small-sample statistics."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from typing import Any

from pydantic import BaseModel

# Two-sided 95% Student-t critical values by degrees of freedom.
_T_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
    9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120,
    17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def run_fingerprint(
    *,
    command_template: list[str],
    stage: str | None,
    user_config: dict[str, Any] | None,
    params: dict[str, str],
    vars: dict[str, str],
) -> dict[str, Any]:
    """
    Build the dict whose hash identifies a run's configuration, ignoring the seed.

    Returns
    -------
    dict
        Canonical description of what the run does.
    """
    return {
        "command": list(command_template),
        "stage": stage,
        "config": {k: v for k, v in (user_config or {}).items() if k != "seed"},
        "params": {k: v for k, v in params.items() if k != "seed"},
        "vars": dict(vars),
    }


def config_hash(data: dict[str, Any]) -> str:
    """
    Hash a configuration dict, ignoring a top-level ``seed`` key.

    Examples
    --------
    >>> config_hash({"lr": 1, "seed": 1}) == config_hash({"lr": 1, "seed": 2})
    True
    """
    payload = {k: v for k, v in data.items() if k != "seed"}
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class Stats(BaseModel):
    """Mean, sample std, count, and 95% t-interval of a seed group."""

    mean: float
    std: float
    n: int
    ci_low: float | None = None
    ci_high: float | None = None


def t_critical(df: int) -> float:
    """Return the two-sided 95% t critical value (1.96 beyond 30 df)."""
    return _T_975.get(df, 1.96)


def summarize(values: list[float]) -> Stats:
    """
    Summarize one group's values.

    Parameters
    ----------
    values : list of float
        At least one value.

    Returns
    -------
    Stats
        ``ci_low``/``ci_high`` are None when ``n == 1``.
    """
    n = len(values)
    mean = math.fsum(values) / n
    if n == 1:
        return Stats(mean=mean, std=0.0, n=1)
    std = statistics.stdev(values)
    half = t_critical(n - 1) * std / math.sqrt(n)
    return Stats(mean=mean, std=std, n=n, ci_low=mean - half, ci_high=mean + half)


def intervals_overlap(a: Stats, b: Stats) -> bool | None:
    """Return whether two 95% intervals overlap, or None if either has n < 2."""
    if a.ci_low is None or a.ci_high is None or b.ci_low is None or b.ci_high is None:
        return None
    return a.ci_low <= b.ci_high and b.ci_low <= a.ci_high
```

- [ ] **Step 4: Implement `leaderboard.py`**

```python
"""Rank seed groups of a task by its primary metric."""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from hypothex.core.config import ProjectConfig, parse_metric_key
from hypothex.core.records import RunRecord, RunStatus, ScoreRecord
from hypothex.core.seeds import Stats, intervals_overlap, summarize


class LeaderboardRow(BaseModel):
    """One seed group: runs with the same config hash and commit."""

    group_id: str
    run_ids: list[str]
    latest_run_id: str
    hypothesis: str
    commit: str | None
    config_hash: str
    n: int
    scores: dict[str, Stats]
    primary: Stats | None
    single_seed: bool
    within_noise_of_best: bool | None = None


class Leaderboard(BaseModel):
    """A task's ranked seed groups plus runs that need attention."""

    project: str
    task: str
    primary: str
    higher_is_better: bool
    metric_versions: dict[str, str]
    rows: list[LeaderboardRow]
    needs_reeval: list[str]
    unscored: list[str]


def build_leaderboard(
    project: str,
    task: str,
    config: ProjectConfig,
    runs: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    versions: dict[str, str] | None = None,
) -> Leaderboard:
    """
    Build a leaderboard for one task.

    Only finished, unarchived runs of the task count. Scores must match the
    selected metric version and have no error; the newest such score wins.

    Parameters
    ----------
    project, task : str
        Task identity.
    config : ProjectConfig
        Current project config (metric versions and direction).
    runs : list of RunRecord
        Candidate runs.
    scores : dict of str to list of ScoreRecord
        Scores per run id.
    versions : dict of str to str, optional
        Metric version overrides; default is each metric's current version.

    Returns
    -------
    Leaderboard
    """
    spec = config.tasks[task]
    chosen = {m: (versions or {}).get(m, config.metrics[m].version) for m in spec.metrics}
    primary_metric, primary_key = parse_metric_key(spec.primary)
    higher = config.metrics[primary_metric].higher_is_better
    eligible = [r for r in runs
                if r.task == task and r.status == RunStatus.FINISHED and not r.archived]

    per_run: dict[str, dict[str, float]] = {}
    needs_reeval: list[str] = []
    unscored: list[str] = []
    for r in eligible:
        run_scores = sorted(scores.get(r.run_id, []), key=lambda s: s.created_at)
        current: dict[tuple[str, str], float] = {}
        for s in run_scores:
            if (s.metric in chosen and s.version == chosen[s.metric] and s.error is None
                    and s.value is not None):
                current[(s.metric, s.key)] = s.value
        stale = any(s.metric in chosen and s.version != chosen[s.metric] for s in run_scores)
        missing_metric = any(all(m != k[0] for k in current) for m in chosen)
        if stale and missing_metric:
            needs_reeval.append(r.run_id)
        if current:
            per_run[r.run_id] = {f"{m}/{k}": v for (m, k), v in current.items()}
        elif not stale:
            unscored.append(r.run_id)

    groups: dict[tuple[str, str | None], list[RunRecord]] = defaultdict(list)
    for r in eligible:
        if r.run_id in per_run:
            groups[(r.config_hash, r.git.commit)].append(r)

    rows: list[LeaderboardRow] = []
    for (chash, commit), members in groups.items():
        members.sort(key=lambda r: (r.created_at, r.run_id))
        keys = sorted({k for m in members for k in per_run[m.run_id]})
        stats = {k: summarize([per_run[m.run_id][k] for m in members if k in per_run[m.run_id]])
                 for k in keys}
        latest = members[-1]
        rows.append(LeaderboardRow(
            group_id=f"{chash.removeprefix('sha256:')[:8]}@{(commit or 'nogit')[:7]}",
            run_ids=[m.run_id for m in members],
            latest_run_id=latest.run_id,
            hypothesis=latest.hypothesis,
            commit=commit,
            config_hash=chash,
            n=len(members),
            scores=stats,
            primary=stats.get(f"{primary_metric}/{primary_key}"),
            single_seed=len(members) == 1,
        ))

    def sort_key(row: LeaderboardRow) -> tuple[int, float]:
        if row.primary is None:
            return (1, 0.0)
        return (0, -row.primary.mean if higher else row.primary.mean)

    rows.sort(key=sort_key)
    if rows and rows[0].primary is not None:
        best = rows[0].primary
        for row in rows[1:]:
            if row.primary is not None:
                row.within_noise_of_best = intervals_overlap(row.primary, best)

    return Leaderboard(
        project=project,
        task=task,
        primary=f"{primary_metric}/{primary_key}",
        higher_is_better=higher,
        metric_versions=chosen,
        rows=rows,
        needs_reeval=needs_reeval,
        unscored=unscored,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_seeds.py tests/core/test_leaderboard.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/seeds.py src/hypothex/core/leaderboard.py tests/core/test_seeds.py tests/core/test_leaderboard.py
git commit -m "feat: seed-grouped leaderboards with 95% t-intervals"
```

---

### Task 10: Context (write path) and evaluation

**Files:**
- Create: `src/hypothex/core/context.py`, `src/hypothex/core/evaluation.py`, `tests/conftest.py`
- Modify: `tests/factories.py` (add `seed_finished_run`)
- Test: `tests/core/test_context.py`, `tests/core/test_evaluation.py`

**Interfaces:**
- Consumes: Tasks 1–9.
- Produces:
  - `hypothex.core.context.Context` (dataclass: `layout, store, index, events, descriptor`) with `open(home: Path | None = None) -> Context` (classmethod; creates dirs, rebuilds or gap-repairs the index), `find_record(run_id) -> RunRecord`, `run_dir(record) -> Path`, `register_project(repo: Path) -> ProjectEntry`, `create_run(record) -> RunRecord`, `update_run(run_id, event_type, mutate: Callable[[RunRecord], RunRecord], payload=None) -> RunRecord`, `add_score(record, score) -> None`, `emit(event_type, record, payload=None) -> None`.
  - `hypothex.core.evaluation`: `EvalReport(evaluated: list[str], skipped: dict[str, str], warnings: list[str])`; `ValidationReport(ok: bool, errors: list[str], warnings: list[str])`; `evaluate_run(ctx, run_id, *, metrics=None) -> tuple[list[ScoreRecord], list[str]]`; `reeval(ctx, *, run_id=None, project=None, task=None, metric=None, force=False) -> EvalReport`; `validate_project(ctx, repo) -> ValidationReport`.
  - `tests/conftest.py` fixtures: `home`, `ctx`, `toy_repo`.
  - `tests/factories.py`: `seed_finished_run(ctx, repo, run_id, *, task="toy-acc", predictions=None, config_hash="sha256:aaaa", commit="c1", seed=None) -> RunRecord`.

- [ ] **Step 1: Add fixtures and factory**

`tests/conftest.py`:

```python
from pathlib import Path

import pytest

from hypothex.core.context import Context
from tests.factories import write_toy_project


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "hxhome"
    monkeypatch.setenv("HYPOTHEX_HOME", str(h))
    monkeypatch.delenv("HYPOTHEX_AGENT", raising=False)
    return h


@pytest.fixture
def ctx(home: Path) -> Context:
    return Context.open(home)


@pytest.fixture
def toy_repo(tmp_path: Path) -> Path:
    return write_toy_project(tmp_path / "toy")
```

Append to `tests/factories.py` (add `from hypothex.core.context import Context` and `from hypothex.core.records import GitInfo` to the imports):

```python
def seed_finished_run(
    ctx: Context,
    repo: Path,
    run_id: str,
    *,
    task: str = "toy-acc",
    predictions: list[dict] | None = None,
    config_hash: str = "sha256:aaaa",
    commit: str | None = "c1",
    seed: int | None = None,
) -> RunRecord:
    """Register the project and create a finished run, optionally with predictions."""
    entry = ctx.register_project(repo)
    record = make_record(
        run_id, project=entry.project, task=task, status=RunStatus.FINISHED,
        config_hash=config_hash, git=GitInfo(commit=commit), seed=seed, cwd=str(repo),
        environment_id=ctx.descriptor.environment_id,
    )
    ctx.create_run(record)
    if predictions is not None:
        path = ctx.run_dir(record) / "predictions" / "predictions.jsonl"
        path.write_text("".join(json.dumps(p) + "\n" for p in predictions))
    return record
```

- [ ] **Step 2: Write the failing tests**

`tests/core/test_context.py`:

```python
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import RunNotFoundError
from hypothex.core.records import RunStatus
from tests.factories import make_record


def test_open_creates_layout_and_is_idempotent(home: Path) -> None:
    ctx = Context.open(home)
    assert ctx.layout.store.is_dir() and ctx.layout.index_db.is_file()
    assert Context.open(home).descriptor.environment_id == ctx.descriptor.environment_id


def test_create_and_update_run_write_file_event_and_index(ctx: Context) -> None:
    record = ctx.create_run(make_record("r1"))
    updated = ctx.update_run("r1", "run.started",
                             lambda r: r.model_copy(update={"status": RunStatus.RUNNING}))
    assert updated.status == RunStatus.RUNNING
    assert ctx.store.read_record("toy", "r1").status == RunStatus.RUNNING
    got = ctx.index.get_run("r1")
    assert got is not None and got.status == RunStatus.RUNNING
    assert [e.type for e in ctx.events.since(0)] == ["run.created", "run.started"]
    assert ctx.find_record("r1").run_id == record.run_id


def test_update_run_keeps_concurrent_curation(ctx: Context) -> None:
    ctx.create_run(make_record("r1"))
    ctx.update_run("r1", "run.tagged", lambda r: r.model_copy(update={"tags": ["keep"]}))
    ctx.update_run("r1", "run.finished",
                   lambda r: r.model_copy(update={"status": RunStatus.FINISHED}))
    assert ctx.find_record("r1").tags == ["keep"]


def test_open_repairs_index_gaps(home: Path) -> None:
    ctx = Context.open(home)
    ctx.store.create_run(make_record("orphan"))  # file written, index not
    assert Context.open(home).index.get_run("orphan") is not None


def test_open_rebuilds_deleted_index(home: Path) -> None:
    ctx = Context.open(home)
    ctx.create_run(make_record("r1"))
    ctx.layout.index_db.unlink()
    assert Context.open(home).index.get_run("r1") is not None


def test_find_record_unknown(ctx: Context) -> None:
    with pytest.raises(RunNotFoundError):
        ctx.find_record("nope")
```

`tests/core/test_evaluation.py`:

```python
from pathlib import Path

import pytest
import yaml

from hypothex.core.context import Context
from hypothex.core.errors import EvalError
from hypothex.core.evaluation import evaluate_run, reeval, validate_project
from tests.factories import PREDS_075, seed_finished_run, write_toy_project


def test_evaluate_run_scores_file_and_index(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    scores, warnings = evaluate_run(ctx, "r1")
    assert [(s.metric, s.version, s.key, s.value) for s in scores] == [
        ("accuracy", "v1", "value", 0.75)
    ]
    assert warnings == []
    assert ctx.store.read_scores("toy", "r1") == scores
    assert ctx.index.scores_for(["r1"])["r1"] == scores
    assert "run.score_added" in [e.type for e in ctx.events.since(0)]


def test_failing_metric_records_error_and_others_score(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", task="toy-broken", predictions=PREDS_075)
    scores, _ = evaluate_run(ctx, "r1")
    by_metric = {s.metric: s for s in scores}
    assert by_metric["accuracy"].value == 0.75
    assert by_metric["broken"].value is None and "boom" in (by_metric["broken"].error or "")


def test_reeval_skips_run_without_predictions(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_075)
    report = reeval(ctx, project="toy", task="toy-acc")
    assert report.evaluated == ["r2"]
    assert report.skipped == {"r1": "no predictions"}


def test_reeval_skips_already_scored_unless_forced(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    assert reeval(ctx, run_id="r1").evaluated == ["r1"]
    assert reeval(ctx, run_id="r1").skipped == {"r1": "already scored at the current version"}
    assert reeval(ctx, run_id="r1", force=True).evaluated == ["r1"]


def test_version_bump_rescores_and_keeps_old(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    write_toy_project(toy_repo, accuracy_version="v2")
    report = reeval(ctx, project="toy", task="toy-acc")
    assert report.evaluated == ["r1"]
    versions = [s.version for s in ctx.store.read_scores("toy", "r1")]
    assert versions == ["v1", "v2"]


def test_reeval_rejects_non_current_version(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    with pytest.raises(EvalError, match="only the current version"):
        reeval(ctx, run_id="r1", metric="accuracy@v9")


def test_metric_code_change_without_bump_warns(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    path = toy_repo / "toymetrics.py"
    path.write_text(path.read_text().replace(
        "def accuracy(examples):\n", "def accuracy(examples):\n    # tweak\n"))
    _, warnings = evaluate_run(ctx, "r1")
    assert any("without a version bump" in w for w in warnings)


def test_evaluate_removed_task_is_clear_error(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    cfg_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    del cfg["tasks"]["toy-acc"]
    cfg_path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(EvalError, match="no longer exists"):
        evaluate_run(ctx, "r1")


def test_validate_project(ctx: Context, toy_repo: Path) -> None:
    ok = validate_project(ctx, toy_repo)
    assert ok.ok and ok.errors == []
    cfg_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["metrics"]["broken"]["fn"] = "nomodule:fn"
    cfg["stages"]["infer"] += " --beam {beam}"
    cfg_path.write_text(yaml.safe_dump(cfg))
    bad = validate_project(ctx, toy_repo)
    assert not bad.ok
    assert any("nomodule" in e for e in bad.errors)
    assert any("beam" in w for w in bad.warnings)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_context.py tests/core/test_evaluation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.context'`.

- [ ] **Step 4: Implement `context.py`**

```python
"""Everything a Hypothex operation needs, plus the single write path for runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hypothex.core.config import load_project_config
from hypothex.core.environment import EnvironmentDescriptor, load_descriptor
from hypothex.core.events import EventLog
from hypothex.core.index import Index, rebuild_index, repair_index_gaps
from hypothex.core.layout import Layout, default_home
from hypothex.core.records import RunRecord, ScoreRecord
from hypothex.core.store import ProjectEntry, RunStore, run_lock


@dataclass
class Context:
    """
    Open handles to the store, index, event log, and environment identity.

    Use ``Context.open()``; all run state changes go through ``create_run``,
    ``update_run``, and ``add_score`` so files, events, and index stay in step.
    """

    layout: Layout
    store: RunStore
    index: Index
    events: EventLog
    descriptor: EnvironmentDescriptor

    @classmethod
    def open(cls, home: Path | None = None) -> Context:
        """
        Open (and if needed create) a Hypothex home.

        Parameters
        ----------
        home : Path, optional
            Home directory; defaults to ``default_home()``.

        Returns
        -------
        Context
        """
        layout = Layout((home or default_home()).expanduser().resolve())
        layout.ensure()
        store = RunStore(layout)
        index = Index(layout.index_db)
        ctx = cls(layout=layout, store=store, index=index, events=EventLog(layout.events_db),
                  descriptor=load_descriptor(layout))
        if index.rebuilt_schema:
            rebuild_index(index, store)
        else:
            repair_index_gaps(index, store)
        return ctx

    def find_record(self, run_id: str) -> RunRecord:
        """
        Read a run's current record from its file.

        Raises
        ------
        RunNotFoundError
            If the run does not exist.
        """
        indexed = self.index.get_run(run_id)
        project = indexed.project if indexed else self.store.find_project_of(run_id)
        return self.store.read_record(project, run_id)

    def run_dir(self, record: RunRecord) -> Path:
        """Return the run's folder."""
        return self.layout.run_dir(record.project, record.run_id)

    def register_project(self, repo: Path) -> ProjectEntry:
        """Load ``hypothex.yaml`` from ``repo`` and (re)register the project."""
        entry = self.store.register_project(load_project_config(repo), repo)
        self.index.upsert_project(entry)
        return entry

    def create_run(self, record: RunRecord) -> RunRecord:
        """Create the run folder, then emit ``run.created``, then index it."""
        self.store.create_run(record)
        self.events.append("run.created", project=record.project, run_id=record.run_id,
                           payload={"status": record.status.value})
        self.index.upsert_run(record)
        return record

    def update_run(
        self,
        run_id: str,
        event_type: str,
        mutate: Callable[[RunRecord], RunRecord],
        payload: dict[str, Any] | None = None,
    ) -> RunRecord:
        """
        Apply ``mutate`` to the on-disk record under the run lock.

        The fresh record is re-read inside the lock, so concurrent writers (for
        example tagging while the run finishes) never lose each other's changes.

        Returns
        -------
        RunRecord
            The written record.
        """
        project = self.find_record(run_id).project
        with run_lock(self.layout.run_dir(project, run_id)):
            updated = mutate(self.store.read_record(project, run_id))
            self.store.write_record(updated)
            self.events.append(event_type, project=project, run_id=run_id,
                               payload={"status": updated.status.value, **(payload or {})})
            self.index.upsert_run(updated)
        return updated

    def add_score(self, record: RunRecord, score: ScoreRecord) -> None:
        """Append a score to the file, emit ``run.score_added``, and index it."""
        with run_lock(self.run_dir(record)):
            self.store.append_score(record.project, record.run_id, score)
            self.events.append("run.score_added", project=record.project, run_id=record.run_id,
                               payload=score.model_dump(mode="json"))
            self.index.add_score(record.run_id, score)

    def emit(self, event_type: str, record: RunRecord, payload: dict[str, Any] | None = None) -> None:
        """Emit an informational event about a run (no state change)."""
        self.events.append(event_type, project=record.project, run_id=record.run_id,
                           payload=payload or {})
```

- [ ] **Step 5: Implement `evaluation.py`**

```python
"""Score runs with versioned metrics, re-evaluate, and validate projects."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from hypothex.core.config import (
    BUILTIN_TEMPLATE_VARS,
    CONFIG_FILENAME,
    ProjectConfig,
    TaskSpec,
    load_project_config,
    parse_metric_version,
    template_fields,
)
from hypothex.core.context import Context
from hypothex.core.datasets import resolve_dataset_path
from hypothex.core.errors import ConfigError, EvalError, NoPredictionsError
from hypothex.core.evalrunner import default_python_cmd, run_worker
from hypothex.core.ids import utcnow
from hypothex.core.records import RunRecord, RunStatus, ScoreRecord


class EvalReport(BaseModel):
    """Outcome of a re-evaluation over one or more runs."""

    evaluated: list[str] = Field(default_factory=list)
    skipped: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    """Outcome of ``hx validate``."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _task_setup(ctx: Context, record: RunRecord) -> tuple[Path, ProjectConfig, TaskSpec]:
    if record.task is None:
        raise EvalError(f"run {record.run_id} has no task; nothing to evaluate against")
    repo = Path(ctx.store.load_project(record.project).repo)
    config = load_project_config(repo)
    if record.task not in config.tasks:
        raise EvalError(f"task {record.task!r} no longer exists in {repo / CONFIG_FILENAME}")
    return repo, config, config.tasks[record.task]


def evaluate_run(
    ctx: Context, run_id: str, *, metrics: list[str] | None = None
) -> tuple[list[ScoreRecord], list[str]]:
    """
    Score one run with the current version of its task's metrics.

    Scores are appended; older scores are never changed.

    Parameters
    ----------
    ctx : Context
    run_id : str
    metrics : list of str, optional
        Subset of the task's metrics; default all.

    Returns
    -------
    scores : list of ScoreRecord
        New scores (an ``error`` row with key ``*`` for a metric that raised).
    warnings : list of str
        E.g. metric code changed without a version bump.

    Raises
    ------
    NoPredictionsError
        If the run has no predictions file.
    EvalError
        For any other evaluation failure.
    """
    record = ctx.find_record(run_id)
    repo, config, task = _task_setup(ctx, record)
    names = metrics or task.metrics
    unknown = [m for m in names if m not in task.metrics]
    if unknown:
        raise EvalError(f"metrics {unknown} are not part of task {record.task!r}")
    run_dir = ctx.run_dir(record)
    if not (run_dir / "predictions" / "predictions.jsonl").is_file():
        raise NoPredictionsError(f"run {run_id} has no predictions/predictions.jsonl")
    ds = config.datasets[task.dataset]
    dataset = None
    if ds.host in ("local", ctx.descriptor.label):
        path = resolve_dataset_path(repo, ds.path_for(task.split))
        if path.is_file():
            dataset = {"path": str(path), "id_field": ds.id_field,
                       "reference_field": ds.reference_field}
    request = {
        "repo": str(repo),
        "run_dir": str(run_dir),
        "dataset": dataset,
        "metrics": [{"name": n, "version": config.metrics[n].version, "fn": config.metrics[n].fn,
                     "params": config.metrics[n].params} for n in names],
    }
    result = run_worker("evaluate", request, default_python_cmd(repo, config), cwd=repo)
    now = utcnow()
    known = ctx.store.metric_hashes(record.project)
    scores: list[ScoreRecord] = []
    warnings: list[str] = []
    for r in result["results"]:
        ref = f"{r['name']}@{r['version']}"
        digest = r["source_hash"]
        if digest and ref in known and known[ref] != digest:
            warnings.append(f"metric {r['name']} code changed without a version bump "
                            f"(still {r['version']})")
        elif digest and ref not in known:
            known[ref] = digest
        if r["error"]:
            scores.append(ScoreRecord(metric=r["name"], version=r["version"], key="*",
                                      error=r["error"], source_hash=digest, created_at=now))
        scores.extend(
            ScoreRecord(metric=r["name"], version=r["version"], key=k, value=float(v),
                        source_hash=digest, created_at=now)
            for k, v in r["values"].items()
        )
    ctx.store.save_metric_hashes(record.project, known)
    for score in scores:
        ctx.add_score(record, score)
    return scores, warnings


def reeval(
    ctx: Context,
    *,
    run_id: str | None = None,
    project: str | None = None,
    task: str | None = None,
    metric: str | None = None,
    force: bool = False,
) -> EvalReport:
    """
    Re-score saved predictions without rerunning inference.

    Parameters
    ----------
    ctx : Context
    run_id : str, optional
        One run. Otherwise ``project`` and ``task`` select all finished runs.
    project, task : str, optional
    metric : str, optional
        ``name`` or ``name@version``; the version must be the current one.
    force : bool
        Re-score even runs already scored at the current version.

    Returns
    -------
    EvalReport
    """
    if run_id is not None:
        targets = [ctx.find_record(run_id)]
    elif project is not None and task is not None:
        targets = list(reversed(ctx.index.list_runs(project=project, task=task,
                                                     status=RunStatus.FINISHED,
                                                     include_archived=True, limit=None)))
    else:
        raise EvalError("give a run id, or a project and a task")
    report = EvalReport()
    if not targets:
        return report
    repo, config, task_spec = _task_setup(ctx, targets[0])
    names = task_spec.metrics
    if metric is not None:
        name, version = parse_metric_version(metric)
        if name not in task_spec.metrics:
            raise EvalError(f"metric {name!r} is not part of task {targets[0].task!r}")
        current = config.metrics[name].version
        if version is not None and version != current:
            raise EvalError(f"metric {name} is at {current} in {repo / CONFIG_FILENAME}; "
                            "only the current version can be computed")
        names = [name]
    wanted = {n: config.metrics[n].version for n in names}
    existing = ctx.index.scores_for([t.run_id for t in targets])
    for record in targets:
        have = existing.get(record.run_id, [])
        done = all(any(s.metric == n and s.version == v and s.error is None for s in have)
                   for n, v in wanted.items())
        if done and not force:
            report.skipped[record.run_id] = "already scored at the current version"
            continue
        try:
            _, warnings = evaluate_run(ctx, record.run_id, metrics=names)
        except NoPredictionsError:
            report.skipped[record.run_id] = "no predictions"
            continue
        except EvalError as exc:
            report.skipped[record.run_id] = str(exc)[:500]
            continue
        report.evaluated.append(record.run_id)
        report.warnings.extend(w for w in warnings if w not in report.warnings)
    return report


def validate_project(ctx: Context, repo: Path) -> ValidationReport:
    """
    Check a project's ``hypothex.yaml``, metric imports, and dataset paths.

    Returns
    -------
    ValidationReport
    """
    try:
        config = load_project_config(repo)
    except ConfigError as exc:
        return ValidationReport(ok=False, errors=[str(exc)])
    errors: list[str] = []
    warnings: list[str] = []
    for stage, template in config.stages.items():
        custom = template_fields(template) - BUILTIN_TEMPLATE_VARS
        if custom:
            warnings.append(f"stage {stage!r} uses custom variables {sorted(custom)}; "
                            "pass them with --var name=value")
    for name, spec in config.datasets.items():
        if spec.host not in ("local", ctx.descriptor.label):
            continue
        for raw in dict.fromkeys([spec.path, *spec.splits.values()]):
            path = resolve_dataset_path(repo, raw)
            if not path.exists():
                warnings.append(f"dataset {name!r}: path not found: {path}")
    if config.metrics:
        request = {"repo": str(repo),
                   "metrics": [{"name": n, "fn": m.fn} for n, m in config.metrics.items()]}
        try:
            described = run_worker("describe", request, default_python_cmd(repo, config),
                                   cwd=repo)["metrics"]
        except EvalError as exc:
            errors.append(f"could not run the metric worker: {exc}")
            described = {}
        known = ctx.store.metric_hashes(config.project)
        for name, info in described.items():
            spec = config.metrics[name]
            if not info["importable"]:
                errors.append(f"metric {name!r}: cannot import {spec.fn}: {info['error']}")
                continue
            ref = f"{name}@{spec.version}"
            if info["source_hash"] and known.get(ref) not in (None, info["source_hash"]):
                warnings.append(f"metric {name!r} code changed without a version bump "
                                f"(still {spec.version})")
    return ValidationReport(ok=not errors, errors=errors, warnings=warnings)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests -v`
Expected: all PASS (Tasks 1–10).

- [ ] **Step 7: Commit**

```bash
git add src/hypothex/core/context.py src/hypothex/core/evaluation.py tests/conftest.py tests/factories.py tests/core/test_context.py tests/core/test_evaluation.py
git commit -m "feat: context write path and versioned evaluation with re-eval"
```

---
### Task 11: Creating and executing runs (foreground)

**Files:**
- Create: `src/hypothex/core/execution.py`
- Test: `tests/core/test_execution.py`

**Interfaces:**
- Consumes: Tasks 1–10 (notably `Context`, `evaluate_run`, `capture_env`, `git_info`, `capture_diff`, `dataset_ref`, `run_fingerprint`, `config_hash`, `render_template`).
- Produces (`hypothex.core.execution`):
  - `STOP_MARKER = "stop_requested"`, `TERM_GRACE_SECONDS = 10.0`.
  - `RunRequest` dataclass: `repo: Path, command: list[str] | None = None, stage: str | None = None, task: str | None = None, hypothesis: str = "", seed: int | None = None, tags: list[str], config_path: Path | None = None, params: dict[str, str], vars: dict[str, str], kind: RunKind = FULL, parent: str | None = None, cwd: Path | None = None, created_by: str = "human"`. `command` is an argv template (may contain `{vars}`); when it is None, the stage template is used; `stage` alone is a label when `command` is given.
  - `process_create_time(pid: int) -> float | None`, `process_alive(pid: int | None, create_time: float | None) -> bool`, `terminate_group(pid: int, grace: float = TERM_GRACE_SECONDS) -> None`.
  - `prepare_run(ctx, req) -> RunRecord` (status `queued`; fails before creating any folder on bad input).
  - `execute_run(ctx, run_id, *, stdout_sink: BinaryIO | None = None, stderr_sink: BinaryIO | None = None, auto_evaluate: bool = True) -> RunRecord`.
  - Child process env: `HYPOTHEX_RUN_DIR`, `HYPOTHEX_RUN_ID`, `HYPOTHEX_PROJECT`, `HYPOTHEX_SEED` (if seed), `PYTHONUNBUFFERED=1`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_execution.py`:

```python
import sys
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import RunRequest, execute_run, prepare_run
from hypothex.core.records import RunStatus
from tests.factories import write_toy_project

PY = sys.executable
WRITE_PREDS = (
    "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
    "open(d + '/predictions/predictions.jsonl', 'w').write(''.join("
    "json.dumps({'id': f'ex-{i}', 'prediction': i % 2}) + '\\n' for i in range(4)))"
)


def cmd(code: str, *args: str) -> list[str]:
    return [PY, "-c", code, *args]


def run_fg(ctx: Context, req: RunRequest):
    return execute_run(ctx, prepare_run(ctx, req).run_id)


def test_foreground_run_finishes_with_logs(ctx: Context, toy_repo: Path) -> None:
    code = "import sys; print('hello'); print('warn', file=sys.stderr)"
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(code), hypothesis="smoke"))
    assert rec.status == RunStatus.QUEUED and rec.git.commit and rec.hypothesis == "smoke"
    done = execute_run(ctx, rec.run_id)
    assert done.status == RunStatus.FINISHED and done.exit_code == 0
    run_dir = ctx.run_dir(done)
    assert (run_dir / "logs" / "stdout.log").read_text().strip() == "hello"
    assert "warn" in (run_dir / "logs" / "stderr.log").read_text()
    assert (run_dir / "env" / "system.json").is_file()
    types = [e.type for e in ctx.events.since(0) if e.run_id == rec.run_id]
    assert types == ["run.created", "run.started", "run.finished"]


def test_failing_command_is_failed(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd("raise SystemExit(3)")))
    assert done.status == RunStatus.FAILED and done.exit_code == 3


def test_missing_command_fails_before_run_dir(ctx: Context, toy_repo: Path) -> None:
    with pytest.raises(RunError, match="command not found"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=["definitely-not-a-command-xyz"]))
    assert ctx.store.list_run_ids() == {}


def test_bad_task_and_missing_template_var(ctx: Context, toy_repo: Path) -> None:
    with pytest.raises(RunError, match="unknown task"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), task="nope"))
    with pytest.raises(RunError, match="checkpoint"):
        prepare_run(ctx, RunRequest(repo=toy_repo, stage="infer"))
    assert ctx.store.list_run_ids() == {}


def test_task_run_auto_evaluates(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(WRITE_PREDS), task="toy-acc"))
    scores = ctx.store.read_scores("toy", done.run_id)
    assert [(s.metric, s.value) for s in scores] == [("accuracy", 0.75)]
    assert done.datasets[0].name == "toyset" and done.datasets[0].hash_mode == "full"


def test_task_run_without_predictions_finishes_unscored(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd("print(1)"), task="toy-acc"))
    assert done.status == RunStatus.FINISHED
    assert ctx.store.read_scores("toy", done.run_id) == []
    skipped = [e for e in ctx.events.since(0) if e.type == "run.eval_skipped"]
    assert skipped and "predictions" in skipped[0].payload["reason"]


def test_seed_template_and_seed_group_hash(ctx: Context, toy_repo: Path) -> None:
    code = "import os, sys; print(sys.argv[1], os.environ['HYPOTHEX_SEED'])"
    a = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code, "{seed}"), seed=1))
    b = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code, "{seed}"), seed=2))
    assert a.command[-1] == "1" and b.command[-1] == "2"
    assert a.config_hash == b.config_hash
    assert (ctx.run_dir(b) / "logs" / "stdout.log").read_text().strip() == "2 2"


def test_non_git_repo_runs(ctx: Context, tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "plain", use_git=False)
    done = run_fg(ctx, RunRequest(repo=repo, command=cmd("print(1)")))
    assert done.status == RunStatus.FINISHED and done.git.commit is None


def test_config_file_is_copied(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("lr: 0.1\nseed: 1\n")
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(
        "import sys; print(open(sys.argv[1]).read())", "{config}"), config_path=cfg))
    assert "lr: 0.1" in (ctx.run_dir(done) / "config.yaml").read_text()
    assert "lr: 0.1" in (ctx.run_dir(done) / "logs" / "stdout.log").read_text()


def test_agent_requires_hypothesis(ctx: Context, toy_repo: Path,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPOTHEX_AGENT", "claude")
    with pytest.raises(RunError, match="hypothesis"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))


def test_logged_artifacts_and_metrics_are_ingested(ctx: Context, toy_repo: Path) -> None:
    code = (
        "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
        "open(d + '/artifacts.jsonl', 'a').write(json.dumps("
        "{'kind': 'checkpoint', 'path': '/tmp/m.pt'}) + '\\n'); "
        "open(d + '/metrics.jsonl', 'a').write(json.dumps("
        "{'name': 'loss', 'step': 0, 'value': 1.0}) + '\\n')"
    )
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code)))
    assert [(a.kind, a.path) for a in done.artifacts] == [("checkpoint", "/tmp/m.pt")]
    assert [p.name for p in ctx.index.metric_points(done.run_id)] == ["loss"]
    assert "checkpoint" in (ctx.run_dir(done) / "run.yaml").read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_execution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.execution'`.

- [ ] **Step 3: Implement `execution.py`**

```python
"""Create runs and execute them with full capture."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import psutil

from hypothex.core.config import load_project_config, render_template
from hypothex.core.context import Context
from hypothex.core.datasets import FingerprintCache, dataset_ref, resolve_dataset_path
from hypothex.core.envcapture import capture_env
from hypothex.core.errors import HypothexError, RunError, TemplateError
from hypothex.core.evalrunner import default_python_cmd
from hypothex.core.evaluation import evaluate_run
from hypothex.core.fsutil import atomic_write_text, read_yaml, write_yaml
from hypothex.core.gitinfo import capture_diff, git_info
from hypothex.core.ids import new_run_id, utcnow
from hypothex.core.records import ExecutorInfo, RunKind, RunRecord, RunStatus
from hypothex.core.seeds import config_hash, run_fingerprint

STOP_MARKER = "stop_requested"
TERM_GRACE_SECONDS = 10.0


@dataclass
class RunRequest:
    """
    Everything needed to create a run.

    ``command`` is an argv template that may contain ``{vars}``; if it is None
    the ``stage`` template from ``hypothex.yaml`` is used.
    """

    repo: Path
    command: list[str] | None = None
    stage: str | None = None
    task: str | None = None
    hypothesis: str = ""
    seed: int | None = None
    tags: list[str] = field(default_factory=list)
    config_path: Path | None = None
    params: dict[str, str] = field(default_factory=dict)
    vars: dict[str, str] = field(default_factory=dict)
    kind: RunKind = RunKind.FULL
    parent: str | None = None
    cwd: Path | None = None
    created_by: str = "human"


def process_create_time(pid: int) -> float | None:
    """Return a process's start time, or None if it does not exist."""
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def process_alive(pid: int | None, create_time: float | None) -> bool:
    """
    Return True if ``pid`` is running (not a zombie) and matches ``create_time``.

    Parameters
    ----------
    pid : int or None
    create_time : float or None
        Expected start time; guards against pid reuse. None skips the check.
    """
    if pid is None:
        return False
    try:
        proc = psutil.Process(pid)
        if create_time is not None and abs(proc.create_time() - create_time) > 1.0:
            return False
        return proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _signal_group(pid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def terminate_group(pid: int, grace: float = TERM_GRACE_SECONDS) -> None:
    """Send SIGTERM to a process group, then SIGKILL after ``grace`` seconds."""
    _signal_group(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not process_alive(pid, None):
            return
        time.sleep(0.1)
    _signal_group(pid, signal.SIGKILL)


def _executable_exists(argv0: str, cwd: Path) -> bool:
    if os.sep in argv0:
        path = Path(argv0)
        path = path if path.is_absolute() else cwd / path
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(argv0) is not None


def prepare_run(ctx: Context, req: RunRequest) -> RunRecord:
    """
    Validate a request, create the run folder, and capture git/env/dataset state.

    Nothing is created when the request is invalid.

    Parameters
    ----------
    ctx : Context
    req : RunRequest

    Returns
    -------
    RunRecord
        The new run with status ``queued``.

    Raises
    ------
    RunError
        Unknown task/stage, missing template value, command not found, or an
        agent run without a hypothesis.
    """
    repo = req.repo.resolve()
    config = load_project_config(repo)
    if req.task is not None and req.task not in config.tasks:
        raise RunError(f"unknown task {req.task!r}; known tasks: {sorted(config.tasks)}")
    if req.command is None:
        if req.stage is None:
            raise RunError("give a command or a stage")
        if req.stage not in config.stages:
            raise RunError(f"project has no stage {req.stage!r}; known stages: "
                           f"{sorted(config.stages)}")
        template = shlex.split(config.stages[req.stage])
    else:
        template = list(req.command)
    if not template:
        raise RunError("empty command")
    if os.environ.get("HYPOTHEX_AGENT") and not req.hypothesis.strip():
        raise RunError("agents must give a hypothesis (--hypothesis): why does this run exist?")
    if req.config_path is not None and not req.config_path.is_file():
        raise RunError(f"config file not found: {req.config_path}")
    user_config = read_yaml(req.config_path) if req.config_path is not None else None

    cwd = (req.cwd or repo).resolve()
    run_id = new_run_id(req.task)
    run_dir = ctx.layout.run_dir(config.project, run_id)
    values = {"run_id": run_id, "run_dir": str(run_dir), "repo": str(repo), "task": req.task or ""}
    if req.seed is not None:
        values["seed"] = str(req.seed)
    if req.config_path is not None:
        values["config"] = str(run_dir / "config.yaml")
    task_spec = config.tasks.get(req.task) if req.task else None
    if task_spec is not None:
        ds = config.datasets[task_spec.dataset]
        values.update({
            "dataset.name": task_spec.dataset,
            "dataset.version": ds.version,
            "dataset.path": str(resolve_dataset_path(repo, ds.path_for(task_spec.split))),
        })
    values.update(req.vars)
    try:
        argv = [render_template(part, values) for part in template]
    except TemplateError as exc:
        raise RunError(str(exc)) from exc
    if not _executable_exists(argv[0], cwd):
        raise RunError(f"command not found: {argv[0]}")

    entry = ctx.store.register_project(config, repo)
    ctx.index.upsert_project(entry)
    datasets = []
    if task_spec is not None:
        cache = FingerprintCache(ctx.layout.dataset_cache)
        datasets.append(dataset_ref(task_spec.dataset, config.datasets[task_spec.dataset],
                                    task_spec.split, repo, cache, ctx.descriptor.label))
    fingerprint = run_fingerprint(command_template=template, stage=req.stage,
                                  user_config=user_config, params=req.params, vars=req.vars)
    record = RunRecord(
        run_id=run_id, project=config.project, task=req.task, hypothesis=req.hypothesis.strip(),
        kind=req.kind, parent=req.parent, stage=req.stage, command=argv,
        command_template=template, vars=dict(req.vars), params=dict(req.params), cwd=str(cwd),
        environment_id=ctx.descriptor.environment_id, host=ctx.descriptor.label,
        executor=ExecutorInfo(pid=os.getpid(), pid_create_time=process_create_time(os.getpid())),
        git=git_info(cwd), datasets=datasets, seed=req.seed, config_hash=config_hash(fingerprint),
        status=RunStatus.QUEUED, created_at=utcnow(), tags=sorted(set(req.tags)),
        created_by=req.created_by,
    )
    ctx.create_run(record)
    if user_config is not None:
        write_yaml(run_dir / "config.yaml", user_config)
    diff = capture_diff(cwd)
    if diff.diff:
        atomic_write_text(run_dir / "git.diff", diff.diff)
    if diff.stat:
        atomic_write_text(run_dir / "git.stat", diff.stat)
    if diff.too_large:
        atomic_write_text(run_dir / "git.diff.too_large", "diff larger than the capture limit\n")
    capture_env(repo, run_dir / "env", default_python_cmd(repo, config))
    return record


def _pump(src: BinaryIO | None, log_path: Path, sink: BinaryIO | None) -> threading.Thread:
    def run() -> None:
        if src is None:
            return
        out = sink
        fd = src.fileno()
        with log_path.open("ab") as fh:
            while chunk := os.read(fd, 65536):
                fh.write(chunk)
                fh.flush()
                if out is not None:
                    try:
                        out.write(chunk)
                        out.flush()
                    except (OSError, ValueError):
                        out = None

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@dataclass
class _TermState:
    signalled: bool = False


@contextmanager
def _forward_termination(pid: int) -> Iterator[_TermState]:
    """Forward SIGTERM/SIGHUP to the child group (main thread only)."""
    state = _TermState()
    if threading.current_thread() is not threading.main_thread():
        yield state
        return

    def handler(signum: int, frame: object) -> None:
        state.signalled = True
        _signal_group(pid, signal.SIGTERM)
        timer = threading.Timer(TERM_GRACE_SECONDS, _signal_group, args=(pid, signal.SIGKILL))
        timer.daemon = True
        timer.start()

    previous = {sig: signal.signal(sig, handler) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield state
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


def execute_run(
    ctx: Context,
    run_id: str,
    *,
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
    auto_evaluate: bool = True,
) -> RunRecord:
    """
    Execute a queued run in this process and record the outcome.

    Output is written to ``logs/`` and optionally echoed to sinks. Ctrl-C,
    SIGTERM, SIGHUP, or a stop request end the run as ``killed``. A finished
    task run with predictions is scored automatically.

    Parameters
    ----------
    ctx : Context
    run_id : str
    stdout_sink, stderr_sink : binary file, optional
        Where to echo the child's output.
    auto_evaluate : bool
        Score finished task runs.

    Returns
    -------
    RunRecord
        The final record.
    """
    record = ctx.find_record(run_id)
    if record.status != RunStatus.QUEUED:
        raise RunError(f"run {run_id} is {record.status.value}, not queued")
    run_dir = ctx.run_dir(record)
    me = ExecutorInfo(pid=os.getpid(), pid_create_time=process_create_time(os.getpid()))
    if (run_dir / STOP_MARKER).exists():
        return ctx.update_run(run_id, "run.killed", lambda r: r.model_copy(update={
            "status": RunStatus.KILLED, "ended_at": utcnow(), "executor": me}),
            {"reason": "stopped before start"})
    env = {**os.environ, "HYPOTHEX_RUN_DIR": str(run_dir), "HYPOTHEX_RUN_ID": record.run_id,
           "HYPOTHEX_PROJECT": record.project, "PYTHONUNBUFFERED": "1"}
    if record.seed is not None:
        env["HYPOTHEX_SEED"] = str(record.seed)
    try:
        proc = subprocess.Popen(record.command, cwd=record.cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
    except OSError as exc:
        (run_dir / "logs" / "stderr.log").write_text(f"hypothex: could not start command: {exc}\n")
        now = utcnow()
        return ctx.update_run(run_id, "run.failed", lambda r: r.model_copy(update={
            "status": RunStatus.FAILED, "started_at": now, "ended_at": now, "exit_code": 127,
            "executor": me}), {"reason": str(exc)})

    started = me.model_copy(update={"child_pid": proc.pid})
    ctx.update_run(run_id, "run.started", lambda r: r.model_copy(update={
        "status": RunStatus.RUNNING, "started_at": utcnow(), "executor": started}))
    pumps = [_pump(proc.stdout, run_dir / "logs" / "stdout.log", stdout_sink),
             _pump(proc.stderr, run_dir / "logs" / "stderr.log", stderr_sink)]
    interrupted = False
    with _forward_termination(proc.pid) as term:
        try:
            exit_code = proc.wait()
        except KeyboardInterrupt:
            interrupted = True
            terminate_group(proc.pid)
            exit_code = proc.wait()
    for pump in pumps:
        pump.join()

    stopped = interrupted or term.signalled or (run_dir / STOP_MARKER).exists()
    if stopped:
        status = RunStatus.KILLED
    elif exit_code == 0:
        status = RunStatus.FINISHED
    else:
        status = RunStatus.FAILED
    logged = ctx.store.read_artifacts(record.project, record.run_id)
    ctx.index.replace_metric_points(record.run_id,
                                    ctx.store.read_metric_points(record.project, record.run_id))

    def finish(r: RunRecord) -> RunRecord:
        merged = {(a.kind, a.path): a for a in [*r.artifacts, *logged]}
        return r.model_copy(update={"status": status, "ended_at": utcnow(),
                                    "exit_code": exit_code, "artifacts": list(merged.values())})

    final = ctx.update_run(run_id, f"run.{status.value}", finish, {"exit_code": exit_code})
    if auto_evaluate and status == RunStatus.FINISHED and final.task:
        try:
            evaluate_run(ctx, run_id)
        except HypothexError as exc:  # the run itself finished; scoring can be retried
            ctx.emit("run.eval_skipped", final, {"reason": str(exc)[:500]})
    return ctx.find_record(run_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_execution.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/execution.py tests/core/test_execution.py
git commit -m "feat: create and execute runs with capture, stop handling, auto-evaluation"
```

---

### Task 12: Background launch, stop, rerun, re-infer, startup repair

**Files:**
- Create: `src/hypothex/core/control.py`, `src/hypothex/core/supervisor.py`
- Test: `tests/core/test_control.py`

**Interfaces:**
- Consumes: Task 11 (`RunRequest`, `prepare_run`, `execute_run`, `process_alive`, `process_create_time`, `terminate_group`, `STOP_MARKER`, `TERM_GRACE_SECONDS`), Task 6 (`head_commit`, `capture_diff`, `create_worktree`).
- Produces (`hypothex.core.control`):
  - `QUEUED_GRACE_SECONDS = 60.0`, `SUPERVISOR_PID_FILE = "supervisor.pid"`.
  - `launch_run(ctx, req) -> RunRecord` (returns immediately, status `queued` or later).
  - `wait_for_run(ctx, run_id, *, timeout=60.0, statuses=TERMINAL_STATUSES) -> RunRecord` (raises `RunError` on timeout).
  - `stop_run(ctx, run_id, *, grace=TERM_GRACE_SECONDS) -> RunRecord`.
  - `rerun(ctx, run_id, *, background=True, created_by="human", stdout_sink=None, stderr_sink=None) -> RunRecord`.
  - `reinfer(ctx, run_id, *, checkpoint=None, background=True, created_by="human", stdout_sink=None, stderr_sink=None) -> RunRecord`.
  - `repair_runs(ctx) -> list[RunRecord]` (runs marked `lost`).
  - `hypothex.core.supervisor.main(argv=None) -> int` (`python -m hypothex.core.supervisor <run_id> --home <home>`).

- [ ] **Step 1: Write the failing tests**

`tests/core/test_control.py`:

```python
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.control import launch_run, reinfer, repair_runs, rerun, stop_run, wait_for_run
from hypothex.core.errors import RunError
from hypothex.core.execution import RunRequest, execute_run, prepare_run, process_create_time
from hypothex.core.ids import utcnow
from hypothex.core.records import ExecutorInfo, RunKind, RunStatus
from tests.factories import git, make_record

PY = sys.executable


def cmd(code: str) -> list[str]:
    return [PY, "-c", code]


def dead_pid() -> int:
    proc = subprocess.Popen([PY, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_launch_run_in_background_finishes(ctx: Context, toy_repo: Path) -> None:
    rec = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("print('bg')"), hypothesis="bg"))
    done = wait_for_run(ctx, rec.run_id, timeout=60)
    assert done.status == RunStatus.FINISHED
    run_dir = ctx.run_dir(done)
    assert (run_dir / "logs" / "stdout.log").read_text().strip() == "bg"
    assert (run_dir / "supervisor.pid").is_file()


def test_stop_run_kills_background_run(ctx: Context, toy_repo: Path) -> None:
    rec = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("import time; time.sleep(60)")))
    wait_for_run(ctx, rec.run_id, timeout=30, statuses=frozenset({RunStatus.RUNNING}))
    start = time.monotonic()
    stopped = stop_run(ctx, rec.run_id)
    assert stopped.status == RunStatus.KILLED
    assert time.monotonic() - start < 15
    with pytest.raises(RunError, match="only queued or running"):
        stop_run(ctx, rec.run_id)


def test_rerun_same_commit_runs_in_place(ctx: Context, toy_repo: Path) -> None:
    parent = execute_run(ctx, prepare_run(ctx, RunRequest(
        repo=toy_repo, command=cmd("print('hi')"), hypothesis="h")).run_id)
    child = rerun(ctx, parent.run_id, background=False)
    assert child.parent == parent.run_id and child.status == RunStatus.FINISHED
    assert child.cwd == parent.cwd and child.config_hash == parent.config_hash
    assert child.hypothesis.startswith(f"Rerun of {parent.run_id}")


def test_rerun_after_new_commit_uses_worktree(ctx: Context, toy_repo: Path) -> None:
    (toy_repo / "marker.txt").write_text("old")
    git(toy_repo, "add", "marker.txt")
    git(toy_repo, "commit", "-qm", "marker old")
    parent = execute_run(ctx, prepare_run(ctx, RunRequest(
        repo=toy_repo, command=cmd("print(open('marker.txt').read())"))).run_id)
    (toy_repo / "marker.txt").write_text("new")
    git(toy_repo, "commit", "-qam", "marker new")
    child = rerun(ctx, parent.run_id, background=False)
    assert "worktrees" in child.cwd
    assert (ctx.run_dir(child) / "logs" / "stdout.log").read_text().strip() == "old"
    assert child.git.commit == parent.git.commit


def test_reinfer_uses_checkpoint_artifact(ctx: Context, toy_repo: Path) -> None:
    code = ("import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
            "open(d + '/artifacts.jsonl', 'a').write(json.dumps("
            "{'kind': 'checkpoint', 'path': '/tmp/model.pt'}) + '\\n')")
    parent = execute_run(ctx, prepare_run(ctx, RunRequest(
        repo=toy_repo, command=cmd(code), task="toy-acc")).run_id)
    child = reinfer(ctx, parent.run_id, background=False)
    assert child.kind == RunKind.INFER and child.vars["checkpoint"] == "/tmp/model.pt"
    assert "inferred with /tmp/model.pt" in (ctx.run_dir(child) / "logs" / "stdout.log").read_text()
    assert [s.value for s in ctx.store.read_scores("toy", child.run_id)] == [0.75]


def test_reinfer_without_checkpoint_errors(ctx: Context, toy_repo: Path) -> None:
    parent = execute_run(ctx, prepare_run(ctx, RunRequest(
        repo=toy_repo, command=cmd("pass"))).run_id)
    with pytest.raises(RunError, match="no checkpoint"):
        reinfer(ctx, parent.run_id, background=False)


def _active(ctx: Context, rid: str, status: RunStatus, pid: int, **kw: object) -> None:
    ctx.create_run(make_record(rid, status=status, environment_id=ctx.descriptor.environment_id,
                               executor=ExecutorInfo(pid=pid,
                                                     pid_create_time=process_create_time(pid)),
                               **kw))


def test_repair_marks_dead_running_as_lost(ctx: Context) -> None:
    _active(ctx, "dead", RunStatus.RUNNING, dead_pid())
    _active(ctx, "alive", RunStatus.RUNNING, os.getpid())
    lost = repair_runs(ctx)
    assert [r.run_id for r in lost] == ["dead"]
    assert ctx.find_record("dead").status == RunStatus.LOST
    assert ctx.find_record("alive").status == RunStatus.RUNNING


def test_repair_queued_uses_grace_period(ctx: Context) -> None:
    _active(ctx, "old", RunStatus.QUEUED, dead_pid(), created_at=utcnow() - timedelta(minutes=5))
    _active(ctx, "new", RunStatus.QUEUED, dead_pid())
    assert [r.run_id for r in repair_runs(ctx)] == ["old"]


def test_repair_ignores_other_environments(ctx: Context) -> None:
    ctx.create_run(make_record("other", status=RunStatus.RUNNING, environment_id="elsewhere",
                               executor=ExecutorInfo(pid=dead_pid())))
    assert repair_runs(ctx) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_control.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.core.control'`.

- [ ] **Step 3: Implement `supervisor.py`**

```python
"""Background run supervisor.

Started by ``launch_run`` as::

    python -m hypothex.core.supervisor <run_id> --home <hypothex home>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hypothex.core.context import Context
from hypothex.core.execution import execute_run
from hypothex.core.records import RunStatus


def main(argv: list[str] | None = None) -> int:
    """Execute one queued run; exit 0 if it finished, else 1."""
    parser = argparse.ArgumentParser(prog="hypothex.core.supervisor")
    parser.add_argument("run_id")
    parser.add_argument("--home", required=True)
    args = parser.parse_args(argv)
    ctx = Context.open(Path(args.home))
    record = execute_run(ctx, args.run_id)
    return 0 if record.status == RunStatus.FINISHED else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement `control.py`**

```python
"""Background launch, stop, rerun, re-infer, and startup repair."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import (
    STOP_MARKER,
    TERM_GRACE_SECONDS,
    RunRequest,
    execute_run,
    prepare_run,
    process_alive,
    process_create_time,
    terminate_group,
)
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.gitinfo import capture_diff, create_worktree, head_commit
from hypothex.core.ids import utcnow
from hypothex.core.records import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    RunKind,
    RunRecord,
    RunStatus,
)

QUEUED_GRACE_SECONDS = 60.0
SUPERVISOR_PID_FILE = "supervisor.pid"


def launch_run(ctx: Context, req: RunRequest) -> RunRecord:
    """
    Create a run and execute it in a detached supervisor process.

    Returns
    -------
    RunRecord
        The run as recorded right after launch.
    """
    record = prepare_run(ctx, req)
    run_dir = ctx.run_dir(record)
    with (run_dir / "logs" / "supervisor.log").open("ab") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "hypothex.core.supervisor", record.run_id,
             "--home", str(ctx.layout.home)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    atomic_write_text(run_dir / SUPERVISOR_PID_FILE, json.dumps(
        {"pid": proc.pid, "create_time": process_create_time(proc.pid)}))
    ctx.emit("run.launched", record, {"supervisor_pid": proc.pid})
    return ctx.find_record(record.run_id)


def wait_for_run(
    ctx: Context,
    run_id: str,
    *,
    timeout: float = 60.0,
    statuses: frozenset[RunStatus] = TERMINAL_STATUSES,
) -> RunRecord:
    """
    Poll until the run reaches one of ``statuses``.

    Raises
    ------
    RunError
        On timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        record = ctx.find_record(run_id)
        if record.status in statuses or record.status in TERMINAL_STATUSES:
            return record
        if time.monotonic() > deadline:
            raise RunError(f"run {run_id} still {record.status.value} after {timeout}s")
        time.sleep(0.1)


def _supervisor_alive(run_dir: Path, record: RunRecord) -> bool:
    if process_alive(record.executor.pid, record.executor.pid_create_time):
        return True
    pid_file = run_dir / SUPERVISOR_PID_FILE
    if record.status == RunStatus.QUEUED and pid_file.is_file():
        info = json.loads(pid_file.read_text(encoding="utf-8"))
        return process_alive(info["pid"], info.get("create_time"))
    return False


def _mark(status: RunStatus) -> Callable[[RunRecord], RunRecord]:
    def mutate(r: RunRecord) -> RunRecord:
        if r.status in TERMINAL_STATUSES:
            return r
        return r.model_copy(update={"status": status, "ended_at": utcnow()})

    return mutate


def stop_run(ctx: Context, run_id: str, *, grace: float = TERM_GRACE_SECONDS) -> RunRecord:
    """
    Stop a queued or running run; it ends as ``killed``.

    Raises
    ------
    RunError
        If the run is not queued or running.
    """
    record = ctx.find_record(run_id)
    if record.status not in ACTIVE_STATUSES:
        raise RunError(f"run {run_id} is {record.status.value}; "
                       "only queued or running runs can be stopped")
    run_dir = ctx.run_dir(record)
    atomic_write_text(run_dir / STOP_MARKER, utcnow().isoformat())
    child = record.executor.child_pid
    if record.status == RunStatus.RUNNING and child is not None and process_alive(child, None):
        terminate_group(child, grace)
    deadline = time.monotonic() + grace + 5
    while time.monotonic() < deadline:
        current = ctx.find_record(run_id)
        if current.status in TERMINAL_STATUSES:
            return current
        if not _supervisor_alive(run_dir, current):
            break
        time.sleep(0.1)
    return ctx.update_run(run_id, "run.killed", _mark(RunStatus.KILLED), {"reason": "stopped"})


def _start(
    ctx: Context,
    req: RunRequest,
    background: bool,
    stdout_sink: BinaryIO | None,
    stderr_sink: BinaryIO | None,
) -> RunRecord:
    if background:
        return launch_run(ctx, req)
    record = prepare_run(ctx, req)
    return execute_run(ctx, record.run_id, stdout_sink=stdout_sink, stderr_sink=stderr_sink)


def rerun(
    ctx: Context,
    run_id: str,
    *,
    background: bool = True,
    created_by: str = "human",
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
) -> RunRecord:
    """
    Run the same command, commit, config, seed, and vars again as a child run.

    If the repo is no longer at the recorded commit (or its uncommitted diff
    differs), the rerun executes in a fresh git worktree at the recorded commit
    with the saved diff applied.

    Raises
    ------
    RunError
        If the saved diff was too large to reproduce.
    """
    parent = ctx.find_record(run_id)
    repo = Path(ctx.store.load_project(parent.project).repo)
    parent_dir = ctx.run_dir(parent)
    if (parent_dir / "git.diff.too_large").exists():
        raise RunError(f"run {run_id} had an uncommitted diff too large to save; "
                       "it cannot be reproduced exactly")
    diff_file = parent_dir / "git.diff"
    saved_diff = diff_file.read_text(encoding="utf-8") if diff_file.is_file() else None
    cwd = Path(parent.cwd)
    if parent.git.commit is not None:
        same_tree = (head_commit(repo) == parent.git.commit
                     and capture_diff(repo).diff == saved_diff)
        if not same_tree:
            worktree = ctx.layout.worktrees_dir(parent.project) / (
                f"{parent.run_id}-{secrets.token_hex(3)}")
            create_worktree(repo, parent.git.commit, worktree, saved_diff)
            try:
                relative = cwd.relative_to(repo)
            except ValueError:
                relative = Path()
            cwd = worktree / relative
    config_file = parent_dir / "config.yaml"
    req = RunRequest(
        repo=repo, command=list(parent.command_template), stage=parent.stage, task=parent.task,
        hypothesis=f"Rerun of {parent.run_id}: {parent.hypothesis}".strip(),
        seed=parent.seed, tags=list(parent.tags),
        config_path=config_file if config_file.is_file() else None,
        params=dict(parent.params), vars=dict(parent.vars), kind=parent.kind,
        parent=parent.run_id, cwd=cwd, created_by=created_by,
    )
    return _start(ctx, req, background, stdout_sink, stderr_sink)


def reinfer(
    ctx: Context,
    run_id: str,
    *,
    checkpoint: str | None = None,
    background: bool = True,
    created_by: str = "human",
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
) -> RunRecord:
    """
    Run the project's ``infer`` stage with a run's checkpoint as a child run.

    Raises
    ------
    RunError
        If there is no ``infer`` stage or no checkpoint.
    """
    parent = ctx.find_record(run_id)
    repo = Path(ctx.store.load_project(parent.project).repo)
    config = load_project_config(repo)
    if "infer" not in config.stages:
        raise RunError("project has no `infer` stage in hypothex.yaml; add one to use re-infer")
    checkpoints = [a.path for a in parent.artifacts if a.kind == "checkpoint"]
    chosen = checkpoint or (checkpoints[-1] if checkpoints else None)
    if chosen is None:
        raise RunError(f"run {run_id} has no checkpoint artifact; pass --checkpoint PATH")
    req = RunRequest(
        repo=repo, stage="infer", task=parent.task,
        hypothesis=f"Re-infer of {parent.run_id}: {parent.hypothesis}".strip(),
        seed=parent.seed, tags=list(parent.tags), vars={**parent.vars, "checkpoint": chosen},
        kind=RunKind.INFER, parent=parent.run_id, created_by=created_by,
    )
    return _start(ctx, req, background, stdout_sink, stderr_sink)


def repair_runs(ctx: Context) -> list[RunRecord]:
    """
    Mark this environment's orphaned queued/running runs as ``lost``.

    A run is orphaned when its supervisor is gone (queued runs get a
    ``QUEUED_GRACE_SECONDS`` grace period). An orphaned child process is
    terminated so it does not run unrecorded.

    Returns
    -------
    list of RunRecord
        Runs that were marked lost.
    """
    lost: list[RunRecord] = []
    candidates = [r for status in ACTIVE_STATUSES
                  for r in ctx.index.list_runs(status=status, include_archived=True, limit=None)]
    for indexed in candidates:
        if indexed.environment_id != ctx.descriptor.environment_id:
            continue
        current = ctx.find_record(indexed.run_id)
        if current.status not in ACTIVE_STATUSES:
            ctx.index.upsert_run(current)
            continue
        if _supervisor_alive(ctx.run_dir(current), current):
            continue
        age = (utcnow() - current.created_at).total_seconds()
        if current.status == RunStatus.QUEUED and age < QUEUED_GRACE_SECONDS:
            continue
        reason = "supervisor exited without recording a result"
        child = current.executor.child_pid
        if child is not None and process_alive(child, None):
            terminate_group(child)
            reason += "; orphaned process terminated"
        lost.append(ctx.update_run(current.run_id, "run.lost", _mark(RunStatus.LOST),
                                   {"reason": reason}))
    return sorted(lost, key=lambda r: r.run_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_control.py -v`
Expected: PASS (background tests take a few seconds each).

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/core/control.py src/hypothex/core/supervisor.py tests/core/test_control.py
git commit -m "feat: background launch, stop, rerun via worktree, re-infer, startup repair"
```

---
### Task 13: Queries and curation (the shared read/write surface for CLI, API, MCP)

**Files:**
- Create: `src/hypothex/core/queries.py`
- Test: `tests/core/test_queries.py`

**Interfaces:**
- Consumes: Tasks 1–12.
- Produces (`hypothex.core.queries`):
  - Models: `TaskSummary(project, name, description, dataset, dataset_version, split, metrics: dict[str, str], primary, higher_is_better, n_runs, best: float | None)`; `RunDetail(record, scores, paths: dict[str, str], notes, has_diff, metric_names, children)`; `Comparison(run_ids, fields: dict[str, list[Any]], scores: dict[str, list[float | None]])`; `PredictionRow(id, prediction, reference, scores: dict[str, dict[str, Any]])`; `PredictionPage(run_id, total, offset, limit, rows)`; `ExampleDiff(a, b, metric, field, fixed, broken, both_pass, both_fail)`; `LogChunk(stream, text, offset, size)`.
  - Functions: `refresh_project(ctx, project) -> ProjectEntry`; `list_projects(ctx) -> list[ProjectEntry]`; `resolve_task(ctx, ref, project=None) -> tuple[ProjectEntry, str]` (`ref` may be `project/task`); `list_tasks(ctx, project=None) -> list[TaskSummary]`; `get_task(ctx, ref, project=None) -> dict`; `get_leaderboard(ctx, ref, project=None, versions=None) -> Leaderboard`; `show_run(ctx, run_id) -> RunDetail`; `metric_history(ctx, run_id) -> list[MetricPoint]`; `compare_runs(ctx, run_ids) -> Comparison`; `get_predictions(ctx, run_id, *, offset=0, limit=50, metric=None, failures_only=False, field="correct") -> PredictionPage`; `compare_examples(ctx, a, b, metric, field="correct") -> ExampleDiff`; `read_log(ctx, run_id, stream="stdout", offset=None) -> LogChunk`; `tag_run(ctx, run_id, add=(), remove=()) -> RunRecord`; `star_run(ctx, run_id, on=True) -> RunRecord`; `archive_run(ctx, run_id, on=True) -> RunRecord`; `add_note(ctx, run_id, text, author="human") -> None`; `check_datasets(ctx, project=None) -> list[DatasetDrift]`; `dataset_overlap(ctx, project, dataset, key_field=None) -> OverlapReport`.
  - Constants: `LOG_TAIL_BYTES = 8 * 1024 * 1024`, `LOG_TAIL_LINES = 5000`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_queries.py`:

```python
from pathlib import Path

import pytest
import yaml

from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.datasets import FingerprintCache
from hypothex.core.errors import ConfigError
from hypothex.core.evaluation import evaluate_run
from hypothex.core.records import DatasetRef
from tests.factories import PREDS_075, make_record, seed_finished_run, write_toy_project

ALL_RIGHT = [{"id": f"ex-{i}", "prediction": r} for i, r in enumerate([0, 1, 0, 0])]


def _set_project_name(repo: Path, name: str) -> None:
    path = repo / "hypothex.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["project"] = name
    path.write_text(yaml.safe_dump(cfg))


def test_resolve_task_and_ambiguity(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    ctx.register_project(toy_repo)
    assert q.resolve_task(ctx, "toy-acc")[1] == "toy-acc"
    assert q.resolve_task(ctx, "toy/toy-acc")[0].project == "toy"
    with pytest.raises(ConfigError, match="unknown task"):
        q.resolve_task(ctx, "nope")
    other = write_toy_project(tmp_path / "toy2", use_git=False)
    _set_project_name(other, "toy2")
    ctx.register_project(other)
    with pytest.raises(ConfigError, match="several projects"):
        q.resolve_task(ctx, "toy-acc")


def test_list_tasks_reports_best(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    summaries = {t.name: t for t in q.list_tasks(ctx)}
    assert summaries["toy-acc"].best == 0.75 and summaries["toy-acc"].n_runs == 1
    assert summaries["toy-acc"].metrics == {"accuracy": "v1"}


def test_leaderboard_reflects_yaml_version_bump(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    write_toy_project(toy_repo, accuracy_version="v2")
    board = q.get_leaderboard(ctx, "toy-acc")
    assert board.metric_versions == {"accuracy": "v2"}
    assert board.needs_reeval == ["r1"] and board.rows == []


def test_show_run_paths_children_and_removed_task(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    ctx.create_run(make_record("r2", parent="r1"))
    detail = q.show_run(ctx, "r1")
    assert detail.paths["repo"] == str(toy_repo.resolve())
    assert detail.paths["run_dir"].endswith("/runs/r1")
    assert detail.children == ["r2"]
    cfg_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    del cfg["tasks"]["toy-acc"]
    cfg_path.write_text(yaml.safe_dump(cfg))
    assert q.show_run(ctx, "r1").record.task == "toy-acc"


def test_compare_runs(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    ctx.create_run(make_record("a", params={"lr": "0.1"}, seed=1))
    ctx.create_run(make_record("b", params={"lr": "0.2"}, seed=1))
    cmp = q.compare_runs(ctx, ["a", "b"])
    assert cmp.fields == {"params.lr": ["0.1", "0.2"]}
    with pytest.raises(Exception, match="at least two"):
        q.compare_runs(ctx, ["a"])


def test_predictions_page_and_failures(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    page = q.get_predictions(ctx, "r1")
    assert page.total == 4 and page.rows[1].reference == 1
    assert page.rows[0].scores["accuracy@v1"]["correct"] is True
    fails = q.get_predictions(ctx, "r1", failures_only=True)
    assert [r.id for r in fails.rows] == ["ex-3"]
    assert q.get_predictions(ctx, "r1", offset=3, limit=5).rows[0].id == "ex-3"


def test_compare_examples(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "b", predictions=ALL_RIGHT)
    evaluate_run(ctx, "a")
    evaluate_run(ctx, "b")
    diff = q.compare_examples(ctx, "a", "b", "accuracy")
    assert diff.metric == "accuracy@v1"
    assert diff.fixed == ["ex-3"] and diff.broken == [] and diff.both_pass == 3


def test_curation(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    assert q.tag_run(ctx, "r1", add=["x", "y"]).tags == ["x", "y"]
    assert q.tag_run(ctx, "r1", remove=["x"]).tags == ["y"]
    assert q.star_run(ctx, "r1").starred
    q.add_note(ctx, "r1", "promising", author="agent:claude")
    assert "promising" in q.show_run(ctx, "r1").notes
    q.archive_run(ctx, "r1")
    assert ctx.index.list_runs() == []
    types = [e.type for e in ctx.events.since(0)]
    assert {"run.tagged", "run.starred", "run.note_added", "run.archived"} <= set(types)


def test_read_log_tail_and_offset(ctx: Context, toy_repo: Path) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    log = ctx.run_dir(rec) / "logs" / "stdout.log"
    log.write_text("a\nb\n")
    first = q.read_log(ctx, "r1")
    assert first.text == "a\nb\n" and first.offset == 4
    with log.open("a") as fh:
        fh.write("c\n")
    assert q.read_log(ctx, "r1", offset=first.offset).text == "c\n"


def test_check_datasets(ctx: Context, toy_repo: Path) -> None:
    data = toy_repo / "data" / "test.jsonl"
    fp = FingerprintCache(ctx.layout.dataset_cache).fingerprint(data)
    ctx.register_project(toy_repo)
    ctx.create_run(make_record("r1", datasets=[DatasetRef(
        name="toyset", version="v1", path=str(data), hash=fp.hash, hash_mode=fp.mode)]))
    assert [d.status for d in q.check_datasets(ctx)] == ["ok"]
    data.write_text(data.read_text() + '{"id": "ex-9", "reference": 1}\n')
    assert [d.status for d in q.check_datasets(ctx)] == ["changed"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_queries.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `queries.py`**

```python
"""Read models and curation actions shared by the CLI, API, and MCP server."""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hypothex.core.config import load_project_config, parse_metric_version
from hypothex.core.context import Context
from hypothex.core.datasets import (
    DatasetDrift,
    FingerprintCache,
    OverlapReport,
    check_runs,
    overlap,
    resolve_dataset_path,
)
from hypothex.core.errors import ConfigError, EvalError, RunError, StoreError
from hypothex.core.fsutil import read_jsonl, read_yaml
from hypothex.core.leaderboard import Leaderboard, build_leaderboard
from hypothex.core.records import MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.store import ProjectEntry

LOG_TAIL_BYTES = 8 * 1024 * 1024
LOG_TAIL_LINES = 5000
LOG_STREAMS = ("stdout", "stderr", "supervisor")


class TaskSummary(BaseModel):
    """A task with its current metric versions and best primary value."""

    project: str
    name: str
    description: str
    dataset: str
    dataset_version: str
    split: str | None
    metrics: dict[str, str]
    primary: str
    higher_is_better: bool
    n_runs: int
    best: float | None


class RunDetail(BaseModel):
    """Everything about one run, including where every file lives."""

    record: RunRecord
    scores: list[ScoreRecord]
    paths: dict[str, str]
    notes: str
    has_diff: bool
    metric_names: list[str]
    children: list[str]


class Comparison(BaseModel):
    """Differences between two or more runs."""

    run_ids: list[str]
    fields: dict[str, list[Any]]
    scores: dict[str, list[float | None]]


class PredictionRow(BaseModel):
    """One example with its per-example scores."""

    id: str
    prediction: Any = None
    reference: Any = None
    scores: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PredictionPage(BaseModel):
    """A page of predictions."""

    run_id: str
    total: int
    offset: int
    limit: int
    rows: list[PredictionRow]


class ExampleDiff(BaseModel):
    """Which examples one run fixed or broke relative to another."""

    a: str
    b: str
    metric: str
    field: str
    fixed: list[str]
    broken: list[str]
    both_pass: int
    both_fail: int


class LogChunk(BaseModel):
    """A slice of a run log; pass ``offset`` back to continue."""

    stream: str
    text: str
    offset: int
    size: int


# projects and tasks ----------------------------------------------------------
def refresh_project(ctx: Context, project: str) -> ProjectEntry:
    """
    Re-read a project's ``hypothex.yaml`` so views use the current config.

    Falls back to the stored snapshot when the repo is gone or the file is invalid.
    """
    entry = ctx.store.load_project(project)
    try:
        return ctx.register_project(Path(entry.repo))
    except ConfigError:
        return entry


def list_projects(ctx: Context) -> list[ProjectEntry]:
    """Return all projects with a refreshed config snapshot."""
    return [refresh_project(ctx, e.project) for e in ctx.store.list_projects()]


def resolve_task(ctx: Context, ref: str, project: str | None = None) -> tuple[ProjectEntry, str]:
    """
    Find a task by ``task`` or ``project/task``.

    Raises
    ------
    ConfigError
        Unknown or ambiguous task.
    """
    if project is None and "/" in ref:
        project, ref = ref.split("/", 1)
    entries = [refresh_project(ctx, project)] if project else list_projects(ctx)
    matches = [e for e in entries if ref in e.config.tasks]
    if not matches:
        where = f" in project {project!r}" if project else ""
        raise ConfigError(f"unknown task {ref!r}{where}")
    if len(matches) > 1:
        names = ", ".join(sorted(e.project for e in matches))
        raise ConfigError(f"task {ref!r} exists in several projects ({names}); use project/task")
    return matches[0], ref


def get_leaderboard(
    ctx: Context, ref: str, project: str | None = None, versions: dict[str, str] | None = None
) -> Leaderboard:
    """Build the leaderboard of a task from indexed runs and scores."""
    entry, task = resolve_task(ctx, ref, project)
    runs = ctx.index.list_runs(project=entry.project, task=task, include_archived=True,
                               limit=None)
    scores = ctx.index.scores_for(r.run_id for r in runs)
    return build_leaderboard(entry.project, task, entry.config, runs, scores, versions)


def _summary(ctx: Context, entry: ProjectEntry, name: str) -> TaskSummary:
    spec = entry.config.tasks[name]
    board = get_leaderboard(ctx, name, entry.project)
    best = board.rows[0].primary.mean if board.rows and board.rows[0].primary else None
    n_runs = len(ctx.index.list_runs(project=entry.project, task=name,
                                     status=RunStatus.FINISHED, limit=None))
    return TaskSummary(
        project=entry.project, name=name, description=spec.description, dataset=spec.dataset,
        dataset_version=entry.config.datasets[spec.dataset].version, split=spec.split,
        metrics={m: entry.config.metrics[m].version for m in spec.metrics},
        primary=board.primary, higher_is_better=board.higher_is_better, n_runs=n_runs, best=best,
    )


def list_tasks(ctx: Context, project: str | None = None) -> list[TaskSummary]:
    """Summarize every task, optionally for one project."""
    entries = [refresh_project(ctx, project)] if project else list_projects(ctx)
    return [_summary(ctx, e, name) for e in entries for name in sorted(e.config.tasks)]


def get_task(ctx: Context, ref: str, project: str | None = None) -> dict[str, Any]:
    """Return a task's summary plus its dataset, metric, and stage definitions."""
    entry, name = resolve_task(ctx, ref, project)
    spec = entry.config.tasks[name]
    return {
        "summary": _summary(ctx, entry, name).model_dump(mode="json"),
        "repo": entry.repo,
        "dataset": {"name": spec.dataset,
                    **entry.config.datasets[spec.dataset].model_dump(mode="json")},
        "metrics": {m: entry.config.metrics[m].model_dump(mode="json") for m in spec.metrics},
        "stages": entry.config.stages,
    }


# runs ----------------------------------------------------------------------------
def show_run(ctx: Context, run_id: str) -> RunDetail:
    """Return a run with its scores, notes, children, and all file paths."""
    record = ctx.find_record(run_id)
    run_dir = ctx.run_dir(record)
    paths = {
        "run_dir": str(run_dir),
        "cwd": record.cwd,
        "stdout": str(run_dir / "logs" / "stdout.log"),
        "stderr": str(run_dir / "logs" / "stderr.log"),
        "predictions": str(run_dir / "predictions"),
        "env": str(run_dir / "env"),
    }
    try:
        paths["repo"] = ctx.store.load_project(record.project).repo
    except StoreError:
        pass
    if (run_dir / "config.yaml").is_file():
        paths["config"] = str(run_dir / "config.yaml")
    for ref in record.datasets:
        paths[f"dataset:{ref.name}"] = f"{ref.host}:{ref.path}"
    for i, art in enumerate(record.artifacts):
        paths[f"artifact:{art.kind}:{i}"] = f"{art.host}:{art.path}"
    children = [r.run_id for r in ctx.index.list_runs(project=record.project,
                                                       include_archived=True, limit=None)
                if r.parent == run_id]
    return RunDetail(
        record=record,
        scores=ctx.store.read_scores(record.project, run_id),
        paths=paths,
        notes=ctx.store.read_notes(record.project, run_id),
        has_diff=(run_dir / "git.diff").is_file(),
        metric_names=sorted({p.name for p in ctx.index.metric_points(run_id)}),
        children=sorted(children),
    )


def metric_history(ctx: Context, run_id: str) -> list[MetricPoint]:
    """Return a run's indexed (downsampled) metric history."""
    ctx.find_record(run_id)
    return ctx.index.metric_points(run_id)


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}", v, out)
    else:
        out[prefix] = value


def compare_runs(ctx: Context, run_ids: list[str]) -> Comparison:
    """
    Compare runs: only fields that differ, plus the latest score per metric version.

    Raises
    ------
    RunError
        With fewer than two runs.
    """
    if len(run_ids) < 2:
        raise RunError("compare needs at least two runs")
    records = [ctx.find_record(r) for r in run_ids]
    flat: list[dict[str, Any]] = []
    for rec in records:
        f: dict[str, Any] = {"task": rec.task, "commit": rec.git.commit, "seed": rec.seed,
                             "stage": rec.stage, "command": shlex.join(rec.command_template),
                             "hypothesis": rec.hypothesis}
        _flatten("params", rec.params, f)
        _flatten("vars", rec.vars, f)
        cfg = ctx.run_dir(rec) / "config.yaml"
        if cfg.is_file():
            _flatten("config", read_yaml(cfg), f)
        flat.append(f)
    keys = sorted(set().union(*flat))
    fields = {k: [f.get(k) for f in flat] for k in keys
              if len({json.dumps(f.get(k), sort_keys=True, default=str) for f in flat}) > 1}
    all_scores = ctx.index.scores_for(run_ids)
    latest: list[dict[str, float | None]] = []
    for rid in run_ids:
        row: dict[str, float | None] = {}
        for s in sorted(all_scores.get(rid, []), key=lambda s: s.created_at):
            if s.error is None:
                row[f"{s.metric}@{s.version}/{s.key}"] = s.value
        latest.append(row)
    score_keys = sorted(set().union(*latest))
    return Comparison(run_ids=run_ids, fields=fields,
                      scores={k: [row.get(k) for row in latest] for k in score_keys})


def _references(ctx: Context, record: RunRecord) -> dict[str, Any]:
    if record.task is None:
        return {}
    try:
        repo = Path(ctx.store.load_project(record.project).repo)
        config = load_project_config(repo)
        spec = config.tasks[record.task]
    except (StoreError, ConfigError, KeyError):
        return {}
    ds = config.datasets[spec.dataset]
    path = resolve_dataset_path(repo, ds.path_for(spec.split))
    return {str(r[ds.id_field]): r.get(ds.reference_field)
            for r in read_jsonl(path) if ds.id_field in r}


def _per_example(run_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted((run_dir / "predictions").glob("scores.*.jsonl")):
        ref = path.name[len("scores."):-len(".jsonl")]
        out[ref] = {str(r["id"]): {k: v for k, v in r.items() if k != "id"}
                    for r in read_jsonl(path) if "id" in r}
    return out


def _is_failure(value: Any) -> bool:
    return value is False or (isinstance(value, int | float) and value == 0)


def get_predictions(
    ctx: Context,
    run_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
    metric: str | None = None,
    failures_only: bool = False,
    field: str = "correct",
) -> PredictionPage:
    """
    Page through a run's predictions with references and per-example scores.

    Parameters
    ----------
    metric : str, optional
        ``name`` or ``name@version`` to limit which per-example scores are shown.
    failures_only : bool
        Keep rows where ``field`` is False or 0 in a shown metric.
    field : str
        Per-example field that marks success.

    Raises
    ------
    EvalError
        ``failures_only`` without any per-example scores.
    """
    record = ctx.find_record(run_id)
    run_dir = ctx.run_dir(record)
    per = _per_example(run_dir)
    if metric is not None:
        per = {k: v for k, v in per.items() if k == metric or k.split("@")[0] == metric}
    refs = _references(ctx, record)
    rows = [
        PredictionRow(
            id=str(r["id"]),
            prediction=r.get("prediction"),
            reference=r["reference"] if "reference" in r else refs.get(str(r["id"])),
            scores={m: d.get(str(r["id"]), {}) for m, d in per.items()},
        )
        for r in read_jsonl(run_dir / "predictions" / "predictions.jsonl") if "id" in r
    ]
    if failures_only:
        if not per:
            raise EvalError("no per-example scores for this run; run `hx reeval` first")
        rows = [row for row in rows
                if any(field in s and _is_failure(s[field]) for s in row.scores.values())]
    return PredictionPage(run_id=run_id, total=len(rows), offset=offset, limit=limit,
                          rows=rows[offset: offset + limit])


def compare_examples(ctx: Context, a: str, b: str, metric: str,
                     field: str = "correct") -> ExampleDiff:
    """
    List examples fixed (fail in ``a``, pass in ``b``) and broken (the reverse).

    Parameters
    ----------
    metric : str
        ``name`` (current version) or ``name@version``.
    """
    rec_a = ctx.find_record(a)
    name, version = parse_metric_version(metric)
    if version is None:
        version = refresh_project(ctx, rec_a.project).config.metrics[name].version
    ref = f"{name}@{version}"
    passed: list[dict[str, bool]] = []
    for rid in (a, b):
        per = _per_example(ctx.run_dir(ctx.find_record(rid))).get(ref)
        if per is None:
            raise EvalError(f"run {rid} has no per-example scores for {ref}")
        passed.append({i: not _is_failure(v.get(field)) for i, v in per.items() if field in v})
    pa, pb = passed
    ids = sorted(pa.keys() & pb.keys())
    return ExampleDiff(
        a=a, b=b, metric=ref, field=field,
        fixed=[i for i in ids if not pa[i] and pb[i]],
        broken=[i for i in ids if pa[i] and not pb[i]],
        both_pass=sum(1 for i in ids if pa[i] and pb[i]),
        both_fail=sum(1 for i in ids if not pa[i] and not pb[i]),
    )


def read_log(ctx: Context, run_id: str, stream: str = "stdout",
             offset: int | None = None) -> LogChunk:
    """
    Read a run log. Without ``offset``: the tail (last 5,000 lines / 8 MiB).

    With ``offset``: new bytes since that offset (up to 8 MiB).
    """
    if stream not in LOG_STREAMS:
        raise RunError(f"unknown log stream {stream!r}; use one of {LOG_STREAMS}")
    path = ctx.run_dir(ctx.find_record(run_id)) / "logs" / f"{stream}.log"
    size = path.stat().st_size if path.is_file() else 0
    start = max(0, size - LOG_TAIL_BYTES) if offset is None else min(offset, size)
    data = b""
    if size:
        with path.open("rb") as fh:
            fh.seek(start)
            data = fh.read(LOG_TAIL_BYTES)
    text = data.decode("utf-8", errors="replace")
    if offset is None:
        text = "".join(text.splitlines(keepends=True)[-LOG_TAIL_LINES:])
    return LogChunk(stream=stream, text=text, offset=start + len(data), size=size)


# curation -------------------------------------------------------------------------
def tag_run(ctx: Context, run_id: str, add: Iterable[str] = (),
            remove: Iterable[str] = ()) -> RunRecord:
    """Add and remove tags."""
    add_set, remove_set = set(add), set(remove)
    return ctx.update_run(run_id, "run.tagged", lambda r: r.model_copy(
        update={"tags": sorted((set(r.tags) | add_set) - remove_set)}))


def star_run(ctx: Context, run_id: str, on: bool = True) -> RunRecord:
    """Star or unstar a run."""
    return ctx.update_run(run_id, "run.starred",
                          lambda r: r.model_copy(update={"starred": on}), {"on": on})


def archive_run(ctx: Context, run_id: str, on: bool = True) -> RunRecord:
    """Archive (hide) or unarchive a run."""
    return ctx.update_run(run_id, "run.archived",
                          lambda r: r.model_copy(update={"archived": on}), {"on": on})


def add_note(ctx: Context, run_id: str, text: str, author: str = "human") -> None:
    """Append a note to a run."""
    record = ctx.find_record(run_id)
    ctx.store.append_note(record.project, run_id, text, author)
    ctx.emit("run.note_added", record, {"author": author})


# datasets --------------------------------------------------------------------------
def check_datasets(ctx: Context, project: str | None = None) -> list[DatasetDrift]:
    """Re-fingerprint datasets used by runs and report drift."""
    records = ctx.index.list_runs(project=project, include_archived=True, limit=None)
    return check_runs(records, FingerprintCache(ctx.layout.dataset_cache))


def dataset_overlap(ctx: Context, project: str, dataset: str,
                    key_field: str | None = None) -> OverlapReport:
    """Count examples shared between a dataset's splits."""
    entry = refresh_project(ctx, project)
    if dataset not in entry.config.datasets:
        raise ConfigError(f"project {project!r} has no dataset {dataset!r}")
    return overlap(dataset, entry.config.datasets[dataset], Path(entry.repo), key_field)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_queries.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/core/queries.py tests/core/test_queries.py
git commit -m "feat: query layer, example browser data, curation actions"
```

---
### Task 14: Python SDK (`import hypothex as hx`)

**Files:**
- Create: `src/hypothex/sdk.py`
- Modify: `src/hypothex/__init__.py`
- Test: `tests/test_sdk.py`

**Interfaces:**
- Consumes: Task 1 (`append_jsonl`, `append_note_file`), Task 8 (`Example`, `MetricResult`).
- Produces: `hypothex.current() -> Run | NoopRun`; `hypothex.seed(default: int | None = None) -> int | None`; `Run(run_dir: Path, run_id: str, project: str)` with `active = True`, `log(values, step=None) -> None`, `log_predictions(rows) -> int`, `log_artifact(path, kind="file", host="local") -> None`, `note(text) -> None`; `NoopRun` with the same methods, `active = False`, `run_dir = None`, `run_id = None`. Package re-exports: `Example, MetricResult, NoopRun, Run, current, seed, __version__`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sdk.py`:

```python
import json
from pathlib import Path

import pytest

import hypothex as hx
from hypothex import sdk


@pytest.fixture
def run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "predictions").mkdir(parents=True)
    monkeypatch.setenv("HYPOTHEX_RUN_DIR", str(run_dir))
    monkeypatch.setenv("HYPOTHEX_RUN_ID", "r1")
    monkeypatch.setenv("HYPOTHEX_PROJECT", "toy")
    monkeypatch.setenv("HYPOTHEX_SEED", "7")
    monkeypatch.setattr(sdk, "_current", None)
    return run_dir


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_noop_outside_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPOTHEX_RUN_DIR", raising=False)
    monkeypatch.delenv("HYPOTHEX_SEED", raising=False)
    run = hx.current()
    assert isinstance(run, hx.NoopRun) and not run.active and run.run_id is None
    run.log({"loss": 1.0})
    assert run.log_predictions([{"id": "a", "prediction": 1}]) == 0
    run.log_artifact("/x")
    run.note("n")
    assert hx.seed() is None and hx.seed(3) == 3


def test_log_auto_and_explicit_steps(run_env: Path) -> None:
    run = hx.current()
    assert isinstance(run, hx.Run) and run.run_id == "r1" and run.project == "toy"
    run.log({"loss": 1.0, "acc": 0.5})
    hx.current().log({"loss": 0.5})  # same object: step continues
    run.log({"loss": 0.1}, step=100)
    rows = _lines(run_env / "metrics.jsonl")
    assert [(r["name"], r["step"]) for r in rows] == [("loss", 0), ("acc", 0), ("loss", 1),
                                                      ("loss", 100)]
    assert hx.seed() == 7


def test_log_predictions_validates_rows(run_env: Path) -> None:
    run = hx.current()
    assert run.log_predictions([{"id": "a", "prediction": 1}, {"id": 2, "prediction": [0]}]) == 2
    assert _lines(run_env / "predictions" / "predictions.jsonl")[1] == {"id": 2, "prediction": [0]}
    with pytest.raises(ValueError, match="'id' and 'prediction'"):
        run.log_predictions([{"prediction": 1}])


def test_log_artifact_and_note(run_env: Path, tmp_path: Path) -> None:
    ckpt = tmp_path / "m.pt"
    ckpt.write_bytes(b"12345")
    run = hx.current()
    run.log_artifact(ckpt, kind="checkpoint")
    row = _lines(run_env / "artifacts.jsonl")[0]
    assert row == {"kind": "checkpoint", "path": str(ckpt.resolve()), "host": "local", "size": 5}
    run.note("loss spikes at 9k")
    assert "loss spikes at 9k" in (run_env / "notes.md").read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sdk.py -v`
Expected: FAIL with `AttributeError: module 'hypothex' has no attribute 'current'`.

- [ ] **Step 3: Implement `sdk.py`**

```python
"""SDK used inside a run started by ``hx run`` / ``hx launch``.

Examples
--------
>>> import hypothex as hx
>>> run = hx.current()          # a no-op outside Hypothex, so code runs unchanged
>>> run.log({"loss": 0.41})
>>> run.log_predictions([{"id": "ex-1", "prediction": 1}])
0
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hypothex.core.fsutil import append_jsonl, append_note_file


class Run:
    """
    Handle to the current run's folder.

    Parameters
    ----------
    run_dir : Path
        The run folder (``$HYPOTHEX_RUN_DIR``).
    run_id : str
        Run id.
    project : str
        Project name.
    """

    active = True

    def __init__(self, run_dir: Path, run_id: str, project: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.project = project
        self._steps: dict[str, int] = {}

    def log(self, values: Mapping[str, float], step: int | None = None) -> None:
        """
        Log metric values; each name gets its own auto-incrementing step.

        Parameters
        ----------
        values : mapping of str to float
            E.g. ``{"loss": 0.41}``.
        step : int, optional
            Explicit step for all values.
        """
        now = time.time()
        for name, value in values.items():
            s = step if step is not None else self._steps.get(name, -1) + 1
            self._steps[name] = s
            append_jsonl(self.run_dir / "metrics.jsonl",
                         {"name": name, "step": s, "value": float(value), "t": now})

    def log_predictions(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """
        Append prediction rows to ``predictions/predictions.jsonl``.

        Each row needs ``id`` and ``prediction``; ``reference`` and ``meta`` are optional.

        Returns
        -------
        int
            Number of rows written.

        Raises
        ------
        ValueError
            If a row lacks ``id`` or ``prediction``.
        """
        path = self.run_dir / "predictions" / "predictions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                if "id" not in row or "prediction" not in row:
                    raise ValueError("each prediction row needs 'id' and 'prediction'")
                fh.write(json.dumps(dict(row), default=str) + "\n")
                count += 1
        return count

    def log_artifact(self, path: str | os.PathLike[str], kind: str = "file",
                     host: str = "local") -> None:
        """
        Record a large file by path (it is not copied).

        Parameters
        ----------
        path : path-like
            File location.
        kind : str
            E.g. ``checkpoint``; re-infer uses the last ``checkpoint``.
        host : str
            Where the file lives.
        """
        resolved = Path(path).expanduser().resolve()
        size = resolved.stat().st_size if resolved.is_file() else None
        append_jsonl(self.run_dir / "artifacts.jsonl",
                     {"kind": kind, "path": str(resolved), "host": host, "size": size})

    def note(self, text: str) -> None:
        """Append a note to the run's ``notes.md``."""
        append_note_file(self.run_dir / "notes.md", text, "sdk")


class NoopRun:
    """Stand-in used outside Hypothex: every method does nothing."""

    active = False
    run_dir: Path | None = None
    run_id: str | None = None
    project: str | None = None

    def log(self, values: Mapping[str, float], step: int | None = None) -> None:
        """Do nothing."""

    def log_predictions(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """Do nothing and return 0."""
        return 0

    def log_artifact(self, path: str | os.PathLike[str], kind: str = "file",
                     host: str = "local") -> None:
        """Do nothing."""

    def note(self, text: str) -> None:
        """Do nothing."""


_current: Run | None = None


def current() -> Run | NoopRun:
    """
    Return the run started by Hypothex, or a ``NoopRun`` outside one.

    The same ``Run`` object is returned on repeated calls, so auto steps continue.
    """
    global _current
    run_dir = os.environ.get("HYPOTHEX_RUN_DIR")
    if not run_dir:
        return NoopRun()
    if _current is None or str(_current.run_dir) != run_dir:
        _current = Run(Path(run_dir), os.environ.get("HYPOTHEX_RUN_ID", ""),
                       os.environ.get("HYPOTHEX_PROJECT", ""))
    return _current


def seed(default: int | None = None) -> int | None:
    """Return ``--seed`` passed to ``hx run`` (``$HYPOTHEX_SEED``), else ``default``."""
    raw = os.environ.get("HYPOTHEX_SEED")
    return int(raw) if raw else default
```

`src/hypothex/__init__.py`:

```python
"""Hypothex: experiment tracker and control panel for AI researchers and their agents."""

from hypothex._version import __version__
from hypothex.metrics import Example, MetricResult
from hypothex.sdk import NoopRun, Run, current, seed

__all__ = ["Example", "MetricResult", "NoopRun", "Run", "__version__", "current", "seed"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sdk.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/sdk.py src/hypothex/__init__.py tests/test_sdk.py
git commit -m "feat: in-run Python SDK"
```

---

### Task 15: The `hx` CLI

**Files:**
- Create: `src/hypothex/cli/__init__.py` (empty), `src/hypothex/cli/main.py`
- Test: `tests/cli/__init__.py` (empty), `tests/cli/test_cli.py`

**Interfaces:**
- Consumes: Tasks 10–13 (`Context`, `prepare_run`, `execute_run`, `launch_run`, `wait_for_run`, `rerun`, `reinfer`, `stop_run`, `repair_runs`, `reeval`, `validate_project`, `rebuild_index`, `queries`).
- Produces: Typer `app` and console entry `cli()` (`hx`). Commands: `init, validate, projects, tasks, task show, leaderboard, runs, show, run, launch, rerun, reinfer, reeval, stop, compare, examples, predictions, logs, tag, star, archive, note, datasets check, datasets overlap, reindex, repair, serve, mcp`. Every command accepts `--json`. Global options: `--home` (env `HYPOTHEX_HOME`), `--version`. `created_by` is `agent:$HYPOTHEX_AGENT` when that env var is set, else `human`.

- [ ] **Step 1: Write the failing tests**

`tests/cli/test_cli.py`:

```python
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypothex.cli.main import app, cli
from hypothex.core.errors import RunError
from tests.factories import write_toy_project

runner = CliRunner()
PY = sys.executable
WRITE_PREDS = (
    "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
    "open(d + '/predictions/predictions.jsonl', 'w').write(''.join("
    "json.dumps({'id': f'ex-{i}', 'prediction': i % 2}) + '\\n' for i in range(4)))"
)


def hx(*args: str) -> dict | list:
    argv = list(args)
    argv.insert(argv.index("--") if "--" in argv else len(argv), "--json")
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.fixture
def in_repo(toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(toy_repo)
    return toy_repo


def _run(seed: int = 1, code: str = WRITE_PREDS) -> dict:
    out = hx("run", "-t", "toy-acc", "-H", "baseline", "--seed", str(seed), "--", PY, "-c", code)
    assert isinstance(out, dict)
    return out


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and result.stdout.strip()


def test_init_refuses_overwrite(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = hx("init", "--project", "demo")
    assert Path(out["path"]).read_text().startswith("# Hypothex project file")
    with pytest.raises(RunError, match="exists"):
        runner.invoke(app, ["init"], catch_exceptions=False)


def test_validate_ok(in_repo: Path) -> None:
    assert hx("validate")["ok"] is True


def test_run_json_status_and_exit_code(in_repo: Path) -> None:
    out = _run()
    assert out["status"] == "finished" and out["task"] == "toy-acc"
    result = runner.invoke(app, ["run", "--json", "--", PY, "-c", "raise SystemExit(3)"])
    assert result.exit_code == 3
    assert json.loads(result.stdout)["status"] == "failed"


def test_read_commands(in_repo: Path) -> None:
    a = _run(1)
    b = _run(2)
    board = hx("leaderboard", "toy-acc")
    assert len(board["rows"]) == 1 and board["rows"][0]["n"] == 2
    assert {r["run_id"] for r in hx("runs")} == {a["run_id"], b["run_id"]}
    detail = hx("show", a["run_id"])
    assert detail["paths"]["repo"] == str(in_repo.resolve())
    assert hx("compare", a["run_id"], b["run_id"])["fields"]["seed"] == [1, 2]
    assert hx("tasks")[0]["project"] == "toy"
    assert hx("projects")[0]["project"] == "toy"
    assert hx("task", "show", "toy-acc")["dataset"]["name"] == "toyset"
    assert hx("predictions", a["run_id"], "--failures")["rows"][0]["id"] == "ex-3"
    assert hx("examples", a["run_id"], b["run_id"], "--metric", "accuracy")["both_pass"] == 3
    assert "text" in hx("logs", a["run_id"])


def test_reeval_after_version_bump(in_repo: Path) -> None:
    _run()
    write_toy_project(in_repo, accuracy_version="v2")
    assert len(hx("leaderboard", "toy-acc")["needs_reeval"]) == 1
    assert len(hx("reeval", "--task", "toy-acc")["evaluated"]) == 1
    assert hx("leaderboard", "toy-acc")["metric_versions"] == {"accuracy": "v2"}


def test_curation_commands(in_repo: Path) -> None:
    rid = _run()["run_id"]
    assert hx("tag", rid, "--add", "ablation")["tags"] == ["ablation"]
    assert hx("star", rid)["starred"] is True
    hx("note", rid, "works")
    assert "works" in hx("show", rid)["notes"]
    assert hx("archive", rid)["archived"] is True
    assert hx("runs") == []


def test_launch_wait_and_rerun(in_repo: Path) -> None:
    out = hx("launch", "--wait", "-H", "bg", "--", PY, "-c", "print('bg')")
    assert out["status"] == "finished"
    child = hx("rerun", out["run_id"], "--foreground")
    assert child["parent"] == out["run_id"] and child["status"] == "finished"


def test_agent_requires_hypothesis(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPOTHEX_AGENT", "claude")
    with pytest.raises(RunError, match="hypothesis"):
        runner.invoke(app, ["run", "--", PY, "-c", "pass"], catch_exceptions=False)


def test_reindex_and_repair_and_datasets(in_repo: Path) -> None:
    _run()
    assert hx("reindex")["runs"] == 1
    assert hx("repair")["lost"] == []
    assert [d["status"] for d in hx("datasets", "check")] == ["ok"]
    assert hx("datasets", "overlap", "toy", "toyset")["pairs"] == {}


def test_cli_errors_are_json(home: Path, monkeypatch: pytest.MonkeyPatch,
                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["hx", "show", "nope", "--json"])
    with pytest.raises(SystemExit) as exc:
        cli()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["type"] == "RunNotFoundError"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.cli'`.

- [ ] **Step 3: Implement `cli/main.py`**

```python
"""The ``hx`` command-line interface. Every command supports ``--json``."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import BaseModel

from hypothex._version import __version__
from hypothex.core import queries as q
from hypothex.core.config import CONFIG_FILENAME, find_repo_root, parse_metric_version, starter_config
from hypothex.core.context import Context
from hypothex.core.control import launch_run, reinfer, repair_runs, rerun, stop_run, wait_for_run
from hypothex.core.errors import HypothexError, RunError
from hypothex.core.evaluation import reeval, validate_project
from hypothex.core.execution import RunRequest, execute_run, prepare_run
from hypothex.core.index import rebuild_index
from hypothex.core.records import TERMINAL_STATUSES, RunRecord, RunStatus

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="Hypothex: experiment tracker and control panel for AI researchers "
                       "and their agents.")
task_app = typer.Typer(no_args_is_help=True, help="Inspect tasks.")
datasets_app = typer.Typer(no_args_is_help=True, help="Dataset fingerprints and checks.")
app.add_typer(task_app, name="task")
app.add_typer(datasets_app, name="datasets")

JsonFlag = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]
ProjectOpt = Annotated[str | None, typer.Option("--project", "-p", help="Project name.")]
WAIT_FOREVER = 7 * 24 * 3600.0


class _State:
    home: Path | None = None


_state = _State()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    home: Annotated[Path | None, typer.Option("--home", envvar="HYPOTHEX_HOME",
                                              help="Hypothex home directory.")] = None,
    version: Annotated[bool, typer.Option("--version", callback=_version_callback,
                                          is_eager=True, help="Show the version.")] = False,
) -> None:
    """Hypothex: experiment tracker and control panel for AI researchers and their agents."""
    _state.home = home


# helpers --------------------------------------------------------------------------
def _ctx() -> Context:
    return Context.open(_state.home)


def _dump(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_dump(v) for v in obj]
    return obj


def _print_json(obj: Any) -> None:
    typer.echo(json.dumps(_dump(obj), indent=2, default=str))


def _table(headers: list[str], rows: list[list[Any]]) -> None:
    cells = [[str(c) if c is not None else "—" for c in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h)
              for i, h in enumerate(headers)]
    typer.secho("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)), bold=True)
    for row in cells:
        typer.echo("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))


def _pairs(values: list[str] | None, flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise RunError(f"{flag} must look like name=value, got {item!r}")
        out[key] = value
    return out


def _created_by() -> str:
    agent = os.environ.get("HYPOTHEX_AGENT")
    return f"agent:{agent}" if agent else "human"


def _stats(s: Any) -> str:
    if s is None:
        return "—"
    return f"{s.mean:.4f} ± {s.std:.4f} (n={s.n})"


def _request(
    argv: list[str], *, task: str | None, hypothesis: str | None, seed: int | None,
    tags: list[str] | None, config: Path | None, params: list[str] | None,
    variables: list[str] | None, stage: str | None, repo: Path | None, interactive: bool,
) -> RunRequest:
    root = (repo or find_repo_root(Path.cwd())).resolve()
    if not argv and stage is None:
        raise RunError("give a command after `--`, or --stage NAME")
    hyp = hypothesis
    if (hyp is None and interactive and sys.stdin.isatty()
            and not os.environ.get("HYPOTHEX_AGENT")):
        hyp = typer.prompt("Hypothesis (why does this run exist?)", default="",
                           show_default=False)
    return RunRequest(
        repo=root, command=list(argv) or None, stage=stage, task=task, hypothesis=hyp or "",
        seed=seed, tags=tags or [], config_path=config.resolve() if config else None,
        params=_pairs(params, "--param"), vars=_pairs(variables, "--var"),
        cwd=Path.cwd() if repo is None else None, created_by=_created_by(),
    )


def _finish(record: RunRecord, as_json: bool) -> None:
    if as_json:
        _print_json(record)
    else:
        for ref in record.datasets:
            if ref.hash_mode == "missing":
                typer.secho(f"warning: dataset {ref.name} not found at {ref.path}", fg="yellow",
                            err=True)
        typer.secho(f"{record.status.value} (exit {record.exit_code}) {record.run_id}",
                    fg="green" if record.status == RunStatus.FINISHED else "red", err=True)
    if record.status in TERMINAL_STATUSES and record.status != RunStatus.FINISHED:
        raise typer.Exit(record.exit_code or 1)


RUN_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}
TaskOpt = Annotated[str | None, typer.Option("--task", "-t", help="Task this run belongs to.")]
HypOpt = Annotated[str | None, typer.Option("--hypothesis", "-H", help="Why this run exists.")]
SeedOpt = Annotated[int | None, typer.Option("--seed", help="Seed; use {seed} in the command.")]
TagOpt = Annotated[list[str] | None, typer.Option("--tag", help="Tag (repeatable).")]
ConfigOpt = Annotated[Path | None, typer.Option("--config", help="Config file; use {config}.")]
ParamOpt = Annotated[list[str] | None, typer.Option("--param", help="name=value (repeatable).")]
VarOpt = Annotated[list[str] | None, typer.Option("--var", help="Template var name=value.")]
StageOpt = Annotated[str | None, typer.Option("--stage", help="Run a stage from hypothex.yaml.")]
RepoOpt = Annotated[Path | None, typer.Option("--repo", help="Project repo (default: cwd).")]


# project ---------------------------------------------------------------------------
@app.command()
def init(
    project: Annotated[str | None, typer.Option(help="Project name (default: folder).")] = None,
    force: Annotated[bool, typer.Option(help="Overwrite an existing file.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Create a starter hypothex.yaml in the current directory."""
    path = Path.cwd() / CONFIG_FILENAME
    if path.exists() and not force:
        raise RunError(f"{path} exists; use --force to overwrite")
    name = project or re.sub(r"[^a-z0-9_.-]+", "-", Path.cwd().name.lower()).strip("-") or "project"
    path.write_text(starter_config(name), encoding="utf-8")
    if as_json:
        _print_json({"path": str(path), "project": name})
    else:
        typer.echo(f"wrote {path}; edit it, then run `hx validate`")


@app.command()
def validate(repo: RepoOpt = None, as_json: JsonFlag = False) -> None:
    """Check hypothex.yaml, metric imports, and dataset paths."""
    report = validate_project(_ctx(), repo or find_repo_root(Path.cwd()))
    if as_json:
        _print_json(report)
    else:
        for e in report.errors:
            typer.secho(f"error: {e}", fg="red")
        for w in report.warnings:
            typer.secho(f"warning: {w}", fg="yellow")
        if report.ok:
            typer.secho("ok", fg="green")
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def projects(as_json: JsonFlag = False) -> None:
    """List projects."""
    entries = q.list_projects(_ctx())
    if as_json:
        _print_json([{"project": e.project, "repo": e.repo, "tasks": sorted(e.config.tasks)}
                     for e in entries])
        return
    _table(["project", "repo", "tasks"],
           [[e.project, e.repo, ", ".join(sorted(e.config.tasks))] for e in entries])


@app.command()
def tasks(project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """List tasks with their dataset, metric versions, and best score."""
    items = q.list_tasks(_ctx(), project)
    if as_json:
        _print_json(items)
        return
    _table(["task", "dataset", "metrics", "primary", "runs", "best"],
           [[f"{t.project}/{t.name}", f"{t.dataset}@{t.dataset_version}",
             ", ".join(f"{m}@{v}" for m, v in t.metrics.items()), t.primary, t.n_runs,
             None if t.best is None else f"{t.best:.4f}"] for t in items])


@task_app.command("show")
def task_show(ref: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Show a task: dataset, metrics, stages, repo."""
    detail = q.get_task(_ctx(), ref, project)
    if as_json:
        _print_json(detail)
    else:
        typer.echo(yaml.safe_dump(detail, sort_keys=False))


@app.command()
def leaderboard(
    ref: str,
    project: ProjectOpt = None,
    metric: Annotated[list[str] | None, typer.Option(
        "--metric", help="Pin a metric version: name@version (repeatable).")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Rank seed groups of a task (mean ± std over seeds)."""
    versions = {}
    for item in metric or []:
        name, version = parse_metric_version(item)
        if version is None:
            raise RunError(f"--metric needs name@version, got {item!r}")
        versions[name] = version
    board = q.get_leaderboard(_ctx(), ref, project, versions or None)
    if as_json:
        _print_json(board)
        return
    typer.secho(f"{board.project}/{board.task}  primary={board.primary}  "
                f"versions={board.metric_versions}", bold=True)
    rows = []
    for i, r in enumerate(board.rows, 1):
        noise = {True: "within noise", False: "", None: "single seed" if r.single_seed else ""}
        rows.append([i, r.group_id, _stats(r.primary), noise[r.within_noise_of_best],
                     r.latest_run_id, r.hypothesis[:50]])
    _table(["#", "group", board.primary, "note", "latest run", "hypothesis"], rows)
    if board.needs_reeval:
        typer.secho(f"{len(board.needs_reeval)} runs scored on older metric versions: "
                    f"run `hx reeval --task {board.project}/{board.task}`", fg="yellow")
    if board.unscored:
        typer.secho(f"{len(board.unscored)} finished runs have no scores", fg="yellow")


# runs ---------------------------------------------------------------------------
@app.command("runs")
def list_runs_cmd(
    project: ProjectOpt = None,
    task: TaskOpt = None,
    status: Annotated[RunStatus | None, typer.Option(help="Filter by status.")] = None,
    tag: Annotated[str | None, typer.Option(help="Filter by tag.")] = None,
    archived: Annotated[bool, typer.Option(help="Include archived runs.")] = False,
    limit: Annotated[int, typer.Option(help="Maximum rows.")] = 50,
    as_json: JsonFlag = False,
) -> None:
    """List runs, newest first."""
    records = _ctx().index.list_runs(project=project, task=task, status=status, tag=tag,
                                     include_archived=archived, limit=limit)
    if as_json:
        _print_json(records)
        return
    _table(["run", "task", "status", "created", "hypothesis"],
           [[r.run_id, r.task, r.status.value, r.created_at.strftime("%Y-%m-%d %H:%M"),
             r.hypothesis[:50]] for r in records])


@app.command()
def show(run_id: str, as_json: JsonFlag = False) -> None:
    """Show everything about a run, including where every file lives."""
    detail = q.show_run(_ctx(), run_id)
    if as_json:
        _print_json(detail)
        return
    r = detail.record
    typer.secho(f"{r.run_id}  [{r.status.value}]  {r.project}/{r.task or 'exploratory'}", bold=True)
    typer.echo(f"hypothesis: {r.hypothesis or '—'}")
    typer.echo(f"command:    {r.command_display}")
    typer.echo(f"git:        {r.git.commit or '—'}{' (dirty)' if r.git.dirty else ''}")
    typer.secho("paths:", bold=True)
    for k, v in detail.paths.items():
        typer.echo(f"  {k:<22} {v}")
    if detail.scores:
        typer.secho("scores:", bold=True)
        for s in detail.scores:
            typer.echo(f"  {s.metric}@{s.version}/{s.key} = {s.value if s.error is None else 'ERROR'}")


@app.command(context_settings=RUN_SETTINGS)
def run(
    ctx: typer.Context, task: TaskOpt = None, hypothesis: HypOpt = None, seed: SeedOpt = None,
    tag: TagOpt = None, config: ConfigOpt = None, param: ParamOpt = None, var: VarOpt = None,
    stage: StageOpt = None, repo: RepoOpt = None, as_json: JsonFlag = False,
) -> None:
    """Run a command in the foreground and record it: hx run -t TASK -H WHY -- CMD..."""
    req = _request(ctx.args, task=task, hypothesis=hypothesis, seed=seed, tags=tag,
                   config=config, params=param, variables=var, stage=stage, repo=repo,
                   interactive=not as_json)
    c = _ctx()
    record = prepare_run(c, req)
    typer.secho(f"run {record.run_id} -> {c.run_dir(record)}", fg="cyan", err=True)
    final = execute_run(c, record.run_id,
                        stdout_sink=sys.stderr.buffer if as_json else sys.stdout.buffer,
                        stderr_sink=sys.stderr.buffer)
    _finish(final, as_json)


@app.command(context_settings=RUN_SETTINGS)
def launch(
    ctx: typer.Context, task: TaskOpt = None, hypothesis: HypOpt = None, seed: SeedOpt = None,
    tag: TagOpt = None, config: ConfigOpt = None, param: ParamOpt = None, var: VarOpt = None,
    stage: StageOpt = None, repo: RepoOpt = None,
    wait: Annotated[bool, typer.Option(help="Block until the run ends.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Start a run in the background (same options as `hx run`)."""
    req = _request(ctx.args, task=task, hypothesis=hypothesis, seed=seed, tags=tag,
                   config=config, params=param, variables=var, stage=stage, repo=repo,
                   interactive=not as_json)
    c = _ctx()
    record = launch_run(c, req)
    if wait:
        record = wait_for_run(c, record.run_id, timeout=WAIT_FOREVER)
        _finish(record, as_json)
    elif as_json:
        _print_json(record)
    else:
        typer.echo(f"launched {record.run_id}; follow with `hx logs {record.run_id} --follow`")


ForegroundOpt = Annotated[bool, typer.Option(help="Run here and stream output.")]


def _started(record: RunRecord, foreground: bool, as_json: bool) -> None:
    if foreground:
        _finish(record, as_json)
    elif as_json:
        _print_json(record)
    else:
        typer.echo(f"launched {record.run_id}")


def _emit(obj: Any, as_json: bool, text: str) -> None:
    if as_json:
        _print_json(obj)
    else:
        typer.echo(text)


@app.command("rerun")
def rerun_cmd(run_id: str, foreground: ForegroundOpt = False, as_json: JsonFlag = False) -> None:
    """Rerun with the same command, commit, config, and seed."""
    record = rerun(_ctx(), run_id, background=not foreground, created_by=_created_by(),
                   stdout_sink=None if as_json else sys.stdout.buffer,
                   stderr_sink=sys.stderr.buffer)
    _started(record, foreground, as_json)


@app.command("reinfer")
def reinfer_cmd(
    run_id: str,
    checkpoint: Annotated[str | None, typer.Option(help="Checkpoint path override.")] = None,
    foreground: ForegroundOpt = False,
    as_json: JsonFlag = False,
) -> None:
    """Run the `infer` stage again with this run's checkpoint."""
    record = reinfer(_ctx(), run_id, checkpoint=checkpoint, background=not foreground,
                     created_by=_created_by(),
                     stdout_sink=None if as_json else sys.stdout.buffer,
                     stderr_sink=sys.stderr.buffer)
    _started(record, foreground, as_json)


@app.command("reeval")
def reeval_cmd(
    run_id: Annotated[str | None, typer.Argument(help="One run; or use --task.")] = None,
    task: TaskOpt = None,
    project: ProjectOpt = None,
    metric: Annotated[str | None, typer.Option(help="name or name@version (current).")] = None,
    force: Annotated[bool, typer.Option(help="Re-score already scored runs.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Re-score saved predictions with the current metric versions."""
    c = _ctx()
    if run_id is not None:
        report = reeval(c, run_id=run_id, metric=metric, force=force)
    elif task is not None:
        entry, name = q.resolve_task(c, task, project)
        report = reeval(c, project=entry.project, task=name, metric=metric, force=force)
    else:
        raise RunError("give a run id or --task")
    if as_json:
        _print_json(report)
        return
    typer.echo(f"evaluated {len(report.evaluated)}, skipped {len(report.skipped)}")
    for rid, why in report.skipped.items():
        typer.echo(f"  skipped {rid}: {why}")
    for w in report.warnings:
        typer.secho(f"warning: {w}", fg="yellow")


@app.command()
def stop(run_id: str, as_json: JsonFlag = False) -> None:
    """Stop a queued or running run."""
    record = stop_run(_ctx(), run_id)
    _emit(record, as_json, f"{record.run_id} {record.status.value}")


@app.command()
def compare(run_ids: list[str], as_json: JsonFlag = False) -> None:
    """Show config and score differences between runs."""
    cmp = q.compare_runs(_ctx(), run_ids)
    if as_json:
        _print_json(cmp)
        return
    _table(["field", *cmp.run_ids], [[k, *v] for k, v in {**cmp.fields, **cmp.scores}.items()])


@app.command()
def examples(
    a: str, b: str,
    metric: Annotated[str, typer.Option(help="name or name@version.")],
    field: Annotated[str, typer.Option(help="Per-example success field.")] = "correct",
    as_json: JsonFlag = False,
) -> None:
    """List examples fixed or broken by run B relative to run A."""
    diff = q.compare_examples(_ctx(), a, b, metric, field)
    if as_json:
        _print_json(diff)
        return
    typer.echo(f"fixed {len(diff.fixed)}, broken {len(diff.broken)}, "
               f"both pass {diff.both_pass}, both fail {diff.both_fail}")
    for i in diff.broken[:20]:
        typer.secho(f"  broken: {i}", fg="red")
    for i in diff.fixed[:20]:
        typer.secho(f"  fixed:  {i}", fg="green")


@app.command()
def predictions(
    run_id: str,
    metric: Annotated[str | None, typer.Option(help="name or name@version.")] = None,
    failures: Annotated[bool, typer.Option(help="Only failing examples.")] = False,
    field: Annotated[str, typer.Option(help="Per-example success field.")] = "correct",
    offset: int = 0,
    limit: int = 20,
    as_json: JsonFlag = False,
) -> None:
    """Page through a run's predictions with per-example scores."""
    page = q.get_predictions(_ctx(), run_id, offset=offset, limit=limit, metric=metric,
                             failures_only=failures, field=field)
    if as_json:
        _print_json(page)
        return
    _table(["id", "prediction", "reference", "scores"],
           [[r.id, json.dumps(r.prediction)[:40], json.dumps(r.reference)[:40],
             json.dumps(r.scores)[:60]] for r in page.rows])
    typer.echo(f"{page.offset}-{page.offset + len(page.rows)} of {page.total}")


@app.command()
def logs(
    run_id: str,
    stream: Annotated[str, typer.Option(help="stdout, stderr, or supervisor.")] = "stdout",
    follow: Annotated[bool, typer.Option(help="Keep printing until the run ends.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Print a run's log (tail), optionally following it."""
    c = _ctx()
    chunk = q.read_log(c, run_id, stream)
    if as_json:
        _print_json(chunk)
        return
    typer.echo(chunk.text, nl=False)
    while follow:
        if c.find_record(run_id).status in TERMINAL_STATUSES:
            typer.echo(q.read_log(c, run_id, stream, chunk.offset).text, nl=False)
            return
        time.sleep(1)
        chunk = q.read_log(c, run_id, stream, chunk.offset)
        typer.echo(chunk.text, nl=False)


# curation -------------------------------------------------------------------------
@app.command()
def tag(
    run_id: str,
    add: Annotated[list[str] | None, typer.Option("--add", help="Tag to add.")] = None,
    remove: Annotated[list[str] | None, typer.Option("--remove", help="Tag to remove.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Add or remove tags."""
    record = q.tag_run(_ctx(), run_id, add or [], remove or [])
    _emit(record, as_json, ", ".join(record.tags) or "(no tags)")


OffFlag = Annotated[bool, typer.Option("--off", help="Undo.")]


@app.command()
def star(run_id: str, off: OffFlag = False, as_json: JsonFlag = False) -> None:
    """Star (or --off unstar) a run."""
    record = q.star_run(_ctx(), run_id, on=not off)
    _emit(record, as_json, f"starred={record.starred}")


@app.command()
def archive(run_id: str, off: OffFlag = False, as_json: JsonFlag = False) -> None:
    """Archive (hide) or --off unarchive a run."""
    record = q.archive_run(_ctx(), run_id, on=not off)
    _emit(record, as_json, f"archived={record.archived}")


@app.command()
def note(
    run_id: str, text: str,
    author: Annotated[str | None, typer.Option(help="Author (default: human/agent).")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Add a note to a run."""
    q.add_note(_ctx(), run_id, text, author or _created_by())
    _emit({"ok": True}, as_json, "noted")


# datasets & maintenance -------------------------------------------------------------
@datasets_app.command("check")
def datasets_check(project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Re-fingerprint datasets used by runs and report changes."""
    drift = q.check_datasets(_ctx(), project)
    if as_json:
        _print_json(drift)
        return
    _table(["run", "dataset", "status", "path"],
           [[d.run_id, d.dataset, d.status, d.path] for d in drift])


@datasets_app.command("overlap")
def datasets_overlap(
    project: str, dataset: str,
    key: Annotated[str | None, typer.Option(help="JSON field identifying an example.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Count examples shared between a dataset's splits."""
    report = q.dataset_overlap(_ctx(), project, dataset, key)
    if as_json:
        _print_json(report)
        return
    _table(["splits", "shared"], [[k, v] for k, v in report.pairs.items()])


@app.command()
def reindex(as_json: JsonFlag = False) -> None:
    """Rebuild the index from run folders."""
    c = _ctx()
    count = rebuild_index(c.index, c.store)
    _emit({"runs": count}, as_json, f"indexed {count} runs")


@app.command()
def repair(as_json: JsonFlag = False) -> None:
    """Mark runs whose supervisor died as lost."""
    lost = repair_runs(_ctx())
    if as_json:
        _print_json({"lost": [r.run_id for r in lost]})
    else:
        typer.echo(f"marked {len(lost)} runs lost")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port.")] = 7777,
) -> None:
    """Serve the HTTP/WebSocket API (and the UI when built)."""
    import uvicorn

    from hypothex.api.app import create_app

    uvicorn.run(create_app(_state.home), host=host, port=port)


@app.command()
def mcp() -> None:
    """Run the MCP server over stdio (for Claude Code, Codex, ...)."""
    from hypothex.mcp.server import build_server

    build_server(_state.home).run()


def cli() -> None:
    """Console entry point: expected errors print cleanly (JSON with --json)."""
    try:
        app()
    except HypothexError as exc:
        if "--json" in sys.argv:
            print(json.dumps({"error": str(exc), "type": type(exc).__name__}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/cli -v && uv run ruff check src tests && uv run hx --help`
Expected: PASS; help lists all commands.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/cli tests/cli
git commit -m "feat: hx CLI with --json on every command"
```

---

### Task 16: HTTP + WebSocket API

**Files:**
- Create: `src/hypothex/api/__init__.py` (empty), `src/hypothex/api/app.py`
- Test: `tests/api/__init__.py` (empty), `tests/api/test_app.py`

**Interfaces:**
- Consumes: Tasks 10–13.
- Produces: `hypothex.api.app.create_app(home: Path | None = None, *, background_repair: bool = True) -> FastAPI`. Routes:
  - `GET /.well-known/hypothex/environment` → `EnvironmentDescriptor`.
  - `GET /api/v1/projects`, `GET /api/v1/tasks?project=`, `GET /api/v1/tasks/{project}/{task}`, `GET /api/v1/tasks/{project}/{task}/leaderboard?metric=name@v` (repeatable), `POST /api/v1/tasks/{project}/{task}/reeval`.
  - `GET /api/v1/runs?project&task&status&tag&archived&limit`, `POST /api/v1/runs` (launch), `GET /api/v1/runs/{id}`, `GET /api/v1/runs/{id}/metrics`, `GET /api/v1/runs/{id}/logs?stream&offset`, `GET /api/v1/runs/{id}/predictions?offset&limit&metric&failures_only&field`, `POST /api/v1/runs/{id}/{rerun|reinfer|reeval|stop|tags|star|archive|notes}`.
  - `GET /api/v1/compare?ids=a,b`, `GET /api/v1/compare/examples?a&b&metric&field`, `GET /api/v1/datasets/check?project=`.
  - `WS /api/v1/ws`: client sends `{"type":"subscribe","after_sequence":N}`; server sends `{"type":"event","event":{...}}` for each event after N, then `{"type":"ready","last_sequence":M}` once caught up, then live events.
  - Every POST body accepts `command_id` (idempotent via `EventLog.run_once`) and `created_by`.
  - Errors: `HypothexError` → HTTP 400 `{"error","type"}`; `StoreError`/`RunNotFoundError` → 404.
  - Serves `src/hypothex/ui_dist/` at `/` when it contains `index.html` (Phase 1b).

- [ ] **Step 1: Write the failing tests**

`tests/api/test_app.py`:

```python
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from tests.factories import PREDS_075, seed_finished_run


@pytest.fixture
def client(home: Path) -> Iterator[TestClient]:
    with TestClient(create_app(home, background_repair=False)) as c:
        yield c


def test_environment_descriptor(client: TestClient) -> None:
    body = client.get("/.well-known/hypothex/environment").json()
    assert body["protocol_version"] == 1 and len(body["environment_id"]) == 32


def test_projects_tasks_leaderboard(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    assert client.get("/api/v1/projects").json()[0]["project"] == "toy"
    tasks = {t["name"]: t for t in client.get("/api/v1/tasks").json()}
    assert tasks["toy-acc"]["best"] == 0.75
    board = client.get("/api/v1/tasks/toy/toy-acc/leaderboard").json()
    assert board["rows"][0]["run_ids"] == ["r1"]
    assert client.get("/api/v1/tasks/toy/toy-acc").json()["dataset"]["name"] == "toyset"


def test_run_detail_logs_predictions_and_errors(client: TestClient, ctx: Context,
                                                toy_repo: Path) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    (ctx.run_dir(rec) / "logs" / "stdout.log").write_text("hello\n")
    assert client.get("/api/v1/runs/r1").json()["record"]["run_id"] == "r1"
    assert client.get("/api/v1/runs/r1/logs").json()["text"] == "hello\n"
    page = client.get("/api/v1/runs/r1/predictions", params={"failures_only": True}).json()
    assert [r["id"] for r in page["rows"]] == ["ex-3"]
    missing = client.get("/api/v1/runs/nope")
    assert missing.status_code == 404 and missing.json()["type"] == "RunNotFoundError"
    bad = client.get("/api/v1/tasks/toy/nope")
    assert bad.status_code == 400 and "unknown task" in bad.json()["error"]


def test_reeval_is_idempotent(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    body = {"command_id": "cmd-123", "force": True}
    first = client.post("/api/v1/runs/r1/reeval", json=body).json()
    second = client.post("/api/v1/runs/r1/reeval", json=body).json()
    assert first == second and first["evaluated"] == ["r1"]
    added = [e for e in ctx.events.since(0) if e.type == "run.score_added"]
    assert len(added) == 1


def test_curation_endpoints(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    assert client.post("/api/v1/runs/r1/tags", json={"add": ["x"]}).json()["tags"] == ["x"]
    assert client.post("/api/v1/runs/r1/star", json={"on": True}).json()["starred"] is True
    assert client.post("/api/v1/runs/r1/notes", json={"text": "hi"}).json() == {"ok": True}
    assert client.post("/api/v1/runs/r1/archive", json={"on": True}).json()["archived"] is True
    assert client.get("/api/v1/runs").json() == []
    assert len(client.get("/api/v1/runs", params={"archived": True}).json()) == 1


def test_launch_via_api(client: TestClient, toy_repo: Path) -> None:
    body = {"repo": str(toy_repo), "command": [sys.executable, "-c", "print('api')"],
            "hypothesis": "api launch", "command_id": "launch-1"}
    run_id = client.post("/api/v1/runs", json=body).json()["run_id"]
    assert client.post("/api/v1/runs", json=body).json()["run_id"] == run_id  # idempotent
    deadline = time.monotonic() + 60
    status = ""
    while time.monotonic() < deadline:
        status = client.get(f"/api/v1/runs/{run_id}").json()["record"]["status"]
        if status == "finished":
            break
        time.sleep(0.2)
    assert status == "finished"


def test_ws_replays_then_signals_ready(client: TestClient, ctx: Context) -> None:
    for i in range(3):
        ctx.events.append("test.event", payload={"i": i})
    last = ctx.events.last_sequence()
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "after_sequence": 0})
        seen = [ws.receive_json() for _ in range(last)]
        assert [m["event"]["sequence"] for m in seen] == list(range(1, last + 1))
        assert ws.receive_json() == {"type": "ready", "last_sequence": last}
        ctx.events.append("test.live")
        live = ws.receive_json()
        assert live["type"] == "event" and live["event"]["type"] == "test.live"
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "after_sequence": last - 1})
        assert ws.receive_json()["event"]["sequence"] == last
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.api'`.

- [ ] **Step 3: Implement `api/app.py`**

```python
"""HTTP + WebSocket API. The UI and remote clients use only this."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hypothex._version import __version__
from hypothex.core import control
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.errors import HypothexError, StoreError
from hypothex.core.evaluation import reeval
from hypothex.core.execution import RunRequest
from hypothex.core.records import RunStatus

log = logging.getLogger(__name__)

REPAIR_INTERVAL_SECONDS = 30.0
WS_POLL_SECONDS = 0.5
WS_BATCH = 500
UI_DIST = Path(__file__).resolve().parent.parent / "ui_dist"


class ActionBody(BaseModel):
    """Common fields of every POST body."""

    command_id: str | None = None
    created_by: str = "api"


class LaunchBody(ActionBody):
    repo: str
    task: str | None = None
    stage: str | None = None
    command: list[str] | None = None
    hypothesis: str = ""
    seed: int | None = None
    tags: list[str] = Field(default_factory=list)
    params: dict[str, str] = Field(default_factory=dict)
    vars: dict[str, str] = Field(default_factory=dict)


class ReinferBody(ActionBody):
    checkpoint: str | None = None


class ReevalBody(ActionBody):
    metric: str | None = None
    force: bool = False


class TagBody(ActionBody):
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class FlagBody(ActionBody):
    on: bool = True


class NoteBody(ActionBody):
    text: str
    author: str = "api"


def _dump(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_dump(v) for v in obj]
    return obj


async def _repair_loop(ctx: Context) -> None:
    while True:
        await asyncio.sleep(REPAIR_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(control.repair_runs, ctx)
        except Exception:  # noqa: BLE001 - keep the server alive
            log.exception("run repair failed")


def create_app(home: Path | None = None, *, background_repair: bool = True) -> FastAPI:
    """
    Build the FastAPI application.

    Parameters
    ----------
    home : Path, optional
        Hypothex home; defaults to ``$HYPOTHEX_HOME`` or ``~/.hypothex``.
    background_repair : bool
        Mark orphaned runs lost every 30 s (disable in tests).

    Returns
    -------
    FastAPI
    """
    ctx = Context.open(home)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(control.repair_runs, ctx)
        task = asyncio.create_task(_repair_loop(ctx)) if background_repair else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="Hypothex", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.ctx = ctx

    @app.exception_handler(HypothexError)
    async def hypothex_error(_: Request, exc: HypothexError) -> JSONResponse:
        status = 404 if isinstance(exc, StoreError) else 400
        return JSONResponse(status_code=status,
                            content={"error": str(exc), "type": type(exc).__name__})

    def once(body: ActionBody, fn: Callable[[], Any]) -> dict[str, Any]:
        return ctx.events.run_once(body.command_id, lambda: _dump(fn()))

    # environment -----------------------------------------------------------------
    @app.get("/.well-known/hypothex/environment")
    def environment() -> dict[str, Any]:
        return ctx.descriptor.model_dump(mode="json")

    # projects & tasks ------------------------------------------------------------
    @app.get("/api/v1/projects")
    def projects() -> list[dict[str, Any]]:
        return [{"project": e.project, "repo": e.repo, "description": e.config.description,
                 "tasks": sorted(e.config.tasks)} for e in q.list_projects(ctx)]

    @app.get("/api/v1/tasks")
    def tasks(project: str | None = None) -> list[dict[str, Any]]:
        return _dump(q.list_tasks(ctx, project))

    @app.get("/api/v1/tasks/{project}/{task}")
    def task_detail(project: str, task: str) -> dict[str, Any]:
        return q.get_task(ctx, task, project)

    @app.get("/api/v1/tasks/{project}/{task}/leaderboard")
    def leaderboard(project: str, task: str,
                    metric: list[str] = Query(default=[])) -> dict[str, Any]:
        versions = {}
        for item in metric:
            name, _, version = item.partition("@")
            if version:
                versions[name] = version
        return _dump(q.get_leaderboard(ctx, task, project, versions or None))

    @app.post("/api/v1/tasks/{project}/{task}/reeval")
    def task_reeval(project: str, task: str, body: ReevalBody) -> dict[str, Any]:
        return once(body, lambda: reeval(ctx, project=project, task=task, metric=body.metric,
                                         force=body.force))

    # runs ----------------------------------------------------------------------------
    @app.get("/api/v1/runs")
    def runs(project: str | None = None, task: str | None = None,
             status: RunStatus | None = None, tag: str | None = None,
             archived: bool = False, limit: int = 200) -> list[dict[str, Any]]:
        return _dump(ctx.index.list_runs(project=project, task=task, status=status, tag=tag,
                                         include_archived=archived, limit=limit))

    @app.post("/api/v1/runs")
    def launch(body: LaunchBody) -> dict[str, Any]:
        req = RunRequest(repo=Path(body.repo), command=body.command, stage=body.stage,
                         task=body.task, hypothesis=body.hypothesis, seed=body.seed,
                         tags=body.tags, params=body.params, vars=body.vars,
                         created_by=body.created_by)
        return once(body, lambda: control.launch_run(ctx, req))

    @app.get("/api/v1/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        return _dump(q.show_run(ctx, run_id))

    @app.get("/api/v1/runs/{run_id}/metrics")
    def run_metrics(run_id: str) -> list[dict[str, Any]]:
        return _dump(q.metric_history(ctx, run_id))

    @app.get("/api/v1/runs/{run_id}/logs")
    def run_logs(run_id: str, stream: str = "stdout", offset: int | None = None) -> dict[str, Any]:
        return _dump(q.read_log(ctx, run_id, stream, offset))

    @app.get("/api/v1/runs/{run_id}/predictions")
    def run_predictions(run_id: str, offset: int = 0, limit: int = 50, metric: str | None = None,
                        failures_only: bool = False, field: str = "correct") -> dict[str, Any]:
        return _dump(q.get_predictions(ctx, run_id, offset=offset, limit=limit, metric=metric,
                                       failures_only=failures_only, field=field))

    @app.post("/api/v1/runs/{run_id}/rerun")
    def run_rerun(run_id: str, body: ActionBody) -> dict[str, Any]:
        return once(body, lambda: control.rerun(ctx, run_id, created_by=body.created_by))

    @app.post("/api/v1/runs/{run_id}/reinfer")
    def run_reinfer(run_id: str, body: ReinferBody) -> dict[str, Any]:
        return once(body, lambda: control.reinfer(ctx, run_id, checkpoint=body.checkpoint,
                                                   created_by=body.created_by))

    @app.post("/api/v1/runs/{run_id}/reeval")
    def run_reeval(run_id: str, body: ReevalBody) -> dict[str, Any]:
        return once(body, lambda: reeval(ctx, run_id=run_id, metric=body.metric,
                                         force=body.force))

    @app.post("/api/v1/runs/{run_id}/stop")
    def run_stop(run_id: str, body: ActionBody) -> dict[str, Any]:
        return once(body, lambda: control.stop_run(ctx, run_id))

    @app.post("/api/v1/runs/{run_id}/tags")
    def run_tags(run_id: str, body: TagBody) -> dict[str, Any]:
        return once(body, lambda: q.tag_run(ctx, run_id, body.add, body.remove))

    @app.post("/api/v1/runs/{run_id}/star")
    def run_star(run_id: str, body: FlagBody) -> dict[str, Any]:
        return once(body, lambda: q.star_run(ctx, run_id, body.on))

    @app.post("/api/v1/runs/{run_id}/archive")
    def run_archive(run_id: str, body: FlagBody) -> dict[str, Any]:
        return once(body, lambda: q.archive_run(ctx, run_id, body.on))

    @app.post("/api/v1/runs/{run_id}/notes")
    def run_note(run_id: str, body: NoteBody) -> dict[str, Any]:
        def act() -> dict[str, bool]:
            q.add_note(ctx, run_id, body.text, body.author)
            return {"ok": True}

        return once(body, act)

    # compare & datasets ----------------------------------------------------------------
    @app.get("/api/v1/compare")
    def compare(ids: str) -> dict[str, Any]:
        return _dump(q.compare_runs(ctx, [i for i in ids.split(",") if i]))

    @app.get("/api/v1/compare/examples")
    def compare_examples(a: str, b: str, metric: str, field: str = "correct") -> dict[str, Any]:
        return _dump(q.compare_examples(ctx, a, b, metric, field))

    @app.get("/api/v1/datasets/check")
    def datasets_check(project: str | None = None) -> list[dict[str, Any]]:
        return _dump(q.check_datasets(ctx, project))

    # live events -------------------------------------------------------------------------
    @app.websocket("/api/v1/ws")
    async def events_ws(ws: WebSocket) -> None:
        await ws.accept()
        try:
            msg = await ws.receive_json()
            if msg.get("type") != "subscribe":
                await ws.send_json({"type": "error",
                                    "error": "first message must be {type: subscribe, "
                                             "after_sequence: N}"})
                await ws.close()
                return
            last = int(msg.get("after_sequence", 0))
            ready = False
            while True:
                batch = await asyncio.to_thread(ctx.events.since, last, WS_BATCH)
                for event in batch:
                    await ws.send_json({"type": "event", "event": event.model_dump(mode="json")})
                    last = event.sequence
                if len(batch) < WS_BATCH:
                    if not ready:
                        await ws.send_json({"type": "ready", "last_sequence": last})
                        ready = True
                    await asyncio.sleep(WS_POLL_SECONDS)
        except WebSocketDisconnect:
            return

    if (UI_DIST / "index.html").is_file():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api -v`
Expected: PASS.

- [ ] **Step 5: Smoke-test the real server**

Run: `uv run hx serve --port 7788 & sleep 2; curl -s localhost:7788/.well-known/hypothex/environment; kill %1`
Expected: JSON descriptor with `"protocol_version":1`.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/api tests/api
git commit -m "feat: HTTP API with idempotent actions and resumable WebSocket event stream"
```

---

### Task 17: MCP server (stdio and HTTP)

**Files:**
- Create: `src/hypothex/mcp/__init__.py` (empty), `src/hypothex/mcp/server.py`
- Modify: `src/hypothex/api/app.py` (mount MCP at `/mcp`)
- Test: `tests/mcp/__init__.py` (empty), `tests/mcp/test_server.py`

**Interfaces:**
- Consumes: Tasks 10–13; `mcp.server.fastmcp.FastMCP`.
- Produces: `hypothex.mcp.server.build_server(home: Path | None = None) -> FastMCP` with tools (all return a JSON object): `list_projects`, `list_tasks(project=None)`, `get_task(task, project=None)`, `get_leaderboard(task, project=None)`, `list_runs(project=None, task=None, status=None, tag=None, limit=50)`, `get_run(run_id)`, `compare_runs(run_ids)`, `launch_run(repo, hypothesis, task=None, stage=None, command=None, seed=None, params=None, template_vars=None, tags=None, agent="mcp")`, `rerun(run_id, agent="mcp")`, `reinfer(run_id, checkpoint=None, agent="mcp")`, `reevaluate(run_id=None, task=None, project=None, metric=None, force=False)`, `stop_run(run_id)`, `add_note(run_id, text, author="agent")`, `tag_run(run_id, add=None, remove=None)`, `get_predictions(run_id, metric=None, failures_only=False, offset=0, limit=50)`. The API serves the same server over streamable HTTP at `/mcp/`.

Note for the implementer: the `mcp` SDK API has moved between releases. Before writing code, check the installed version's docs with context7 (`/modelcontextprotocol/python-sdk`) for: `FastMCP(...)` constructor, `@mcp.tool()`, `mcp.run()` (stdio), `streamable_http_app()`, `session_manager.run()`, `settings.streamable_http_path`, and `mcp.shared.memory.create_connected_server_and_client_session`. Keep the tool names and argument names below exactly; adapt only SDK plumbing.

- [ ] **Step 1: Write the failing tests**

`tests/mcp/test_server.py`:

```python
import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.mcp.server import build_server
from tests.factories import PREDS_075, seed_finished_run

EXPECTED_TOOLS = {
    "list_projects", "list_tasks", "get_task", "get_leaderboard", "list_runs", "get_run",
    "compare_runs", "launch_run", "rerun", "reinfer", "reevaluate", "stop_run", "add_note",
    "tag_run", "get_predictions",
}


def call(home: Path, name: str, args: dict[str, Any] | None = None) -> tuple[bool, Any]:
    server = build_server(home)

    async def go() -> tuple[bool, Any]:
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            result = await client.call_tool(name, args or {})
            if result.isError:
                return True, result.content[0].text
            if result.structuredContent is not None:
                return False, result.structuredContent
            return False, json.loads(result.content[0].text)

    return asyncio.run(go())


def test_all_tools_are_listed(home: Path) -> None:
    server = build_server(home)

    async def go() -> set[str]:
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(go()) == EXPECTED_TOOLS


def test_read_tools(home: Path, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    err, projects = call(home, "list_projects")
    assert not err and projects["projects"][0]["project"] == "toy"
    err, board = call(home, "get_leaderboard", {"task": "toy-acc"})
    assert not err and board["rows"][0]["run_ids"] == ["r1"]
    err, run = call(home, "get_run", {"run_id": "r1"})
    assert not err and run["paths"]["repo"] == str(toy_repo.resolve())


def test_launch_requires_hypothesis(home: Path, toy_repo: Path) -> None:
    err, message = call(home, "launch_run", {"repo": str(toy_repo), "hypothesis": " ",
                                            "command": ["true"]})
    assert err and "hypothesis" in message


def test_reevaluate_note_and_tag(home: Path, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    err, report = call(home, "reevaluate", {"run_id": "r1"})
    assert not err and report["evaluated"] == ["r1"]
    assert call(home, "add_note", {"run_id": "r1", "text": "fine"}) == (False, {"ok": True})
    err, tagged = call(home, "tag_run", {"run_id": "r1", "add": ["mcp"]})
    assert tagged["run"]["tags"] == ["mcp"]


def test_mcp_is_served_over_http(home: Path) -> None:
    app = create_app(home, background_repair=False)
    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        resp = client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"}}},
        )
        assert resp.status_code == 200
        assert "hypothex" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mcp -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hypothex.mcp'`.

- [ ] **Step 3: Implement `mcp/server.py`**

```python
"""MCP server: Hypothex actions as tools for coding agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from hypothex.core import control
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.evaluation import reeval
from hypothex.core.execution import RunRequest
from hypothex.core.records import RunStatus

INSTRUCTIONS = """\
Hypothex tracks ML/AI experiments across projects. Each run belongs to a task
(dataset + versioned metrics) and records its hypothesis, exact command, git commit,
dataset fingerprints, config, environment, logs, predictions, and scores.

Loop for a new iteration:
1. list_tasks -> pick the task. 2. get_leaderboard -> see what is best and what was tried.
3. get_run on the top rows -> read hypotheses and notes; do not repeat work.
4. launch_run with a one-sentence hypothesis; use seeds (>= 3) before claiming a win.
5. compare_runs against the best; add_note with what you learned.
Never delete runs. Never change a metric's code without bumping its version in
hypothex.yaml; then call reevaluate for the task.
"""


def build_server(home: Path | None = None) -> FastMCP:
    """
    Build the Hypothex MCP server.

    Parameters
    ----------
    home : Path, optional
        Hypothex home directory.

    Returns
    -------
    FastMCP
        Run with ``.run()`` for stdio, or mount ``.streamable_http_app()``.
    """
    mcp = FastMCP("hypothex", instructions=INSTRUCTIONS)
    holder: dict[str, Context] = {}

    def ctx() -> Context:
        if "ctx" not in holder:
            holder["ctx"] = Context.open(home)
        return holder["ctx"]

    def dump(obj: Any) -> Any:
        return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj

    @mcp.tool()
    def list_projects() -> dict[str, Any]:
        """List projects with their repo paths and task names."""
        return {"projects": [{"project": e.project, "repo": e.repo,
                              "tasks": sorted(e.config.tasks)} for e in q.list_projects(ctx())]}

    @mcp.tool()
    def list_tasks(project: str | None = None) -> dict[str, Any]:
        """List tasks: dataset@version, metric versions, primary metric, run count, best."""
        return {"tasks": [dump(t) for t in q.list_tasks(ctx(), project)]}

    @mcp.tool()
    def get_task(task: str, project: str | None = None) -> dict[str, Any]:
        """Show a task's dataset (path, version), metrics (fn, version), stages, and repo."""
        return q.get_task(ctx(), task, project)

    @mcp.tool()
    def get_leaderboard(task: str, project: str | None = None) -> dict[str, Any]:
        """Rank seed groups of a task (mean ± std, n); lists runs needing re-evaluation."""
        return dump(q.get_leaderboard(ctx(), task, project))

    @mcp.tool()
    def list_runs(project: str | None = None, task: str | None = None,
                  status: str | None = None, tag: str | None = None,
                  limit: int = 50) -> dict[str, Any]:
        """List runs, newest first. status: queued|running|finished|failed|killed|lost."""
        records = ctx().index.list_runs(project=project, task=task,
                                        status=RunStatus(status) if status else None, tag=tag,
                                        limit=limit)
        return {"runs": [dump(r) for r in records]}

    @mcp.tool()
    def get_run(run_id: str) -> dict[str, Any]:
        """Everything about a run: record, scores, notes, children, and all file paths."""
        return dump(q.show_run(ctx(), run_id))

    @mcp.tool()
    def compare_runs(run_ids: list[str]) -> dict[str, Any]:
        """Show config fields and scores that differ between runs."""
        return dump(q.compare_runs(ctx(), run_ids))

    @mcp.tool()
    def launch_run(repo: str, hypothesis: str, task: str | None = None,
                   stage: str | None = None, command: list[str] | None = None,
                   seed: int | None = None, params: dict[str, str] | None = None,
                   template_vars: dict[str, str] | None = None,
                   tags: list[str] | None = None, agent: str = "mcp") -> dict[str, Any]:
        """
        Start a run in the background. Give a command (argv list; may use {seed},
        {run_dir}, {dataset.path}, ...) or a stage name from hypothex.yaml. A
        hypothesis is required.
        """
        if not hypothesis.strip():
            raise ValueError("a hypothesis is required: why does this run exist?")
        record = control.launch_run(ctx(), RunRequest(
            repo=Path(repo), command=command, stage=stage, task=task, hypothesis=hypothesis,
            seed=seed, tags=tags or [], params=params or {}, vars=template_vars or {},
            created_by=f"agent:{agent}"))
        return {"run": dump(record), "run_dir": str(ctx().run_dir(record))}

    @mcp.tool()
    def rerun(run_id: str, agent: str = "mcp") -> dict[str, Any]:
        """Rerun with the same command, commit (via worktree if needed), config, and seed."""
        return {"run": dump(control.rerun(ctx(), run_id, created_by=f"agent:{agent}"))}

    @mcp.tool()
    def reinfer(run_id: str, checkpoint: str | None = None, agent: str = "mcp") -> dict[str, Any]:
        """Run the project's `infer` stage with this run's (or the given) checkpoint."""
        return {"run": dump(control.reinfer(ctx(), run_id, checkpoint=checkpoint,
                                            created_by=f"agent:{agent}"))}

    @mcp.tool()
    def reevaluate(run_id: str | None = None, task: str | None = None,
                   project: str | None = None, metric: str | None = None,
                   force: bool = False) -> dict[str, Any]:
        """Re-score saved predictions with current metric versions (one run or a whole task)."""
        c = ctx()
        if run_id is not None:
            return dump(reeval(c, run_id=run_id, metric=metric, force=force))
        if task is None:
            raise ValueError("give run_id or task")
        entry, name = q.resolve_task(c, task, project)
        return dump(reeval(c, project=entry.project, task=name, metric=metric, force=force))

    @mcp.tool()
    def stop_run(run_id: str) -> dict[str, Any]:
        """Stop a queued or running run."""
        return {"run": dump(control.stop_run(ctx(), run_id))}

    @mcp.tool()
    def add_note(run_id: str, text: str, author: str = "agent") -> dict[str, Any]:
        """Append a Markdown note to a run (findings, next steps)."""
        q.add_note(ctx(), run_id, text, author)
        return {"ok": True}

    @mcp.tool()
    def tag_run(run_id: str, add: list[str] | None = None,
                remove: list[str] | None = None) -> dict[str, Any]:
        """Add or remove tags on a run."""
        return {"run": dump(q.tag_run(ctx(), run_id, add or [], remove or []))}

    @mcp.tool()
    def get_predictions(run_id: str, metric: str | None = None, failures_only: bool = False,
                        offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """Page through predictions with references and per-example scores."""
        return dump(q.get_predictions(ctx(), run_id, offset=offset, limit=limit, metric=metric,
                                      failures_only=failures_only))

    return mcp
```

- [ ] **Step 4: Mount MCP over HTTP in the API**

In `src/hypothex/api/app.py`:

1. Add the import: `from hypothex.mcp.server import build_server`.
2. At the top of `create_app`, after `ctx = Context.open(home)`:

```python
    mcp_server = build_server(home)
    mcp_server.settings.streamable_http_path = "/"
    mcp_http = mcp_server.streamable_http_app()
```

3. Wrap the lifespan body so the MCP session manager runs:

```python
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(control.repair_runs, ctx)
        task = asyncio.create_task(_repair_loop(ctx)) if background_repair else None
        async with mcp_server.session_manager.run():
            try:
                yield
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
```

4. Before the UI mount at the end of `create_app`: `app.mount("/mcp", mcp_http)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/mcp tests/api -v`
Expected: PASS. If `test_mcp_is_served_over_http` gets 421/403, the SDK's DNS-rebinding protection is rejecting the host; configure `FastMCP(..., transport_security=TransportSecuritySettings(allowed_hosts=["127.0.0.1:*", "localhost:*"]))` per the installed SDK docs.

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/mcp src/hypothex/api/app.py tests/mcp
git commit -m "feat: MCP server over stdio and streamable HTTP"
```

---
### Task 18: Toy example, end-to-end test, and the agent skill

**Files:**
- Create: `examples/toy-classifier/README.md`, `examples/toy-classifier/hypothex.yaml`, `examples/toy-classifier/make_data.py`, `examples/toy-classifier/toy_metrics.py`, `examples/toy-classifier/train_eval.py`, `skills/hypothex/SKILL.md`
- Test: `tests/test_e2e_toy.py`, `tests/test_skill.py`

**Interfaces:**
- Consumes: the whole CLI (Task 15) and SDK (Task 14).
- Produces: a runnable example project and a skill file whose `hx` commands all exist.

- [ ] **Step 1: Write the example project**

`examples/toy-classifier/hypothex.yaml`:

```yaml
project: toy-classifier
description: Three scikit-learn models on a synthetic 3-class problem.

datasets:
  toyset:
    version: v1
    path: data/test.jsonl
    splits: {train: data/train.jsonl, test: data/test.jsonl}

metrics:
  accuracy:
    version: v1
    fn: toy_metrics:accuracy
    changelog: {v1: fraction of exact matches}
  macro_f1:
    version: v1
    fn: toy_metrics:macro_f1
    changelog: {v1: sklearn macro F1}

tasks:
  toy-test:
    description: Classify the held-out test split.
    dataset: toyset
    split: test
    metrics: [accuracy, macro_f1]
    primary: accuracy

stages:
  train: python train_eval.py --model {model} --seed {seed}

env:
  python: [python]
```

`examples/toy-classifier/make_data.py`:

```python
"""Generate data/train.jsonl and data/test.jsonl for the toy task."""

import json
from pathlib import Path

from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split


def main(out_dir: Path = Path(__file__).parent / "data") -> None:
    """Write a deterministic synthetic 3-class dataset."""
    x, y = make_classification(n_samples=600, n_features=10, n_informative=5, n_classes=3,
                               n_clusters_per_class=1, random_state=0)
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.3, random_state=0,
                                                        stratify=y)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, xs, ys in (("train", x_train, y_train), ("test", x_test, y_test)):
        with (out_dir / f"{name}.jsonl").open("w") as fh:
            for i, (features, label) in enumerate(zip(xs, ys, strict=True)):
                row = {"id": f"{name}-{i}", "x": [round(float(v), 6) for v in features],
                       "reference": int(label)}
                fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
```

`examples/toy-classifier/toy_metrics.py`:

```python
"""Metrics for the toy task. Bump the version in hypothex.yaml when you change one."""

from sklearn.metrics import f1_score

from hypothex import Example, MetricResult


def accuracy(examples: list[Example]) -> MetricResult:
    """Fraction of exact matches, with per-example correctness."""
    per = {e.id: {"correct": e.prediction == e.reference} for e in examples}
    return MetricResult(values={"value": sum(v["correct"] for v in per.values()) / len(per)},
                        per_example=per)


def macro_f1(examples: list[Example]) -> float:
    """Macro-averaged F1."""
    return float(f1_score([e.reference for e in examples], [e.prediction for e in examples],
                          average="macro"))
```

`examples/toy-classifier/train_eval.py`:

```python
"""Train one model and write test predictions through the Hypothex SDK."""

import argparse
import json
import pickle
from pathlib import Path

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier

import hypothex as hx

HERE = Path(__file__).parent


def load(split: str) -> list[dict]:
    """Read one split."""
    text = (HERE / "data" / f"{split}.jsonl").read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def build(model: str, seed: int):  # noqa: ANN201 - returns an sklearn estimator
    """Create the estimator."""
    if model == "logreg":
        return LogisticRegression(max_iter=1000, random_state=seed)
    if model == "rf":
        return RandomForestClassifier(n_estimators=50, random_state=seed)
    if model == "knn":
        return KNeighborsClassifier(n_neighbors=5)
    raise SystemExit(f"unknown model {model!r}")


def main() -> None:
    """Fit, log train accuracy, write predictions and a checkpoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    run = hx.current()
    train, test = load("train"), load("test")
    clf = build(args.model, args.seed)
    clf.fit([r["x"] for r in train], [r["reference"] for r in train])
    run.log({"train_accuracy": float(clf.score([r["x"] for r in train],
                                               [r["reference"] for r in train]))})
    preds = clf.predict([r["x"] for r in test])
    run.log_predictions({"id": r["id"], "prediction": int(p)}
                        for r, p in zip(test, preds, strict=True))
    if isinstance(run, hx.Run):
        ckpt = run.run_dir / "model.pkl"
        ckpt.write_bytes(pickle.dumps(clf))
        run.log_artifact(ckpt, kind="checkpoint")
    print(f"{args.model} seed={args.seed} done")


if __name__ == "__main__":
    main()
```

`examples/toy-classifier/README.md`:

````markdown
# Toy classifier example

Three scikit-learn models, three seeds each, one task (`toy-test`), two metrics.

```bash
cd examples/toy-classifier
uv run python make_data.py
git init -q && git add -A && git commit -qm init   # optional, gives exact reruns

for m in logreg rf knn; do
  for s in 1 2 3; do
    uv run hx run -t toy-test -H "baseline: $m" --seed $s -- \
      python train_eval.py --model $m --seed {seed}
  done
done

uv run hx leaderboard toy-test
uv run hx show <run-id>                 # every path: code, data, results, checkpoint
uv run hx predictions <run-id> --failures
```

Change a metric? Edit `toy_metrics.py`, bump its `version` in `hypothex.yaml`, then:

```bash
uv run hx reeval --task toy-test        # re-scores saved predictions; old scores are kept
```
````

- [ ] **Step 2: Write the skill file**

`skills/hypothex/SKILL.md`:

````markdown
---
name: hypothex
description: Use when running, comparing, or iterating on ML/AI experiments in a repo that has a hypothex.yaml, or when asked to track, rerun, re-evaluate, or compare experiments with Hypothex (`hx`).
---

# Hypothex: the experiment loop

Hypothex records every run: task (dataset + versioned metrics), hypothesis, exact
command, git commit + uncommitted diff, config, seed, dataset fingerprints,
environment, logs, predictions, scores. Always use `--json` and parse the output.

Set `HYPOTHEX_AGENT=<your name>` in your environment. Runs then record you as the
author, and Hypothex rejects runs that have no hypothesis.

## Loop for a new iteration

1. Find the task: `hx tasks --json`. Details: `hx task show <task> --json`
   (dataset path + version, metric fns + versions, stages, repo).
2. See the state of the art: `hx leaderboard <task> --json`. Rows are seed groups
   (`mean ± std`, `n`). `within_noise_of_best: true` means "not a real win yet".
3. Read what was tried: `hx show <run_id> --json` for the top rows. Read
   `record.hypothesis` and `notes`. Do not repeat a finished idea.
4. Run the new iteration from the project repo, with a one-sentence hypothesis
   and at least 3 seeds before you claim anything:

   ```bash
   for s in 1 2 3; do
     hx run --json -t <task> -H "<why this should help>" --seed $s -- \
       python train.py --model new --seed {seed}
   done
   ```

   `{seed}`, `{run_dir}`, `{dataset.path}`, `{config}` are filled in by Hypothex.
   Use `{seed}` (not a literal number) so runs group into one seed group.
   Long jobs: `hx launch ... --json` returns at once; check with
   `hx logs <run_id> --follow` or `hx show <run_id> --json`.
5. Compare: `hx compare <new_run> <best_run> --json`, and
   `hx examples <best_run> <new_run> --metric <metric> --json` to see which
   examples got fixed or broken.
6. Write down what you learned: `hx note <run_id> "<finding and next step>"`.
   Tag useful runs: `hx tag <run_id> --add baseline`.

## Rules

- Never delete run folders. To hide a dead end, use `hx archive <run_id>`.
- Never change a metric's code without bumping its `version` in `hypothex.yaml`.
  Then run `hx reeval --task <task> --json`. Old scores stay. The leaderboard
  uses the current version.
- Rerun exactly: `hx rerun <run_id> --json` (same commit, config, and seed; uses
  a git worktree if needed). Re-score only: `hx reeval <run_id> --json`.
  New inference from a checkpoint: `hx reinfer <run_id> --json`.
- If `hx validate --json` shows errors, fix `hypothex.yaml` before you run.
- Your code logs through the SDK: `import hypothex as hx; run = hx.current()`.
  Use `run.log({...})`, `run.log_predictions([{"id": ..., "prediction": ...}])`, and
  `run.log_artifact(path, kind="checkpoint")`. It does nothing outside Hypothex.

## Where things are

`hx show <run_id> --json` → `paths`: `run_dir`, `repo`, `cwd`, `config`,
`stdout`/`stderr`, `predictions`, `env`, `dataset:<name>` (host:path),
`artifact:<kind>:<i>` (host:path). Everything under `run_dir` is plain YAML/JSONL
you can read directly.
````

- [ ] **Step 3: Write the failing tests**

`tests/test_skill.py`:

```python
import re
from pathlib import Path

import typer

from hypothex.cli.main import app

SKILL = Path(__file__).resolve().parents[1] / "skills" / "hypothex" / "SKILL.md"


def test_skill_frontmatter() -> None:
    text = SKILL.read_text()
    assert text.startswith("---\nname: hypothex\ndescription: Use when")


def test_every_hx_command_in_skill_exists() -> None:
    group = typer.main.get_command(app)
    known = set(group.commands)  # type: ignore[attr-defined]
    used = set(re.findall(r"\bhx ([a-z]+)", SKILL.read_text()))
    assert used, "skill mentions no commands"
    assert used <= known, f"unknown commands in SKILL.md: {used - known}"
```

`tests/test_e2e_toy.py`:

```python
"""End to end: the toy example through the real CLI."""

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from hypothex.cli.main import app
from tests.factories import init_git_repo

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "toy-classifier"
runner = CliRunner()


def hx(*args: str) -> dict:
    argv = list(args)
    argv.insert(argv.index("--") if "--" in argv else len(argv), "--json")
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_toy_classifier_end_to_end(home: Path, tmp_path: Path,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "toy-classifier"
    shutil.copytree(EXAMPLE, repo, ignore=shutil.ignore_patterns("data"))
    cfg_path = repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["env"]["python"] = [sys.executable]
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    monkeypatch.chdir(repo)
    assert runner.invoke(app, ["--help"]).exit_code == 0
    runpy.run_path(str(repo / "make_data.py"), run_name="__main__")
    init_git_repo(repo)

    # 3 models x 3 seeds
    for model in ("logreg", "rf", "knn"):
        for seed in (1, 2, 3):
            out = hx("run", "-t", "toy-test", "-H", f"baseline {model}", "--seed", str(seed),
                     "--", sys.executable, "train_eval.py", "--model", model, "--seed", "{seed}")
            assert out["status"] == "finished"

    board = hx("leaderboard", "toy-test")
    assert len(board["rows"]) == 3 and all(r["n"] == 3 for r in board["rows"])
    assert board["rows"][0]["primary"]["mean"] > 0.5

    # bump a metric version: old scores become stale, re-eval rescores from predictions
    cfg["metrics"]["accuracy"]["version"] = "v2"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    stale = hx("leaderboard", "toy-test")
    assert len(stale["needs_reeval"]) == 9
    assert len(hx("reeval", "--task", "toy-test")["evaluated"]) == 9
    board = hx("leaderboard", "toy-test")
    assert board["metric_versions"]["accuracy"] == "v2"
    assert all(r["n"] == 3 and r["primary"] is not None for r in board["rows"])

    best = board["rows"][0]
    detail = hx("show", best["latest_run_id"])
    versions = {s["version"] for s in detail["scores"] if s["metric"] == "accuracy"}
    assert versions == {"v1", "v2"}
    assert detail["paths"]["dataset:toyset"].endswith("data/test.jsonl")
    assert any(k.startswith("artifact:checkpoint") for k in detail["paths"])

    cmp = hx("compare", *best["run_ids"][:2])
    assert cmp["fields"]["seed"] != [None, None]

    # exact rerun and re-infer-free re-score of one run
    child = hx("rerun", best["latest_run_id"], "--foreground")
    assert child["status"] == "finished" and child["parent"] == best["latest_run_id"]

    # the index is disposable: delete it, rebuild, get the same leaderboard
    before = hx("leaderboard", "toy-test")
    for path in home.glob("index.db*"):
        path.unlink()
    hx("reindex")
    assert hx("leaderboard", "toy-test") == before
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_skill.py tests/test_e2e_toy.py -v`
Expected: PASS (the E2E test takes roughly 30–90 s).

- [ ] **Step 5: Commit**

```bash
git add examples skills tests/test_skill.py tests/test_e2e_toy.py
git commit -m "feat: toy example, end-to-end test, and agent skill"
```

---

### Task 19: Docs, README, CI

**Files:**
- Create: `docs/conf.py`, `docs/index.rst`, `docs/quickstart.rst`, `docs/project_file.rst`, `docs/cli.rst`, `docs/sdk.rst`, `docs/agents.rst`, `docs/architecture.rst`, `.github/workflows/ci.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything.
- Produces: `uv run sphinx-build -b html docs docs/_build/html` builds; CI runs lint, format check, types, tests.

- [ ] **Step 1: Sphinx config and pages**

`docs/conf.py`:

```python
"""Sphinx configuration."""

project = "Hypothex"
author = "Shreyas Vinaya Sathyanarayana"
extensions = ["sphinx.ext.autodoc", "sphinx.ext.viewcode", "numpydoc"]
html_theme = "sphinx_rtd_theme"
numpydoc_show_class_members = False
exclude_patterns = ["_build", "superpowers"]
```

`docs/index.rst`:

```rst
Hypothex
========

Experiment tracker and control panel for AI researchers and their agents.

.. toctree::
   :maxdepth: 2

   quickstart
   project_file
   cli
   sdk
   agents
   architecture
```

`docs/quickstart.rst`: copy the commands from `examples/toy-classifier/README.md` (install with `uv add hypothex` or `uv tool install hypothex`, `hx init`, `hx validate`, `hx run -t TASK -H WHY --seed N -- CMD {seed}`, `hx leaderboard`, `hx show`, bump metric version, `hx reeval --task`), each as a `.. code-block:: bash` with one sentence of explanation.

`docs/project_file.rst`: the annotated `hypothex.yaml` from spec section 3.1, adjusted to `primary: topk/k=1`, plus the list of built-in template variables (`run_id, run_dir, repo, task, seed, config, checkpoint, dataset.name, dataset.version, dataset.path`) and the rule that other `{name}` values come from `--var name=value`.

`docs/cli.rst`: one section per command group (discover, run, evaluate, compare, curate, datasets, maintenance, servers). Each section gives one example command with `--json` and one sentence on what it does.

`docs/sdk.rst`:

```rst
Python SDK
==========

.. code-block:: python

   import hypothex as hx

   run = hx.current()   # no-op outside Hypothex
   run.log({"loss": 0.41})
   run.log_predictions([{"id": "ex-1", "prediction": 1}])
   run.log_artifact("model.pt", kind="checkpoint")

.. automodule:: hypothex.sdk
   :members:

Metric functions
----------------

.. automodule:: hypothex.metrics
   :members:
```

`docs/agents.rst`: how to connect agents —
(1) CLI: set `HYPOTHEX_AGENT=claude` and use `--json`;
(2) skill: copy `skills/hypothex/` into `~/.claude/skills/` (Claude Code) or reference it from `AGENTS.md` (Codex);
(3) MCP over stdio: `claude mcp add hypothex -- uv run --project /path/to/hypothex hx mcp`;
(4) MCP over HTTP: `hx serve`, then connect to `http://127.0.0.1:7777/mcp/`;
(5) HTTP API: the OpenAPI docs are at `/api/docs`.

`docs/architecture.rst`: short version of spec sections 3 and 5.2–5.3 (files first, rebuildable index, event log + `after_sequence` replay, idempotent `command_id`, per-run lock, supervisors and repair), plus a "Phase 2" note about env servers per machine.

- [ ] **Step 2: README**

Replace `README.md` with: one-line pitch; a "Why" list (the four bullets from the current README); "Install" (`uv tool install hypothex`); a 6-command quickstart (from Task 18's example README); "For agents" (skill + MCP one-liners from `docs/agents.rst`); "Status: phase 1a (core backend); UI in progress"; license Apache-2.0; link to the spec.

- [ ] **Step 3: CI**

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync --all-groups
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run ty check src
      - run: uv run pytest -q
      - run: uv run sphinx-build -b html docs docs/_build/html
```

- [ ] **Step 4: Verify everything locally**

Run:

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check src && uv run pytest -q && uv run sphinx-build -b html docs docs/_build/html
```

Expected: all green. Fix any `ty` findings in `src/` (do not silence them with blanket ignores; a targeted `# type: ignore[code]` with a reason is acceptable only for third-party typing gaps).

- [ ] **Step 5: Commit**

```bash
git add docs/conf.py docs/*.rst README.md .github/workflows/ci.yml
git commit -m "docs: Sphinx docs, README quickstart, CI workflow"
```

---

### Task 20: Acceptance — agent loop and DeepRetro pilot

**Files:**
- Create: `docs/superpowers/plans/2026-09-26-hypothex-phase1a-acceptance.md` (results log)

**Interfaces:**
- Consumes: the finished phase 1a.
- Produces: evidence for the spec's phase 1a "done when": toy E2E green in CI; an agent completes the loop using only the skill file; DeepRetro onboarded with one task and ≥ 3 runs.

- [ ] **Step 1: Toy E2E green in CI**

Push the branch, open a PR, and confirm the `ci` workflow passes on both OSes. Record the run URL in the acceptance log.

- [ ] **Step 2: Agent-only loop**

In a scratch copy of `examples/toy-classifier` (data generated, git initialised, 3 baseline models × 3 seeds already run), start a fresh agent session whose only instructions are the contents of `skills/hypothex/SKILL.md` plus: "Improve the best accuracy on task toy-test with a new model. Follow the skill." with `HYPOTHEX_AGENT=acceptance`. Pass criteria, checked afterwards with `hx runs --json` and `hx show`:
- ≥ 3 new runs on `toy-test`, all with a non-empty hypothesis and `created_by == "agent:acceptance"`, sharing one `config_hash` (seed group of n ≥ 3);
- the agent ran `hx compare` or `hx examples` against the previous best;
- a note exists on at least one new run.
Record the transcript path and the pass/fail per criterion in the acceptance log.

- [ ] **Step 3: DeepRetro pilot (with the user)**

Ask the user which DeepRetro evaluation to onboard (a benchmark that runs in minutes, its dataset path, and its metric). Then in `~/Desktop/code/DeepRetro`: `hx init`, fill `hypothex.yaml` (dataset with host/path, one metric module with a versioned function, one task, the `infer` stage), `hx validate`, and run the chosen evaluation 3 times (3 seeds or 3 configurations) with `hx run`. Pass criteria: `hx leaderboard <task>` shows the runs; `hx show` lists every path (repo@commit, dataset host:path + hash, run dir, checkpoint); `hx reeval --task` works after a version bump. Record the results in the acceptance log.

- [ ] **Step 4: Commit the acceptance log**

```bash
git add docs/superpowers/plans/2026-09-26-hypothex-phase1a-acceptance.md
git commit -m "docs: phase 1a acceptance results"
```

---

## Notes and deliberate deviations from the spec

- `hx datasets register` is not a command: datasets are registered by declaring them in `hypothex.yaml`; `hx datasets check` fingerprints them. (Spec 7.2 lists `register`.)
- The index uses a schema-version-and-rebuild scheme instead of Alembic until Postgres arrives in phase 3 (spec 3.4 updated).
- Writes are synchronous under a per-run lock (run folder → event → index); the event log is the change feed (spec 5.3 updated).
- Not in 1a (by phase table): remote env servers, SSH/SLURM, hosts, queue, sweeps, cost, notebook, baselines, alerts, export, storage cleanup, auth, UI (plan 1b after mockups).
