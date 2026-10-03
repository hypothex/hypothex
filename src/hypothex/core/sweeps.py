"""Sweeps: a grid of params (plus seeded random samples) times seeds, launched as one group."""

from __future__ import annotations

import hashlib
import itertools
import logging
import math
import re
import sys
from datetime import datetime
from random import Random

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hypothex.core.config import BUILTIN_TEMPLATE_VARS, NAME_PATTERN
from hypothex.core.errors import HypothexError

log = logging.getLogger(__name__)

SWEEP_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
PARAM_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_.]*$"
SWEEP_TAG_PREFIX = "sweep:"
SWEEP_OWNER_CHARS = 8
"""A sweep tag names its owner by the first 8 hex digits of its environment id."""
SAMPLE_DIGITS = 4


class SweepError(HypothexError):
    """A sweep request is invalid: bad grid, seeds, size, or command template."""


class SweepParam(BaseModel):
    """
    One swept parameter: a list of grid ``values`` or a ``low``/``high`` range.

    Range params are sampled ``SweepSpec.random`` times (log-uniform when ``log``).

    Examples
    --------
    >>> SweepParam(name="lr", values=["1e-4", "3e-4"]).is_range
    False
    >>> SweepParam(name="lr", low=1e-5, high=1e-2, log=True).is_range
    True
    """

    model_config = ConfigDict(coerce_numbers_to_str=True, extra="forbid")

    name: str = Field(pattern=PARAM_NAME_PATTERN)
    values: list[str] | None = None
    low: float | None = Field(None, allow_inf_nan=False)
    high: float | None = Field(None, allow_inf_nan=False)
    log: bool = False

    @model_validator(mode="after")
    def _check(self) -> SweepParam:
        """Require exactly one of ``values`` or ``low``/``high``, each well formed."""
        if self.name in BUILTIN_TEMPLATE_VARS:
            raise ValueError(f"param name {self.name!r} is reserved")
        ranged = self.low is not None or self.high is not None
        if self.values is not None:
            if ranged:
                raise ValueError(f"param {self.name!r}: give values or low/high, not both")
            if not self.values or any(not v for v in self.values):
                raise ValueError(f"param {self.name!r}: values must be non-empty strings")
            if len(set(self.values)) != len(self.values):
                raise ValueError(f"param {self.name!r}: duplicate values")
            if self.log:
                raise ValueError(f"param {self.name!r}: log applies to low/high only")
            return self
        if self.low is None or self.high is None:
            raise ValueError(f"param {self.name!r}: give values, or both low and high")
        if not self.low < self.high:
            raise ValueError(f"param {self.name!r}: low must be below high")
        if self.log and self.low <= 0:
            raise ValueError(f"param {self.name!r}: log scale needs low > 0")
        return self

    @property
    def is_range(self) -> bool:
        """True for a ``low``/``high`` param, False for a grid param."""
        return self.values is None


class SweepSpec(BaseModel, extra="forbid"):
    """
    A sweep's definition, as stored in ``<store>/<project>/sweeps/<id>.yaml``.

    The file never lists runs: a sweep's runs are the runs tagged
    ``sweep:<owner8>:<id>`` (``sweep_tag``, ``sweep_runs``). ``seeds`` lists
    every seed the sweep asks for; ``extend_sweep`` adds to it before it
    launches.
    """

    id: str = Field(pattern=SWEEP_ID_PATTERN)
    project: str = Field(pattern=NAME_PATTERN)
    task: str | None
    host: str | None
    grid: list[SweepParam]
    random: int | None = Field(None, ge=1)
    seeds: list[int] = Field(min_length=1)
    command_template: list[str] = Field(min_length=1)
    created_by: str
    created_at: datetime

    @model_validator(mode="after")
    def _check(self) -> SweepSpec:
        """Reject duplicate param names or seeds, and ranges without ``random``."""
        names = [p.name for p in self.grid]
        dups = sorted({n for n in names if names.count(n) > 1})
        if dups:
            raise ValueError(f"duplicate params: {', '.join(dups)}")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("duplicate seeds")
        if self.random is None and any(p.is_range for p in self.grid):
            raise ValueError("low/high params need random=N samples")
        return self


def sweep_tag(owner: str, sweep_id: str) -> str:
    """
    Return the tag every run of a sweep carries: ``sweep:<owner8>:<id>``.

    The owner is the environment that holds the sweep's definition (the hub,
    for sweeps made through it). Sweep ids are short and per hub, and one host
    can serve two hubs, so the tag names the owner: each hub's membership
    query (an exact tag match) sees only its own runs.

    Parameters
    ----------
    owner : str
        Environment id of the owner; its first ``SWEEP_OWNER_CHARS`` characters
        are used.
    sweep_id : str
        Sweep id.

    Returns
    -------
    str
        ``sweep:<owner8>:<id>``.

    Examples
    --------
    >>> sweep_tag("0a1b2c3d4e5f60718293a4b5c6d7e8f9", "s-7f3a")
    'sweep:0a1b2c3d:s-7f3a'
    """
    return f"{SWEEP_TAG_PREFIX}{owner[:SWEEP_OWNER_CHARS]}:{sweep_id}"


def parse_sweep_tag(tag: str) -> tuple[str, str] | None:
    """
    Split a sweep tag into its owner and sweep id.

    Parameters
    ----------
    tag : str
        Any run tag.

    Returns
    -------
    tuple of (str, str) or None
        ``(owner8, sweep_id)``, or None when ``tag`` is not a sweep tag.

    Examples
    --------
    >>> parse_sweep_tag("sweep:0a1b2c3d:s-7f3a")
    ('0a1b2c3d', 's-7f3a')
    >>> parse_sweep_tag("best") is None
    True
    """
    if not tag.startswith(SWEEP_TAG_PREFIX):
        return None
    owner, sep, sweep_id = tag.removeprefix(SWEEP_TAG_PREFIX).partition(":")
    if not sep or not owner or re.fullmatch(SWEEP_ID_PATTERN, sweep_id) is None:
        return None
    return owner, sweep_id


