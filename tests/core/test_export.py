import os
from pathlib import Path

import pytest
import yaml

from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.evaluation import evaluate_run
from hypothex.core.export import (
    ExportOptions,
    compare_table,
    export_compare,
    export_task,
    latex_escape,
    leaderboard_table,
    render,
    task_table,
)
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import BaselineRow, Leaderboard, LeaderboardRow, NoiseInterval
from hypothex.core.records import RunStatus, ScoreRecord
from hypothex.core.seeds import Stats
from tests.factories import PREDS_075, make_record, seed_finished_run, write_toy_project


def group(
    gid: str,
    label: str,
    acc: list[float],
    acc_stats: Stats,
    f1: list[float],
    f1_stats: Stats,
    lo: float,
    hi: float,
    within: bool | None,
) -> LeaderboardRow:
    return LeaderboardRow(
        group_id=gid,
        run_ids=[f"{label}-{i}" for i in range(len(acc))],
        latest_run_id=f"{label}-0",
        hypothesis=label,
        commit="c1",
        config_hash=f"sha256:{gid}",
        n=len(acc),
        scores={"acc/value": acc_stats, "f1/value": f1_stats},
        primary=acc_stats,
        single_seed=len(acc) == 1,
        within_noise_of_best=within,
        label=label,
        seed_values={"acc/value": acc, "f1/value": f1},
        identical_seeds=len(acc) > 1 and len(set(acc)) == 1,
        test_interval=NoiseInterval(lo=lo, hi=hi, method="wilson", n=200),
        vs_best=None,
        created_by=["human"],
        usage=None,
    )


def make_board(*, baselines: bool = True) -> Leaderboard:
    rows = [
        group(
            "aaaa0001@c1", "svm", [0.91, 0.92, 0.93], Stats(mean=0.92, std=0.01, n=3),
            [0.88, 0.89, 0.90], Stats(mean=0.89, std=0.01, n=3), 0.871, 0.954, None,
        ),
        group(
            "aaaa0002@c1", "rf", [0.905, 0.91, 0.915], Stats(mean=0.91, std=0.005, n=3),
            [0.9, 0.91, 0.92], Stats(mean=0.91, std=0.01, n=3), 0.862, 0.947, True,
        ),
        group(
            "aaaa0003@c1", "logreg", [0.88, 0.88, 0.88], Stats(mean=0.88, std=0.0, n=3),
            [0.85, 0.86, 0.87], Stats(mean=0.86, std=0.01, n=3), 0.826, 0.925, False,
        ),
        group(
            "aaaa0004@c1", "knn", [0.85], Stats(mean=0.85, std=0.0, n=1),
            [0.8], Stats(mean=0.8, std=0.0, n=1), 0.794, 0.894, None,
        ),
    ]  # fmt: skip
    board = Leaderboard(
        project="toy",
        task="t",
        primary="acc/value",
        higher_is_better=True,
        metric_versions={"acc": "v2", "f1": "v1"},
        rows=rows,
        needs_reeval=[],
        unscored=[],
        headline="",
        kind="generic",
        stat_strip=[],
        value_format="fraction",
    )
    if baselines:
        board.baselines = [
            BaselineRow(
                name="Smith_2024 & co",
                values={"acc/value": 0.9, "f1/value": 0.87},
                std={"acc/value": 0.004},
                source="arXiv:2401.01234",
                source_url="https://arxiv.org/abs/2401.01234",
                version_match={"acc": True, "f1": True},
                primary=0.9,
                delta_vs_best=0.02,
            ),
            BaselineRow(
                name="Lee 2023",
                values={"acc/value": 0.93},
                std={},
                source="doi:10.1000/xyz123",
                source_url="https://doi.org/10.1000/xyz123",
                version_match={"acc": False, "f1": False},
                primary=0.93,
                delta_vs_best=-0.01,
            ),
        ]
    return board


