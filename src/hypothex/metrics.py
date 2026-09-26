"""Public contract for metric functions.

A metric function lives in project code and has this shape::

    from hypothex import Example, MetricResult

    def accuracy(examples: list[Example], **params) -> MetricResult | float | dict[str, float]:
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real
from typing import Any, cast


@dataclass(frozen=True)
class Example:
    """
    One prediction joined with its reference.

    Parameters
    ----------
    id : str
        Example id (from the predictions file).
    prediction : Any
        Model output.
    reference : Any
        Gold answer (inline in the predictions row, or joined from the dataset).
    meta : dict
        Extra fields from the predictions row.
    """

    id: str
    prediction: Any
    reference: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricResult:
    """
    What a metric function returns.

    Parameters
    ----------
    values : dict of str to float
        One or more values, e.g. ``{"k=1": 0.61, "k=5": 0.83}``. Use ``"value"``
        for single-valued metrics.
    per_example : dict of str to dict
        Optional per-example details keyed by example id, e.g.
        ``{"ex-3": {"correct": False}}``. Shown in the example browser.

    Examples
    --------
    >>> MetricResult(values={"value": 0.75}).values["value"]
    0.75
    """

    values: dict[str, float]
    per_example: dict[str, dict[str, Any]] = field(default_factory=dict)


def _is_number(x: object) -> bool:
    return isinstance(x, Real) and not isinstance(x, bool)


def normalize_result(raw: object) -> MetricResult:
    """
    Convert a metric function's return value into a validated ``MetricResult``.

    Parameters
    ----------
    raw : MetricResult, float, or dict of str to float

    Returns
    -------
    MetricResult
        A result whose ``values`` is a non-empty dict of str to ``float``.

    Raises
    ------
    TypeError
        For any other type, or a ``MetricResult`` whose ``values`` is not a
        non-empty dict of numbers.

    Examples
    --------
    >>> normalize_result(0.5).values
    {'value': 0.5}
    >>> normalize_result(MetricResult(values={"k=1": 1})).values
    {'k=1': 1.0}
    """
    if isinstance(raw, MetricResult):
        values = raw.values
        if not (
            isinstance(values, dict) and values and all(_is_number(v) for v in values.values())
        ):
            raise TypeError(
                "MetricResult.values must be a non-empty dict of str to number; got "
                f"{values!r:.200}"
            )
        return MetricResult(
            values={str(k): float(v) for k, v in values.items()}, per_example=raw.per_example
        )
    if _is_number(raw):
        return MetricResult(values={"value": float(cast(float, raw))})
    if isinstance(raw, dict) and raw and all(_is_number(v) for v in raw.values()):
        return MetricResult(values={str(k): float(v) for k, v in raw.items()})
    raise TypeError(f"metric returned {type(raw).__name__}; expected MetricResult, number, or dict")