# expansion ---------------------------------------------------------------------------
def _draw(param: SweepParam, rng: Random) -> str:
    """Sample one value of a range param as a short string inside ``[low, high]``."""
    assert param.low is not None and param.high is not None
    if param.log:
        x = math.exp(rng.uniform(math.log(param.low), math.log(param.high)))
    else:
        x = rng.uniform(param.low, param.high)
    text = format(x, f".{SAMPLE_DIGITS}g")
    return text if param.low <= float(text) <= param.high else repr(x)


def _sample_indices(rng: Random, total: int, k: int) -> list[int]:
    """Pick ``k`` distinct indices in ``range(total)``, sorted, without listing the range."""
    if total <= sys.maxsize:
        return sorted(rng.sample(range(total), k))  # range is lazy; same draws as before
    picked: set[int] = set()
    while len(picked) < k:  # k <= MAX_SWEEP_RUNS and total is huge: few repeats
        picked.add(rng.randrange(total))
    return sorted(picked)


def _combo_at(params: list[SweepParam], index: int) -> dict[str, str]:
    """Decode a flat index of the grid product (last param fastest, like itertools.product)."""
    values: dict[str, str] = {}
    for param in reversed(params):
        options = list(param.values or ())
        index, pick = divmod(index, len(options))
        values[param.name] = options[pick]
    return {p.name: values[p.name] for p in params}


def expand(spec: SweepSpec, rng_seed: int = 0) -> list[dict[str, str]]:
    """
    List the sweep's param combinations (seeds are applied separately).

    Grid params form a product in the order given. With range params, ``random``
    samples are drawn once and crossed with every grid combination, so each grid
    cell sees the same samples. Without range params, ``random=N`` keeps N grid
    combinations chosen at random (all of them when N is at least the grid size).

    Parameters
    ----------
    spec : SweepSpec
        The sweep.
    rng_seed : int
        Seed of the random draws; the same seed gives the same list.

    Returns
    -------
    list of dict of str to str
        One dict per combination, keys in ``spec.grid`` order, duplicates removed.
        A sweep with no params gives ``[{}]``.

    Examples
    --------
    >>> spec = SweepSpec(id="s-1", project="toy", task=None, host=None,
    ...     grid=[SweepParam(name="lr", values=["1e-4", "3e-4"]),
    ...           SweepParam(name="beam", values=["1", "5"])],
    ...     seeds=[1], command_template=["train"], created_by="human",
    ...     created_at="2026-10-03T00:00:00Z")
    >>> expand(spec)[:2]
    [{'lr': '1e-4', 'beam': '1'}, {'lr': '1e-4', 'beam': '5'}]
    """
    fixed = [p for p in spec.grid if not p.is_range]
    ranged = [p for p in spec.grid if p.is_range]
    total = math.prod(len(p.values or ()) for p in fixed)
    rng = Random(rng_seed)
    if not ranged and spec.random is not None and spec.random < total:
        # pick flat indices and decode them: the full product may be astronomically big
        combos = [_combo_at(fixed, i) for i in _sample_indices(rng, total, spec.random)]
    else:  # bounded: launch refuses more than MAX_SWEEP_RUNS runs (grid x samples x seeds)
        combos = [
            dict(zip([p.name for p in fixed], values, strict=True))
            for values in itertools.product(*[list(p.values or ()) for p in fixed])
        ]
        if ranged:
            samples = [{p.name: _draw(p, rng) for p in ranged} for _ in range(spec.random or 0)]
            combos = [{**c, **s} for c in combos for s in samples]
    names = [p.name for p in spec.grid]
    unique = dict.fromkeys(tuple(c[n] for n in names) for c in combos)
    return [dict(zip(names, key, strict=True)) for key in unique]


def _rng_seed(sweep_id: str) -> int:
    """Derive a stable random seed from a sweep id."""
    return int.from_bytes(hashlib.sha256(sweep_id.encode("utf-8")).digest()[:8], "big")


def sweep_combos(spec: SweepSpec) -> list[dict[str, str]]:
    """
    Return the sweep's combinations with its own stable random seed.

    Launch, extend, and summary all call this, so a random sweep keeps the same
    samples for its whole life.

    Parameters
    ----------
    spec : SweepSpec
        The sweep.

    Returns
    -------
    list of dict of str to str
        ``expand(spec, rng_seed=<hash of spec.id>)``.
    """
    return expand(spec, rng_seed=_rng_seed(spec.id))


def planned_runs(spec: SweepSpec) -> int:
    """
    Return an upper bound on the sweep's run count without expanding it.

    Parameters
    ----------
    spec : SweepSpec
        The sweep.

    Returns
    -------
    int
        Combinations times seeds (before duplicate samples are removed).

    Examples
    --------
    >>> spec = SweepSpec(id="s-1", project="toy", task=None, host=None,
    ...     grid=[SweepParam(name="lr", values=["1", "2", "3"])],
    ...     seeds=[1, 2], command_template=["train"], created_by="human",
    ...     created_at="2026-10-03T00:00:00Z")
    >>> planned_runs(spec)
    6
    """
    grid = math.prod(len(p.values or ()) for p in spec.grid if not p.is_range)
    if any(p.is_range for p in spec.grid):
        combos = grid * (spec.random or 0)
    elif spec.random is not None:
        combos = min(spec.random, grid)
    else:
        combos = grid
    return combos * len(spec.seeds)
