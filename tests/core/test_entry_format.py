"""Stored project snapshots across the ``higher_is_better`` format change (synthetic data)."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from hypothex.core.config import ProjectConfig
from hypothex.core.context import Context
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.leaderboard import build_leaderboard, key_higher_is_better
from hypothex.core.records import GitInfo, RunStatus, ScoreRecord
from hypothex.core.store import ProjectEntry, RunStore
from hypothex.remote.client import EnvClient
from hypothex.remote.hub import _ensure_project
from tests.factories import make_record

T0 = utcnow()


def _config(**latency: Any) -> dict[str, Any]:
    """A system_bench project: primary ``latency/p95``, ``latency`` direction as given."""
    return {
        "project": "bench",
        "datasets": {"d": {"version": "v1", "path": "data/test.jsonl"}},
        "metrics": {
            "latency": {"version": "v1", "fn": "m:latency", **latency},
            "throughput": {"version": "v1", "fn": "m:rps", "higher_is_better": True},
        },
        "tasks": {
            "t": {
                "dataset": "d",
                "metrics": ["latency", "throughput"],
                "primary": "latency/p95",
                "kind": "system_bench",
            }
        },
    }


def _legacy_entry() -> dict[str, Any]:
    """A ``project.json`` as older versions wrote it: no format, every direction ``true``."""
    cfg = _config(higher_is_better=True)
    for m in cfg["metrics"].values():
        m.update(higher_is_better=True, params={}, changelog={}, unit="")
    return {
        "project": "bench",
        "repo": "/somewhere/bench",
        "config": cfg,
        "registered_at": T0.isoformat(),
        "previous_repos": [],
        "remote_host": None,
    }


def _ranked_first(entry: ProjectEntry) -> str:
    """Label of the first row of task ``t`` with a fast (10 ms) and a slow (100 ms) group."""
    runs, scores = [], {}
    for i, (group, p95) in enumerate((("slow", 100.0), ("fast", 10.0))):
        runs.append(
            make_record(
                group,
                project="bench",
                task="t",
                status=RunStatus.FINISHED,
                config_hash=f"sha256:{group}",
                git=GitInfo(commit="c1"),
                hypothesis=group,
                created_at=T0 + timedelta(minutes=i),
            )
        )
        score = ScoreRecord(metric="latency", version="v1", key="p95", value=p95, created_at=T0)
        scores[group] = [score]
    board = build_leaderboard("bench", "t", entry.config, runs, scores)
    assert board.higher_is_better is False
    return board.rows[0].label


def test_a_legacy_snapshot_reads_its_directions_as_not_set() -> None:
    entry = ProjectEntry.model_validate(_legacy_entry())
    assert entry.config_format == 2
    assert entry.config.metrics["latency"].higher_is_better is None
    assert entry.config.metrics["throughput"].higher_is_better is None
    spec = entry.config.tasks["t"]
    assert key_higher_is_better(entry.config, spec, "latency/p95") is False
    assert _ranked_first(entry) == "fast"


def test_a_current_snapshot_keeps_an_explicit_true() -> None:
    cfg = ProjectConfig.model_validate(_config(higher_is_better=True))
    data = {**_legacy_entry(), "config": cfg.model_dump(mode="json"), "config_format": 2}
    entry = ProjectEntry.model_validate(data)
    assert entry.config.metrics["latency"].higher_is_better is True
    assert entry.config.metrics["throughput"].higher_is_better is True


def test_a_registered_project_writes_the_current_format(tmp_path: Path) -> None:
    layout = Layout(tmp_path / "home")
    layout.ensure()
    store = RunStore(layout)
    cfg = ProjectConfig.model_validate(_config())
    entry = store.register_project(cfg, tmp_path / "repo")
    assert entry.config_format == 2
    raw = json.loads(store._project_file("bench").read_text())
    assert raw["config_format"] == 2
    # an unset direction is left out, so older readers use their own default
    assert "higher_is_better" not in raw["config"]["metrics"]["latency"]
    assert raw["config"]["metrics"]["throughput"]["higher_is_better"] is True
    loaded = store.load_project("bench")
    assert loaded.config.metrics["latency"].higher_is_better is None
    assert loaded.config.metrics["throughput"].higher_is_better is True
    dumped = loaded.model_dump(mode="json")
    assert "higher_is_better" not in dumped["config"]["metrics"]["latency"]


class _Host:
    """A host whose ``/projects/{p}/entry`` returns an older version's stored snapshot."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def get_json(self, path: str) -> dict[str, Any]:
        assert path == "/api/v1/projects/bench/entry"
        return self.data


def test_a_hubs_copy_of_a_legacy_host_snapshot_ranks_lower_first(ctx: Context) -> None:
    _ensure_project(ctx, cast(EnvClient, _Host(_legacy_entry())), "gpu1", "bench")
    copy = ctx.store.load_project("bench")
    assert (copy.remote_host, copy.config_format) == ("gpu1", 2)
    assert copy.config.metrics["latency"].higher_is_better is None
    assert _ranked_first(copy) == "fast"
