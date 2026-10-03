"""Filesystem layout of a Hypothex home directory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_home() -> Path:
    """
    Return the Hypothex home directory.

    Returns
    -------
    Path
        ``$HYPOTHEX_HOME`` if set, else ``~/.hypothex``.
    """
    return Path(os.environ.get("HYPOTHEX_HOME", str(Path.home() / ".hypothex"))).expanduser()


@dataclass(frozen=True)
class Layout:
    """
    Paths inside one Hypothex home directory.

    Parameters
    ----------
    home : Path
        Root directory, e.g. ``~/.hypothex``.
    """

    home: Path

    @property
    def store(self) -> Path:
        """Directory holding all project and run folders."""
        return self.home / "store"

    @property
    def index_db(self) -> Path:
        """SQLite index path."""
        return self.home / "index.db"

    @property
    def events_db(self) -> Path:
        """SQLite event log path."""
        return self.home / "events.db"

    @property
    def environment_json(self) -> Path:
        """Stable environment identity file."""
        return self.home / "environment.json"

    @property
    def dataset_cache(self) -> Path:
        """Dataset fingerprint cache file."""
        return self.home / "dataset_cache.json"

    def project_dir(self, project: str) -> Path:
        """Return the folder for one project."""
        return self.store / project

    def runs_dir(self, project: str) -> Path:
        """Return the folder holding a project's runs."""
        return self.project_dir(project) / "runs"

    def run_dir(self, project: str, run_id: str) -> Path:
        """Return the folder of one run."""
        return self.runs_dir(project) / run_id

    def worktrees_dir(self, project: str) -> Path:
        """Return the folder holding git worktrees created for reruns."""
        return self.project_dir(project) / "worktrees"

    def ensure(self) -> None:
        """Create the home and store directories if missing."""
        self.store.mkdir(parents=True, exist_ok=True)


HX_DIR = ".hx"
"""Reserved folder in every run folder for Hypothex's own state (``.hx/mirror-skips.json``).

No remote or artifact path may address it: the env files route refuses it and the hub
mirror never fetches a host path in it (:func:`reserved_run_path`)."""


def reserved_run_path(rel_path: str) -> bool:
    """
    Return True when a run-relative path is inside the reserved ``.hx`` folder.

    Parameters
    ----------
    rel_path : str
        ``/``-separated path relative to a run folder.

    Returns
    -------
    bool
        True when its first component (after empty and ``.`` parts) is ``.hx``.

    Examples
    --------
    >>> reserved_run_path(".hx/mirror-skips.json"), reserved_run_path("./.hx")
    (True, True)
    >>> reserved_run_path("predictions/.hx"), reserved_run_path("predictions/x.skipped")
    (False, False)
    """
    parts = [part for part in rel_path.split("/") if part not in ("", ".")]
    return bool(parts) and parts[0] == HX_DIR
