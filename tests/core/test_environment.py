import logging
import socket
from pathlib import Path

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.environment import load_descriptor
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from hypothex.core.store import RunStore
from tests.factories import make_record


def _home_with_runs(tmp_path: Path, runs: dict[str, tuple[str, str]]) -> Layout:
    """A home whose store holds ``run_id -> (host, environment_id)`` runs."""
    layout = Layout(tmp_path / "home")
    layout.ensure()
    store = RunStore(layout)
    store.register_project(ProjectConfig(project="toy"), tmp_path)
    for run_id, (host, environment_id) in runs.items():
        store.create_run(make_record(run_id, host=host, environment_id=environment_id))
    return layout


def test_missing_file_in_an_empty_store_makes_a_new_stable_id(tmp_path: Path) -> None:
    layout = _home_with_runs(tmp_path, {})
    first = load_descriptor(layout)
    assert len(first.environment_id) == 32
    assert first.label == socket.gethostname()
    assert load_descriptor(layout).environment_id == first.environment_id


def test_missing_file_takes_the_id_back_from_this_hosts_runs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    here = socket.gethostname()
    layout = _home_with_runs(
        tmp_path,
        {"r1": (here, "old-id"), "r2": (here, "old-id"), "r3": ("gpu-box", "remote-id")},
    )
    with caplog.at_level(logging.WARNING, logger="hypothex.core.environment"):
        descriptor = load_descriptor(layout)
    assert descriptor.environment_id == "old-id"
    assert descriptor.label == here
    assert "old-id" in caplog.text
    assert load_descriptor(layout).environment_id == "old-id"  # written back to the file


def test_missing_file_with_two_local_ids_is_refused(tmp_path: Path) -> None:
    here = socket.gethostname()
    layout = _home_with_runs(tmp_path, {"r1": (here, "id-a"), "r2": (here, "id-b")})
    with pytest.raises(ConfigError, match="id-a, id-b"):
        load_descriptor(layout)
    assert not layout.environment_json.exists()
