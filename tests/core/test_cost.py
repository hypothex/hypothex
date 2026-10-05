import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.cost import (
    add_costs,
    billed_gpus,
    compute_cost,
    cost_since,
    price_record,
    today_start,
    wall_hours,
)
from hypothex.core.execution import RunRequest, execute_run, prepare_run
from hypothex.core.records import CostTotals, ExecutorInfo, RunRecord, RunStatus, UsageTotals
from tests.factories import make_record

START = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)


def ended(
    minutes: float,
    gpus: list[int],
    usd: float | None = None,
    *,
    slurm_job_id: str | None = None,
    gpus_requested: int = 0,
) -> RunRecord:
    """A finished run that ran ``minutes`` on ``gpus`` and spent ``usd`` on APIs."""
    return make_record(
        status=RunStatus.FINISHED,
        started_at=START,
        ended_at=START + timedelta(minutes=minutes),
        executor=ExecutorInfo(gpus=gpus, slurm_job_id=slurm_job_id),
        usage=None if usd is None else UsageTotals(usd=usd, calls=1),
        gpus_requested=gpus_requested,
    )


@pytest.mark.parametrize(
    ("minutes", "gpus", "rate", "usd", "expected"),
    [
        (
            90,
            [0, 1],
            2.10,
            0.375,
            CostTotals(
                gpu_hours=3.0,
                gpu_usd=6.3,
                api_usd=0.375,
                total_usd=6.675,
                gpu_pricing_complete=True,
            ),
        ),
        (
            20,
            [3],
            2.1,
            0.375,
            CostTotals(
                gpu_hours=0.333333,
                gpu_usd=0.7,
                api_usd=0.375,
                total_usd=1.075,
                gpu_pricing_complete=True,
            ),
        ),
        (
            45,
            [0, 1, 2, 3],
            None,
            0.5,
            CostTotals(
                gpu_hours=3.0, gpu_usd=0.0, api_usd=0.5, total_usd=0.5, gpu_pricing_complete=False
            ),
        ),
        (
            150,
            [4, 5],
            1.25,
            None,
            CostTotals(
                gpu_hours=5.0, gpu_usd=6.25, api_usd=0.0, total_usd=6.25, gpu_pricing_complete=True
            ),
        ),
        (30, [], 3.0, None, CostTotals(gpu_pricing_complete=True)),
    ],
)
def test_compute_cost(
    minutes: float, gpus: list[int], rate: float | None, usd: float | None, expected: CostTotals
) -> None:
    assert compute_cost(ended(minutes, gpus, usd), rate) == expected


def test_zero_rate_is_free_gpu_time() -> None:
    cost = compute_cost(ended(60, [0], 0.25), 0.0)
    assert cost == CostTotals(
        gpu_hours=1.0, gpu_usd=0.0, api_usd=0.25, total_usd=0.25, gpu_pricing_complete=True
    )


def test_run_that_never_started_costs_only_api() -> None:
    record = make_record(status=RunStatus.KILLED, ended_at=START, usage=UsageTotals(usd=0.125))
    assert wall_hours(record) == 0.0
    assert compute_cost(record, 2.0) == CostTotals(
        api_usd=0.125, total_usd=0.125, gpu_pricing_complete=True
    )


def test_running_run_has_no_wall_time_yet() -> None:
    record = make_record(
        status=RunStatus.RUNNING, started_at=START, executor=ExecutorInfo(gpus=[0])
    )
    assert compute_cost(record, 2.0) == CostTotals(gpu_pricing_complete=True)


def test_clock_skew_never_gives_negative_cost() -> None:
    assert compute_cost(ended(-5, [0, 1], None), 2.0) == CostTotals(gpu_pricing_complete=True)


def test_slurm_run_without_indices_is_billed_for_requested_gpus() -> None:
    record = ended(60, [], None, slurm_job_id="81234", gpus_requested=4)
    assert billed_gpus(record) == 4
    assert compute_cost(record, 1.5) == CostTotals(
        gpu_hours=4.0, gpu_usd=6.0, total_usd=6.0, gpu_pricing_complete=True
    )


def test_slurm_indices_win_over_the_request() -> None:
    record = ended(60, [0, 1], None, slurm_job_id="81234", gpus_requested=4)
    assert billed_gpus(record) == 2


def test_ssh_run_without_gpus_is_not_billed_for_its_request() -> None:
    # gpus_requested without executor.gpus on an SSH host means it never got GPUs.
    assert billed_gpus(ended(60, [], None, gpus_requested=2)) == 0


def test_price_record_fills_cost_of_ended_runs() -> None:
    record = ended(90, [0, 1], 0.375)
    priced = price_record(record, 2.10)
    assert priced.cost == CostTotals(
        gpu_hours=3.0, gpu_usd=6.3, api_usd=0.375, total_usd=6.675, gpu_pricing_complete=True
    )
    assert record.cost is None  # the input is not changed


