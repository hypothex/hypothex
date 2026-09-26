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
