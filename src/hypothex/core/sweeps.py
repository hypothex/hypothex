"""Sweeps: a grid of params (plus seeded random samples) times seeds, launched as one group."""

from __future__ import annotations

import fcntl
import hashlib
import itertools
import json
import logging
import math
import re
import secrets
import sys
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from random import Random
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hypothex.core.config import (
    BUILTIN_TEMPLATE_VARS,
    NAME_PATTERN,
    ProjectConfig,
    load_project_config,
    template_fields,
)
from hypothex.core.context import Context
from hypothex.core.control import cancel_if_queued, launch_run
from hypothex.core.errors import HypothexError, RunError, StoreError
from hypothex.core.events import CommandInterruptedError
from hypothex.core.execution import COMMIT_PATTERN, RunRequest
from hypothex.core.fsutil import atomic_write_text, read_yaml, write_yaml
from hypothex.core.headlines import NO_RUNS, fmt_metric, fmt_metric_delta, fmt_p
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.leaderboard import Leaderboard, LeaderboardRow, build_leaderboard
from hypothex.core.queries import primary_examples
from hypothex.core.records import RunRecord, RunStatus

log = logging.getLogger(__name__)

SWEEP_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
PARAM_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_.]*$"
SWEEP_TAG_PREFIX = "sweep:"
SWEEP_OWNER_CHARS = 8
"""A sweep tag names its owner by the first 8 hex digits of its environment id."""
SAMPLE_DIGITS = 4


class SweepError(HypothexError):
    """A sweep request is invalid: bad grid, seeds, size, or command template."""


class SweepParam(BaseModel):
    """
    One swept parameter: a list of grid ``values`` or a ``low``/``high`` range.

    Range params are sampled ``SweepSpec.random`` times (log-uniform when ``log``).

    Examples
    --------
    >>> SweepParam(name="lr", values=["1e-4", "3e-4"]).is_range
    False
    >>> SweepParam(name="lr", low=1e-5, high=1e-2, log=True).is_range
    True
    """

    model_config = ConfigDict(coerce_numbers_to_str=True, extra="forbid")

    name: str = Field(pattern=PARAM_NAME_PATTERN)
    values: list[str] | None = None
    low: float | None = Field(None, allow_inf_nan=False)
    high: float | None = Field(None, allow_inf_nan=False)
    log: bool = False

    @model_validator(mode="after")
    def _check(self) -> SweepParam:
        """Require exactly one of ``values`` or ``low``/``high``, each well formed."""
        if self.name in BUILTIN_TEMPLATE_VARS:
            raise ValueError(f"param name {self.name!r} is reserved")
        ranged = self.low is not None or self.high is not None
        if self.values is not None:
            if ranged:
                raise ValueError(f"param {self.name!r}: give values or low/high, not both")
            if not self.values or any(not v for v in self.values):
                raise ValueError(f"param {self.name!r}: values must be non-empty strings")
            if len(set(self.values)) != len(self.values):
                raise ValueError(f"param {self.name!r}: duplicate values")
            if self.log:
                raise ValueError(f"param {self.name!r}: log applies to low/high only")
            return self
        if self.low is None or self.high is None:
            raise ValueError(f"param {self.name!r}: give values, or both low and high")
        if not self.low < self.high:
            raise ValueError(f"param {self.name!r}: low must be below high")
        if self.log and self.low <= 0:
            raise ValueError(f"param {self.name!r}: log scale needs low > 0")
        return self

    @property
    def is_range(self) -> bool:
        """True for a ``low``/``high`` param, False for a grid param."""
        return self.values is None


class SweepSpec(BaseModel, extra="forbid"):
    """
    A sweep's definition, as stored in ``<store>/<project>/sweeps/<id>.yaml``.

    The file never lists runs: a sweep's runs are the runs tagged
    ``sweep:<owner8>:<id>`` (``sweep_tag``, ``sweep_runs``). ``seeds`` lists
    every seed the sweep asks for; ``extend_sweep`` adds to it before it
    launches.

    ``commit`` and ``diff`` pin the sweep's code (spec 8A.4): every run, the
    runs an extend adds included, gets them, so new seeds join the same seed
    groups. ``diff`` is ``git diff HEAD --binary`` text applied on top of
    ``commit``. Both are None for a sweep that pins nothing (older files too):
    its runs use the checkout as it is.
    """

    id: str = Field(pattern=SWEEP_ID_PATTERN)
    project: str = Field(pattern=NAME_PATTERN)
    task: str | None
    host: str | None
    grid: list[SweepParam]
    random: int | None = Field(None, ge=1)
    seeds: list[int] = Field(min_length=1)
    command_template: list[str] = Field(min_length=1)
    created_by: str
    created_at: datetime
    commit: str | None = Field(None, pattern=COMMIT_PATTERN.pattern)
    diff: str | None = None

    @model_validator(mode="after")
    def _check(self) -> SweepSpec:
        """Reject duplicate param names or seeds, ranges without ``random``, a bare diff."""
        names = [p.name for p in self.grid]
        dups = sorted({n for n in names if names.count(n) > 1})
        if dups:
            raise ValueError(f"duplicate params: {', '.join(dups)}")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("duplicate seeds")
        if self.random is None and any(p.is_range for p in self.grid):
            raise ValueError("low/high params need random=N samples")
        if self.diff is not None and self.commit is None:
            raise ValueError("a diff needs the commit it was taken against")
        return self


def sweep_tag(owner: str, sweep_id: str) -> str:
    """
    Return the tag every run of a sweep carries: ``sweep:<owner8>:<id>``.

    The owner is the environment that holds the sweep's definition (the hub,
    for sweeps made through it). Sweep ids are short and per hub, and one host
    can serve two hubs, so the tag names the owner: each hub's membership
    query (an exact tag match) sees only its own runs.

    Parameters
    ----------
    owner : str
        Environment id of the owner; its first ``SWEEP_OWNER_CHARS`` characters
        are used.
    sweep_id : str
        Sweep id.

    Returns
    -------
    str
        ``sweep:<owner8>:<id>``.

    Examples
    --------
    >>> sweep_tag("0a1b2c3d4e5f60718293a4b5c6d7e8f9", "s-7f3a")
    'sweep:0a1b2c3d:s-7f3a'
    """
    return f"{SWEEP_TAG_PREFIX}{owner[:SWEEP_OWNER_CHARS]}:{sweep_id}"