def test_price_record_reprices_a_cost_made_without_a_rate() -> None:
    record = ended(60, [0], None).model_copy(update={"cost": CostTotals(gpu_hours=1.0)})
    assert price_record(record, 2.5).cost == CostTotals(
        gpu_hours=1.0, gpu_usd=2.5, total_usd=2.5, gpu_pricing_complete=True
    )


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.KILLED, RunStatus.LOST])
def test_price_record_prices_every_terminal_status(status: RunStatus) -> None:
    record = ended(60, [0], None).model_copy(update={"status": status})
    assert price_record(record, 1.0).cost == CostTotals(
        gpu_hours=1.0, gpu_usd=1.0, total_usd=1.0, gpu_pricing_complete=True
    )


@pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.RUNNING])
def test_price_record_leaves_active_runs_alone(status: RunStatus) -> None:
    record = make_record(status=status, started_at=START, executor=ExecutorInfo(gpus=[0]))
    assert price_record(record, 2.0) is record


# --- cost and executor at run finish (hypothex.core.execution) ---------------------------

USAGE_THEN_EXIT = (
    "import sys, hypothex as hx; r = hx.current(); "
    "r.log_usage(tokens_in=100, tokens_out=20, usd=0.25); "
    "r.log_usage(tokens_in=50, tokens_out=5, usd=0.125); "
    "sys.exit(int(sys.argv[1]))"
)


def launch(ctx: Context, repo: Path, code: str, *args: str) -> RunRecord:
    return prepare_run(ctx, RunRequest(repo=repo, command=[sys.executable, "-c", code, *args]))


@pytest.mark.parametrize(
    ("exit_arg", "status"), [("0", RunStatus.FINISHED), ("3", RunStatus.FAILED)]
)
def test_finish_fills_cost_from_usage(
    ctx: Context, toy_repo: Path, exit_arg: str, status: RunStatus
) -> None:
    done = execute_run(ctx, launch(ctx, toy_repo, USAGE_THEN_EXIT, exit_arg).run_id)
    assert done.status == status
    # 0.25 + 0.125 is exact in binary floating point; no GPUs, so no GPU hours.
    assert done.cost == CostTotals(
        gpu_hours=0.0, gpu_usd=0.0, api_usd=0.375, total_usd=0.375, gpu_pricing_complete=True
    )
    assert ctx.store.read_record("toy", done.run_id).cost == done.cost


def test_finish_without_usage_has_zero_cost(ctx: Context, toy_repo: Path) -> None:
    done = execute_run(ctx, launch(ctx, toy_repo, "print(1)").run_id)
    assert done.cost == CostTotals(gpu_pricing_complete=True)


def test_finish_keeps_scheduler_executor_and_bills_its_gpus(ctx: Context, toy_repo: Path) -> None:
    queued = launch(ctx, toy_repo, "import time; time.sleep(0.2)")
    # What the host scheduler records before it starts a queued run.
    ctx.update_run(
        queued.run_id,
        "run.assigned",
        lambda r: r.model_copy(
            update={
                "executor": r.executor.model_copy(
                    update={"host": "gpu1", "gpus": [0, 1], "queue_position": 2}
                ),
                "gpus_requested": 2,
            }
        ),
    )
    done = execute_run(ctx, queued.run_id)
    assert done.status == RunStatus.FINISHED
    assert (done.executor.host, done.executor.gpus) == ("gpu1", [0, 1])
    assert done.executor.queue_position is None and done.executor.child_pid is not None
    assert done.started_at is not None and done.ended_at is not None
    wall = (done.ended_at - done.started_at).total_seconds() / 3600
    assert done.cost is not None and done.cost.gpu_hours == round(wall * 2, 6) > 0
    assert done.cost.gpu_usd == 0.0 and done.cost.total_usd == 0.0


def test_add_costs_sums_fields_and_is_none_without_costs() -> None:
    total = add_costs(
        [
            CostTotals(gpu_hours=1.0, gpu_usd=2.0, total_usd=2.0),
            None,
            CostTotals(gpu_hours=0.5, gpu_usd=1.0, api_usd=0.25, total_usd=1.25),
        ]
    )
    assert total == CostTotals(gpu_hours=1.5, gpu_usd=3.0, api_usd=0.25, total_usd=3.25)
    assert add_costs([]) is None and add_costs([None, None]) is None


def test_today_start_is_local_midnight() -> None:
    start = today_start()
    now = datetime.now().astimezone()
    assert start.tzinfo is not None
    assert (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0)
    assert start.date() == now.date()
    assert start <= now


def test_cost_since_counts_runs_ended_at_or_after_the_moment() -> None:
    since = START
    runs = [
        make_record(cost=CostTotals(total_usd=1.23456), ended_at=since),
        make_record(cost=CostTotals(total_usd=2.0), ended_at=since + timedelta(hours=1)),
        make_record(cost=CostTotals(total_usd=50.0), ended_at=since - timedelta(seconds=1)),
        make_record(cost=CostTotals(total_usd=70.0), ended_at=None),
        make_record(cost=None, ended_at=since + timedelta(hours=2)),
    ]
    assert cost_since(runs, since) == 3.2346
    assert cost_since([], since) == 0.0