def test_columns_rows_and_marks() -> None:
    table = leaderboard_table(make_board(), ExportOptions())
    assert table.title == "toy/t" and table.columns == ["acc/value", "f1/value"]
    assert table.higher_is_better == {"acc/value": True, "f1/value": True}
    assert [(r.kind, r.label) for r in table.rows] == [
        ("group", "svm"),
        ("group", "rf"),
        ("group", "logreg"),
        ("group", "knn"),
        ("baseline", "Smith_2024 & co"),
        ("baseline", "Lee 2023"),
    ]
    svm, rf, logreg, knn, smith, lee = table.rows
    assert svm.cells["acc/value"].best and not svm.cells["f1/value"].best
    assert rf.cells["f1/value"].best and rf.within_noise and not svm.within_noise
    assert logreg.cells["acc/value"].identical and not logreg.cells["f1/value"].identical
    assert knn.cells["acc/value"].std is None and knn.n == 1
    cell = svm.cells["acc/value"]
    assert (cell.lo, cell.hi, cell.method, cell.n_examples) == (0.871, 0.954, "wilson", 200)
    assert svm.cells["f1/value"].lo is None  # test-set CI only on the primary
    assert not smith.version_mismatch and lee.version_mismatch
    assert lee.cells["f1/value"].mean is None and not lee.cells["acc/value"].best
    assert smith.cells["acc/value"].std == 0.004 and smith.source == "arXiv:2401.01234"


def test_footnotes() -> None:
    assert leaderboard_table(make_board(), ExportOptions()).footnotes == [
        "metric versions: acc@v2, f1@v1",
        "¹ single seed · ◇×n identical seeds · † within noise of best · "
        "‡ metric version differs from the paper",
        "[lo, hi] 95% test-set interval (wilson)",
        "baselines: Smith_2024 & co — arXiv:2401.01234; Lee 2023 — doi:10.1000/xyz123",
    ]


@pytest.mark.parametrize(
    ("noise", "std", "ci", "identical"),
    [("both", True, True, True), ("seed", True, False, True), ("test", False, True, False),
     ("none", False, False, False)],
)  # fmt: skip
def test_noise_modes(noise: str, std: bool, ci: bool, identical: bool) -> None:
    table = leaderboard_table(make_board(), ExportOptions(noise=noise))  # type: ignore[arg-type]
    svm, _, logreg = table.rows[:3]
    assert (svm.cells["acc/value"].std is not None) is std
    assert (svm.cells["acc/value"].lo is not None) is ci
    assert logreg.cells["acc/value"].identical is identical


def test_metrics_top_groups_and_directions() -> None:
    board = make_board(baselines=False)
    table = leaderboard_table(board, ExportOptions(metrics=["f1"], top=2), directions={"f1": False})
    assert table.columns == ["f1/value"] and [r.label for r in table.rows] == ["svm", "rf"]
    assert table.higher_is_better == {"f1/value": False}
    assert table.rows[0].cells["f1/value"].best  # lower f1 wins when told so
    picked = leaderboard_table(board, ExportOptions(groups=["knn", "aaaa0003@c1"]))
    assert [r.label for r in picked.rows] == ["logreg", "knn"]


def test_percent_scales_fraction_boards() -> None:
    table = leaderboard_table(make_board(), ExportOptions(percent=True))
    cell = table.rows[0].cells["acc/value"]
    assert cell.mean == pytest.approx(92.0) and cell.std == pytest.approx(1.0)
    assert cell.lo == pytest.approx(87.1) and "values ×100: acc/value" in table.footnotes
    board = make_board()
    board.value_format = "number"
    plain = leaderboard_table(board, ExportOptions(percent=True))
    assert plain.rows[0].cells["acc/value"].mean == 0.92


@pytest.mark.parametrize("primary", ["acc/value", "latency/p95"])
def test_percent_scales_only_fraction_columns_in_groups_and_baselines(primary: str) -> None:
    board = make_board()
    for row in board.rows:
        row.scores["latency/p95"] = Stats(n=2, mean=440.0, std=10.0)
        row.seed_values["latency/p95"] = [430.0, 450.0]
    board.baselines[0].values["latency/p95"] = 400.0
    board.baselines[0].std["latency/p95"] = 5.0
    board.primary = primary
    board.value_format = "fraction" if primary == "acc/value" else "number"
    board.higher_is_better = primary == "acc/value"
    table = leaderboard_table(
        board,
        ExportOptions(percent=True, metrics=["acc/value", "latency/p95"]),
        directions={"acc/value": True, "latency/p95": False},
        value_formats={"acc/value": "fraction", "latency/p95": "number"},
    )
    assert table.rows[0].cells["acc/value"].mean == pytest.approx(92.0)
    assert table.rows[0].cells["acc/value"].std == pytest.approx(1.0)
    assert table.rows[0].cells["latency/p95"].mean == 440.0
    assert table.rows[0].cells["latency/p95"].std == 10.0
    baseline = next(row for row in table.rows if row.kind == "baseline")
    assert baseline.cells["acc/value"].mean == pytest.approx(90.0)
    assert baseline.cells["acc/value"].std == pytest.approx(0.4)
    assert baseline.cells["latency/p95"].mean == 400.0
    assert baseline.cells["latency/p95"].std == 5.0
    assert "values ×100: acc/value" in table.footnotes