def parse_sweep_tag(tag: str) -> tuple[str, str] | None:
    """
    Split a sweep tag into its owner and sweep id.

    Parameters
    ----------
    tag : str
        Any run tag.

    Returns
    -------
    tuple of (str, str) or None
        ``(owner8, sweep_id)``, or None when ``tag`` is not a sweep tag.

    Examples
    --------
    >>> parse_sweep_tag("sweep:0a1b2c3d:s-7f3a")
    ('0a1b2c3d', 's-7f3a')
    >>> parse_sweep_tag("best") is None
    True
    """
    if not tag.startswith(SWEEP_TAG_PREFIX):
        return None
    owner, sep, sweep_id = tag.removeprefix(SWEEP_TAG_PREFIX).partition(":")
    if not sep or not owner or re.fullmatch(SWEEP_ID_PATTERN, sweep_id) is None:
        return None
    return owner, sweep_id


# expansion ---------------------------------------------------------------------------
def _draw(param: SweepParam, rng: Random) -> str:
    """Sample one value of a range param as a short string inside ``[low, high]``."""
    assert param.low is not None and param.high is not None
    if param.log:
        x = math.exp(rng.uniform(math.log(param.low), math.log(param.high)))
    else:
        x = rng.uniform(param.low, param.high)
    text = format(x, f".{SAMPLE_DIGITS}g")
    return text if param.low <= float(text) <= param.high else repr(x)


def _sample_indices(rng: Random, total: int, k: int) -> list[int]:
    """Pick ``k`` distinct indices in ``range(total)``, sorted, without listing the range."""
    if total <= sys.maxsize:
        return sorted(rng.sample(range(total), k))  # range is lazy; same draws as before
    picked: set[int] = set()
    while len(picked) < k:  # k <= MAX_SWEEP_RUNS and total is huge: few repeats
        picked.add(rng.randrange(total))
    return sorted(picked)


def _combo_at(params: list[SweepParam], index: int) -> dict[str, str]:
    """Decode a flat index of the grid product (last param fastest, like itertools.product)."""
    values: dict[str, str] = {}
    for param in reversed(params):
        options = list(param.values or ())
        index, pick = divmod(index, len(options))
        values[param.name] = options[pick]
    return {p.name: values[p.name] for p in params}


def expand(spec: SweepSpec, rng_seed: int = 0) -> list[dict[str, str]]:
    """
    List the sweep's param combinations (seeds are applied separately).

    Grid params form a product in the order given. With range params, ``random``
    samples are drawn once and crossed with every grid combination, so each grid
    cell sees the same samples. Without range params, ``random=N`` keeps N grid
    combinations chosen at random (all of them when N is at least the grid size).

    Parameters
    ----------
    spec : SweepSpec
        The sweep.
    rng_seed : int
        Seed of the random draws; the same seed gives the same list.

    Returns
    -------
    list of dict of str to str
        One dict per combination, keys in ``spec.grid`` order, duplicates removed.
        A sweep with no params gives ``[{}]``.

    Examples
    --------
    >>> spec = SweepSpec(id="s-1", project="toy", task=None, host=None,
    ...     grid=[SweepParam(name="lr", values=["1e-4", "3e-4"]),
    ...           SweepParam(name="beam", values=["1", "5"])],
    ...     seeds=[1], command_template=["train"], created_by="human",
    ...     created_at="2026-10-03T00:00:00Z")
    >>> expand(spec)[:2]
    [{'lr': '1e-4', 'beam': '1'}, {'lr': '1e-4', 'beam': '5'}]
    """
    fixed = [p for p in spec.grid if not p.is_range]
    ranged = [p for p in spec.grid if p.is_range]
    total = math.prod(len(p.values or ()) for p in fixed)
    rng = Random(rng_seed)
    if not ranged and spec.random is not None and spec.random < total:
        # pick flat indices and decode them: the full product may be astronomically big
        combos = [_combo_at(fixed, i) for i in _sample_indices(rng, total, spec.random)]
    else:  # bounded: launch refuses more than MAX_SWEEP_RUNS runs (grid x samples x seeds)
        combos = [
            dict(zip([p.name for p in fixed], values, strict=True))
            for values in itertools.product(*[list(p.values or ()) for p in fixed])
        ]
        if ranged:
            samples = [{p.name: _draw(p, rng) for p in ranged} for _ in range(spec.random or 0)]
            combos = [{**c, **s} for c in combos for s in samples]
    names = [p.name for p in spec.grid]
    unique = dict.fromkeys(tuple(c[n] for n in names) for c in combos)
    return [dict(zip(names, key, strict=True)) for key in unique]


def _rng_seed(sweep_id: str) -> int:
    """Derive a stable random seed from a sweep id."""
    return int.from_bytes(hashlib.sha256(sweep_id.encode("utf-8")).digest()[:8], "big")


def sweep_combos(spec: SweepSpec) -> list[dict[str, str]]:
    """
    Return the sweep's combinations with its own stable random seed.

    Launch, extend, and summary all call this, so a random sweep keeps the same
    samples for its whole life.

    Parameters
    ----------
    spec : SweepSpec
        The sweep.

    Returns
    -------
    list of dict of str to str
        ``expand(spec, rng_seed=<hash of spec.id>)``.
    """
    return expand(spec, rng_seed=_rng_seed(spec.id))


