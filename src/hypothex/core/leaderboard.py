"""Rank seed groups of a task by its primary metric, with seed and test-set noise."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import threading
from array import array
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

import xxhash
from pydantic import BaseModel, Field

from hypothex.core import stats
from hypothex.core.config import ProjectConfig, TaskKind, TaskSpec, parse_metric_key
from hypothex.core.cost import add_costs
from hypothex.core.errors import ConfigError
from hypothex.core.headlines import (
    ValueFormat,
    metric_unit,
    paired_gain_interval,
    percentile_of,
    task_headline,
    task_stat_strip,
    value_format,
)
from hypothex.core.index import index_generation
from hypothex.core.records import (
    CostTotals,
    GitInfo,
    RunRecord,
    RunStatus,
    ScoreRecord,
    UsageTotals,
)
from hypothex.core.seeds import Stats, clamp, summarize

if TYPE_CHECKING:
    from hypothex.core.context import Context

PerExample = dict[str, dict[str, dict[str, Any]]]
"""run_id -> example_id -> per-example fields of the primary metric."""

BINARY_FIELDS = ("correct", "solved")
LABEL_MAX = 32
NOISE_ALPHA = 0.05
"""``within_noise_of_best`` is true when the test against the best gives ``p >= 0.05``."""
LEGACY_DIRTY = "dirty"
"""``diff_key`` of a dirty run recorded without a diff hash."""
_CLAUSE = re.compile(
    r"[,;:()]|\s[-–—]\s|\.(?:\s|$)|\s(?:because|should|so that|since|to see if|in order to)\s",
    re.IGNORECASE,
)


_DERIVED_PREFIX = re.compile(r"^(?:(?:Rerun|Re-infer) of \S+:\s*)+")
"""``Rerun of <id>:`` / ``Re-infer of <id>:`` (also chained) that ``control`` prepends."""


class NoiseInterval(BaseModel):
    """A 95% interval from test-set noise."""

    lo: float
    hi: float
    method: Literal["wilson", "bootstrap"]
    n: int


class VersusBest(BaseModel):
    """How a seed group compares to the best group."""

    delta: float
    p: float | None
    fixed: int | None
    broken: int | None
    test: Literal["sign", "paired_bootstrap", "welch"] | None
    examples_needed: int | None
    delta_rel: float | None = None
    """``delta`` over the best group's mean (``None`` when that mean is 0)."""


class EvaluationPopulation(BaseModel):
    """Auditable population for a cost comparison over the selected success metric.

    Fingerprints encode actual example IDs and recorded dataset identity rather
    than relying on equal counts. Attempts and solved count every member run,
    including repeats of a seed whose resource usage remains in group costs.
    """

    metric: str
    version: str
    source_hash: str
    field: str
    dataset_fingerprint: str
    example_ids_hash: str
    examples: int
    attempts: int
    solved: int


class RepeatObservation(BaseModel):
    """One recorded repeat score with its exact evaluator and dataset identity."""

    run_id: str
    value: float
    metric: str
    version: str
    key: str
    source_hash: str
    dataset_fingerprint: str


class LeaderboardRow(BaseModel):
    """One seed group: runs with the same config hash, commit and uncommitted diff."""

    group_id: str
    run_ids: list[str]
    latest_run_id: str
    hypothesis: str
    commit: str | None
    config_hash: str
    n: int
    """Distinct seeds; reruns of a seed are one sample, runs without a seed one each."""
    scores: dict[str, Stats]
    primary: Stats | None
    single_seed: bool
    within_noise_of_best: bool | None = None
    """``vs_best.p >= 0.05`` (not a real win yet); ``None`` for the best row or without a p."""
    label: str
    seed_values: dict[str, list[float]]
    identical_seeds: bool
    test_interval: NoiseInterval | None
    vs_best: VersusBest | None
    created_by: list[str]
    usage: UsageTotals | None
    cost: CostTotals | None = None
    """Sum of the member runs' ``cost`` (spec 8A.7); None when no run has one yet."""
    cost_complete: bool = False
    """Every member has a cost record with explicitly complete GPU pricing."""
    repeat_observations: list[RepeatObservation] = Field(default_factory=list)
    """Complete, homogeneous recorded p95 repeats for system benchmark time metrics."""
    evaluation_population: EvaluationPopulation | None = None
    """Actual comparable scored attempts; absent when their evidence is incomplete."""


class Leaderboard(BaseModel):
    """A task's ranked seed groups plus runs that need attention."""

    project: str
    task: str
    primary: str
    higher_is_better: bool
    metric_versions: dict[str, str]
    metric_drift: list[str] = Field(default_factory=list)
    """Selected metric versions scored with more than one recorded source hash."""
    rows: list[LeaderboardRow]
    needs_reeval: list[str]
    unscored: list[str]
    headline: str
    kind: TaskKind
    stat_strip: list[dict[str, Any]]
    unit: str = ""
    """Display unit of the primary metric (``headlines.metric_unit``): ``ms``, ``$``, ..."""
    value_format: ValueFormat = "fraction"
    """How to show primary values and vs-best deltas (``headlines.value_format``)."""