def test_no_baselines_option_and_empty_board() -> None:
    groups_only = leaderboard_table(make_board(), ExportOptions(baselines=False))
    assert all(r.kind == "group" for r in groups_only.rows)
    empty = make_board(baselines=False)
    empty.rows = []
    table = leaderboard_table(empty, ExportOptions())
    assert table.columns == ["acc/value"] and table.rows == []
    assert table.footnotes == ["metric versions: acc@v2"]


def test_options_are_strict() -> None:
    with pytest.raises(ValueError):
        ExportOptions(format="html")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ExportOptions(digits=9)
    assert ExportOptions().model_dump()["noise"] == "both"


GOLDEN = Path(__file__).parent / "golden" / "export"


def check_golden(name: str, text: str) -> None:
    """Compare with a golden file; ``HX_UPDATE_GOLDEN=1`` rewrites it instead."""
    path = GOLDEN / name
    if os.environ.get("HX_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("fmt", "ext"), [("markdown", "md"), ("latex", "tex"), ("csv", "csv")])
def test_board_matches_the_golden_file(fmt: str, ext: str) -> None:
    opts = ExportOptions(format=fmt)  # type: ignore[arg-type]
    text = render(leaderboard_table(make_board(), opts), opts)
    check_golden(f"board.{ext}", text)
    assert text == render(leaderboard_table(make_board(), opts), opts)  # deterministic


def test_latex_is_ascii() -> None:
    opts = ExportOptions(format="latex")
    assert render(leaderboard_table(make_board(), opts), opts).isascii()


def test_latex_escape() -> None:
    text = latex_escape("a_b & 50% $x #1 {y} ~ ^ \\ é ± †")
    assert text == (
        r"a\_b \& 50\% \$x \#1 \{y\} \textasciitilde{} \textasciicircum{} "
        r"\textbackslash{} e $\pm$ $^{\dagger}$"
    )
    assert text.isascii()


def test_standalone_latex_wraps_a_table() -> None:
    opts = ExportOptions(format="latex", standalone=True, caption="Toy results", label="tab:toy")
    text = render(leaderboard_table(make_board(), opts), opts)
    lines = text.splitlines()
    assert lines[:5] == [
        r"% requires \usepackage{booktabs}",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Toy results}",
        r"\label{tab:toy}",
    ]
    assert r"\par\smallskip\footnotesize" in lines
    assert lines[-2] == (
        r"baselines: Smith\_2024 \& co --- arXiv:2401.01234; Lee 2023 --- doi:10.1000/xyz123"
    )
    assert lines[-1] == r"\end{table}" and not any(line.startswith("% metric") for line in lines)


def test_noise_and_digits_in_markdown() -> None:
    opts = ExportOptions(noise="none", digits=1, mark_noise=False, baselines=False)
    lines = render(leaderboard_table(make_board(), opts), opts).splitlines()
    assert lines[2] == "| svm | 3 | **0.9** | 0.9 |"
    assert lines[3] == "| rf | 3 | 0.9 | **0.9** |"  # no † when mark_noise is off


def test_missing_values_never_print_nan() -> None:
    board = make_board()
    board.rows[0].scores.pop("f1/value")
    for fmt, missing in (("markdown", "—"), ("latex", "--")):
        opts = ExportOptions(format=fmt)  # type: ignore[arg-type]
        text = render(leaderboard_table(board, opts), opts)
        svm_line = text.splitlines()[2 if fmt == "markdown" else 5]
        assert "nan" not in text.lower() and missing in svm_line


def test_empty_board_renders_a_header_only_table() -> None:
    board = make_board(baselines=False)
    board.rows = []
    opts = ExportOptions()
    assert render(leaderboard_table(board, opts), opts) == (
        "| group | n | acc/value ↑ |\n|:--|--:|--:|\n\n- metric versions: acc@v2\n"
    )