def planned_runs(spec: SweepSpec) -> int:
    """
    Return an upper bound on the sweep's run count without expanding it.

    Parameters
    ----------
    spec : SweepSpec
        The sweep.

    Returns
    -------
    int
        Combinations times seeds (before duplicate samples are removed).

    Examples
    --------
    >>> spec = SweepSpec(id="s-1", project="toy", task=None, host=None,
    ...     grid=[SweepParam(name="lr", values=["1", "2", "3"])],
    ...     seeds=[1, 2], command_template=["train"], created_by="human",
    ...     created_at="2026-10-03T00:00:00Z")
    >>> planned_runs(spec)
    6
    """
    grid = math.prod(len(p.values or ()) for p in spec.grid if not p.is_range)
    if any(p.is_range for p in spec.grid):
        combos = grid * (spec.random or 0)
    elif spec.random is not None:
        combos = min(spec.random, grid)
    else:
        combos = grid
    return combos * len(spec.seeds)


# storage -----------------------------------------------------------------------------
def sweeps_dir(layout: Layout, project: str) -> Path:
    """
    Return the folder holding a project's sweep files.

    Parameters
    ----------
    layout : Layout
        Home layout.
    project : str
        Project name.

    Returns
    -------
    Path
        ``<store>/<project>/sweeps``.
    """
    return layout.project_dir(project) / "sweeps"


def sweep_path(layout: Layout, project: str, sweep_id: str) -> Path:
    """
    Return the file of one sweep, refusing names that could leave the store.

    Parameters
    ----------
    layout : Layout
        Home layout.
    project : str
        Project name.
    sweep_id : str
        Sweep id.

    Returns
    -------
    Path
        ``<store>/<project>/sweeps/<id>.yaml``.

    Raises
    ------
    StoreError
        If ``project`` or ``sweep_id`` is not a valid name.
    """
    if not re.fullmatch(NAME_PATTERN, project) or not re.fullmatch(SWEEP_ID_PATTERN, sweep_id):
        raise StoreError(f"unknown sweep {project}/{sweep_id}")
    return sweeps_dir(layout, project) / f"{sweep_id}.yaml"


def save_sweep(layout: Layout, spec: SweepSpec) -> Path:
    """
    Atomically write a sweep file.

    Parameters
    ----------
    layout : Layout
        Home layout.
    spec : SweepSpec
        The sweep.

    Returns
    -------
    Path
        The written file, ``<store>/<project>/sweeps/<id>.yaml``.
    """
    path = sweep_path(layout, spec.project, spec.id)
    write_yaml(path, spec.model_dump(mode="json"))
    return path


def load_sweep(layout: Layout, project: str, sweep_id: str) -> SweepSpec:
    """
    Read a sweep file.

    Parameters
    ----------
    layout : Layout
        Home layout.
    project : str
        Project name.
    sweep_id : str
        Sweep id.

    Returns
    -------
    SweepSpec
        The stored sweep.

    Raises
    ------
    StoreError
        If the sweep does not exist or its file cannot be parsed.
    """
    path = sweep_path(layout, project, sweep_id)
    if not path.is_file():
        raise StoreError(f"unknown sweep {sweep_id!r} in project {project!r}")
    try:
        spec = SweepSpec.model_validate(read_yaml(path))
    except (ValueError, yaml.YAMLError) as exc:  # includes pydantic ValidationError
        raise StoreError(f"unreadable sweep file {path}: {_brief(exc)}") from exc
    if spec.id != sweep_id or spec.project != project:
        raise StoreError(f"sweep file {path} holds {spec.project}/{spec.id}")
    return spec


def _brief(exc: Exception) -> str:
    """One-line message for a validation or parse error."""
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'sweep'}: {e['msg']}" for e in exc.errors()
        )
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


@contextmanager
def _sweep_lock(layout: Layout, project: str, sweep_id: str) -> Iterator[None]:
    """Hold an exclusive cross-process lock on one sweep file."""
    path = sweep_path(layout, project, sweep_id).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def new_sweep_id(layout: Layout, project: str) -> str:
    """
    Reserve a new sweep id by creating its (empty) file exclusively.

    Parameters
    ----------
    layout : Layout
        Home layout.
    project : str
        Project name.

    Returns
    -------
    str
        ``s-`` plus 4 hex digits (12 after 64 collisions); its file now exists.
    """
    folder = sweeps_dir(layout, project)
    folder.mkdir(parents=True, exist_ok=True)
    for attempt in range(65):
        sweep_id = f"s-{secrets.token_hex(2 if attempt < 64 else 6)}"
        try:
            sweep_path(layout, project, sweep_id).open("x").close()
        except FileExistsError:
            continue
        return sweep_id
    raise StoreError(f"could not reserve a sweep id in {folder}")


# summary ------------------------------------------------------------------------------
STATUS_KEYS = tuple(s.value for s in RunStatus)


class SweepSummary(BaseModel):
    """
    A sweep's spec, progress, and per-cell results.

    ``cells`` holds one dict per param combination: ``params``, ``group_id``,
    ``n`` (scored seeds), ``mean``, ``lo``/``hi`` (95% interval: test-set when
    per-example scores exist, else over seeds), ``std``, ``run_ids``, and
    ``runs`` (``run_id``, ``status``, ``seed`` of each run). ``best`` is the
    best scored cell.
    """

    spec: SweepSpec
    counts: dict[str, int]
    cells: list[dict[str, Any]]
    best: dict[str, Any] | None
    headline: str
    total_usd: float
    run_ids: list[str] = Field(default_factory=list)
    """The sweep's members (runs tagged ``tag``), in launch order; derived."""
    tag: str = ""
    """The sweep's member tag ``sweep:<owner8>:<id>`` (ask ``GET /api/v1/runs?tag=``)."""


