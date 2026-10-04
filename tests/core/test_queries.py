import math
import random
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.datasets import FingerprintCache
from hypothex.core.errors import ConfigError, RemoteProjectError, RunError
from hypothex.core.evaluation import evaluate_run
from hypothex.core.index import store_fingerprint
from hypothex.core.records import DatasetRef, MetricPoint, RunRecord, RunStatus
from hypothex.core.store import ProjectEntry
from hypothex.core.sweeps import SweepSpec, save_sweep
from hypothex.core.sweeps import list_sweeps as list_project_sweeps
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
    ctx.create_run(
        make_record(
            "r1",
            datasets=[
                DatasetRef(
                    name="toyset", version="v1", path=str(data), hash=fp.hash, hash_mode=fp.mode
                )
            ],
        )
    )
    assert [d.status for d in q.check_datasets(ctx)] == ["ok"]
    data.write_text(data.read_text() + '{"id": "ex-9", "reference": 1}\n')
    assert [d.status for d in q.check_datasets(ctx)] == ["changed"]


def test_leaderboard_uses_per_example_scores(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "b", predictions=ALL_RIGHT, config_hash="sha256:bbbb")
    evaluate_run(ctx, "a")
    evaluate_run(ctx, "b")
    board = q.get_leaderboard(ctx, "toy-acc")
    best, other = board.rows
    assert best.run_ids == ["b"] and board.kind == "generic"
    # Reference: statsmodels proportion_confint(4, 4, method="wilson")
    assert best.test_interval is not None and best.test_interval.n == 4
    assert best.test_interval.lo == pytest.approx(0.5101091635454027)
    assert best.test_interval.hi == pytest.approx(1.0)
    vs = other.vs_best
    assert vs is not None and (vs.test, vs.fixed, vs.broken) == ("sign", 1, 0)
    assert vs.p == pytest.approx(1.0)  # scipy.stats.binomtest(0, 1).pvalue
    assert board.headline == f"group {best.group_id} +0.250 over group {other.group_id}, p = 1.00"
    plain = q.get_leaderboard(ctx, "toy-acc", examples=False)
    assert plain.rows[0].test_interval is None
    assert plain.rows[1].vs_best is not None and plain.rows[1].vs_best.test is None