PREDS_025 = [{"id": f"ex-{i}", "prediction": 1} for i in range(4)]  # 1 of 4 correct


@pytest.fixture
def scored(ctx: Context, toy_repo: Path) -> Context:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_025)
    evaluate_run(ctx, "r1")
    evaluate_run(ctx, "r2")
    return ctx


@pytest.mark.parametrize(("fmt", "ext"), [("markdown", "md"), ("csv", "csv")])
def test_compare_matches_the_golden_file(scored: Context, fmt: str, ext: str) -> None:
    opts = ExportOptions(format=fmt)  # type: ignore[arg-type]
    check_golden(f"compare.{ext}", export_compare(scored, ["r1", "r2"], opts))


def test_compare_table_rows(scored: Context) -> None:
    table = compare_table(scored, ["r2", "r1"], ExportOptions())
    assert [(r.kind, r.key, r.n) for r in table.rows] == [("run", "r2", 1), ("run", "r1", 1)]
    assert table.rows[1].cells["accuracy/value"].best
    assert table.title == "compare"


def test_compare_refuses_two_versions_of_one_metric(scored: Context, tmp_path: Path) -> None:
    other = write_toy_project(tmp_path / "toy2", accuracy_version="v2", use_git=False)
    config = yaml.safe_load((other / "hypothex.yaml").read_text())
    config["project"] = "toy2"
    (other / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    seed_finished_run(scored, other, "r3", predictions=PREDS_075)
    evaluate_run(scored, "r3")
    with pytest.raises(RunError, match="accuracy is accuracy@v1 in toy and accuracy@v2 in toy2"):
        compare_table(scored, ["r1", "r3"], ExportOptions())


def test_compare_needs_two_to_twenty_runs(scored: Context) -> None:
    with pytest.raises(RunError):
        compare_table(scored, ["r1"], ExportOptions())
    with pytest.raises(RunError):
        compare_table(scored, ["r1"] * 21, ExportOptions())


def test_task_export_primary_uses_selected_board_and_rejects_compare(
    ctx: Context, toy_repo: Path
) -> None:
    from hypothex.core.errors import ConfigError
    from hypothex.core.queries import get_leaderboard
    from tests.core.test_backlog_backend import indexed

    indexed(ctx, toy_repo)  # acc selects a; latency/p95 selects b, lower is better.
    opts = ExportOptions(primary="latency/p95", noise="both")
    board = get_leaderboard(ctx, "t", "toy", primary=opts.primary)
    table = task_table(ctx, "t", "toy", opts)
    assert table.columns[0] == "latency/p95"
    assert table.rows[0].key == board.rows[0].group_id
    assert table.higher_is_better[board.primary] == board.higher_is_better is False
    assert table.rows[0].cells[board.primary].lo == board.rows[0].test_interval.lo
    assert task_table(ctx, "t", "toy", ExportOptions()).columns[0] == "acc/value"
    with pytest.raises(ConfigError):
        task_table(ctx, "t", "toy", ExportOptions(primary="latency/unknown"))
    with pytest.raises(RunError, match="primary"):
        compare_table(ctx, ["a", "b"], opts)
    with pytest.raises(RunError, match="primary"):
        export_compare(ctx, ["a", "b"], opts)


def test_export_task_uses_the_live_leaderboard(scored: Context) -> None:
    text = export_task(scored, "toy-acc", "toy", ExportOptions())
    header, _, row = text.splitlines()[:3]
    assert header == "| group | n | accuracy/value ↑ |"
    assert row.startswith("| group aaaa@c1 | 2 |")  # r1 and r2 are one seed group
    assert "0.500 ± 0.354" in row and "[" in row  # test-set CI from per-example scores


@pytest.fixture
def bench(ctx: Context, toy_repo: Path) -> Context:
    """A system_bench task: p95 latency 440 ms (base) and 300 ms (fast)."""
    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["metrics"]["lat"] = {"version": "v1", "fn": "toymetrics:accuracy"}
    config["tasks"]["sb"] = {
        "dataset": "toyset", "split": "test", "metrics": ["lat"],
        "primary": "lat/p95", "kind": "system_bench",
    }  # fmt: skip
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    ctx.register_project(toy_repo)
    for run_id, ms in (("base", 440.0), ("fast", 300.0)):
        record = ctx.create_run(
            make_record(
                run_id,
                project="toy",
                task="sb",
                status=RunStatus.FINISHED,
                environment_id=ctx.descriptor.environment_id,
            )
        )
        score = ScoreRecord(metric="lat", version="v1", key="p95", value=ms, created_at=utcnow())
        ctx.add_score(record, score)
    return ctx


def test_compare_ranks_benchmark_percentiles_like_the_leaderboard(bench: Context) -> None:
    table = compare_table(bench, ["base", "fast"], ExportOptions())
    assert table.columns == ["lat/p95"] and table.higher_is_better == {"lat/p95": False}
    assert [r.cells["lat/p95"].best for r in table.rows] == [False, True]  # 300 beats 440
    text = export_compare(bench, ["base", "fast"], ExportOptions())
    assert text.startswith("| run | n | lat/p95 ↓ |")


def test_compare_percent_scales_fractions(scored: Context) -> None:
    table = compare_table(scored, ["r1", "r2"], ExportOptions(percent=True))
    assert [r.cells["accuracy/value"].mean for r in table.rows] == [75.0, 25.0]
    assert "values ×100" in table.footnotes


def test_task_percent_derives_each_columns_unit(scored: Context, toy_repo: Path) -> None:
    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["metrics"]["latency"] = {
        "version": "v1",
        "fn": "toymetrics:accuracy",
        "unit": "ms",
        "higher_is_better": False,
    }
    config["tasks"]["toy-acc"]["metrics"].append("latency")
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    scored.register_project(toy_repo)
    for run_id in ("r1", "r2"):
        scored.add_score(
            scored.find_record(run_id),
            ScoreRecord(
                metric="latency",
                version="v1",
                key="value",
                value=440.0,
                created_at=utcnow(),
            ),
        )
    from hypothex.core.export import task_table

    table = task_table(scored, "toy-acc", "toy", ExportOptions(percent=True))
    assert table.rows[0].cells["accuracy/value"].mean == pytest.approx(50.0)
    assert table.rows[0].cells["latency/value"].mean == 440.0


def test_compare_percent_leaves_latency_alone(bench: Context) -> None:
    table = compare_table(bench, ["base", "fast"], ExportOptions(percent=True))
    assert [r.cells["lat/p95"].mean for r in table.rows] == [440.0, 300.0]
    assert "values ×100" not in table.footnotes


@pytest.mark.parametrize("kind", ["generic", "system_bench"])
@pytest.mark.parametrize("flag", ["omitted", None, True, False])
@pytest.mark.parametrize("key", ["p95", "value", "data.p95"])
@pytest.mark.parametrize("alternate", [False, True])
def test_export_direction_matches_live_consumers(
    ctx: Context,
    toy_repo: Path,
    kind: str,
    flag: str | bool | None,
    key: str,
    alternate: bool,
) -> None:
    from hypothex.core.leaderboard import key_higher_is_better
    from hypothex.core.panels import query_panel
    from hypothex.core.queries import get_leaderboard
    from hypothex.core.taskruns import task_runs
    from hypothex.core.views import PanelSpec

    ref = f"quality/{key}"
    cfg = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    cfg["metrics"]["quality"] = {"version": "v1", "fn": "toymetrics:accuracy"}
    if flag != "omitted":
        cfg["metrics"]["quality"]["higher_is_better"] = flag
    cfg["tasks"]["toy-acc"].update(
        kind=kind,
        metrics=["accuracy", "quality"],
        primary="accuracy" if alternate else ref,
        baselines=[
            {
                "name": "Paper",
                "values": {ref: 0.7},
                "source": "doi:10.1000/test",
                "metric_version_equivalent": {"quality": "v1"},
            }
        ],
    )
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(cfg))
    ctx.register_project(toy_repo)
    for rid, value in (("low", 0.4), ("high", 0.8)):
        rec = ctx.create_run(
            make_record(
                rid,
                task="toy-acc",
                status=RunStatus.FINISHED,
                config_hash=rid,
                environment_id=ctx.descriptor.environment_id,
            )
        )
        for metric, score_key, score_value in (
            ("quality", key, value),
            ("accuracy", "value", 1 - value),
        ):
            ctx.add_score(
                rec,
                ScoreRecord(
                    metric=metric,
                    version="v1",
                    key=score_key,
                    value=score_value,
                    created_at=utcnow(),
                ),
            )
    entry = ctx.store.load_project("toy")
    assert entry.config_format == 2
    stored = entry.model_dump(mode="json")["config"]["metrics"]["quality"]
    if flag is None or flag == "omitted":
        assert "higher_is_better" not in stored
    else:
        assert stored["higher_is_better"] is flag
    expected = flag if isinstance(flag, bool) else not (kind == "system_bench" and "p95" in key)
    assert key_higher_is_better(entry.config, entry.config.tasks["toy-acc"], ref) is expected
    opts = ExportOptions(primary=ref if alternate else None, metrics=[ref])
    board = get_leaderboard(ctx, "toy-acc", "toy", primary=opts.primary)
    table = task_table(ctx, "toy-acc", "toy", opts)
    compare = compare_table(ctx, ["low", "high"], ExportOptions(metrics=[ref]))
    assert table.higher_is_better[ref] is compare.higher_is_better[ref] is expected
    assert board.higher_is_better is expected
    assert board.rows[0].run_ids == ["high" if expected else "low"]
    assert table.rows[0].key == board.rows[0].group_id
    assert table.rows[0].cells[ref].best
    assert [row.cells[ref].best for row in compare.rows] == [not expected, expected]
    assert board.baselines[0].delta_vs_best == pytest.approx(0.1 if expected else 0.3)
    assert table.rows[-1].kind == "baseline" and not table.rows[-1].cells[ref].best
    arrow = "↑" if expected else "↓"
    assert f"{ref} {arrow}" in render(table, opts).splitlines()[0]
    assert task_runs(ctx, "toy-acc", "toy").key_higher_is_better[ref] is expected
    if key == "data.p95":
        panel = query_panel(
            ctx,
            "toy",
            "toy-acc",
            PanelSpec.model_validate(
                {
                    "type": "compare",
                    "title": "Direction",
                    "data": {"datasets": ["data"], "metrics": ["p95"]},
                }
            ),
        )
        assert len(panel.rows) == 2
        assert all(row["higher_is_better"] is expected for row in panel.rows)