def sweep_runs(ctx: Context, spec: SweepSpec) -> list[RunRecord]:
    """
    Return the members of a sweep: its indexed runs tagged ``sweep:<owner8>:<id>``.

    Membership is derived, never stored: a run that a host accepted counts as
    soon as it is mirrored, even when the launch call that started it failed.
    The owner is this environment (its store holds the definition), so the
    runs of another hub's sweep with the same id are never members.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    spec : SweepSpec
        The sweep.

    Returns
    -------
    list of RunRecord
        Archived ones included, in launch order (``created_at``, then run id).
    """
    tag = sweep_tag(ctx.descriptor.environment_id, spec.id)
    tagged = ctx.index.list_runs(project=spec.project, tag=tag, include_archived=True, limit=None)
    return sorted(tagged, key=lambda r: (r.created_at, r.run_id))


def unknown_task_headline(task: str) -> str:
    """
    Headline of a sweep whose task is not in the project config (e.g. after a rename).

    Parameters
    ----------
    task : str
        The task the sweep names.

    Returns
    -------
    str
        The headline; the summary then has no stats.

    Examples
    --------
    >>> unknown_task_headline("toy-acc")
    'Unknown task toy-acc: not in the project config'
    """
    return f"Unknown task {task}: not in the project config"


def _task_config(ctx: Context, spec: SweepSpec) -> ProjectConfig | None:
    """
    The project config when the sweep's task is in it, else None (no task, or unknown).

    An unreadable project file raises (``StoreError``): a sweep with scored runs
    must never quietly look unscored. An unknown task is logged; the caller
    gives it its own headline.
    """
    if spec.task is None:
        return None
    config = ctx.store.load_project(spec.project).config
    if spec.task not in config.tasks:
        log.warning(
            "sweep %s/%s names task %r, which is not in the project config",
            spec.project,
            spec.id,
            spec.task,
        )
        return None
    return config


def _board(
    ctx: Context, spec: SweepSpec, config: ProjectConfig | None, runs: list[RunRecord]
) -> Leaderboard | None:
    """The task leaderboard restricted to ``runs``, or None without a known task."""
    if spec.task is None or config is None:
        return None
    scores = ctx.index.scores_for(r.run_id for r in runs)
    per_example = primary_examples(ctx, config, spec.task, runs, None)
    return build_leaderboard(spec.project, spec.task, config, runs, scores, per_example=per_example)


def _cell(
    params: dict[str, str], members: list[RunRecord], rows: list[LeaderboardRow]
) -> dict[str, Any]:
    """One heat-table cell from its runs and the leaderboard rows they fall in."""
    row = rows[0] if rows else None
    primary = row.primary if row is not None else None
    lo = hi = None
    if row is not None and row.test_interval is not None:
        lo, hi = row.test_interval.lo, row.test_interval.hi
    elif primary is not None:
        lo, hi = primary.ci_low, primary.ci_high
    return {
        "params": params,
        "group_id": row.group_id if row is not None else None,
        "n": primary.n if primary is not None else 0,
        "mean": primary.mean if primary is not None else None,
        "lo": lo,
        "hi": hi,
        "std": primary.std if primary is not None and primary.n > 1 else None,
        "run_ids": [m.run_id for m in members],
        "runs": [{"run_id": m.run_id, "status": m.status.value, "seed": m.seed} for m in members],
    }


def _cells(
    spec: SweepSpec, runs: list[RunRecord], board: Leaderboard | None
) -> list[dict[str, Any]]:
    """Group runs by param combination (in expansion order) and attach their stats."""
    names = [p.name for p in spec.grid]
    keyed: dict[tuple[str, ...], list[RunRecord]] = {
        tuple(c[n] for n in names): [] for c in sweep_combos(spec)
    }
    for r in runs:
        keyed.setdefault(tuple(r.params.get(n, "") for n in names), []).append(r)
    rows = board.rows if board is not None else []
    rank = {row.group_id: i for i, row in enumerate(rows)}
    cells = []
    for key, members in keyed.items():
        ids = {m.run_id for m in members}
        hits = [row for row in rows if ids & set(row.run_ids) and row.primary is not None]
        hits.sort(key=lambda row: (-row.n, rank[row.group_id]))
        cells.append(_cell(dict(zip(names, key, strict=True)), members, hits))
    return cells


def _label(params: dict[str, str]) -> str:
    """``lr 3e-4, beam 10``."""
    return ", ".join(f"{k} {v}" for k, v in params.items())


def _metric_name(primary: str) -> str:
    """``accuracy/value`` -> ``accuracy``; other keys stay as ``topk/k=1``."""
    metric, _, key = primary.partition("/")
    return metric if key == "value" else primary


def _p_between(
    ctx: Context,
    spec: SweepSpec,
    config: ProjectConfig | None,
    runs: list[RunRecord],
    board: Leaderboard | None,
    ranked: list[dict[str, Any]],
) -> float | None:
    """
    p-value of the displayed best cell against the displayed runner-up.

    The leaderboard's ``vs_best`` compares each row with the board's best row,
    which may be a row no cell shows (a cell keeps its largest group). So the
    two displayed rows get their own leaderboard, and its one comparison (the
    same sign, paired-bootstrap, or Welch test) is the headline's p.
    """
    if board is None or len(ranked) < 2:
        return None
    rows = {row.group_id: row for row in board.rows}
    ids = set(rows[ranked[0]["group_id"]].run_ids) | set(rows[ranked[1]["group_id"]].run_ids)
    pair = _board(ctx, spec, config, [r for r in runs if r.run_id in ids])
    if pair is None or len(pair.rows) < 2 or pair.rows[1].vs_best is None:
        return None
    return pair.rows[1].vs_best.p


def _headline(board: Leaderboard | None, ranked: list[dict[str, Any]], p: float | None) -> str:
    """``lr 3e-4: 0.820 accuracy, +0.100 over lr 1e-4, p = 0.07``."""
    if board is None or not ranked:
        return NO_RUNS
    best = ranked[0]
    value = fmt_metric(best["mean"], board.unit, board.value_format)
    head = f"{value} {_metric_name(board.primary)}"
    label = _label(best["params"])
    text = f"{label}: {head}" if label else head
    if len(ranked) < 2:
        return text
    runner = ranked[1]
    delta = fmt_metric_delta(
        best["mean"] - runner["mean"], runner["mean"], board.unit, board.value_format
    )
    differs = {k: v for k, v in runner["params"].items() if best["params"].get(k) != v}
    text += f", {delta} over {_label(differs or runner['params'])}"
    if p is not None:
        text += f", {fmt_p(p)}"
    return text


