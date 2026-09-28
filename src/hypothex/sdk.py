"""SDK used inside a run started by ``hx run`` / ``hx launch``.

Examples
--------
>>> import hypothex as hx
>>> run = hx.current()          # a no-op outside Hypothex, so code runs unchanged
>>> run.log({"loss": 0.41})
>>> run.log_predictions([{"id": "ex-1", "prediction": 1}])
0
>>> run.log_usage(tokens_in=4410, tokens_out=512, usd=0.0131, seconds=4.8, example_id="ex-1")
>>> run.log_trace("ex-1", [{"tool": "check_stock", "args": "CCO", "result": "in stock"}])
>>> run.log_samples("latency_ms", [12.5, 15.0])
>>> run.log_checkpoint("ckpt/step_1000.pt", step=1000, metrics={"val_top1": 0.61})
"""

from __future__ import annotations

import json
import math
import operator
import os
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_text,
    open_jsonl_append,
)
from hypothex.core.store import TraceStep, UsageRow, check_stem_owner, safe_stem


def _why(exc: ValidationError) -> str:
    """
    Describe the first validation error as ``field: message``.

    Parameters
    ----------
    exc : ValidationError
        The pydantic error.

    Returns
    -------
    str
        E.g. ``tokens_in: Input should be greater than or equal to 0``.
    """
    err = exc.errors()[0]
    loc = ".".join(str(part) for part in err["loc"])
    return f"{loc}: {err['msg']}" if loc else err["msg"]