@pytest.mark.parametrize(
    "kind,ref,accept",
    [
        ("generic", "latency/p95", True),
        ("system_bench", "latency/value", True),
        ("system_bench", "latency/p95", False),
    ],
)
def test_compare_checks_effective_direction_across_projects(
    ctx: Context,
    tmp_path: Path,
    kind: str,
    ref: str,
    accept: bool,
) -> None:
    for project, direction in (("unset", None), ("explicit", True)):
        repo = write_toy_project(tmp_path / project, use_git=False)
        cfg = yaml.safe_load((repo / "hypothex.yaml").read_text())
        cfg["project"] = project
        cfg["metrics"]["latency"] = {
            "fn": "toymetrics:accuracy",
            "version": "v1",
            "higher_is_better": direction,
        }
        cfg["tasks"]["toy-acc"].update(metrics=["latency"], primary=ref, kind=kind)
        (repo / "hypothex.yaml").write_text(yaml.safe_dump(cfg))
        ctx.register_project(repo)
        rec = ctx.create_run(
            make_record(
                project,
                project=project,
                task="toy-acc",
                status=RunStatus.FINISHED,
                environment_id=ctx.descriptor.environment_id,
            )
        )
        ctx.add_score(
            rec,
            ScoreRecord(
                metric="latency",
                version="v1",
                key=ref.split("/")[1],
                value=2.0,
                created_at=utcnow(),
            ),
        )
    if accept:
        table = compare_table(ctx, ["unset", "explicit"], ExportOptions())
        assert table.higher_is_better[ref] is True
        assert all(row.cells[ref].best for row in table.rows)
    else:
        with pytest.raises(RunError, match="ranks lower-first.*higher-first"):
            compare_table(ctx, ["unset", "explicit"], ExportOptions())