def _run_usd(record: RunRecord) -> float:
    """Final cost of a run, or its API spend so far when the cost is not filled yet."""
    if record.cost is not None:
        return record.cost.total_usd
    return record.usage.usd if record.usage is not None else 0.0


def summarize_sweep(ctx: Context, project: str, sweep_id: str) -> SweepSummary:
    """
    Summarize a sweep: status counts, per-cell stats, best cell, headline, cost.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    sweep_id : str
        Sweep id.

    Returns
    -------
    SweepSummary
        ``counts`` has every run status plus ``total`` (the number of members;
        ``run_ids`` lists them). Cells follow ``sweep_combos`` order; stats come from the task's
        leaderboard over the sweep's finished runs. ``total_usd`` adds each run's
        ``cost.total_usd`` (its ``usage.usd`` while the cost is not filled).

    Raises
    ------
    StoreError
        If the sweep does not exist, or the project file cannot be read.
        A task that is not in the project config is not an error: the summary
        has no stats and its headline says so (``unknown_task_headline``).
    """
    return _summarize(ctx, load_sweep(ctx.layout, project, sweep_id))


def _summarize(ctx: Context, spec: SweepSpec) -> SweepSummary:
    """``summarize_sweep`` for a loaded spec; project errors propagate."""
    config = _task_config(ctx, spec)
    runs = sweep_runs(ctx, spec)
    counts = dict.fromkeys(STATUS_KEYS, 0)
    for r in runs:
        counts[r.status.value] += 1
    counts["total"] = len(runs)
    board = _board(ctx, spec, config, runs)
    cells = _cells(spec, runs, board)
    rank = {row.group_id: i for i, row in enumerate(board.rows)} if board is not None else {}
    ranked = sorted((c for c in cells if c["mean"] is not None), key=lambda c: rank[c["group_id"]])
    if spec.task is not None and config is None:
        headline = unknown_task_headline(spec.task)
    else:
        headline = _headline(board, ranked, _p_between(ctx, spec, config, runs, board, ranked))
    return SweepSummary(
        spec=spec,
        counts=counts,
        cells=cells,
        best=ranked[0] if ranked else None,
        headline=headline,
        total_usd=math.fsum(_run_usd(r) for r in runs),
        run_ids=[r.run_id for r in runs],
        tag=sweep_tag(ctx.descriptor.environment_id, spec.id),
    )


def list_sweeps(ctx: Context, project: str) -> list[dict[str, Any]]:
    """
    List a project's sweeps, newest first.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.

    Returns
    -------
    list of dict
        ``{id, created_at, n_runs, best}`` per sweep; unreadable sweep files are
        skipped (and logged).

    Raises
    ------
    StoreError
        If the project file cannot be read while a sweep names a task.
    """
    folder = sweeps_dir(ctx.layout, project)
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            spec = load_sweep(ctx.layout, project, path.stem)
        except StoreError:
            log.warning("skipping unreadable sweep file %s", path)
            continue
        summary = _summarize(ctx, spec)
        out.append(
            {
                "id": summary.spec.id,
                "created_at": summary.spec.created_at,
                "n_runs": summary.counts["total"],
                "best": summary.best,
            }
        )
    out.sort(key=lambda s: (s["created_at"], s["id"]), reverse=True)
    return out


# launch -------------------------------------------------------------------------------
MAX_SWEEP_RUNS = 1000
COMMANDS_DIR = ".commands"
"""``<store>/<project>/sweeps/.commands/``: which sweep a launch command created."""
_ALWAYS_FIELDS = frozenset({"run_id", "run_dir", "repo", "task", "seed"})
_TASK_FIELDS = frozenset({"dataset.name", "dataset.version", "dataset.path"})

MAX_RUN_ATTEMPTS = 4
"""Command ids one sweep run may try: its first, then one per interrupted receipt."""

Launcher = Callable[[RunRequest, str], RunRecord]
"""Starts (or queues) one run and returns its record; gets the run's command id.

The hub passes a forwarder. A launcher must turn a repeated command id into
the run it already started (command receipts), never a second run.
"""