# labels and ordering -------------------------------------------------------------
def group_label(
    hypothesis: str, tags: Iterable[str], group_id: str, *, limit: int | None = LABEL_MAX
) -> str:
    """
    Derive a short name for a seed group.

    Parameters
    ----------
    hypothesis : str
        The group's hypothesis (latest run).
    tags : iterable of str
        Tags of the group's runs.
    group_id : str
        The group id, used when there is nothing else.
    limit : int or None
        Longest clause kept whole (default ``LABEL_MAX``, 32); a longer one is cut
        at a word and ends in "…". ``None`` keeps the whole clause, for prose such
        as headlines.

    Returns
    -------
    str
        The hypothesis's first clause (cut at ``, ; : ( )``, a dash, a full stop,
        or words like "because"/"should"), at most ``limit`` characters; else the
        first tag in sorted order; else ``"group <id>"``. Leading ``Rerun of <id>:``
        and ``Re-infer of <id>:`` prefixes are dropped first, so a rerun keeps
        the parent's label.

    Examples
    --------
    >>> group_label("RBF-kernel SVM should beat RF", [], "g")
    'RBF-kernel SVM'
    >>> group_label("", ["svm"], "g")
    'svm'
    >>> group_label("Rerun of 20261004-1-x: svm, rbf", [], "g")
    'svm'
    >>> group_label("40k steps with heavier augmentation lifts accuracy", [], "g")
    '40k steps with heavier…'
    >>> group_label("40k steps with heavier augmentation lifts accuracy", [], "g", limit=None)
    '40k steps with heavier augmentation lifts accuracy'
    """
    text = _DERIVED_PREFIX.sub("", hypothesis.strip())
    parts = [p.strip() for p in _CLAUSE.split(text)]
    clause = next((p for p in parts if p), "")
    if clause:
        if limit is None or len(clause) <= limit:
            return clause
        cut = clause[:limit].rsplit(" ", 1)[0].rstrip() or clause[:limit]
        return cut + "…"
    tag_list = sorted({t for t in tags if t})
    return tag_list[0] if tag_list else f"group {group_id}"


def seed_group_label(
    members: list[RunRecord], group_id: str, version_param: str | None = None
) -> str:
    """
    The one label rule for a seed group (``LeaderboardRow.label`` and ``group_labels``).

    Parameters
    ----------
    members : list of RunRecord
        The group's runs, oldest first.
    group_id : str
        The group id, used when there is nothing else.
    version_param : str, optional
        The task's ``version_param`` (``agent_iteration`` tasks only), else ``None``.

    Returns
    -------
    str
        The ``version_param`` value when given and a run has it; else ``group_label``
        of the newest non-empty hypothesis and the group's tags (the first tag, else
        ``"group <id>"``).

    Examples
    --------
    >>> old = make_record(hypothesis="svm, rbf kernel")  # doctest: +SKIP
    >>> seed_group_label([old, make_record(hypothesis="")], "g")  # doctest: +SKIP
    'svm'
    """
    version = _version_of(members, version_param) if version_param is not None else None
    if version:
        return version
    hypothesis = next((r.hypothesis for r in reversed(members) if r.hypothesis.strip()), "")
    return group_label(hypothesis, (t for m in members for t in m.tags), group_id)


def distinct_labels(
    labels: Mapping[str, str], members_of: Mapping[str, list[RunRecord]]
) -> dict[str, str]:
    """
    Make the labels of seed groups that share one label different.

    Groups of a sweep often share a hypothesis, so ``seed_group_label`` gives
    them one name. Each such group gets ``" · "`` and the ``vars`` that differ
    between those groups (``"lr x beam · lr 1e-3, beam 10"``; a var the group
    does not have is left out). Groups whose names still match get
    ``" · <group id>"`` as well. A label no other group has is kept.

    Parameters
    ----------
    labels : mapping of str to str
        Label per group id (``seed_group_label``).
    members_of : mapping of str to list of RunRecord
        The runs of each group id, oldest first; the newest run's ``vars`` count.

    Returns
    -------
    dict of str to str
        Label per group id, in the order of ``labels``.

    Examples
    --------
    >>> a = [make_record(vars={"lr": "1e-3", "beam": "10"})]  # doctest: +SKIP
    >>> b = [make_record(vars={"lr": "1e-3", "beam": "5"})]  # doctest: +SKIP
    >>> same = {"g1": "lr x beam", "g2": "lr x beam"}
    >>> distinct_labels(same, {"g1": a, "g2": b})  # doctest: +SKIP
    {'g1': 'lr x beam · beam 10', 'g2': 'lr x beam · beam 5'}
    """
    out = dict(labels)
    shared: dict[str, list[str]] = defaultdict(list)
    for group_id, label in labels.items():
        shared[label].append(group_id)
    for label, group_ids in shared.items():
        if len(group_ids) < 2:
            continue
        vars_of = {g: members_of[g][-1].vars for g in group_ids}
        keys = list(dict.fromkeys(k for g in sorted(group_ids) for k in vars_of[g]))
        differ = [k for k in keys if len({vars_of[g].get(k) for g in group_ids}) > 1]
        for g in group_ids:
            parts = [f"{k} {vars_of[g][k]}" for k in differ if k in vars_of[g]]
            out[g] = f"{label} · {', '.join(parts)}" if parts else label
        counts = Counter(out[g] for g in group_ids)
        for g in group_ids:
            if counts[out[g]] > 1:
                out[g] = f"{out[g]} · {g}"
    return out


