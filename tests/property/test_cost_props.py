"""Property tests for ``hypothex.core.cost``: GPU hours x rate + usage.usd."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hypothex.core.cost import (
    COST_DECIMALS,
    add_costs,
    billed_gpus,
    compute_cost,
    cost_since,
    price_record,
    wall_hours,
)
from hypothex.core.records import (
    TERMINAL_STATUSES,
    CostTotals,
    ExecutorInfo,
    RunRecord,
    RunStatus,
    UsageTotals,
)

FAST = settings(max_examples=150, deadline=None)
T0 = datetime(2026, 10, 1, tzinfo=UTC)
ROUND = 10**-COST_DECIMALS
rates = st.one_of(st.none(), st.floats(0, 1e3, allow_nan=False))
usd = st.floats(0, 1e4, allow_nan=False)


@st.composite
def records_with_facts(draw: st.DrawFn) -> tuple[RunRecord, float, int]:
    """A run plus its wall hours and billed GPUs, worked out from the raw draws."""
    started = draw(st.one_of(st.none(), st.integers(-10_000, 10_000)))
    ended = draw(st.one_of(st.none(), st.integers(-10_000, 1_000_000)))
    slurm = draw(st.booleans())
    gpus = draw(st.lists(st.integers(0, 15), unique=True, max_size=8))
    requested = draw(st.integers(0, 8))
    record = RunRecord.model_construct(
        started_at=None if started is None else T0 + timedelta(seconds=started),
        ended_at=None if ended is None else T0 + timedelta(seconds=ended),
        executor=ExecutorInfo(gpus=gpus, slurm_job_id="7" if slurm else None),
        gpus_requested=requested,
        usage=draw(st.one_of(st.none(), st.builds(UsageTotals, usd=usd))),
        status=draw(st.sampled_from(list(RunStatus))),
    )
    # the spec, from the integers drawn above: seconds of run time (never
    # negative, 0 if a timestamp is missing); GPUs held, else SLURM's request
    seconds = 0 if started is None or ended is None else max(ended - started, 0)
    n_gpus = len(gpus) if gpus else (requested if slurm else 0)
    return record, seconds / 3600, n_gpus


def records() -> st.SearchStrategy[RunRecord]:
    return records_with_facts().map(lambda t: t[0])


@FAST
@given(records_with_facts(), rates)
def test_cost_is_gpu_hours_times_rate_plus_api(
    facts: tuple[RunRecord, float, int], rate: float | None
) -> None:
    record, wall, n_gpus = facts
    cost = compute_cost(record, rate)
    hours = wall * n_gpus
    api = record.usage.usd if record.usage is not None else 0.0
    assert min(cost.gpu_hours, cost.gpu_usd, cost.api_usd, cost.total_usd) >= 0.0
    assert cost.gpu_hours == pytest.approx(hours, abs=ROUND)
    assert cost.gpu_usd == pytest.approx(hours * (rate or 0.0), abs=ROUND)
    assert cost.api_usd == pytest.approx(api, abs=ROUND)
    assert cost.total_usd == pytest.approx(cost.gpu_usd + cost.api_usd, abs=2 * ROUND)
    if rate is None or rate == 0.0:
        assert cost.gpu_usd == 0.0


@FAST
@given(records(), st.floats(0, 1e3), st.floats(0, 1e3))
def test_gpu_cost_is_linear_in_the_rate(record: RunRecord, r1: float, r2: float) -> None:
    a, b, ab = compute_cost(record, r1), compute_cost(record, r2), compute_cost(record, r1 + r2)
    assert ab.gpu_usd == pytest.approx(a.gpu_usd + b.gpu_usd, rel=1e-9, abs=3 * ROUND)
    assert ab.gpu_hours == a.gpu_hours == b.gpu_hours
    assert ab.api_usd == a.api_usd


@FAST
@given(records_with_facts())
def test_wall_and_gpus_are_never_negative(facts: tuple[RunRecord, float, int]) -> None:
    record, wall, n_gpus = facts
    assert wall_hours(record) == pytest.approx(wall, rel=1e-12)
    assert billed_gpus(record) == n_gpus
    assert wall_hours(record) >= 0.0
    assert billed_gpus(record) >= 0
    if record.executor.gpus:
        assert billed_gpus(record) == len(record.executor.gpus)
    if record.started_at is None or record.ended_at is None:
        assert wall_hours(record) == 0.0


@FAST
@given(records(), rates)
def test_price_record_prices_only_ended_runs(record: RunRecord, rate: float | None) -> None:
    priced = price_record(record, rate)
    if record.status in TERMINAL_STATUSES:
        assert priced.cost == compute_cost(record, rate)
    else:
        assert priced is record


costs = st.builds(
    lambda h, g, a: CostTotals(gpu_hours=h, gpu_usd=g, api_usd=a, total_usd=round(g + a, 6)),
    st.floats(0, 1e4),
    st.floats(0, 1e4),
    st.floats(0, 1e4),
)


@FAST
@given(st.lists(st.one_of(st.none(), costs), max_size=10))
def test_add_costs_sums_field_by_field(items: list[CostTotals | None]) -> None:
    total = add_costs(items)
    present = [c for c in items if c is not None]
    if not present:
        assert total is None
        return
    assert total is not None
    for field in ("gpu_hours", "gpu_usd", "api_usd", "total_usd"):
        value = getattr(total, field)
        assert value >= 0.0
        assert value == pytest.approx(sum(getattr(c, field) for c in present), abs=ROUND)
    backwards = add_costs(list(reversed(items)))
    assert backwards is not None
    for field in ("gpu_hours", "gpu_usd", "api_usd", "total_usd"):
        assert getattr(backwards, field) == pytest.approx(getattr(total, field), abs=2 * ROUND)


@FAST
@given(st.lists(st.tuples(st.one_of(st.none(), costs), st.integers(-48, 48)), max_size=10))
def test_cost_since_counts_runs_that_ended_since(
    items: list[tuple[CostTotals | None, int]],
) -> None:
    since = T0
    runs = [RunRecord.model_construct(cost=c, ended_at=T0 + timedelta(hours=h)) for c, h in items]
    want = sum(c.total_usd for c, h in items if c is not None and h >= 0)
    got = cost_since(runs, since)
    assert got >= 0.0
    assert got == pytest.approx(want, abs=1e-4)