def run_command_id(
    environment_id: str,
    project: str,
    sweep_id: str,
    params: dict[str, str],
    seed: int | None,
    attempt: int = 0,
) -> str:
    """
    The command id of a sweep run, the same on every launch, retry, and extend.

    A run has one id per ``attempt``. Attempt 0 is the usual one; the next
    attempt is used only after the previous id's receipt was interrupted (see
    ``MAX_RUN_ATTEMPTS``). Each id is fixed, so a resume walks the same ids.

    Parameters
    ----------
    environment_id : str
        The environment that owns the sweep (the hub's): two hubs' sweeps with
        the same short id never share run ids.
    project : str
        Project name.
    sweep_id : str
        Sweep id.
    params : dict of str to str
        The run's combination (order does not matter).
    seed : int or None
        The run's seed.
    attempt : int
        0 for the run's first command id; n for its n-th replacement.

    Returns
    -------
    str
        16 hex digits.

    Examples
    --------
    >>> a = run_command_id("env", "toy", "s-0001", {"lr": "1e-4", "beam": "5"}, 1)
    >>> a == run_command_id("env", "toy", "s-0001", {"beam": "5", "lr": "1e-4"}, 1), len(a)
    (True, 16)
    >>> a == run_command_id("env", "toy", "s-0001", {"lr": "1e-4", "beam": "5"}, 1, attempt=1)
    False
    """
    parts: list[Any] = [environment_id, project, sweep_id, sorted(params.items()), seed]
    if attempt:
        parts.append(attempt)  # attempt 0 keeps the ids runs had before attempts existed
    key = json.dumps(parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _resolve_repo(
    ctx: Context, project: str, task: str | None, repo: Path | None, *, remote: bool = False
) -> Path:
    """
    The project's repo, checked to hold ``project`` and ``task``.

    For a host sweep (``remote``) the hub needs no checkout of its own: when the
    stored repo path is not a folder here (a project copied from a host,
    ``ProjectEntry.remote_host``, or a hub used from another laptop), the
    entry's ``hypothex.yaml`` snapshot is checked instead.
    """
    if repo is None:
        entry = ctx.store.load_project(project)
        path = Path(entry.repo)
        if not path.is_dir():
            if not remote:
                where = entry.remote_host or "another machine"
                raise SweepError(
                    f"project {project!r} has no checkout here (its repo is on {where}); "
                    "run the sweep with --host, or `hx register` a checkout here"
                )
            known = sorted(entry.config.tasks)
            if task is not None and task not in known:
                raise SweepError(f"unknown task {task!r}; known tasks: {known}")
            return path
    else:
        path = repo
    config = load_project_config(path)
    if config.project != project:
        raise SweepError(f"{path} holds project {config.project!r}, not {project!r}")
    if task is not None and task not in config.tasks:
        raise SweepError(f"unknown task {task!r}; known tasks: {sorted(config.tasks)}")
    return path.resolve()


def _check_launchable(spec: SweepSpec) -> None:
    """Refuse oversized sweeps and command fields no run could fill."""
    n = planned_runs(spec)
    if n > MAX_SWEEP_RUNS:
        raise SweepError(f"sweep would launch {n} runs; the limit is {MAX_SWEEP_RUNS}")
    allowed = _ALWAYS_FIELDS | {p.name for p in spec.grid}
    if spec.task is not None:
        allowed |= _TASK_FIELDS
    used = {f for part in spec.command_template for f in template_fields(part)}
    unknown = sorted(used - allowed)
    if unknown:
        names = ", ".join(p.name for p in spec.grid) or "none"
        raise SweepError(
            f"command uses {', '.join('{' + u + '}' for u in unknown)} but no sweep param "
            f"or built-in fills it (sweep params: {names})"
        )
    unused = [p.name for p in spec.grid if p.name not in used]
    if unused:
        names = ", ".join("{" + n + "}" for n in unused)
        raise SweepError(f"the command never uses {names}; every swept param must appear in it")


def mark_sweep(ctx: Context, run_id: str, sweep_id: str) -> RunRecord:
    """
    Record that a run belongs to a sweep (``RunRecord.sweep_id``).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id.
    sweep_id : str
        Sweep id.

    Returns
    -------
    RunRecord
        The updated record (event ``run.tagged``, payload ``{sweep_id}``).
    """
    return ctx.update_run(
        run_id,
        "run.tagged",
        lambda r: r.model_copy(update={"sweep_id": sweep_id}),
        {"sweep_id": sweep_id},
    )


def _local_launcher(ctx: Context, sweep_id: str) -> Launcher:
    """Launch on this machine with ``launch_run`` (once per command id) and mark the sweep."""

    def launch(req: RunRequest, command_id: str) -> RunRecord:
        def start() -> dict[str, Any]:
            record = launch_run(ctx, req)
            if record.sweep_id != sweep_id:
                record = mark_sweep(ctx, record.run_id, sweep_id)
            return record.model_dump(mode="json")

        # the receipt makes a repeated command id return the run it started
        return RunRecord.model_validate(ctx.events.run_once(command_id, start))

    return launch


def _requests(
    spec: SweepSpec,
    seeds: Iterable[int],
    repo: Path,
    *,
    owner: str,
    hypothesis: str,
    gpus: int,
    queue: bool,
) -> Iterator[tuple[int, RunRequest]]:
    """One request per seed and combination, seed-major (seed 1 of every cell first)."""
    combos = sweep_combos(spec)
    tag = sweep_tag(owner, spec.id)
    for seed in seeds:
        for combo in combos:
            yield (
                seed,
                RunRequest(
                    repo=repo,
                    command=list(spec.command_template),
                    task=spec.task,
                    hypothesis=hypothesis,
                    seed=seed,
                    tags=[tag],
                    params=dict(combo),
                    vars=dict(combo),
                    created_by=spec.created_by,
                    gpus=gpus,
                    queue=queue,
                    commit=spec.commit,
                    diff=spec.diff,
                ),
            )


def _combo_key(params: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(params.items()))


def _command_file(layout: Layout, project: str, command_id: str) -> Path:
    digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:32]
    return sweeps_dir(layout, project) / COMMANDS_DIR / f"{digest}.json"


def _claimed_sweep(layout: Layout, project: str, command_id: str | None) -> str | None:
    """The sweep id an earlier call with this ``command_id`` created, if any."""
    if command_id is None:
        return None
    try:
        data = json.loads(_command_file(layout, project, command_id).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    sweep_id = str(data.get("sweep_id"))
    if data.get("command_id") != command_id or not re.fullmatch(SWEEP_ID_PATTERN, sweep_id):
        return None
    return str(data["sweep_id"])


@contextmanager
def _command_lock(layout: Layout, project: str, command_id: str | None) -> Iterator[None]:
    """
    Hold an exclusive cross-process lock on one launch command id.

    Calls with the same ``command_id`` then read, reserve, and publish its
    sweep one at a time, so a race never makes two sweeps for one command.
    No ``command_id`` means nothing to share: no lock.
    """
    if command_id is None:
        yield
        return
    path = _command_file(layout, project, command_id).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _claim_sweep(layout: Layout, project: str, command_id: str | None, sweep_id: str) -> None:
    """Record, before any run starts, that ``command_id`` created ``sweep_id``."""
    if command_id is None:
        return
    path = _command_file(layout, project, command_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"command_id": command_id, "sweep_id": sweep_id}))


def _interrupted(exc: BaseException) -> bool:
    """
    True when a launch failed on an interrupted receipt, here or on a host.

    A host's answer keeps the error's class name (``EnvRequestError.error_type``).
    """
    name = CommandInterruptedError.__name__
    return isinstance(exc, CommandInterruptedError) or getattr(exc, "error_type", None) == name


