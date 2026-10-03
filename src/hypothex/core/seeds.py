"""Seed-invariant run fingerprints and small-sample statistics."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from typing import Any

from pydantic import BaseModel

# Two-sided 95% Student-t critical values by degrees of freedom.
_T_975 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def run_fingerprint(
    *,
    command_template: list[str],
    stage: str | None,
    user_config: dict[str, Any] | None,
    params: dict[str, str],
    vars: dict[str, str],
) -> dict[str, Any]:
    """
    Build the dict whose hash identifies a run's configuration, ignoring the seed.

    Parameters
    ----------
    command_template : list of str
        The unrendered command template.
    stage : str or None
        Named stage that produced the command, if any.
    user_config : dict, optional
        User-supplied configuration values.
    params : dict of str to str
        Rendered template parameters.
    vars : dict of str to str
        Extra template variables.

    Returns
    -------
    dict
        Canonical description of what the run does.
    """
    return {
        "command": list(command_template),
        "stage": stage,
        "config": {k: v for k, v in (user_config or {}).items() if k != "seed"},
        "params": {k: v for k, v in params.items() if k != "seed"},
        "vars": dict(vars),
    }


def config_hash(data: dict[str, Any]) -> str:
    """
    Hash a configuration dict, ignoring a top-level ``seed`` key.

    Key order never matters, at any depth. Keys that ``json`` cannot sort or
    write (mixed ``int`` and ``str`` keys, YAML date keys) are hashed through a
    canonical form instead of raising ``TypeError``.

    Parameters
    ----------
    data : dict
        Configuration data to hash.

    Returns
    -------
    str
        ``sha256:<16 hex>`` digest of the canonicalized data.

    Examples
    --------
    >>> config_hash({"lr": 1, "seed": 1}) == config_hash({"lr": 1, "seed": 2})
    True
    >>> config_hash({"layers": {1: 64, "out": 10}}) == config_hash({"layers": {"out": 10, 1: 64}})
    True
    """
    payload = {k: v for k, v in data.items() if k != "seed"}
    try:
        blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    except TypeError:
        # keys json cannot sort (``{1: a, b: c}``) or write (a YAML date key)
        blob = json.dumps(_canonical(payload), default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_MAP_TAG = "\x00map"


def _key_text(key: Any) -> str:
    """Write a mapping key as ``json.dumps`` would (``1`` -> ``"1"``), else as ``str``."""
    if isinstance(key, str):
        return key
    if key is None or isinstance(key, bool | int | float):
        return json.dumps(key)
    return str(key)


def _canonical(value: Any) -> Any:
    """
    Make every mapping a tagged, key-sorted list of pairs, so any keys sort.

    Only used for configs whose keys ``json.dumps(sort_keys=True)`` rejects, so
    the hash of every config it accepts is unchanged. A mapping becomes
    ``{"\\x00map": [[key, value], ...]}``: objects appear only as that wrapper,
    so two configs that differ give different text.
    """
    if isinstance(value, dict):
        pairs = [[_key_text(k), _canonical(v)] for k, v in value.items()]
        pairs.sort(key=lambda kv: (kv[0], json.dumps(kv[1], default=str)))
        return {_MAP_TAG: pairs}
    if isinstance(value, list | tuple):
        return [_canonical(v) for v in value]
    return value


class Stats(BaseModel):
    """Mean, sample std, count, and 95% t-interval of a seed group."""

    mean: float
    std: float
    n: int
    ci_low: float | None = None
    ci_high: float | None = None


def t_critical(df: int) -> float:
    """
    Return the two-sided 95% t critical value for a given degrees of freedom.

    Parameters
    ----------
    df : int
        Degrees of freedom.

    Returns
    -------
    float
        The two-sided 95% t critical value (1.96 beyond 30 df).
    """
    return _T_975.get(df, 1.96)


def summarize(values: list[float]) -> Stats:
    """
    Summarize one group's values.

    Parameters
    ----------
    values : list of float
        At least one value.

    Returns
    -------
    Stats
        ``ci_low``/``ci_high`` are None when ``n == 1``.
    """
    n = len(values)
    mean = math.fsum(values) / n
    if n == 1:
        return Stats(mean=mean, std=0.0, n=1)
    std = statistics.stdev(values)
    half = t_critical(n - 1) * std / math.sqrt(n)
    return Stats(mean=mean, std=std, n=n, ci_low=mean - half, ci_high=mean + half)


def intervals_overlap(a: Stats, b: Stats) -> bool | None:
    """
    Return whether two 95% intervals overlap.

    Parameters
    ----------
    a, b : Stats
        The two groups' statistics to compare.

    Returns
    -------
    bool or None
        Whether the intervals overlap, or ``None`` if either has ``n < 2``.
    """
    if a.ci_low is None or a.ci_high is None or b.ci_low is None or b.ci_high is None:
        return None
    return a.ci_low <= b.ci_high and b.ci_low <= a.ci_high