def test_compare_ignores_stale_failed_and_nonfinite_scores(scored: Context) -> None:
    rec = scored.find_record("r1")
    for version, value, error in (
        ("v0", 1.0, None),
        ("v1", 1.0, "failed"),
        ("v1", float("nan"), None),
    ):
        scored.add_score(
            rec,
            ScoreRecord(
                metric="accuracy",
                version=version,
                key="value",
                value=value,
                error=error,
                created_at=utcnow(),
            ),
        )
    table = compare_table(
        scored, ["r1", "r2"], ExportOptions(metrics=["accuracy", "accuracy/value", "missing"])
    )
    assert table.columns == ["accuracy/value", "missing/value"]
    assert table.rows[0].cells["accuracy/value"].mean == 0.75
    assert all(row.cells["missing/value"].mean is None for row in table.rows)


def test_compare_accepts_twenty_runs_without_noise(scored: Context) -> None:
    table = compare_table(scored, ["r1", "r2"] * 10, ExportOptions(noise="both"))
    assert len(table.rows) == 20
    assert all(
        cell.std is cell.lo is cell.hi is cell.method is None
        for row in table.rows
        for cell in row.cells.values()
    )


def test_mark_best_handles_ties_missing_and_repeated_calls() -> None:
    from hypothex.core.export import mark_best

    table = leaderboard_table(make_board(), ExportOptions())
    table.rows[1].cells["acc/value"].mean = 0.92
    mark_best(table.rows, {"acc/value": True})
    assert table.rows[0].cells["acc/value"].best
    assert table.rows[1].cells["acc/value"].best
    mark_best(table.rows, {"acc/value": False})
    assert not table.rows[0].cells["acc/value"].best
    assert table.rows[3].cells["acc/value"].best
    assert all(
        not c.best for row in table.rows if row.kind == "baseline" for c in row.cells.values()
    )