def seed_group_labels(
    members_of: Mapping[str, list[RunRecord]], version_param: str | None = None
) -> dict[str, str]:
    """
    Label every seed group: ``seed_group_label``, then ``distinct_labels``.

    This is the label rule of ``LeaderboardRow.label`` for the groups of one
    board, and of ``sources.group_labels`` for the groups of a view.

    Parameters
    ----------
    members_of : mapping of str to list of RunRecord
        The runs of each group id, oldest first.
    version_param : str, optional
        The task's ``version_param`` (``agent_iteration`` tasks only), else ``None``.

    Returns
    -------
    dict of str to str
        A label per group id; groups that would share one get the vars that
        differ, else their group id.

    Examples
    --------
    >>> runs = [make_record(hypothesis="svm, rbf kernel")]  # doctest: +SKIP
    >>> seed_group_labels({"g": runs})  # doctest: +SKIP
    {'g': 'svm'}
    """
    labels = {g: seed_group_label(m, g, version_param) for g, m in members_of.items()}
    return distinct_labels(labels, members_of)


def group_id_for(run: RunRecord) -> str:
    """
    Return the seed-group id of a run.

    Parameters
    ----------
    run : RunRecord
        Any run.

    Returns
    -------
    str
        ``<first 8 hex of the config hash>@<first 7 chars of the commit>``;
        ``nogit`` replaces the commit when the run has no git info. A run with
        uncommitted changes gets ``+<its full recorded diff hash>`` (``+dirty``
        when the record has no diff hash), so it never joins the clean group.

    Examples
    --------
    >>> group_id_for(make_record(config_hash="sha256:0123456789"))  # doctest: +SKIP
    '01234567@nogit'
    """
    base = f"{run.config_hash.removeprefix('sha256:')[:8]}@{(run.git.commit or 'nogit')[:7]}"
    diff = diff_key(run.git)
    if diff is None:
        return base
    return f"{base}+{diff}"


def diff_key(git: GitInfo) -> str | None:
    """
    Identify the uncommitted code a run started with.

    Parameters
    ----------
    git : GitInfo
        The run's git state.

    Returns
    -------
    str or None
        ``git.diff_hash`` when set; ``"dirty"`` for a dirty record without
        one (written before diff hashes existed); ``None`` for a clean run.

    Examples
    --------
    >>> diff_key(GitInfo(commit="abc")) is None
    True
    >>> diff_key(GitInfo(commit="abc", dirty=True))
    'dirty'
    """
    diff_hash: str | None = getattr(git, "diff_hash", None)
    if diff_hash:
        return diff_hash
    return LEGACY_DIRTY if git.dirty else None


def _version_of(members: list[RunRecord], param: str) -> str | None:
    for m in members:
        value = m.params.get(param) or m.vars.get(param)
        if value:
            return value
    return None


def _natural_key(text: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(tok)) if tok.isdigit() else (1, tok.lower()) for tok in re.findall(r"\d+|\D+", text)
    )


def _first_version(
    rows: list[LeaderboardRow], members_of: dict[str, list[RunRecord]], param: str
) -> str | None:
    def key(row: LeaderboardRow) -> tuple[int, tuple[tuple[int, int | str], ...], datetime]:
        members = members_of[row.group_id]
        version = _version_of(members, param)
        created = members[0].created_at
        return (0, _natural_key(version), created) if version else (1, (), created)

    scored = [r for r in rows if r.primary is not None]
    return min(scored, key=key).group_id if scored else None


def _paired_gain(
    best: LeaderboardRow, first: LeaderboardRow, pooled: dict[str, dict[str, float]]
) -> tuple[float, float] | None:
    """
    Paired 95% interval of ``best - first`` over the examples both were scored on.

    Uses the sign-test counts of ``first.vs_best`` (computed on those same shared
    examples) and counts the shared ids here, where they are still known.
    """
    vs = first.vs_best
    if (
        vs is None
        or vs.test != "sign"
        or vs.fixed is None
        or vs.broken is None
        or best.primary is None
        or first.primary is None
    ):
        return None
    shared = pooled.get(best.group_id, {}).keys() & pooled.get(first.group_id, {}).keys()
    gain = best.primary.mean - first.primary.mean
    return paired_gain_interval(gain, vs.fixed, vs.broken, len(shared))


def _select_group(
    selector: str | None, rows: list[LeaderboardRow], members_of: dict[str, list[RunRecord]]
) -> str | None:
    if not selector:
        return None
    if selector.startswith("tag:"):
        tag = selector.removeprefix("tag:")
        for row in rows:
            if any(tag in m.tags for m in members_of[row.group_id]):
                return row.group_id
        return None
    for row in rows:
        if selector in (row.group_id, row.config_hash) or row.group_id.startswith(selector):
            return row.group_id
    return None


def _higher_is_better(config: ProjectConfig, spec: TaskSpec, primary: str | None = None) -> bool:
    metric, key = parse_metric_key(primary or spec.primary)
    if spec.kind == "system_bench" and percentile_of(f"{metric}/{key}"):
        return False
    return config.metrics[metric].higher_is_better


