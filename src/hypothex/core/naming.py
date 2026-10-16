"""Run names: derived from the params that differ inside a task, or set by a rename."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from hypothex.core.errors import RunNameError
from hypothex.core.leaderboard import group_id_for, group_label
from hypothex.core.records import RunRecord

NAME_MAX = 80
"""Longest run name a rename accepts (after trimming)."""
VALUE_MAX = 24
"""Longest param value that may appear in a derived name."""
PATH_MIN = 12
"""A value with ``/`` longer than this is a path and never names a run."""
SEPARATOR = " · "
_HEX = re.compile(r"[0-9a-fA-F]{16,}")
_SKIP_KEYS = frozenset({"seed"})
"""Keys that never name a run: the seed is shown in run views, not in names."""
_SWEEP_TAG = "sweep:"
"""Prefix of the sweep membership tags (``sweeps.SWEEP_TAG_PREFIX``), never a name."""


def _nameable(value: Any) -> bool:
    """
    Whether a param value is short and readable enough to appear in a name.

    Parameters
    ----------
    value : Any
        One param value (``None`` when the run lacks the key).

    Returns
    -------
    bool
        False for values longer than ``VALUE_MAX``, hex hashes of 16 or more
        digits, URLs, and paths (a ``/`` in a value longer than ``PATH_MIN``).

    Examples
    --------
    >>> _nameable("3e-4"), _nameable("0123456789abcdef"), _nameable("data/train/v3.jsonl")
    (True, False, False)
    """
    if value is None:
        return True
    text = str(value)
    if len(text) > VALUE_MAX or _HEX.fullmatch(text) or "://" in text:
        return False
    return not ("/" in text and len(text) > PATH_MIN)


def varying_keys(params: Sequence[Mapping[str, Any]]) -> list[str]:
    """
    Return the keys whose value differs between runs, in first-seen order.

    A key missing from some runs differs from a key that is set. A key with any
    value that cannot name a run (``_nameable``: long, a hash, a URL, a path) is
    left out, and so is ``seed``.

    Parameters
    ----------
    params : sequence of mapping
        One mapping of param name to value per run.

    Returns
    -------
    list of str
        The varying keys.

    Examples
    --------
    >>> varying_keys([{"lr": "1e-3", "db": "v3"}, {"lr": "3e-4", "db": "v3"}])
    ['lr']
    >>> varying_keys([{"ckpt": "0123456789abcdef01"}, {"ckpt": "fedcba9876543210ff"}])
    []
    >>> varying_keys([{"lr": "1e-3"}, {}])
    ['lr']
    """
    keys = list(dict.fromkeys(k for p in params for k in p if k not in _SKIP_KEYS))
    out: list[str] = []
    for key in keys:
        values = [p.get(key) for p in params]
        if len({str(v) if v is not None else None for v in values}) < 2:
            continue
        if all(_nameable(v) for v in values):
            out.append(key)
    return out


def run_settings(run: RunRecord) -> dict[str, str]:
    """
    Return what a run's name is made of: its ``params``, then its other ``vars``.

    A key in both keeps the ``params`` value.

    Parameters
    ----------
    run : RunRecord
        Any run.

    Returns
    -------
    dict of str to str
        Params first, in their order, then the template vars not among them.

    Examples
    --------
    >>> run = make_record(params={"lr": "1e-3"}, vars={"beam": "5", "lr": "x"})  # doctest: +SKIP
    >>> run_settings(run)  # doctest: +SKIP
    {'lr': '1e-3', 'beam': '5'}
    """
    return {**run.params, **{k: v for k, v in run.vars.items() if k not in run.params}}


def short_run_id(run_id: str) -> str:
    """
    Return the random tail of a run id (``ids.new_run_id``), or the id itself.

    Parameters
    ----------
    run_id : str
        Run id such as ``20261015-064419-apt-eval-588f929f``.

    Returns
    -------
    str

    Examples
    --------
    >>> short_run_id("20261015-064419-apt-eval-588f929f")
    '588f929f'
    >>> short_run_id("r1")
    'r1'
    """
    tail = run_id.rsplit("-", 1)[-1]
    return tail if tail != run_id and len(tail) == 8 else run_id


def _fallback(run: RunRecord) -> str:
    """
    The name of a run when no param varies: hypothesis clause, first tag, short id.

    ``group_label`` already gives the clause (without a ``Rerun of <id>:``
    prefix), else the first tag; only its last resort, ``group <id>``, is
    replaced by the short run id. Sweep tags never name a run.
    """
    group_id = group_id_for(run)
    tags = [t for t in run.tags if not t.startswith(_SWEEP_TAG)]
    label = group_label(run.hypothesis, tags, group_id)
    return short_run_id(run.run_id) if label == f"group {group_id}" else label


def derive_names(runs: Sequence[RunRecord]) -> dict[str, str]:
    """
    Name every run by the params that differ between the given runs.

    The runs are those of one task. A run's name is ``key value`` for each
    varying key it has, joined with ``" · "`` (``lr 3e-4 · beam 10``); the seed
    is never part of it. A run with no varying key falls back to the first
    clause of its hypothesis (``leaderboard.group_label``), then its first tag,
    then its short run id (``short_run_id``).

    Parameters
    ----------
    runs : sequence of RunRecord
        The runs to name, usually every run of a task, oldest first (the
        order of first-seen keys).

    Returns
    -------
    dict of str to str
        Derived name per run id.

    Examples
    --------
    >>> a = make_record("a", params={"lr": "1e-3", "db": "v3"})  # doctest: +SKIP
    >>> b = make_record("b", params={"lr": "3e-4", "db": "v3"})  # doctest: +SKIP
    >>> derive_names([a, b])  # doctest: +SKIP
    {'a': 'lr 1e-3', 'b': 'lr 3e-4'}
    """
    settings = [run_settings(r) for r in runs]
    keys = varying_keys(settings)
    out: dict[str, str] = {}
    for run, values in zip(runs, settings, strict=True):
        parts = [f"{k} {values[k]}" for k in keys if k in values]
        out[run.run_id] = SEPARATOR.join(parts) if parts else _fallback(run)
    return out


def display_name(run: RunRecord, derived: Mapping[str, str]) -> str:
    """
    Return the name to show for a run: its own ``name``, else its derived name.

    Parameters
    ----------
    run : RunRecord
        The run.
    derived : mapping of str to str
        Derived names per run id (``derive_names``).

    Returns
    -------
    str

    Examples
    --------
    >>> display_name(make_record("a", name="wide beam"), {"a": "beam 10"})  # doctest: +SKIP
    'wide beam'
    """
    return run.name or derived.get(run.run_id) or short_run_id(run.run_id)


def run_view_name(run: RunRecord, derived: Mapping[str, str]) -> str:
    """
    Return a run's name as run views show it: its own ``name``, else derived plus seed.

    Parameters
    ----------
    run : RunRecord
        The run.
    derived : mapping of str to str
        Derived names per run id (``derive_names``).

    Returns
    -------
    str
        ``run.name`` when set; else the derived name followed by ``" · seed N"``
        when the run has a seed (spec 5.1, rule 4).

    Examples
    --------
    >>> run_view_name(make_record("a", seed=2), {"a": "lr 1e-3"})  # doctest: +SKIP
    'lr 1e-3 · seed 2'
    """
    if run.name:
        return run.name
    base = derived.get(run.run_id) or short_run_id(run.run_id)
    return f"{base}{SEPARATOR}seed {run.seed}" if run.seed is not None else base


def group_display_name(runs: Sequence[RunRecord], derived: Mapping[str, str]) -> str:
    """
    Return the name of a seed group.

    The ``name`` of the group's most recently created renamed run, else the
    derived name of its most recently created run.

    Parameters
    ----------
    runs : sequence of RunRecord
        The group's runs (any order); at least one.
    derived : mapping of str to str
        Derived names per run id (``derive_names``).

    Returns
    -------
    str

    Examples
    --------
    >>> runs = [make_record("a"), make_record("b", name="baseline")]  # doctest: +SKIP
    >>> group_display_name(runs, {"a": "lr 1e-3", "b": "lr 1e-3"})  # doctest: +SKIP
    'baseline'
    """
    ordered = sorted(runs, key=lambda r: (r.created_at, r.run_id))
    named = [r for r in ordered if r.name]
    if named:
        return str(named[-1].name)
    latest = ordered[-1]
    return derived.get(latest.run_id) or short_run_id(latest.run_id)


def _group_tag(group_id: str) -> str:
    """
    The part of a group id that tells two groups on one commit apart.

    Examples
    --------
    >>> _group_tag("0123abcd@c1+9f8e7d6c"), _group_tag("0123abcd@c1")
    ('9f8e7d6c', '0123abcd')
    """
    diff = group_id.partition("+")[2]
    return diff or group_id.partition("@")[0]


def disambiguate(
    names: Mapping[str, str], commits: Mapping[str, str | None], fixed: Collection[str]
) -> dict[str, str]:
    """
    Make group names unique by adding the short commit, then a group tag.

    Two seed groups can derive the same name: the same visible params on another
    commit, or with another uncommitted diff. Only names that collide change:
    first ``" · @<commit[:7]>"``, then, if they still collide, ``" · #<tag>"``
    (the diff hash, else the config hash part of the group id). Groups in
    ``fixed`` (renamed by a person or agent) always keep their name.

    Parameters
    ----------
    names : mapping of str to str
        Name per group id.
    commits : mapping of str to str or None
        Git commit per group id.
    fixed : collection of str
        Group ids whose name must not change.

    Returns
    -------
    dict of str to str
        Name per group id, in the order of ``names``.

    Examples
    --------
    >>> disambiguate({"a@1": "x", "b@2": "x"}, {"a@1": "1234567aa", "b@2": "7654321bb"}, ())
    {'a@1': 'x · @1234567', 'b@2': 'x · @7654321'}
    """
    out = dict(names)
    for step in ("commit", "tag"):
        seen: dict[str, list[str]] = {}
        for gid, name in out.items():
            seen.setdefault(name, []).append(gid)
        clashing = [gid for gids in seen.values() if len(gids) > 1 for gid in gids]
        for gid in clashing:
            if gid in fixed:
                continue
            commit = commits.get(gid)
            if step == "commit" and commit:
                out[gid] = f"{out[gid]}{SEPARATOR}@{commit[:7]}"
            elif step == "tag":
                out[gid] = f"{out[gid]}{SEPARATOR}#{_group_tag(gid)}"
    return out


def group_names(
    members: Mapping[str, Sequence[RunRecord]], derived: Mapping[str, str]
) -> dict[str, str]:
    """
    Return a distinct name per seed group: the display name, then ``disambiguate``.

    Each group's name is ``group_display_name``; the commit that tells clashing
    groups apart is that of the group's most recently created run. Groups with
    a renamed run keep their name exactly.

    Parameters
    ----------
    members : mapping of str to sequence of RunRecord
        The runs of each group id (any order); at least one per group.
    derived : mapping of str to str
        Derived names per run id (``derive_names``).

    Returns
    -------
    dict of str to str
        Name per group id, in the order of ``members``.

    Examples
    --------
    >>> group_names({"a@1": [run_a], "b@2": [run_b]}, {"a": "x", "b": "x"})  # doctest: +SKIP
    {'a@1': 'x · @1111111', 'b@2': 'x · @2222222'}
    """
    names = {g: group_display_name(runs, derived) for g, runs in members.items()}
    commits = {
        g: max(runs, key=lambda r: (r.created_at, r.run_id)).git.commit
        for g, runs in members.items()
    }
    fixed = {g for g, runs in members.items() if any(r.name for r in runs)}
    return disambiguate(names, commits, fixed)


def clean_run_name(name: str | None) -> str | None:
    """
    Normalize a requested run name; empty means "no name" (reset).

    Parameters
    ----------
    name : str or None
        The requested name.

    Returns
    -------
    str or None
        The trimmed name, or None for None or a blank name.

    Raises
    ------
    RunNameError
        If the trimmed name is longer than ``NAME_MAX`` (80) characters or
        contains a line break. It is a ``ValueError`` too, so a request body
        that validates with it answers 422.

    Examples
    --------
    >>> clean_run_name("  lr 3e-4, wide beam ")
    'lr 3e-4, wide beam'
    >>> clean_run_name("   ") is None
    True
    """
    if name is None:
        return None
    text = name.strip()
    if not text:
        return None
    if "\n" in text or "\r" in text:
        raise RunNameError("a run name is one line")
    if len(text) > NAME_MAX:
        raise RunNameError(f"a run name has at most {NAME_MAX} characters, not {len(text)}")
    return text