def test_markdown_escapes_table_delimiters_and_line_breaks() -> None:
    board = make_board(baselines=False)
    board.rows[0].label = "a\\|b\r\nsecond"
    text = render(leaderboard_table(board, ExportOptions()), ExportOptions())
    assert text.splitlines()[2].startswith("| a\\\\\\|b<br>second |")
    assert len([line for line in text.splitlines() if line.startswith("| ")]) == 5


def test_csv_quotes_and_preserves_user_text() -> None:
    import csv
    import io

    board = make_board()
    board.rows[0].label = 'one,"two"\nthree'
    opts = ExportOptions(format="csv")
    text = render(leaderboard_table(board, opts), opts)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows[0]["label"] == board.rows[0].label
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_latex_escapes_labels_captions_and_line_breaks() -> None:
    opts = ExportOptions(
        format="latex", standalone=True, caption="A & B\n50%", label=r"tab:x}\input{file"
    )
    text = render(leaderboard_table(make_board(), opts), opts)
    assert r"\caption{A \& B 50\%}" in text
    assert r"\label{tab:x\}\textbackslash{}input\{file}" in text
    assert latex_escape("label\r\nnext") == "label  next"
    assert latex_escape("ø😀") == "??"


def test_fmt_number_never_prints_negative_zero() -> None:
    from hypothex.core.export import fmt_number

    assert fmt_number(-0.0001, 3) == "0.000"
    assert fmt_number(-0.0, 0) == "0"


def test_compare_missing_key_keeps_configured_direction_and_version(bench: Context) -> None:
    table = compare_table(bench, ["base", "fast"], ExportOptions(metrics=["lat/p99"]))
    assert table.higher_is_better == {"lat/p99": False}
    assert table.footnotes == ["metric versions: lat@v1", "one run per row"]
    assert all(row.cells["lat/p99"].mean is None for row in table.rows)


def test_compare_missing_score_does_not_hide_version_conflict(
    scored: Context, tmp_path: Path
) -> None:
    other = write_toy_project(tmp_path / "unscored", accuracy_version="v2", use_git=False)
    cfg = yaml.safe_load((other / "hypothex.yaml").read_text())
    cfg["project"] = "unscored"
    (other / "hypothex.yaml").write_text(yaml.safe_dump(cfg))
    seed_finished_run(scored, other, "r3", predictions=PREDS_075)
    with pytest.raises(RunError, match="accuracy@v1.*accuracy@v2"):
        compare_table(scored, ["r1", "r3"], ExportOptions(metrics=["accuracy"]))


def test_latex_unicode_normalization_cannot_introduce_commands() -> None:
    assert latex_escape("＼input｛file｝＆％") == r"\textbackslash{}input\{file\}\&\%"


def test_task_export_can_show_an_absent_column(scored: Context) -> None:
    opts = ExportOptions(metrics=["accuracy", "absent/value"])
    table = task_table(scored, "toy-acc", "toy", opts)
    assert table.columns == ["accuracy/value", "absent/value"]
    assert all(row.cells["absent/value"].mean is None for row in table.rows)
    assert table.footnotes[0] == "metric versions: accuracy@v1"