# caches ------------------------------------------------------------------------------
STATS_CACHE_SIZE = 8192
"""Bootstrap results kept per kind (row intervals, paired p-values), least recently used out."""
BOARD_CACHE_SIZE = 128
"""Leaderboards kept by ``cached_leaderboard``, least recently used out."""

_K = TypeVar("_K", bound=Hashable)
_V = TypeVar("_V")


class _Lru(Generic[_K, _V]):
    """A thread-safe least-recently-used map of at most ``size`` entries."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._data: OrderedDict[_K, _V] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: _K, compute: Callable[[], _V]) -> _V:
        """Return the value of ``key``, computing and storing it on a miss."""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
        value = compute()  # outside the lock: two threads may both compute a miss
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)
        return value

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_INTERVALS: _Lru[bytes, tuple[float, float]] = _Lru(STATS_CACHE_SIZE)
_PAIRED_P: _Lru[bytes, float] = _Lru(STATS_CACHE_SIZE)
_BOARDS: _Lru[tuple[Hashable, ...], Leaderboard] = _Lru(BOARD_CACHE_SIZE)


def _digest(values: list[float]) -> bytes:
    """128-bit digest of ``values`` in order (the exact bits of each float)."""
    return xxhash.xxh3_128_digest(array("d", values).tobytes())


def clear_caches() -> None:
    """
    Empty the bootstrap and leaderboard caches of this process.

    Never needed for correct results (every key covers its inputs); tests and
    benchmarks use it to measure cold builds.

    Examples
    --------
    >>> clear_caches()
    """
    _INTERVALS.clear()
    _PAIRED_P.clear()
    _BOARDS.clear()


def cached_leaderboard(
    ctx: Context,
    project: str,
    task: str,
    config: ProjectConfig,
    build: Callable[[], Leaderboard],
    *,
    versions: Mapping[str, str] | None = None,
    variant: Hashable = (),
) -> Leaderboard:
    """
    Return ``build()``, memoized until the index changes.

    The key includes the index file's path and device/inode identity (so a
    replaced database cannot reuse an old generation), ``index.index_generation(ctx)``
    (read before ``build`` runs, so a write during the build only wastes the entry), the
    project, task, a digest of ``config``, ``versions`` and ``variant``.
    ``build`` must read only index data, files written before their index write
    (per-example score files are written before ``Context.add_score``), and
    these arguments. At most ``BOARD_CACHE_SIZE`` boards are kept. Each call
    returns a deep copy, so callers may change it.

    Parameters
    ----------
    ctx : Context
        Open context whose index ``build`` reads.
    project : str
        Project name.
    task : str
        Task name.
    config : ProjectConfig
        The project config ``build`` uses.
    build : callable
        Builds the board on a miss, for example a closure over
        ``build_leaderboard``.
    versions : mapping of str to str, optional
        Metric version overrides ``build`` uses.
    variant : hashable
        Anything else that changes the board: ``examples=False``, a run filter.

    Returns
    -------
    Leaderboard
        A copy of the cached or new board.

    Examples
    --------
    >>> board = cached_leaderboard(  # doctest: +SKIP
    ...     ctx, "toy", "t", config, lambda: build_leaderboard("toy", "t", config, runs, scores)
    ... )
    """
    identity = ctx.index.path.stat()
    key = (
        str(ctx.index.path),
        identity.st_dev,
        identity.st_ino,
        index_generation(ctx),
        project,
        task,
        xxhash.xxh3_128_digest(config.model_dump_json().encode()),
        tuple(sorted((versions or {}).items())),
        variant,
    )
    return _BOARDS.get(key, build).model_copy(deep=True)


# test-set noise --------------------------------------------------------------------
def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def pick_field(rows: Iterable[dict[str, Any]], key: str = "value") -> tuple[str, bool] | None:
    """
    Choose the per-example field used for test-set noise and paired tests.

    Parameters
    ----------
    rows : iterable of dict
        Per-example score dicts (one per example and run).
    key : str
        The primary metric's key, preferred among numeric fields.

    Returns
    -------
    tuple of (str, bool) or None
        Field name and whether it is binary. Order: ``correct`` or ``solved``
        if binary (bools, or 0/1); any all-bool field (sorted by name);
        ``key`` if numeric; any all-numeric field. ``None`` values are ignored.

    Examples
    --------
    >>> pick_field([{"correct": True, "loss": 0.2}])
    ('correct', True)
    >>> pick_field([{"f1": 0.5}], key="f1")
    ('f1', False)
    """
    values: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        for k, v in row.items():
            if v is not None:
                values[k].append(v)

    def binary(k: str) -> bool:
        vs = values[k]
        if all(isinstance(v, bool) for v in vs):
            return True
        return k in BINARY_FIELDS and all(isinstance(v, int) and v in (0, 1) for v in vs)

    for k in BINARY_FIELDS:
        if k in values and binary(k):
            return k, True
    for k in sorted(values):
        if all(isinstance(v, bool) for v in values[k]):
            return k, True
    if key in values and all(_is_number(v) for v in values[key]):
        return key, False
    for k in sorted(values):
        if all(_is_number(v) for v in values[k]):
            return k, False
    return None


def _mean(values: list[float]) -> float:
    """
    Average finite values without overflowing the intermediate sum.

    Parameters
    ----------
    values : list of float
        Nonempty finite values.

    Returns
    -------
    float
        Their mean. Normal values use fsum; overflowing sums use the standard
        library's exact rational summation before conversion back to float.
    """
    try:
        return math.fsum(values) / len(values)
    except OverflowError:
        return statistics.mean(values)


def _pool_runs(run_ids: list[str], per_example: PerExample, field: str) -> dict[str, float]:
    seen: dict[str, list[float]] = defaultdict(list)
    for rid in run_ids:
        for ex, fields in per_example.get(rid, {}).items():
            v = fields.get(field)
            if isinstance(v, bool | int | float) and math.isfinite(v):
                seen[ex].append(float(v))
    return {ex: _mean(vs) for ex, vs in seen.items()}


def _pool(seeds: list[list[str]], per_example: PerExample, field: str) -> dict[str, float]:
    """Mean per example over seeds, after averaging the runs of each seed."""
    seen: dict[str, list[float]] = defaultdict(list)
    for run_ids in seeds:
        for ex, v in _pool_runs(run_ids, per_example, field).items():
            seen[ex].append(v)
    return {ex: _mean(vs) for ex, vs in seen.items()}


def _test_interval(pooled: dict[str, float], binary: bool) -> NoiseInterval | None:
    if not pooled:
        return None
    values = [pooled[k] for k in sorted(pooled)]
    if binary:
        successes = math.floor(math.fsum(values) + 0.5)
        lo, hi = stats.wilson_interval(successes, len(values))
        return NoiseInterval(lo=lo, hi=hi, method="wilson", n=len(values))
    lo, hi = _INTERVALS.get(_digest(values), lambda: stats.bootstrap_mean_interval(values))
    return NoiseInterval(lo=lo, hi=hi, method="bootstrap", n=len(values))


def _versus(
    row: LeaderboardRow,
    best: LeaderboardRow,
    pooled: dict[str, dict[str, float]],
    binary: bool | None,
    primary: str,
) -> VersusBest:
    assert row.primary is not None and best.primary is not None
    vs = _versus_test(row, best, pooled, binary, primary)
    base = best.primary.mean
    vs.delta_rel = vs.delta / abs(base) if base else None
    return vs


def _versus_test(
    row: LeaderboardRow,
    best: LeaderboardRow,
    pooled: dict[str, dict[str, float]],
    binary: bool | None,
    primary: str,
) -> VersusBest:
    assert row.primary is not None and best.primary is not None
    delta = row.primary.mean - best.primary.mean
    mine, theirs = pooled.get(row.group_id, {}), pooled.get(best.group_id, {})
    common = sorted(mine.keys() & theirs.keys())
    if common and binary:
        row_pass = [mine[k] > 0.5 for k in common]
        best_pass = [theirs[k] > 0.5 for k in common]
        fixed = sum(1 for r, b in zip(row_pass, best_pass, strict=True) if b and not r)
        broken = sum(1 for r, b in zip(row_pass, best_pass, strict=True) if r and not b)
        return VersusBest(
            delta=delta,
            p=stats.sign_test(fixed, broken),
            fixed=fixed,
            broken=broken,
            test="sign",
            examples_needed=stats.examples_needed(fixed, broken, len(common)),
        )
    if common and binary is False:
        a, b = [mine[k] for k in common], [theirs[k] for k in common]
        p = _PAIRED_P.get(_digest(a + b), lambda: stats.paired_bootstrap_p(a, b))
        return VersusBest(
            delta=delta, p=p, fixed=None, broken=None, test="paired_bootstrap", examples_needed=None
        )
    p = stats.welch_p(row.seed_values.get(primary, []), best.seed_values.get(primary, []))
    return VersusBest(
        delta=delta,
        p=p,
        fixed=None,
        broken=None,
        test="welch" if p is not None else None,
        examples_needed=None,
    )


# rows --------------------------------------------------------------------------------
def _sum_usage(members: list[RunRecord]) -> UsageTotals | None:
    used = [m.usage for m in members if m.usage is not None]
    if not used:
        return None
    return UsageTotals(
        tokens_in=sum(u.tokens_in for u in used),
        tokens_out=sum(u.tokens_out for u in used),
        usd=math.fsum(u.usd for u in used),
        seconds=math.fsum(u.seconds for u in used),
        calls=sum(u.calls for u in used),
    )


def seed_buckets(members: list[RunRecord]) -> list[list[RunRecord]]:
    """
    Split a seed group's runs by seed: reruns of one seed are one sample, not several.

    Parameters
    ----------
    members : list of RunRecord
        The group's runs, oldest first.

    Returns
    -------
    list of list of RunRecord
        One list per distinct seed, in order of first appearance. Runs without a
        seed are a list of their own each.

    Examples
    --------
    >>> runs = [make_record("a", seed=1), make_record("b", seed=1)]  # doctest: +SKIP
    >>> [[r.run_id for r in b] for b in seed_buckets(runs)]  # doctest: +SKIP
    [['a', 'b']]
    """
    buckets: dict[tuple[str, int | str], list[RunRecord]] = {}
    for m in members:
        key = ("seed", m.seed) if m.seed is not None else ("run", m.run_id)
        buckets.setdefault(key, []).append(m)
    return list(buckets.values())


def _seed_values(
    buckets: list[list[RunRecord]], per_run: dict[str, dict[str, float]]
) -> dict[str, list[float]]:
    """One value per seed and score key: the mean over that seed's runs."""
    keys = sorted({k for b in buckets for m in b for k in per_run[m.run_id]})
    out: dict[str, list[float]] = {}
    for k in keys:
        out[k] = []
        for bucket in buckets:
            values = [per_run[m.run_id][k] for m in bucket if k in per_run[m.run_id]]
            if values:
                out[k].append(_mean(values))
    return out


