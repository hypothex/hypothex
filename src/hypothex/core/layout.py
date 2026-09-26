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
