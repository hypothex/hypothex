"""SDK used inside a run started by ``hx run`` / ``hx launch``.

Examples
--------
>>> import hypothex as hx
>>> run = hx.current()          # a no-op outside Hypothex, so code runs unchanged
>>> run.log({"loss": 0.41})
>>> run.log_predictions([{"id": "ex-1", "prediction": 1}])
0
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hypothex.core.fsutil import append_jsonl, append_note_file


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
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                if "id" not in row or "prediction" not in row:
                    raise ValueError("each prediction row needs 'id' and 'prediction'")
                fh.write(json.dumps(dict(row), default=str) + "\n")
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
        resolved = Path(path).expanduser().resolve()
        size = resolved.stat().st_size if resolved.is_file() else None
        append_jsonl(
            self.run_dir / "artifacts.jsonl",
            {"kind": kind, "path": str(resolved), "host": host, "size": size},
        )

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
    """Return ``--seed`` passed to ``hx run`` (``$HYPOTHEX_SEED``), else ``default``."""
    raw = os.environ.get("HYPOTHEX_SEED")
    return int(raw) if raw else default
