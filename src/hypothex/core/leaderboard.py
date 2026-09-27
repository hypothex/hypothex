"""Rank seed groups of a task by its primary metric, with seed and test-set noise."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.core.config import ProjectConfig, TaskKind, TaskSpec, parse_metric_key
from hypothex.core.headlines import percentile_of
from hypothex.core.records import RunRecord, RunStatus, ScoreRecord, UsageTotals
from hypothex.core.seeds import Stats, intervals_overlap, summarize

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


def _higher_is_better(config: ProjectConfig, spec: TaskSpec) -> bool:
    metric, key = parse_metric_key(spec.primary)
    if spec.kind == "system_bench" and percentile_of(f"{metric}/{key}"):
        return False
    return config.metrics[metric].higher_is_better


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
    version = _version_of(members, spec.version_param)
    if spec.kind == "agent_iteration" and version:
        label = version
    else:
        label = group_label(latest.hypothesis, (t for m in members for t in m.tags), group_id)
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

    Returns
    -------
    Leaderboard
        Ranked seed groups and runs that need attention.
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

    rows = [_make_row(members, per_run, spec, primary) for members in groups.values()]

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
        primary=primary,
        higher_is_better=higher,
        metric_versions=chosen,
        rows=rows,
        needs_reeval=needs_reeval,
        unscored=unscored,
        headline="",
        kind=spec.kind,
        stat_strip=[],
    )