def _member(ctx: Context, spec: SweepSpec, seed: int, params: dict[str, str]) -> RunRecord | None:
    """The sweep's run of (``params``, ``seed``), if one is indexed now."""
    key = (seed, _combo_key(params))
    return next((r for r in sweep_runs(ctx, spec) if (r.seed, _combo_key(r.params)) == key), None)


def _launch_run(
    ctx: Context,
    spec: SweepSpec,
    launch: Launcher,
    seed: int,
    req: RunRequest,
    requested: list[str] | None,
) -> RunRecord:
    """
    Launch one sweep run, past command ids whose receipts were interrupted.

    An interrupted receipt (the server stopped while it launched) never runs
    its command again, so that id would block every resume of the sweep. As
    the receipt asks, the runs are checked first: a member with these params
    and seed is the run that launch made. Else the run's next command id
    (``run_command_id`` ``attempt``) is tried, up to ``MAX_RUN_ATTEMPTS``.
    """
    owner = ctx.descriptor.environment_id
    attempt = 0
    while True:
        command_id = run_command_id(owner, spec.project, spec.id, req.params, seed, attempt)
        if requested is not None:
            requested.append(command_id)
        try:
            return launch(req, command_id)
        except HypothexError as exc:
            if not _interrupted(exc) or attempt == MAX_RUN_ATTEMPTS - 1:
                raise
            member = _member(ctx, spec, seed, req.params)
            if member is not None:
                return member
            log.warning(
                "sweep %s run %s seed %s: command %s was interrupted; trying the next id",
                spec.id,
                req.params,
                seed,
                command_id,
            )
            attempt += 1


def _issue(
    ctx: Context,
    spec: SweepSpec,
    launch: Launcher,
    requests: Iterable[tuple[int, RunRequest]],
    started: list[str],
    requested: list[str] | None = None,
) -> None:
    """
    Issue every (params, seed) of ``requests`` that has no member yet, in order.

    Each run gets its ``run_command_id``, so a run that exists but is not
    indexed yet (its answer lost, or not mirrored) comes back from the
    launcher's receipt instead of starting twice (``_launch_run``: an
    interrupted receipt moves on to the run's next id). ``started`` collects
    the run ids as they come back; ``requested`` collects each command id
    before its request goes out (the caller then knows a request was made).
    """
    have = {(r.seed, _combo_key(r.params)) for r in sweep_runs(ctx, spec)}
    for seed, req in requests:
        if (seed, _combo_key(req.params)) in have:
            continue
        started.append(_launch_run(ctx, spec, launch, seed, req, requested).run_id)


def launch_sweep(
    ctx: Context,
    *,
    project: str,
    grid: list[SweepParam],
    seeds: list[int],
    command: list[str],
    task: str | None = None,
    host: str | None = None,
    random: int | None = None,
    hypothesis: str = "",
    gpus: int = 0,
    queue: bool = False,
    created_by: str = "human",
    repo: Path | None = None,
    launch: Launcher | None = None,
    command_id: str | None = None,
    commit: str | None = None,
    diff: str | None = None,
) -> SweepSummary:
    """
    Create a sweep file and launch one run per param combination and seed.

    Every run gets tag ``sweep:<owner8>:<id>`` (``sweep_tag``; this environment
    owns the sweep), params ``k=v`` (also as template vars, so ``{k}`` in the
    command is filled), and its seed. Runs are launched seed-major.
    If a launch fails, the error is raised and the sweep file stays, even when
    the first request failed (a lost answer may hide an accepted run); only an
    error before any launch request leaves no file.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    grid : list of SweepParam
        Grid and range params.
    seeds : list of int
        Seeds; each combination runs once per seed.
    command : list of str
        Command template with ``{param}`` and ``{seed}`` fields.
    task : str, optional
        Task the runs are scored on.
    host : str, optional
        Host name recorded on the sweep (the ``launch`` callable does the routing).
    random : int, optional
        Number of random samples (see ``expand``).
    hypothesis : str
        Why the sweep exists; copied onto each run.
    gpus : int
        GPUs per run.
    queue : bool
        Queue runs until their GPUs are free.
    created_by : str
        ``human`` or ``agent:<name>``.
    repo : Path, optional
        Project repo; default the registered repo of ``project``.
    launch : callable, optional
        ``(RunRequest, command id) -> RunRecord``; default launches here with
        ``launch_run``, once per command id.
    command_id : str, optional
        The client's command id. A retry with the same id resumes the sweep
        the first call created and issues only its missing runs.
    commit : str, optional
        Commit every run of the sweep pins (stored as ``SweepSpec.commit``,
        so an extend pins it too); default none: the checkout as it is.
    diff : str, optional
        Uncommitted changes applied on top of ``commit`` (``git diff HEAD
        --binary`` text); needs ``commit``.

    Returns
    -------
    SweepSummary
        The new (or resumed) sweep's summary.

    Raises
    ------
    SweepError
        Invalid grid, seeds, size, command fields, task, or repo.
    StoreError
        ``project`` is not registered and no ``repo`` was given.

    Examples
    --------
    >>> launch_sweep(ctx, project="toy", task="toy-acc",
    ...     grid=[SweepParam(name="lr", values=["1e-4", "3e-4"])], seeds=[1, 2],
    ...     command=["python", "train.py", "--lr", "{lr}", "--seed", "{seed}"],
    ...     ).counts["total"]  # doctest: +SKIP
    4
    """
    if gpus < 0:
        raise SweepError("gpus must be 0 or more")
    try:
        draft = SweepSpec(
            id="pending",
            project=project,
            task=task,
            host=host,
            grid=grid,
            random=random,
            seeds=seeds,
            command_template=command,
            created_by=created_by,
            created_at=utcnow(),
            commit=commit,
            diff=diff,
        )
    except ValidationError as exc:
        raise SweepError(f"invalid sweep: {_brief(exc)}") from exc
    _check_launchable(draft)
    repo_path = _resolve_repo(ctx, project, task, repo, remote=launch is not None)
    started: list[str] = []
    # one command id at a time: its claim lookup, id reservation, and claim are one step,
    # so two racing calls never make two sweeps (and two run sets) for one command
    with _command_lock(ctx.layout, project, command_id):
        claimed = _claimed_sweep(ctx.layout, project, command_id)
        spec = draft.model_copy(update={"id": claimed or new_sweep_id(ctx.layout, project)})
        with _sweep_lock(ctx.layout, project, spec.id):
            if claimed is not None and sweep_path(ctx.layout, project, spec.id).is_file():
                spec = load_sweep(ctx.layout, project, spec.id)  # a retry: the stored definition
            else:
                save_sweep(ctx.layout, spec)
                _claim_sweep(ctx.layout, project, command_id, spec.id)  # before any run starts
            requests = _requests(
                spec,
                spec.seeds,
                repo_path,
                owner=ctx.descriptor.environment_id,
                hypothesis=hypothesis,
                gpus=gpus,
                queue=queue,
            )
            requested: list[str] = []
            try:
                _issue(
                    ctx, spec, launch or _local_launcher(ctx, spec.id), requests, started, requested
                )
            except BaseException:
                # once a request went out its outcome is unknown (an accepted run whose answer
                # was lost): the definition stays. Only a failure before any request removes it.
                if not requested and claimed is None:
                    sweep_path(ctx.layout, project, spec.id).unlink(missing_ok=True)
                raise
    return summarize_sweep(ctx, project, spec.id)