def _summarize(values: list[float], unit: str) -> Stats:
    """``summarize``, with the t-interval kept in [0, 1] for a unitless fraction."""
    stats = summarize(values)
    if unit == "" and all(0.0 <= v <= 1.0 for v in values):
        return clamp(stats, 0.0, 1.0)
    return stats


def _make_row(
    members: list[RunRecord],
    per_run: dict[str, dict[str, float]],
    config: ProjectConfig,
    spec: TaskSpec,
    primary: str,
) -> LeaderboardRow:
    members.sort(key=lambda r: (r.created_at, r.run_id))
    latest = members[-1]
    chash, commit = latest.config_hash, latest.git.commit
    group_id = group_id_for(latest)
    buckets = seed_buckets(members)
    n_seeds = len(buckets)
    seed_values = _seed_values(buckets, per_run)
    summary = {
        k: _summarize(v, metric_unit(k, config.metrics[k.split("/", 1)[0]].unit))
        for k, v in seed_values.items()
    }
    prim = seed_values.get(primary, [])
    param = spec.version_param if spec.kind == "agent_iteration" else None
    label = seed_group_label(members, group_id, param)
    return LeaderboardRow(
        group_id=group_id,
        run_ids=[m.run_id for m in members],
        latest_run_id=latest.run_id,
        hypothesis=latest.hypothesis,
        commit=commit,
        config_hash=chash,
        n=n_seeds,
        scores=summary,
        primary=summary.get(primary),
        single_seed=n_seeds == 1,
        label=label,
        seed_values=seed_values,
        identical_seeds=len(prim) > 1 and all(v == prim[0] for v in prim),
        test_interval=None,
        vs_best=None,
        created_by=sorted({m.created_by for m in members}),
        usage=_sum_usage(members),
        cost=add_costs(m.cost for m in members),
        cost_complete=all(
            m.cost is not None and m.cost.gpu_pricing_complete is True for m in members
        ),
    )


