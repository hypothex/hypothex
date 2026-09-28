"""Rank seed groups of a task by its primary metric, with seed and test-set noise."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.core import stats
from hypothex.core.config import ProjectConfig, TaskKind, TaskSpec, parse_metric_key
from hypothex.core.headlines import (
    ValueFormat,
    metric_unit,
    paired_gain_interval,
    percentile_of,
    task_headline,
    task_stat_strip,
    value_format,
)
from hypothex.core.records import RunRecord, RunStatus, ScoreRecord, UsageTotals
from hypothex.core.seeds import Stats, intervals_overlap, summarize

PerExample = dict[str, dict[str, dict[str, Any]]]
"""run_id -> example_id -> per-example fields of the primary metric."""

BINARY_FIELDS = ("correct", "solved")
LABEL_MAX = 32
_CLAUSE = re.compile(
    r"[,;:()]|\s[-–—]\s|\.(?:\s|$)|\s(?:because|should|so that|since|to see if|in order to)\s",
    re.IGNORECASE,
)


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
    label: str
    seed_values: dict[str, list[float]]
    identical_seeds: bool
    test_interval: NoiseInterval | None
    vs_best: VersusBest | None
    created_by: list[str]
    usage: UsageTotals | None


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
    headline: str
    kind: TaskKind
    stat_strip: list[dict[str, Any]]
    unit: str = ""
    """Display unit of the primary metric (``headlines.metric_unit``): ``ms``, ``$``, ..."""
    value_format: ValueFormat = "fraction"
    """How to show primary values and vs-best deltas (``headlines.value_format``)."""


# labels and ordering -------------------------------------------------------------
def group_label(hypothesis: str, tags: Iterable[str], group_id: str) -> str:
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

    Returns
    -------
    str
        The hypothesis's first clause (cut at ``, ; : ( )``, a dash, a full stop,
        or words like "because"/"should"), at most 32 characters; else the first
        tag in sorted order; else ``"group <id>"``.

    Examples
    --------
    >>> group_label("RBF-kernel SVM should beat RF", [], "g")
    'RBF-kernel SVM'
    >>> group_label("", ["svm"], "g")
    'svm'
    """
    parts = [p.strip() for p in _CLAUSE.split(hypothesis.strip())]
    clause = next((p for p in parts if p), "")
    if clause:
        if len(clause) <= LABEL_MAX:
            return clause
        cut = clause[:LABEL_MAX].rsplit(" ", 1)[0].rstrip() or clause[:LABEL_MAX]
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
        ``nogit`` replaces the commit when the run has no git info.

    Examples
    --------
    >>> group_id_for(make_record(config_hash="sha256:0123456789"))  # doctest: +SKIP
    '01234567@nogit'
    """
    return f"{run.config_hash.removeprefix('sha256:')[:8]}@{(run.git.commit or 'nogit')[:7]}"


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


def _higher_is_better(config: ProjectConfig, spec: TaskSpec) -> bool:
    metric, key = parse_metric_key(spec.primary)
    if spec.kind == "system_bench" and percentile_of(f"{metric}/{key}"):
        return False
    return config.metrics[metric].higher_is_better


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


def _pool(run_ids: list[str], per_example: PerExample, field: str) -> dict[str, float]:
    seen: dict[str, list[float]] = defaultdict(list)
    for rid in run_ids:
        for ex, fields in per_example.get(rid, {}).items():
            v = fields.get(field)
            if isinstance(v, bool | int | float) and math.isfinite(v):
                seen[ex].append(float(v))
    return {ex: math.fsum(vs) / len(vs) for ex, vs in seen.items()}


def _test_interval(pooled: dict[str, float], binary: bool) -> NoiseInterval | None:
    if not pooled:
        return None
    values = [pooled[k] for k in sorted(pooled)]
    if binary:
        successes = math.floor(math.fsum(values) + 0.5)
        lo, hi = stats.wilson_interval(successes, len(values))
        return NoiseInterval(lo=lo, hi=hi, method="wilson", n=len(values))
    lo, hi = stats.bootstrap_mean_interval(values)
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
        p = stats.paired_bootstrap_p([mine[k] for k in common], [theirs[k] for k in common])
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


def _make_row(
    members: list[RunRecord],
    per_run: dict[str, dict[str, float]],
    spec: TaskSpec,
    primary: str,
) -> LeaderboardRow:
    members.sort(key=lambda r: (r.created_at, r.run_id))
    latest = members[-1]
    chash, commit = latest.config_hash, latest.git.commit
    group_id = group_id_for(latest)
    keys = sorted({k for m in members for k in per_run[m.run_id]})
    seed_values = {
        k: [per_run[m.run_id][k] for m in members if k in per_run[m.run_id]] for k in keys
    }
    summary = {k: summarize(v) for k, v in seed_values.items()}
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
        n=len(members),
        scores=summary,
        primary=summary.get(primary),
        single_seed=len(members) == 1,
        label=label,
        seed_values=seed_values,
        identical_seeds=len(prim) > 1 and all(v == prim[0] for v in prim),
        test_interval=None,
        vs_best=None,
        created_by=sorted({m.created_by for m in members}),
        usage=_sum_usage(members),
    )


def build_leaderboard(
    project: str,
    task: str,
    config: ProjectConfig,
    runs: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    versions: dict[str, str] | None = None,
    *,
    per_example: PerExample | None = None,
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

    Returns
    -------
    Leaderboard
        Ranked seed groups, runs that need attention, headline and stat strip.
    """
    spec = config.tasks[task]
    chosen = {m: (versions or {}).get(m, config.metrics[m].version) for m in spec.metrics}
    primary_metric, primary_key = parse_metric_key(spec.primary)
    primary = f"{primary_metric}/{primary_key}"
    higher = _higher_is_better(config, spec)
    eligible = [
        r for r in runs if r.task == task and r.status == RunStatus.FINISHED and not r.archived
    ]

    per_run: dict[str, dict[str, float]] = {}
    needs_reeval: list[str] = []
    unscored: list[str] = []
    for r in eligible:
        run_scores = sorted(scores.get(r.run_id, []), key=lambda s: s.created_at)
        current: dict[tuple[str, str], float] = {}
        for s in run_scores:
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

    groups: dict[tuple[str, str | None], list[RunRecord]] = defaultdict(list)
    for r in eligible:
        if r.run_id in per_run:
            groups[(r.config_hash, r.git.commit)].append(r)

    examples = {rid: ex for rid, ex in (per_example or {}).items() if rid in per_run}
    picked = pick_field((f for ex in examples.values() for f in ex.values()), primary_key)
    rows: list[LeaderboardRow] = []
    pooled: dict[str, dict[str, float]] = {}
    for members in groups.values():
        row = _make_row(members, per_run, spec, primary)
        if picked is not None:
            pooled[row.group_id] = _pool(row.run_ids, examples, picked[0])
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
                row.within_noise_of_best = intervals_overlap(row.primary, best.primary)
                binary = picked[1] if picked is not None else None
                row.vs_best = _versus(row, best, pooled, binary, primary)

    by_id = {r.run_id: r for r in eligible}
    members_of = {row.group_id: [by_id[i] for i in row.run_ids] for row in rows}
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