# cancel and extend -------------------------------------------------------------------
def stop_if_queued(ctx: Context, run_id: str) -> RunRecord:
    """
    Stop a run only while it is still queued.

    "Cancel queued" uses this, so a run that the scheduler started a moment ago
    keeps running.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id.

    Returns
    -------
    RunRecord
        The run's record: ``killed`` if it was queued, else unchanged.
    """
    return cancel_if_queued(ctx, run_id)  # one conditional step: never a check, then a stop


def cancel_queued(
    ctx: Context,
    project: str,
    sweep_id: str,
    *,
    stop: Callable[[str], object] | None = None,
) -> SweepSummary:
    """
    Stop every queued run of a sweep; running and finished runs are left alone.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    sweep_id : str
        Sweep id.
    stop : callable, optional
        ``run_id -> Any``; default ``stop_if_queued`` here (queued runs end
        ``killed``). The hub passes a forwarder for runs on remote hosts.

    Returns
    -------
    SweepSummary
        The sweep after the stops.

    Raises
    ------
    StoreError
        If the sweep does not exist.
    """
    spec = load_sweep(ctx.layout, project, sweep_id)
    do_stop = stop or (lambda run_id: stop_if_queued(ctx, run_id))
    for record in sweep_runs(ctx, spec):
        if record.status != RunStatus.QUEUED:
            continue
        try:
            do_stop(record.run_id)
        except RunError as exc:  # ended or started between the read and the stop
            log.info("not stopping %s: %s", record.run_id, exc)
    return summarize_sweep(ctx, project, sweep_id)


def extend_sweep(
    ctx: Context,
    project: str,
    sweep_id: str,
    seeds: list[int],
    *,
    repo: Path | None = None,
    gpus: int | None = None,
    queue: bool | None = None,
    hypothesis: str | None = None,
    launch: Launcher | None = None,
) -> SweepSummary:
    """
    Add seeds to a sweep: one new run per param combination and new seed.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    sweep_id : str
        Sweep id.
    seeds : list of int
        Seeds to add. Seeds already in the sweep are fine: only missing runs
        are issued (an extend that failed midway is resumed this way).
    repo : Path, optional
        Project repo; default the registered repo.
    gpus : int, optional
        GPUs per run; default the sweep's first run's ``gpus_requested`` (else 0).
    queue : bool, optional
        Queue the runs; default True when ``gpus > 0``.
    hypothesis : str, optional
        Default the sweep's first run's hypothesis.
    launch : callable, optional
        ``(RunRequest, command id) -> RunRecord``; default launches here with
        ``launch_run``, once per command id.

    Returns
    -------
    SweepSummary
        The grown sweep.

    Raises
    ------
    SweepError
        No seeds, or the sweep would grow past ``MAX_SWEEP_RUNS``.
    StoreError
        If the sweep does not exist.

    Examples
    --------
    >>> extend_sweep(ctx, "toy", "s-0001", [2, 3]).spec.seeds  # doctest: +SKIP
    [1, 2, 3]
    """
    new = list(dict.fromkeys(seeds))
    if not new:
        raise SweepError("give at least one seed")
    with _sweep_lock(ctx.layout, project, sweep_id):
        spec = load_sweep(ctx.layout, project, sweep_id)
        grown = spec.model_copy(
            update={"seeds": [*spec.seeds, *[s for s in new if s not in spec.seeds]]}
        )
        _check_launchable(grown)
        runs = sweep_runs(ctx, spec)
        first = runs[0] if runs else None
        n_gpus = gpus if gpus is not None else (first.gpus_requested if first else 0)
        if n_gpus < 0:
            raise SweepError("gpus must be 0 or more")
        if hypothesis is None:
            hypothesis = first.hypothesis if first else ""
        repo_path = _resolve_repo(ctx, project, spec.task, repo, remote=launch is not None)
        save_sweep(ctx.layout, grown)  # the definition first: a retry knows every seed
        requests = _requests(
            grown,
            grown.seeds,
            repo_path,
            owner=ctx.descriptor.environment_id,
            hypothesis=hypothesis,
            gpus=n_gpus,
            queue=queue if queue is not None else n_gpus > 0,
        )
        _issue(ctx, grown, launch or _local_launcher(ctx, sweep_id), requests, [])
    return summarize_sweep(ctx, project, sweep_id)
