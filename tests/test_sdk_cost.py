import json
from pathlib import Path

import pytest

import hypothex as hx
from hypothex import sdk
from hypothex.core.context import Context


@pytest.fixture
def run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "predictions").mkdir(parents=True)
    monkeypatch.setenv("HYPOTHEX_RUN_DIR", str(run_dir))
    monkeypatch.setenv("HYPOTHEX_RUN_ID", "r1")
    monkeypatch.setenv("HYPOTHEX_PROJECT", "toy")
    monkeypatch.setattr(sdk, "_current", None)
    return run_dir


def test_log_cost_writes_a_usage_row(run_env: Path) -> None:
    hx.current().log_cost(0.0131, tokens_in=4410, tokens_out=512, example_id="ex-1")
    hx.current().log_cost(0.5)
    rows = [json.loads(line) for line in (run_env / "usage.jsonl").read_text().splitlines()]
    assert rows == [
        {"example_id": "ex-1", "tokens_in": 4410, "tokens_out": 512, "usd": 0.0131, "seconds": 0.0},
        {"example_id": None, "tokens_in": 0, "tokens_out": 0, "usd": 0.5, "seconds": 0.0},
    ]


def test_log_cost_refuses_bad_values(run_env: Path) -> None:
    with pytest.raises(ValueError):
        hx.current().log_cost(-1.0)
    assert not (run_env / "usage.jsonl").exists()


def test_noop_log_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPOTHEX_RUN_DIR", raising=False)
    monkeypatch.setattr(sdk, "_current", None)
    assert hx.current().log_cost(1.0, tokens_in=3) is None


def test_log_cost_flows_into_finished_run_cost(ctx: Context, toy_repo: Path) -> None:
    """Actual command execution aggregates SDK costs into the final run record."""
    import sys

    from hypothex.core.execution import RunRequest, execute_run, prepare_run

    command = [
        sys.executable,
        "-c",
        (
            "import hypothex as hx; "
            "hx.current().log_cost(0.125, tokens_in=7, tokens_out=2); "
            "hx.current().log_cost(0.25)"
        ),
    ]
    record = prepare_run(ctx, RunRequest(repo=toy_repo, command=command))
    done = execute_run(ctx, record.run_id)
    assert done.usage is not None and done.usage.usd == 0.375
    assert done.usage.tokens_in == 7 and done.usage.tokens_out == 2
    assert done.cost is not None and done.cost.api_usd == 0.375
