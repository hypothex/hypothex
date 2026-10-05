import json
import logging
import socket
from pathlib import Path

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.environment import load_descriptor
from hypothex.core.errors import ConfigError, StoreError
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


@pytest.mark.parametrize("claim_kind", ["valid", "malformed", "dangling"])
@pytest.mark.parametrize("has_local_run", [False, True])
def test_recovery_never_adopts_a_claimed_mirror_with_the_local_hostname(
    tmp_path: Path, claim_kind: str, has_local_run: bool
) -> None:
    here = socket.gethostname()
    runs = {"remote-r": (here, "remote-id")}
    if has_local_run:
        runs["local-r"] = (here, "local-id")
    layout = _home_with_runs(tmp_path, runs)
    claim = layout.store / ".claims" / "remote-r.json"
    claim.parent.mkdir()
    if claim_kind == "valid":
        claim.write_text(
            json.dumps({"project": "toy", "environment_id": "remote-id", "host": "gpu1"}),
            encoding="utf-8",
        )
    elif claim_kind == "malformed":
        claim.write_text("{", encoding="utf-8")
    else:
        claim.symlink_to(claim.parent / "missing")

    descriptor = load_descriptor(layout)

    assert descriptor.environment_id != "remote-id"
    if has_local_run:
        assert descriptor.environment_id == "local-id"
    else:
        assert len(descriptor.environment_id) == 32
    assert load_descriptor(layout).environment_id == descriptor.environment_id


@pytest.mark.parametrize("text", ['{"environment_id": "ab', "[1, 2]", '{"label": "mac"}'])
def test_an_unreadable_file_is_a_store_error_and_is_kept(tmp_path: Path, text: str) -> None:
    layout = _home_with_runs(tmp_path, {})
    layout.environment_json.write_text(text, encoding="utf-8")
    with pytest.raises(StoreError, match="environment.json"):
        load_descriptor(layout)
    assert layout.environment_json.read_text(encoding="utf-8") == text
