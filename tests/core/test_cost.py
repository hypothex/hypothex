from datetime import UTC, datetime, timedelta

import pytest

from hypothex.core.cost import billed_gpus, compute_cost, price_record, wall_hours
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
            CostTotals(gpu_hours=3.0, gpu_usd=6.3, api_usd=0.375, total_usd=6.675),
        ),
        (
            20,
            [3],
            2.1,
            0.375,
            CostTotals(gpu_hours=0.333333, gpu_usd=0.7, api_usd=0.375, total_usd=1.075),
        ),
        (
            45,
            [0, 1, 2, 3],
            None,
            0.5,
            CostTotals(gpu_hours=3.0, gpu_usd=0.0, api_usd=0.5, total_usd=0.5),
        ),
        (
            150,
            [4, 5],
            1.25,
            None,
            CostTotals(gpu_hours=5.0, gpu_usd=6.25, api_usd=0.0, total_usd=6.25),
        ),
        (30, [], 3.0, None, CostTotals()),
    ],
)
def test_compute_cost(
    minutes: float, gpus: list[int], rate: float | None, usd: float | None, expected: CostTotals
) -> None:
    assert compute_cost(ended(minutes, gpus, usd), rate) == expected


def test_zero_rate_is_free_gpu_time() -> None:
    cost = compute_cost(ended(60, [0], 0.25), 0.0)
    assert cost == CostTotals(gpu_hours=1.0, gpu_usd=0.0, api_usd=0.25, total_usd=0.25)


def test_run_that_never_started_costs_only_api() -> None:
    record = make_record(status=RunStatus.KILLED, ended_at=START, usage=UsageTotals(usd=0.125))
    assert wall_hours(record) == 0.0
    assert compute_cost(record, 2.0) == CostTotals(api_usd=0.125, total_usd=0.125)


def test_running_run_has_no_wall_time_yet() -> None:
    record = make_record(
        status=RunStatus.RUNNING, started_at=START, executor=ExecutorInfo(gpus=[0])
    )
    assert compute_cost(record, 2.0) == CostTotals()


def test_clock_skew_never_gives_negative_cost() -> None:
    assert compute_cost(ended(-5, [0, 1], None), 2.0) == CostTotals()


def test_slurm_run_without_indices_is_billed_for_requested_gpus() -> None:
    record = ended(60, [], None, slurm_job_id="81234", gpus_requested=4)
    assert billed_gpus(record) == 4
    assert compute_cost(record, 1.5) == CostTotals(gpu_hours=4.0, gpu_usd=6.0, total_usd=6.0)


def test_slurm_indices_win_over_the_request() -> None:
    record = ended(60, [0, 1], None, slurm_job_id="81234", gpus_requested=4)
    assert billed_gpus(record) == 2


def test_ssh_run_without_gpus_is_not_billed_for_its_request() -> None:
    # gpus_requested without executor.gpus on an SSH host means it never got GPUs.
    assert billed_gpus(ended(60, [], None, gpus_requested=2)) == 0


def test_price_record_fills_cost_of_ended_runs() -> None:
    record = ended(90, [0, 1], 0.375)
    priced = price_record(record, 2.10)
    assert priced.cost == CostTotals(gpu_hours=3.0, gpu_usd=6.3, api_usd=0.375, total_usd=6.675)
    assert record.cost is None  # the input is not changed


def test_price_record_reprices_a_cost_made_without_a_rate() -> None:
    record = ended(60, [0], None).model_copy(update={"cost": CostTotals(gpu_hours=1.0)})
    assert price_record(record, 2.5).cost == CostTotals(gpu_hours=1.0, gpu_usd=2.5, total_usd=2.5)


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.KILLED, RunStatus.LOST])
def test_price_record_prices_every_terminal_status(status: RunStatus) -> None:
    record = ended(60, [0], None).model_copy(update={"status": status})
    assert price_record(record, 1.0).cost == CostTotals(gpu_hours=1.0, gpu_usd=1.0, total_usd=1.0)


@pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.RUNNING])
def test_price_record_leaves_active_runs_alone(status: RunStatus) -> None:
    record = make_record(status=status, started_at=START, executor=ExecutorInfo(gpus=[0]))
    assert price_record(record, 2.0) is record