def _selected_primary(
    config: ProjectConfig,
    task: str,
    primary: str | None,
    scores: dict[str, list[ScoreRecord]],
    versions: dict[str, str],
) -> str:
    """Validate a task metric and a configured or observed selected-version key."""
    spec = config.tasks[task]
    ref = spec.primary if primary is None else primary
    name, key = parse_metric_key(ref)
    if name not in spec.metrics or not key or "/" in key or "@" in ref:
        raise ConfigError(f"unknown leaderboard primary {ref!r} for task {task!r}")
    normalized = f"{name}/{key}"
    configured = "/".join(parse_metric_key(spec.primary))
    if primary is not None and normalized != configured:
        keys = {
            s.key
            for rows in scores.values()
            for s in rows
            if s.metric == name and s.version == versions[name]
        }
        if key not in keys and not (key == "value" and not keys):
            raise ConfigError(
                f"unknown leaderboard key {ref!r} at {name}@{versions[name]}; "
                f"recorded keys: {', '.join(sorted(keys)) or 'none'}"
            )
    return normalized


def _evidenced_score(
    records: list[ScoreRecord],
    metric: str,
    key: str,
    version: str,
) -> ScoreRecord | None:
    """Require the latest exact or whole-metric result to be a sourced success."""
    matching = [
        s for s in records if s.metric == metric and s.version == version and s.key in {key, "*"}
    ]
    if not matching:
        return None
    latest = max(matching, key=lambda s: s.created_at)
    if (
        latest.key != key
        or latest.error is not None
        or latest.value is None
        or not math.isfinite(latest.value)
        or not latest.source_hash
    ):
        return None
    return latest


