"""What a run cost: GPU hours priced at the host's rate, plus API spend."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from hypothex.core.records import TERMINAL_STATUSES, CostTotals, RunRecord

COST_DECIMALS = 6


def billed_gpus(record: RunRecord) -> int:
    """
    Return how many GPUs a run is billed for.

    The GPUs the run held (``executor.gpus``). A SLURM run whose node did not
    report indices is billed for what it asked for (``gpus_requested``),
    because SLURM reserved that many.

    Parameters
    ----------
    record : RunRecord
        The run.

    Returns
    -------
    int
        Number of GPUs; 0 for CPU runs.

    Examples
    --------
    >>> from hypothex.core.records import ExecutorInfo
    >>> billed_gpus(RunRecord.model_construct(executor=ExecutorInfo(gpus=[0, 2])))
    2
    >>> slurm = ExecutorInfo(slurm_job_id="81234")
    >>> billed_gpus(RunRecord.model_construct(executor=slurm, gpus_requested=4))
    4
    """
    if record.executor.gpus:
        return len(record.executor.gpus)
    if record.executor.slurm_job_id is not None:
        return record.gpus_requested
    return 0


def wall_hours(record: RunRecord) -> float:
    """
    Return a run's wall time in hours.

    Parameters
    ----------
    record : RunRecord
        The run.

    Returns
    -------
    float
        ``ended_at - started_at`` in hours; 0 when the run never started or has
        not ended, and 0 (not negative) when clocks put the end before the start.
    """
    if record.started_at is None or record.ended_at is None:
        return 0.0
    return max((record.ended_at - record.started_at).total_seconds(), 0.0) / 3600.0


def compute_cost(record: RunRecord, usd_per_gpu_hour: float | None) -> CostTotals:
    """
    Compute what a run cost.

    ``gpu_hours = wall × GPUs`` (``wall_hours`` × ``billed_gpus``);
    ``gpu_usd = gpu_hours × usd_per_gpu_hour`` (0 when the host has no rate);
    ``api_usd = usage.usd``; ``total_usd = gpu_usd + api_usd``. Each value is
    rounded to 6 decimals after the sums, so float noise never shows up in
    ``run.yaml``.

    Parameters
    ----------
    record : RunRecord
        The run, normally ended (``started_at`` and ``ended_at`` set).
    usd_per_gpu_hour : float or None
        The host's price per GPU hour from ``environments.yaml``; None if unknown.

    Returns
    -------
    CostTotals
        The run's cost.

    Examples
    --------
    >>> from datetime import UTC, datetime, timedelta
    >>> from hypothex.core.records import ExecutorInfo, UsageTotals
    >>> start = datetime(2026, 10, 3, 10, tzinfo=UTC)
    >>> rec = RunRecord.model_construct(
    ...     started_at=start,
    ...     ended_at=start + timedelta(minutes=90),
    ...     executor=ExecutorInfo(gpus=[0, 1]),
    ...     usage=UsageTotals(usd=0.375),
    ...     gpus_requested=2,
    ... )
    >>> compute_cost(rec, 2.10)
    CostTotals(gpu_hours=3.0, gpu_usd=6.3, api_usd=0.375, total_usd=6.675)
    """
    gpu_hours = wall_hours(record) * billed_gpus(record)
    gpu_usd = gpu_hours * (usd_per_gpu_hour or 0.0)
    api_usd = record.usage.usd if record.usage is not None else 0.0
    return CostTotals(
        gpu_hours=round(gpu_hours, COST_DECIMALS),
        gpu_usd=round(gpu_usd, COST_DECIMALS),
        api_usd=round(api_usd, COST_DECIMALS),
        total_usd=round(gpu_usd + api_usd, COST_DECIMALS),
    )


def price_record(record: RunRecord, usd_per_gpu_hour: float | None) -> RunRecord:
    """
    Return the record with ``cost`` computed at a given rate, once it has ended.

    Env servers do not know their price (it lives in the hub's
    ``environments.yaml``), so they fill ``cost`` at finish with no rate. The
    hub calls this on each mirrored record with the host's
    ``usd_per_gpu_hour``; it also prices ended runs that have no cost yet
    (``lost``, killed before start). Active runs are returned unchanged.

    Parameters
    ----------
    record : RunRecord
        A run record.
    usd_per_gpu_hour : float or None
        The host's price per GPU hour; None if unknown.

    Returns
    -------
    RunRecord
        A copy with ``cost`` set when the run has ended, else ``record`` itself.
    """
    if record.status not in TERMINAL_STATUSES:
        return record
    return record.model_copy(update={"cost": compute_cost(record, usd_per_gpu_hour)})


def add_costs(costs: Iterable[CostTotals | None]) -> CostTotals | None:
    """
    Sum cost totals field by field (a seed group, a day, a sweep).

    Parameters
    ----------
    costs : iterable of CostTotals or None
        Costs to add; None entries (runs without a cost yet) are skipped.

    Returns
    -------
    CostTotals or None
        The sum, each value rounded to 6 decimals; None when no cost was given.

    Examples
    --------
    >>> add_costs([CostTotals(gpu_usd=1.0, total_usd=1.0), None, CostTotals(api_usd=0.5,
    ...     total_usd=0.5)]).total_usd
    1.5
    >>> add_costs([None]) is None
    True
    """
    present = [c for c in costs if c is not None]
    if not present:
        return None
    return CostTotals(
        gpu_hours=round(sum(c.gpu_hours for c in present), 6),
        gpu_usd=round(sum(c.gpu_usd for c in present), 6),
        api_usd=round(sum(c.api_usd for c in present), 6),
        total_usd=round(sum(c.total_usd for c in present), 6),
    )


def today_start() -> datetime:
    """
    Return local midnight today, as an aware datetime.

    "Today's cost" counts runs that ended at or after this moment. Host rows and
    the Overview both use it, so their ``cost_today_usd`` values agree.

    Returns
    -------
    datetime
        Today at 00:00 in the machine's local time zone.

    Examples
    --------
    >>> start = today_start()
    >>> (start.hour, start.minute, start.second, start.microsecond)
    (0, 0, 0, 0)
    >>> start.tzinfo is not None
    True
    """
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def cost_since(runs: Iterable[RunRecord], since: datetime) -> float:
    """
    Sum ``cost.total_usd`` of the runs that ended at or after a moment.

    Runs with no cost or no ``ended_at`` are skipped. A run counts on the day it
    ended, however long ago it started.

    Parameters
    ----------
    runs : iterable of RunRecord
        Runs to sum.
    since : datetime
        Aware start of the period (normally ``today_start()``).

    Returns
    -------
    float
        Total USD, rounded to 4 decimals; 0.0 when no run matches.

    Examples
    --------
    >>> from datetime import UTC, datetime
    >>> since = datetime(2026, 10, 3, tzinfo=UTC)
    >>> runs = [
    ...     RunRecord.model_construct(cost=CostTotals(total_usd=1.25),
    ...         ended_at=datetime(2026, 10, 3, 9, tzinfo=UTC)),
    ...     RunRecord.model_construct(cost=CostTotals(total_usd=9.0),
    ...         ended_at=datetime(2026, 10, 2, 23, tzinfo=UTC)),
    ...     RunRecord.model_construct(cost=None, ended_at=datetime(2026, 10, 3, tzinfo=UTC)),
    ... ]
    >>> cost_since(runs, since)
    1.25
    """
    total = sum(
        r.cost.total_usd
        for r in runs
        if r.cost is not None and r.ended_at is not None and r.ended_at >= since
    )
    return round(total, 4)