def _finite(value: Any, what: str) -> float:
    """
    Convert ``value`` to a finite float.

    Parameters
    ----------
    value : Any
        Number (or numeric string) to convert.
    what : str
        What the value is, for the error message.

    Returns
    -------
    float
        The value as a float.

    Raises
    ------
    ValueError
        If ``value`` is not a number, or is NaN or infinite.

    Examples
    --------
    >>> _finite("1.5", "x")
    1.5
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number):
        raise ValueError(f"{what} must be a finite number, got {value!r}")
    return number


class Run:
    """
    Handle to the current run's folder.

    Parameters
    ----------
    run_dir : Path
        The run folder (``$HYPOTHEX_RUN_DIR``).
    run_id : str
        Run id.
    project : str
        Project name.
    """

    active = True

    def __init__(self, run_dir: Path, run_id: str, project: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.project = project
        self._steps: dict[str, int] = {}

    def log(self, values: Mapping[str, float], step: int | None = None) -> None:
        """
        Log metric values; each name gets its own auto-incrementing step.

        Parameters
        ----------
        values : mapping of str to float
            E.g. ``{"loss": 0.41}``.
        step : int, optional
            Explicit step for all values.
        """
        now = time.time()
        for name, value in values.items():
            s = step if step is not None else self._steps.get(name, -1) + 1
            self._steps[name] = s
            append_jsonl(
                self.run_dir / "metrics.jsonl",
                {"name": name, "step": s, "value": float(value), "t": now},
            )

    def log_predictions(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """
        Append prediction rows to ``predictions/predictions.jsonl``.

        Each row needs ``id`` and ``prediction``; ``reference`` and ``meta`` are optional.

        Returns
        -------
        int
            Number of rows written.

        Raises
        ------
        ValueError
            If a row lacks ``id`` or ``prediction``.
        """
        path = self.run_dir / "predictions" / "predictions.jsonl"
        count = 0
        with open_jsonl_append(path) as fh:
            for row in rows:
                if "id" not in row or "prediction" not in row:
                    raise ValueError("each prediction row needs 'id' and 'prediction'")
                fh.write((json.dumps(dict(row), default=str) + "\n").encode("utf-8"))
                count += 1
        return count

    def log_artifact(
        self, path: str | os.PathLike[str], kind: str = "file", host: str = "local"
    ) -> None:
        """
        Record a large file by path (it is not copied).

        Parameters
        ----------
        path : path-like
            File location.
        kind : str
            E.g. ``checkpoint``; re-infer uses the last ``checkpoint``.
        host : str
            Where the file lives.
        """
        self._append_artifact(path, kind, host, {})

    def log_checkpoint(
        self,
        path: str | os.PathLike[str],
        step: int,
        metrics: Mapping[str, float] | None = None,
        host: str = "local",
    ) -> None:
        """
        Record a checkpoint by path, with the step it was saved at and its metrics.

        Same as ``log_artifact(path, kind="checkpoint")`` plus ``step`` and ``metrics``,
        which the training views use to mark checkpoints on the curves. Logging the
        same path again (e.g. an overwritten ``last.pt``) keeps only the latest entry
        when the run ends.

        Parameters
        ----------
        path : path-like
            Checkpoint file.
        step : int
            Training step the checkpoint was saved at.
        metrics : mapping of str to float, optional
            E.g. ``{"val_top1": 0.61}``.
        host : str
            Where the file lives.

        Raises
        ------
        TypeError
            If ``step`` is not an integer.
        ValueError
            If a metric value is not a finite number; nothing is written then.

        Examples
        --------
        >>> hx.current().log_checkpoint("step_1000.pt", 1000, {"val_top1": 0.61})  # doctest: +SKIP
        """
        checked_step = operator.index(step)
        values = {
            str(k): _finite(v, f"checkpoint metric {k!r}") for k, v in (metrics or {}).items()
        }
        self._append_artifact(path, "checkpoint", host, {"step": checked_step, "metrics": values})

    def _append_artifact(
        self, path: str | os.PathLike[str], kind: str, host: str, extra: dict[str, Any]
    ) -> None:
        """
        Append one row to ``artifacts.jsonl``.

        Parameters
        ----------
        path : path-like
            File location; resolved to an absolute path.
        kind : str
            Artifact kind.
        host : str
            Where the file lives.
        extra : dict
            Extra fields, e.g. ``step`` and ``metrics`` for checkpoints.
        """
        resolved = Path(path).expanduser().resolve()
        size = resolved.stat().st_size if resolved.is_file() else None
        append_jsonl(
            self.run_dir / "artifacts.jsonl",
            {"kind": kind, "path": str(resolved), "host": host, "size": size, **extra},
        )

    def log_trace(self, example_id: str, steps: Iterable[Mapping[str, Any]]) -> None:
        """
        Write one example's agent trajectory to ``traces/<example_id>.jsonl``.

        The file is replaced, so logging the same example again keeps only the new
        trace. A step is ``{turn, tool, args, result, tokens_in, tokens_out, seconds,
        error}``; every key is optional except that ``turn`` defaults to the step's
        1-based position. A non-empty ``error`` marks the step (and the trace) failed.
        The file name is ``store.safe_stem(example_id)`` (unsafe characters become
        ``_`` plus a hash of the id); the original id is stored in each line. An
        empty ``steps`` still writes the file, as one marker line
        ``{"example_id": <id>}``, so the trace list shows it with 0 turns.

        Parameters
        ----------
        example_id : str
            The example the trajectory belongs to (matches the prediction ``id``).
        steps : iterable of mapping
            The steps in order.

        Raises
        ------
        ValueError
            If ``example_id`` is empty or a step is invalid (for example a negative
            token count, an infinite ``seconds``, or a non-integer ``turn``); nothing
            is written then.
        StoreError
            If the trace file of this stem already holds another example id (an id
            collision, ``store.check_stem_owner``); nothing is written then.

        Examples
        --------
        >>> hx.current().log_trace("ex-1", [
        ...     {"tool": "retro_expand", "args": {"top_k": 8}, "result": "8 precursors",
        ...      "tokens_in": 4410, "tokens_out": 512, "seconds": 4.8},
        ...     {"tool": "check_stock", "args": "CCO", "error": "timeout 8 s"},
        ... ])  # doctest: +SKIP
        """
        path = self.run_dir / "traces" / f"{safe_stem(example_id)}.jsonl"
        lines: list[str] = []
        for position, step in enumerate(steps, start=1):
            try:
                parsed = TraceStep.model_validate({"turn": position, **step})
            except ValidationError as exc:
                raise ValueError(
                    f"trace step {position} of {example_id!r} is invalid: {_why(exc)}"
                ) from None
            row = {"example_id": example_id, **parsed.model_dump()}
            lines.append(json.dumps(row, default=str) + "\n")
        if not lines:
            lines.append(json.dumps({"example_id": example_id}) + "\n")
        check_stem_owner(path, "example_id", example_id)
        atomic_write_text(path, "".join(lines))

    def log_usage(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
        usd: float = 0.0,
        seconds: float = 0.0,
        example_id: str | None = None,
    ) -> None:
        """
        Append one model call's usage to ``usage.jsonl``.

        When the run ends, all rows are summed into the run's ``usage`` totals
        (``calls`` = number of rows).

        Parameters
        ----------
        tokens_in, tokens_out : int
            Input and output tokens.
        usd : float
            Cost in US dollars.
        seconds : float
            Wall time of the call.
        example_id : str, optional
            The example the call was made for.

        Raises
        ------
        ValueError
            If a value is negative, not a number, or not finite (``nan``, ``inf``);
            nothing is written then.

        Examples
        --------
        >>> hx.current().log_usage(tokens_in=4410, tokens_out=512, usd=0.0131)  # doctest: +SKIP
        """
        try:
            row = UsageRow(
                example_id=example_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                usd=usd,
                seconds=seconds,
            )
        except ValidationError as exc:
            raise ValueError(f"invalid usage: {_why(exc)}") from None
        append_jsonl(self.run_dir / "usage.jsonl", row.model_dump(mode="json"))

    def log_samples(self, name: str, values: Iterable[float]) -> None:
        """
        Append raw sample values (e.g. latencies) to ``samples/<name>.jsonl``.

        Each value becomes one ``{"name": name, "value": v}`` line. Percentiles are
        computed from these raw values, so log every sample, not a summary. The file
        name is ``store.safe_stem(name)`` (unsafe characters become ``_`` plus a hash
        of the name); readers use the stored ``name``.

        Parameters
        ----------
        name : str
            Series name, e.g. ``latency_ms``.
        values : iterable of float
            The samples.

        Raises
        ------
        ValueError
            If ``name`` is empty or a value is not a finite number; nothing is
            written then.
        StoreError
            If the sample file of this stem already holds another series name (a
            name collision, ``store.check_stem_owner``); nothing is written then.

        Examples
        --------
        >>> hx.current().log_samples("latency_ms", [12.5, 15.0, 11.2])  # doctest: +SKIP
        """
        path = self.run_dir / "samples" / f"{safe_stem(name)}.jsonl"
        what = f"sample of {name!r}"
        lines = [
            json.dumps({"name": name, "value": _finite(value, what)}) + "\n" for value in values
        ]
        if not lines:
            return
        check_stem_owner(path, "name", name)
        with open_jsonl_append(path) as fh:
            fh.write("".join(lines).encode("utf-8"))

    def note(self, text: str) -> None:
        """Append a note to the run's ``notes.md``."""
        append_note_file(self.run_dir / "notes.md", text, "sdk")