def test_leaderboard_examples_follow_version_override(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    evaluate_run(ctx, "a")
    write_toy_project(toy_repo, accuracy_version="v2")
    evaluate_run(ctx, "a")
    (ctx.run_dir(ctx.find_record("a")) / "predictions" / "scores.accuracy@v2.jsonl").unlink()
    assert q.get_leaderboard(ctx, "toy-acc").rows[0].test_interval is None
    old = q.get_leaderboard(ctx, "toy-acc", versions={"accuracy": "v1"})
    assert old.rows[0].test_interval is not None and old.rows[0].test_interval.n == 4


def _copy_from_host(ctx: Context, project: str = "toy") -> None:
    """Turn a hub registration into a host's copy whose reported repo path exists here."""
    entry = ctx.store.load_project(project).model_copy(update={"remote_host": "gpu1"})
    ctx.store.save_project(entry)
    ctx.index.upsert_project(entry)  # as the hub's mirror does (_ensure_project)


def test_refreshing_a_host_copy_never_registers_its_repo_path(ctx: Context, toy_repo: Path) -> None:
    # listing projects re-reads hypothex.yaml; for a host's copy that would register the
    # host-reported path here and drop remote_host, so evaluation would run its metric code
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    _copy_from_host(ctx)
    assert [e.remote_host for e in q.list_projects(ctx)] == ["gpu1"]
    assert q.refresh_project(ctx, "toy").remote_host == "gpu1"
    entry, task = q.resolve_task(ctx, "toy-acc")
    assert (entry.remote_host, task) == ("gpu1", "toy-acc")
    assert ctx.store.load_project("toy").remote_host == "gpu1"
    assert ctx.index.get_project("toy").remote_host == "gpu1"  # type: ignore[union-attr]
    with pytest.raises(RemoteProjectError):
        evaluate_run(ctx, "r1")


def test_a_host_copy_never_reads_dataset_files_from_its_repo_path(
    ctx: Context, toy_repo: Path
) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    _copy_from_host(ctx)
    page = q.get_predictions(ctx, "r1")
    assert page.total == 4 and [r.reference for r in page.rows] == [None] * 4
    with pytest.raises(RemoteProjectError):
        q.dataset_overlap(ctx, "toy", "toyset")


def test_reads_leave_an_unchanged_project_alone(ctx: Context, toy_repo: Path) -> None:
    # PERF-F5: a read-only refresh must not rewrite project.json, bump the index
    # generation, or change the project folder's mtime (the store fingerprint)
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    project_file = ctx.layout.store / "toy" / "project.json"
    before = project_file.read_bytes()
    stamp = (project_file.stat().st_mtime_ns, project_file.parent.stat().st_mtime_ns)
    generation = ctx.index.generation()
    fingerprint = store_fingerprint(ctx.store)[0]
    q.list_projects(ctx)
    q.list_tasks(ctx)
    q.resolve_task(ctx, "toy/toy-acc")
    q.get_leaderboard(ctx, "toy-acc")
    assert project_file.read_bytes() == before
    assert (project_file.stat().st_mtime_ns, project_file.parent.stat().st_mtime_ns) == stamp
    assert ctx.index.generation() == generation
    assert store_fingerprint(ctx.store)[0] == fingerprint


def test_refresh_registers_again_when_the_config_changed(ctx: Context, toy_repo: Path) -> None:
    first = ctx.register_project(toy_repo)
    write_toy_project(toy_repo, accuracy_version="v2")
    entry = q.refresh_project(ctx, "toy")
    assert entry.config.metrics["accuracy"].version == "v2"
    assert ctx.store.load_project("toy").config == entry.config
    assert ctx.index.get_project("toy") == entry
    assert entry.registered_at >= first.registered_at


def test_show_run_finds_children_without_listing_the_project(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PERF-F8a: children come from the indexed parent column, archived ones too
    seed_finished_run(ctx, toy_repo, "r1")
    ctx.create_run(make_record("r3", parent="r1"))
    ctx.create_run(make_record("r2", parent="r1"))
    ctx.create_run(make_record("other"))
    q.archive_run(ctx, "r3")

    def no_listing(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("show_run listed the project's runs")

    monkeypatch.setattr(ctx.index, "list_runs", no_listing)
    assert q.show_run(ctx, "r1").children == ["r2", "r3"]
    assert q.show_run(ctx, "other").children == []


def test_list_tasks_counts_finished_runs_and_follows_new_scores(
    ctx: Context, toy_repo: Path
) -> None:
    # PERF-F7: n_runs is a COUNT; the ranking is reused only while the index is unchanged
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    evaluate_run(ctx, "a")
    ctx.create_run(make_record("queued", task="toy-acc", status=RunStatus.QUEUED))
    seed_finished_run(ctx, toy_repo, "hidden", predictions=ALL_RIGHT)
    q.archive_run(ctx, "hidden")
    first = {t.name: t for t in q.list_tasks(ctx)}["toy-acc"]
    assert (first.n_runs, first.best) == (1, 0.75)
    seed_finished_run(ctx, toy_repo, "b", predictions=ALL_RIGHT, config_hash="sha256:bbbb")
    evaluate_run(ctx, "b")
    second = {t.name: t for t in q.list_tasks(ctx)}["toy-acc"]
    assert (second.n_runs, second.best) == (2, 1.0)
    write_toy_project(toy_repo, accuracy_version="v2")
    bumped = {t.name: t for t in q.list_tasks(ctx)}["toy-acc"]
    assert (bumped.n_runs, bumped.best, bumped.metrics) == (2, None, {"accuracy": "v2"})


def test_list_tasks_reads_runs_once_per_task_and_not_again_when_unchanged(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    evaluate_run(ctx, "a")
    listed: list[object] = []
    real = ctx.index.list_runs

    def counting(**kwargs: Any) -> list[RunRecord]:
        listed.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(ctx.index, "list_runs", counting)
    tasks = q.list_tasks(ctx)
    assert len(listed) == len(tasks)
    listed.clear()
    assert q.list_tasks(ctx) == tasks
    assert listed == []
    assert q.get_task(ctx, "toy-acc")["summary"]["best"] == 0.75
    assert listed == []


def _reference_lttb(data: list[tuple[float, float]], threshold: int) -> list[int]:
    """Indexes the published LTTB algorithm (Steinarsson 2013) keeps."""
    every = (len(data) - 2) / (threshold - 2)
    a, kept = 0, [0]
    for i in range(threshold - 2):
        lo, hi = int(math.floor((i + 1) * every) + 1), int(math.floor((i + 2) * every) + 1)
        nxt = data[lo : min(hi, len(data))]
        avg_x, avg_y = sum(x for x, _ in nxt) / len(nxt), sum(y for _, y in nxt) / len(nxt)
        ax, ay = data[a]
        start, stop = int(math.floor(i * every) + 1), int(math.floor((i + 1) * every) + 1)
        areas = [
            abs((ax - avg_x) * (data[j][1] - ay) - (ax - data[j][0]) * (avg_y - ay))
            for j in range(start, stop)
        ]
        a = start + areas.index(max(areas))
        kept.append(a)
    return [*kept, len(data) - 1]


def test_lttb_matches_the_reference_and_keeps_peaks() -> None:
    rng = random.Random(7)
    for n, limit in [(100, 10), (997, 50), (500, 499), (31, 3)]:
        values = [rng.gauss(0, 1) for _ in range(n)]
        series = [MetricPoint(name="m", step=i * 2, value=v) for i, v in enumerate(values)]
        kept = q.lttb(series, limit)
        expected = _reference_lttb([(p.step, p.value) for p in series], limit)
        assert kept == [series[i] for i in expected]
    spike = [MetricPoint(name="m", step=i, value=100.0 if i == 57 else 0.0) for i in range(200)]
    assert any(p.value == 100.0 for p in q.lttb(spike, 20))
    assert q.lttb(spike, 2) == [spike[0], spike[-1]]
    assert q.lttb(spike[:5], 5) == spike[:5]
    with pytest.raises(RunError, match="at least 2"):
        q.lttb(spike, 1)


def test_metric_history_filters_names_and_caps_points(ctx: Context, toy_repo: Path) -> None:
    # PERF-F9a: the run page asks only for the charts it shows, at plot width
    seed_finished_run(ctx, toy_repo, "r1")
    points = [
        MetricPoint(name=name, step=step, value=float(step % 7))
        for name in ("loss", "acc", "sys/gpu")
        for step in range(300)
    ]
    ctx.index.replace_metric_points("r1", points)
    full = q.metric_history(ctx, "r1")
    assert full == ctx.index.metric_points("r1") and len(full) == 900
    loss = q.metric_history(ctx, "r1", names=["loss"])
    assert {p.name for p in loss} == {"loss"} and len(loss) == 300
    capped = q.metric_history(ctx, "r1", names=["loss", "acc"], max_points=40)
    assert [p.name for p in capped] == ["acc"] * 40 + ["loss"] * 40
    assert capped[0].step == 0 and capped[39].step == 299
    assert q.metric_history(ctx, "r1", names=[]) == []
    assert q.metric_history(ctx, "r1", names=["loss"], max_points=1000) == loss
    with pytest.raises(RunError, match="at least 2"):
        q.metric_history(ctx, "r1", max_points=1)


def _sweep(project: str, sweep_id: str, created_at: str) -> SweepSpec:
    return SweepSpec.model_validate(
        {
            "id": sweep_id,
            "project": project,
            "task": "toy-acc",
            "host": None,
            "grid": [{"name": "lr", "values": ["1e-4", "3e-4"]}],
            "seeds": [1],
            "command_template": ["python", "train.py", "--lr", "{lr}"],
            "created_by": "human",
            "created_at": created_at,
        }
    )


def test_list_sweeps_spans_projects_newest_first(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    ctx.register_project(toy_repo)
    other = write_toy_project(tmp_path / "toy2", use_git=False)
    _set_project_name(other, "toy2")
    ctx.register_project(other)
    save_sweep(ctx.layout, _sweep("toy", "s-0001", "2026-10-01T00:00:00Z"))
    save_sweep(ctx.layout, _sweep("toy2", "s-0001", "2026-10-03T00:00:00Z"))
    save_sweep(ctx.layout, _sweep("toy", "s-0002", "2026-10-02T00:00:00Z"))
    rows = q.list_sweeps(ctx)
    assert [(r["project"], r["id"]) for r in rows] == [
        ("toy2", "s-0001"),
        ("toy", "s-0002"),
        ("toy", "s-0001"),
    ]
    assert set(rows[0]) == {"project", "id", "created_at", "n_runs", "best"}
    assert rows[0]["n_runs"] == 0 and rows[0]["best"] is None
    only = q.list_sweeps(ctx, "toy")
    assert only == [{"project": "toy", **s} for s in list_project_sweeps(ctx, "toy")]
    assert [r["id"] for r in only] == ["s-0002", "s-0001"]
    assert q.list_sweeps(ctx, "nothing-here") == []


def _as_host_copy(ctx: Context, host: str = "gpu1") -> ProjectEntry:
    entry = ctx.store.load_project("toy").model_copy(update={"remote_host": host})
    ctx.store.save_project(entry)
    ctx.index.upsert_project(entry)
    return entry


def test_a_host_copy_is_never_read_from_its_repo_path(ctx: Context, toy_repo: Path) -> None:
    # I-2: a remote_host entry's repo is a path on the host; the hub must not
    # load hypothex.yaml or dataset files from that path, even if it exists here
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    assert q.get_predictions(ctx, "r1").rows[1].reference == 1
    copy = _as_host_copy(ctx)
    write_toy_project(toy_repo, accuracy_version="v9")
    entry = q.refresh_project(ctx, "toy")
    assert entry == copy and ctx.store.load_project("toy") == copy
    assert q.list_projects(ctx) == [copy]
    assert q.get_predictions(ctx, "r1").rows[1].reference is None
    with pytest.raises(ConfigError, match="copied from host gpu1"):
        q.dataset_overlap(ctx, "toy", "toyset")


def test_get_leaderboard_reuses_the_board_until_the_index_changes(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PERF-F1 handoff: the task board comes from leaderboard.cached_leaderboard
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    evaluate_run(ctx, "a")
    builds: list[str] = []
    real = q.build_leaderboard

    def spy(*args: Any, **kw: Any) -> Any:
        builds.append(args[1])
        return real(*args, **kw)

    monkeypatch.setattr(q, "build_leaderboard", spy)
    first = q.get_leaderboard(ctx, "toy-acc")
    first.rows.clear()  # a caller's change must not reach the cache
    again = q.get_leaderboard(ctx, "toy-acc")
    assert len(builds) == 1 and len(again.rows) == 1
    q.get_leaderboard(ctx, "toy-acc", examples=False)
    assert len(builds) == 2  # examples=False is its own board
    seed_finished_run(ctx, toy_repo, "b", predictions=ALL_RIGHT, config_hash="sha256:bbbb")
    evaluate_run(ctx, "b")
    assert len(q.get_leaderboard(ctx, "toy-acc").rows) == 2 and len(builds) == 3


def test_show_run_lists_metric_names_without_reading_the_points(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    points = [MetricPoint(name=n, step=s, value=1.0) for n in ("lr", "acc") for s in range(50)]
    ctx.index.replace_metric_points("r1", points)

    def no_points(*args: Any, **kw: Any) -> Any:
        raise AssertionError("show_run read every metric point")

    monkeypatch.setattr(ctx.index, "metric_points", no_points)
    monkeypatch.setattr(ctx.index, "metric_points_for", no_points)
    assert q.show_run(ctx, "r1").metric_names == ["acc", "lr"]
