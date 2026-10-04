import fcntl
from pathlib import Path

import pytest
import yaml

from hypothex.core import evaluation
from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.errors import EvalError
from hypothex.core.evaluation import evaluate_run, metric_drift, reeval, validate_project
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


def test_non_numeric_worker_values_become_a_metric_error(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_finished_run(ctx, toy_repo, "r1", task="toy-broken", predictions=PREDS_075)
    fake = {
        "n_examples": 4,
        "results": [
            {
                "name": "accuracy",
                "version": "v1",
                "values": {"value": 0.5},
                "error": None,
                "source_hash": None,
            },
            {
                "name": "broken",
                "version": "v1",
                "values": {"value": "high"},
                "error": None,
                "source_hash": None,
            },
        ],
    }
    monkeypatch.setattr(evaluation, "run_worker", lambda *a, **k: fake)
    scores, _ = evaluate_run(ctx, "r1")
    by_metric = {s.metric: s for s in scores}
    assert by_metric["accuracy"].value == 0.5
    assert by_metric["broken"].value is None and "non-numeric" in (by_metric["broken"].error or "")


def test_reeval_records_unexpected_error_and_continues(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_075)
    real = evaluation.evaluate_run

    def flaky(c: Context, run_id: str, **kw: object) -> object:
        if run_id == "r1":
            raise RuntimeError("disk on fire")
        return real(c, run_id, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(evaluation, "evaluate_run", flaky)
    report = reeval(ctx, project="toy", task="toy-acc")
    assert report.evaluated == ["r2"]
    assert report.skipped == {"r1": "RuntimeError: disk on fire"}


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


def _tweak_accuracy(repo: Path) -> None:
    """Change the accuracy metric's code without bumping its version."""
    path = repo / "toymetrics.py"
    path.write_text(
        path.read_text().replace(
            "def accuracy(examples):\n", "def accuracy(examples):\n    # tweak\n"
        )
    )


def test_metric_code_change_without_bump_warns(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    _tweak_accuracy(toy_repo)
    _, warnings = evaluate_run(ctx, "r1")
    assert any("without a version bump" in w for w in warnings)


def test_metric_drift_warning_is_a_run_warning_event(ctx: Context, toy_repo: Path) -> None:
    # auto-eval (execution, slurm) keeps no report: the warning must reach the run's events
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    _tweak_accuracy(toy_repo)
    evaluate_run(ctx, "r1")
    messages = [e.payload["message"] for e in ctx.events.since(0) if e.type == "run.warning"]
    assert messages == ["metric accuracy code changed without a version bump (still v1)"]


def test_metric_drift_names_changed_metrics(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", task="toy-broken", predictions=PREDS_075)
    config = load_project_config(toy_repo)
    assert metric_drift(ctx, toy_repo, config) == []  # nothing recorded yet
    evaluate_run(ctx, "r1")
    assert metric_drift(ctx, toy_repo, config) == []
    _tweak_accuracy(toy_repo)
    assert metric_drift(ctx, toy_repo, config) == ["accuracy@v1"]
    assert metric_drift(ctx, toy_repo, config, ["broken"]) == []
    assert any("without a version bump" in w for w in validate_project(ctx, toy_repo).warnings)


def test_reeval_warns_about_metric_drift_without_force(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    _tweak_accuracy(toy_repo)
    report = reeval(ctx, project="toy", task="toy-acc")
    assert report.skipped == {"r1": "already scored at the current version"}
    assert report.warnings == ["metric accuracy code changed without a version bump (still v1)"]


def test_evaluate_removed_task_is_clear_error(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    cfg_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    del cfg["tasks"]["toy-acc"]
    cfg_path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(EvalError, match="no longer exists"):
        evaluate_run(ctx, "r1")


def test_a_project_copied_from_a_host_is_never_evaluated_from_its_repo_path(
    ctx: Context, toy_repo: Path
) -> None:
    # the host reported a repo path that also exists here: its hypothex.yaml and
    # metric code must not run on the hub (SEC-5)
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    entry = ctx.store.load_project("toy")
    ctx.store.save_project(entry.model_copy(update={"remote_host": "gpu1"}))
    with pytest.raises(EvalError, match="copied from host gpu1"):
        evaluate_run(ctx, "r1")
    with pytest.raises(EvalError, match="copied from host gpu1"):
        reeval(ctx, project="toy", task="toy-acc")
    assert ctx.store.read_scores("toy", "r1") == []
    assert ctx.index.scores_for(["r1"]) == {}


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


def _project_lock_is_held(ctx: Context) -> bool:
    lock_file = ctx.layout.project_dir("toy") / ".lock"
    if not lock_file.exists():
        return False
    with lock_file.open("a") as fh:  # a second open file description conflicts with flock
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return False


def test_metric_hashes_update_holds_project_lock(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seen: list[tuple[str, bool]] = []
    real_read, real_save = ctx.store.metric_hashes, ctx.store.save_metric_hashes

    def read(project: str) -> dict[str, str]:
        seen.append(("read", _project_lock_is_held(ctx)))
        return real_read(project)

    def save(project: str, hashes: dict[str, str]) -> None:
        seen.append(("save", _project_lock_is_held(ctx)))
        real_save(project, hashes)

    monkeypatch.setattr(ctx.store, "metric_hashes", read)
    monkeypatch.setattr(ctx.store, "save_metric_hashes", save)
    evaluate_run(ctx, "r1")
    assert seen == [("read", True), ("save", True)]
    assert not _project_lock_is_held(ctx)
    assert list(real_read("toy")) == ["accuracy@v1"]