class NoopRun:
    """Stand-in used outside Hypothex: every method does nothing."""

    active = False
    run_dir: Path | None = None
    run_id: str | None = None
    project: str | None = None

    def log(self, values: Mapping[str, float], step: int | None = None) -> None:
        """Do nothing."""

    def log_predictions(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """Do nothing and return 0."""
        return 0

    def log_artifact(
        self, path: str | os.PathLike[str], kind: str = "file", host: str = "local"
    ) -> None:
        """Do nothing."""

    def log_checkpoint(
        self,
        path: str | os.PathLike[str],
        step: int,
        metrics: Mapping[str, float] | None = None,
        host: str = "local",
    ) -> None:
        """Do nothing."""

    def log_trace(self, example_id: str, steps: Iterable[Mapping[str, Any]]) -> None:
        """Do nothing."""

    def log_usage(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
        usd: float = 0.0,
        seconds: float = 0.0,
        example_id: str | None = None,
    ) -> None:
        """Do nothing."""

    def log_samples(self, name: str, values: Iterable[float]) -> None:
        """Do nothing."""

    def note(self, text: str) -> None:
        """Do nothing."""


_current: Run | None = None


def current() -> Run | NoopRun:
    """
    Return the run started by Hypothex, or a ``NoopRun`` outside one.

    The same ``Run`` object is returned on repeated calls, so auto steps continue.
    """
    global _current
    run_dir = os.environ.get("HYPOTHEX_RUN_DIR")
    if not run_dir:
        return NoopRun()
    if _current is None or str(_current.run_dir) != run_dir:
        _current = Run(
            Path(run_dir),
            os.environ.get("HYPOTHEX_RUN_ID", ""),
            os.environ.get("HYPOTHEX_PROJECT", ""),
        )
    return _current


def seed(default: int | None = None) -> int | None:
    """
    Return ``--seed`` passed to ``hx run`` (``$HYPOTHEX_SEED``), else ``default``.

    Parameters
    ----------
    default : int, optional
        Value returned when ``$HYPOTHEX_SEED`` is unset or empty.

    Returns
    -------
    int or None
        The seed.

    Raises
    ------
    ValueError
        If ``$HYPOTHEX_SEED`` is set but is not an integer.

    Examples
    --------
    >>> seed(default=0)  # outside a Hypothex run
    0
    """
    raw = os.environ.get("HYPOTHEX_SEED", "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"HYPOTHEX_SEED must be an integer, got {raw!r}") from None