def _population(
    members: list[RunRecord],
    examples: PerExample,
    scores: dict[str, list[ScoreRecord]],
    spec: TaskSpec,
    primary: str,
    version: str,
    picked: tuple[str, bool] | None,
    hashes: dict[str, str],
) -> EvaluationPopulation | None:
    """Account only for complete, homogeneous binary evaluation populations."""
    if picked is None or not picked[1]:
        return None
    metric, key = parse_metric_key(primary)
    field = picked[0]
    cohort: set[str] | None = None
    dataset: tuple[str, str, str | None, str, str | None] | None = None
    source: str | None = None
    attempts = solved = 0
    for run in members:
        values = examples.get(run.run_id)
        if not values:
            return None
        ids = set(values)
        if cohort is not None and ids != cohort:
            return None
        cohort = ids
        refs = [r for r in run.datasets if r.name == spec.dataset and r.split == spec.split]
        if len(refs) != 1 or not refs[0].hash:
            return None
        ref = refs[0]
        assert ref.hash is not None
        identity = (ref.name, ref.version, ref.split, ref.hash, ref.hash_mode)
        if dataset is not None and identity != dataset:
            return None
        dataset = identity
        latest = _evidenced_score(scores.get(run.run_id, []), metric, key, version)
        if latest is None:
            return None
        if (
            latest.per_example_hash is None
            or latest.per_example_hash != hashes.get(run.run_id)
            or latest.evaluation_examples != len(values)
            or latest.evaluation_ids_hash
            != "sha256:" + hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
        ):
            return None
        if not latest.source_hash or source is not None and latest.source_hash != source:
            return None
        source = latest.source_hash
        binary = [row.get(field) for row in values.values()]
        if any(type(v) not in (bool, int) or v not in (0, 1) for v in binary):
            return None
        successes = sum(v for v in binary if isinstance(v, int))
        assert latest.value is not None
        if not math.isclose(float(latest.value), successes / len(binary), abs_tol=1e-12):
            return None
        solved += successes
        attempts += len(binary)
    if cohort is None or dataset is None or source is None:
        return None
    return EvaluationPopulation(
        metric=primary,
        version=version,
        source_hash=source,
        field=field,
        dataset_fingerprint="sha256:" + hashlib.sha256(json.dumps(dataset).encode()).hexdigest(),
        example_ids_hash="sha256:"
        + hashlib.sha256(json.dumps(sorted(cohort)).encode()).hexdigest(),
        examples=len(cohort),
        attempts=attempts,
        solved=solved,
    )


def _repeat_observations(
    members: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    spec: TaskSpec,
    primary: str,
    version: str,
    unit: str | None,
    higher: bool,
) -> list[RepeatObservation]:
    """Expose only complete comparable recorded latency repeats, without sampling."""
    metric, key = parse_metric_key(primary)
    if spec.kind != "system_bench" or key != "p95" or unit not in {"ms", "s"} or higher:
        return []
    if len(members) > 128:
        return []
    result: list[RepeatObservation] = []
    context: tuple[str, str] | None = None
    for run in members:
        score = _evidenced_score(scores.get(run.run_id, []), metric, key, version)
        refs = [r for r in run.datasets if r.name == spec.dataset and r.split == spec.split]
        if score is None or len(refs) != 1 or not refs[0].hash:
            return []
        assert score.source_hash is not None and score.value is not None
        ref = refs[0]
        fingerprint = (
            "sha256:"
            + hashlib.sha256(
                json.dumps((ref.name, ref.version, ref.split, ref.hash, ref.hash_mode)).encode()
            ).hexdigest()
        )
        identity = (score.source_hash, fingerprint)
        if context is not None and context != identity:
            return []
        context = identity
        result.append(
            RepeatObservation(
                run_id=run.run_id,
                value=score.value,
                metric=metric,
                version=version,
                key=key,
                source_hash=score.source_hash,
                dataset_fingerprint=fingerprint,
            )
        )
    return result


