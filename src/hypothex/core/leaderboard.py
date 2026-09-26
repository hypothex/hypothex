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
    project : str
        Project name.
    task : str
        Task name.
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
        Ranked seed groups plus runs that need attention.
    """
    spec = config.tasks[task]
    chosen = {m: (versions or {}).get(m, config.metrics[m].version) for m in spec.metrics}
    primary_metric, primary_key = parse_metric_key(spec.primary)
    higher = config.metrics[primary_metric].higher_is_better
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

    rows: list[LeaderboardRow] = []
    for (chash, commit), members in groups.items():
        members.sort(key=lambda r: (r.created_at, r.run_id))
        keys = sorted({k for m in members for k in per_run[m.run_id]})
        stats = {
            k: summarize([per_run[m.run_id][k] for m in members if k in per_run[m.run_id]])
            for k in keys
        }
        latest = members[-1]
        rows.append(
            LeaderboardRow(
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
            )
        )

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
