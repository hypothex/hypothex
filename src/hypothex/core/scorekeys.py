"""Score keys with parts (``reported/<dataset>.<model>.<metric>``) and a task's key pattern."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import NamedTuple

MAX_KEY_PARTS = 3
"""Most parts a task's ``score_keys`` pattern names (``{dataset}.{model}.{metric}``)."""
METRIC_PART = "metric"
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class KeyParts(NamedTuple):
    """
    The parts of one score key such as ``reported/set-1.m-a.top10``.

    ``prefix`` is the metric name before ``/`` (``reported``); ``dataset``,
    ``model`` and ``metric`` are the dotted parts of its key. ``model`` is None
    for a two-part key (``<dataset>.<metric>``).
    """

    prefix: str
    dataset: str
    model: str | None
    metric: str


def parse_key_pattern(pattern: str) -> list[str]:
    """
    Read a task's ``score_keys`` pattern into its part names.

    Parameters
    ----------
    pattern : str
        Two or three ``{name}`` placeholders joined by ``.``; one must be
        ``{metric}``. Names are identifiers and differ.

    Returns
    -------
    list of str
        The part names in key order.

    Raises
    ------
    ValueError
        If the pattern is not two or three dot-joined placeholders, a name is
        repeated, or ``{metric}`` is missing.

    Examples
    --------
    >>> parse_key_pattern("{dataset}.{model}.{metric}")
    ['dataset', 'model', 'metric']
    >>> parse_key_pattern("{benchmark}.{metric}")
    ['benchmark', 'metric']
    """
    names: list[str] = []
    for piece in pattern.split("."):
        found = _PLACEHOLDER.fullmatch(piece)
        if found is None:
            raise ValueError(
                f"score_keys part {piece!r} must be one {{name}} placeholder, "
                'as in "{dataset}.{model}.{metric}"'
            )
        names.append(found.group(1))
    if not 2 <= len(names) <= MAX_KEY_PARTS:
        raise ValueError(f"score_keys has 2 or {MAX_KEY_PARTS} parts, not {len(names)}")
    if len(set(names)) != len(names):
        raise ValueError("score_keys part names must differ")
    if METRIC_PART not in names:
        raise ValueError("score_keys needs a {metric} part")
    return names


def split_score_key(key: str, names: Sequence[str] | None = None) -> KeyParts | None:
    """
    Split a score key (``metric/key``) into dataset, model and metric parts.

    Without ``names`` the key after the first ``/`` is split on ``.``: three or
    more parts give ``dataset`` (all but the last two, dots kept), ``model`` and
    ``metric``; two parts give ``dataset`` and ``metric``. With ``names``
    (``parse_key_pattern``) the key is split from the right into that many
    parts (the first keeps any extra dots). The part named ``metric`` is the
    metric. Of a three-part pattern, a part named ``dataset`` is the dataset and
    a part named ``model`` the model; otherwise the first other part is the
    dataset and the second the model. A two-part pattern has no model.

    Parameters
    ----------
    key : str
        A score key such as ``reported/set-1.m-a.top10``.
    names : sequence of str, optional
        The task's key part names (``TaskSpec.key_parts``).

    Returns
    -------
    KeyParts or None
        None when the key has fewer parts than needed (``acc/value``).

    Examples
    --------
    >>> split_score_key("reported/set-1.m-a.top10")
    KeyParts(prefix='reported', dataset='set-1', model='m-a', metric='top10')
    >>> split_score_key("reported/all.frac")
    KeyParts(prefix='reported', dataset='all', model=None, metric='frac')
    >>> split_score_key("r/m-a.set-1.top10", ["model", "dataset", "metric"])
    KeyParts(prefix='r', dataset='set-1', model='m-a', metric='top10')
    >>> split_score_key("acc/value") is None
    True
    """
    prefix, sep, tail = key.partition("/")
    if not sep:
        prefix, tail = "", key
    if names is None:
        parts = tail.split(".")
        if len(parts) < 2:
            return None
        if len(parts) == 2:
            return KeyParts(prefix, parts[0], None, parts[1])
        return KeyParts(prefix, ".".join(parts[:-2]), parts[-2], parts[-1])
    parts = tail.rsplit(".", len(names) - 1)
    if len(parts) != len(names) or not all(parts):
        return None
    by_name = dict(zip(names, parts, strict=True))
    others = [n for n in names if n != METRIC_PART]
    if len(others) == 1:
        return KeyParts(prefix, by_name[others[0]], None, by_name[METRIC_PART])
    if "dataset" in others:
        dataset = "dataset"
    elif "model" in others:
        dataset = next(n for n in others if n != "model")
    else:
        dataset = others[0]
    model = next(n for n in others if n != dataset)
    return KeyParts(prefix, by_name[dataset], by_name[model], by_name[METRIC_PART])