def build_leaderboard(
    project: str,
    task: str,
    config: ProjectConfig,
    runs: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    versions: dict[str, str] | None = None,
    *,
    per_example: PerExample | None = None,
    per_example_hashes: dict[str, str] | None = None,
    primary: str | None = None,
) -> Leaderboard:
    """
    Build a leaderboard for one task.

    Only finished, unarchived runs of the task count. Scores must match the
    selected metric version and have no error; the newest such score wins.

    Parameters
    ----------
    project : str
        Project name.
    task : str
        Task name.
    config : ProjectConfig
        Current project config (metric versions, direction, task kind).
    runs : list of RunRecord
        Candidate runs.
    scores : dict of str to list of ScoreRecord
        Scores per run id.
    versions : dict of str to str, optional
        Metric version overrides; default is each metric's current version.
    per_example : dict, optional
        run_id -> example_id -> per-example fields of the primary metric at
        the selected version. Enables test-set intervals and paired tests;
        without it rows are compared with a Welch t-test over seed values.
    per_example_hashes : dict of str to str, optional
        SHA256 of exact parsed per-example bytes per run. Required only for
        cost-population attribution; must match the selected score record.
    primary : str, optional
        Select a configured task metric or observed metric/key for ranking.
        Direction, units and evidence follow this metric; the default is the
        task's configured primary. Versions remain independently selectable.

    Returns
    -------
    Leaderboard
        Ranked seed groups, runs that need attention, headline and stat strip.
    """
    spec = config.tasks[task]
    chosen = {m: (versions or {}).get(m, config.metrics[m].version) for m in spec.metrics}
    requested_primary = primary
    primary = _selected_primary(config, task, primary, scores, chosen)
    primary_metric, primary_key = parse_metric_key(primary)
    higher = (
        config.metrics[primary_metric].higher_is_better
        if requested_primary is not None and primary != "/".join(parse_metric_key(spec.primary))
        else _higher_is_better(config, spec)
    )
    eligible = [
        r for r in runs if r.task == task and r.status == RunStatus.FINISHED and not r.archived
    ]

    source_hashes: dict[str, set[str]] = defaultdict(set)
    per_run: dict[str, dict[str, float]] = {}
    needs_reeval: list[str] = []
    unscored: list[str] = []
    for r in eligible:
        run_scores = sorted(scores.get(r.run_id, []), key=lambda s: s.created_at)
        current: dict[tuple[str, str], float] = {}
        for s in run_scores:
            if s.source_hash and s.metric in chosen and s.version == chosen[s.metric]:
                source_hashes[f"{s.metric}@{s.version}"].add(s.source_hash)
            if (
                s.metric in chosen
                and s.version == chosen[s.metric]
                and s.error is None
                and s.value is not None
                and math.isfinite(s.value)
            ):
                current[(s.metric, s.key)] = s.value
        stale = any(s.metric in chosen and s.version != chosen[s.metric] for s in run_scores)
        missing_metric = any(all(m != k[0] for k in current) for m in chosen)
        if stale and missing_metric:
            needs_reeval.append(r.run_id)
        if current:
            per_run[r.run_id] = {f"{m}/{k}": v for (m, k), v in current.items()}
        elif not stale:
            unscored.append(r.run_id)

    groups: dict[tuple[str, str | None, str | None], list[RunRecord]] = defaultdict(list)
    eligible_groups: dict[tuple[str, str | None, str | None], set[str]] = defaultdict(set)
    for r in runs:
        if r.task == task and not r.archived:
            eligible_groups[(r.config_hash, r.git.commit, diff_key(r.git))].add(r.run_id)
    for r in eligible:
        if r.run_id in per_run:
            groups[(r.config_hash, r.git.commit, diff_key(r.git))].append(r)

    examples = {rid: ex for rid, ex in (per_example or {}).items() if rid in per_run}
    picked = pick_field((f for ex in examples.values() for f in ex.values()), primary_key)
    if requested_primary is not None and (
        primary_key != "value"
        or any(primary_key in row for ex in examples.values() for row in ex.values())
    ):
        # An explicitly selected output key must not borrow another binary or
        # numeric field from the metric's per-example payload.
        fields = [row.get(primary_key) for ex in examples.values() for row in ex.values()]
        if fields and all(isinstance(v, (bool, int, float)) and math.isfinite(v) for v in fields):
            picked = (primary_key, all(type(v) in (bool, int) and v in (0, 1) for v in fields))
        else:
            picked = None
    rows: list[LeaderboardRow] = []
    pooled: dict[str, dict[str, float]] = {}
    for identity, members in groups.items():
        row = _make_row(members, per_run, config, spec, primary)
        row.repeat_observations = _repeat_observations(
            members,
            scores,
            spec,
            primary,
            chosen[primary_metric],
            config.metrics[primary_metric].unit,
            higher,
        )
        row.evaluation_population = _population(
            members,
            examples,
            scores,
            spec,
            primary,
            chosen[primary_metric],
            picked,
            per_example_hashes or {},
        )
        if set(row.run_ids) != eligible_groups[identity]:
            # Existing rankings include scored members only. Missing scored
            # attempts make cost/population and repeat claims incomplete.
            row.cost_complete = False
            row.evaluation_population = None
            row.repeat_observations = []
        if picked is not None:
            seeds = [[m.run_id for m in b] for b in seed_buckets(members)]
            pooled[row.group_id] = _pool(seeds, examples, picked[0])
            row.test_interval = _test_interval(pooled[row.group_id], picked[1])
        rows.append(row)

    def sort_key(row: LeaderboardRow) -> tuple[int, float]:
        if row.primary is None:
            return (1, 0.0)
        return (0, -row.primary.mean if higher else row.primary.mean)

    rows.sort(key=sort_key)
    if rows and rows[0].primary is not None:
        best = rows[0]
        for row in rows[1:]:
            if row.primary is not None and best.primary is not None:
                binary = picked[1] if picked is not None else None
                row.vs_best = _versus(row, best, pooled, binary, primary)
                p = row.vs_best.p
                row.within_noise_of_best = None if p is None else p >= NOISE_ALPHA

    by_id = {r.run_id: r for r in eligible}
    members_of = {row.group_id: [by_id[i] for i in row.run_ids] for row in rows}
    labels = distinct_labels({row.group_id: row.label for row in rows}, members_of)
    for row in rows:
        row.label = labels[row.group_id]
    reference = None
    gain_interval = None
    if spec.kind == "system_bench":
        reference = _select_group(spec.baseline, rows, members_of)
    elif spec.kind == "agent_iteration":
        reference = _first_version(rows, members_of, spec.version_param)
        first = next((row for row in rows if row.group_id == reference), None)
        if first is not None and first is not rows[0]:
            gain_interval = _paired_gain(rows[0], first, pooled)

    unit = metric_unit(primary, config.metrics[primary_metric].unit)
    board = Leaderboard(
        project=project,
        task=task,
        primary=primary,
        higher_is_better=higher,
        metric_versions=chosen,
        metric_drift=sorted(ref for ref, hashes in source_hashes.items() if len(hashes) > 1),
        rows=rows,
        needs_reeval=needs_reeval,
        unscored=unscored,
        headline="",
        kind=spec.kind,
        stat_strip=[],
        unit=unit,
        value_format=value_format(unit, (r.primary.mean for r in rows if r.primary), higher),
    )
    board.headline = task_headline(board, reference=reference, gain_interval=gain_interval)
    board.stat_strip = task_stat_strip(board, reference=reference)
    return board
