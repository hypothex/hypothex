"""Cleanup selection and bookkeeping across the actual hub/owner HTTP boundary."""

from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from hypothex.core.context import Context
from hypothex.core.ids import utcnow
from hypothex.core.records import Artifact, RunStatus
from hypothex.core.storage import cleaned_artifacts, measure_path
from tests.api.envserver import remote_hub, wait_until
from tests.factories import make_record


def _owner(ctx: Context, run_id: str, artifacts: list[Artifact]) -> None:
    """Create an eligible owner without changing the referenced artifact bytes."""
    ended = utcnow() - timedelta(days=40)
    ctx.create_run(
        make_record(
            run_id,
            archived=True,
            status=RunStatus.FINISHED,
            started_at=ended - timedelta(hours=1),
            ended_at=ended,
            artifacts=artifacts,
            environment_id=ctx.descriptor.environment_id,
        )
    )


@pytest.mark.parametrize("late", [False, True])
def test_remote_cleanup_preserves_excluded_nested_artifact(tmp_path: Path, late: bool) -> None:
    """Host preflight/apply protect an excluded binding even before it is mirrored."""
    with remote_hub(tmp_path) as remote:
        folder = tmp_path / "host-artifacts" / "checkpoint"
        folder.mkdir(parents=True)
        log = folder / "training.log"
        log.write_bytes(b"excluded log" * 2000)
        _owner(remote.env, "selected", [Artifact(kind="checkpoint", path=str(folder))])
        wait_until(lambda: "selected" in remote.hub.index.run_ids(), timeout=30)

        def excluded() -> None:
            _owner(remote.env, "excluded", [Artifact(kind="log", path=str(log))])

        if not late:
            excluded()
        response = remote.client.post("/api/v1/storage/plan", json={"kinds": ["checkpoint"]})
        assert response.status_code == 200
        plan = response.json()
        if late:
            assert len(plan["items"]) == 1
            excluded()
            applied = remote.client.post(
                f"/api/v1/storage/plans/{plan['plan_id']}/apply",
                json={"confirm_bytes": plan["total_bytes"]},
            )
            assert applied.status_code == 200
            result = applied.json()
            assert result["deleted"] == [] and result["freed_bytes"] == 0
            assert result["skipped"] and result["errors"] == []
        else:
            assert plan["items"] == [] and plan["total_bytes"] == 0
            assert plan["refused"]
        assert log.read_bytes() == b"excluded log" * 2000
        for run_id in ("selected", "excluded"):
            assert cleaned_artifacts(remote.env, remote.env.find_record(run_id)) == []


def test_remote_cleanup_does_not_expand_a_saved_plan_to_a_new_owner(tmp_path: Path) -> None:
    """An eligible new owner requires a new plan rather than silent deletion/association."""
    with remote_hub(tmp_path) as remote:
        artifact = tmp_path / "host-artifacts" / "shared.pt"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"shared" * 2000)
        _owner(remote.env, "planned", [Artifact(kind="checkpoint", path=str(artifact))])
        wait_until(lambda: "planned" in remote.hub.index.run_ids(), timeout=30)
        response = remote.client.post("/api/v1/storage/plan", json={})
        assert response.status_code == 200
        plan = response.json()
        assert [item["run_id"] for item in plan["items"]] == ["planned"]
        _owner(remote.env, "new-owner", [Artifact(kind="checkpoint", path=str(artifact))])
        response = remote.client.post(
            f"/api/v1/storage/plans/{plan['plan_id']}/apply",
            json={"confirm_bytes": plan["total_bytes"]},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["freed_bytes"] == 0 and result["deleted"] == []
        assert result["skipped"] and result["errors"] == []
        assert artifact.read_bytes() == b"shared" * 2000
        for run_id in ("planned", "new-owner"):
            assert cleaned_artifacts(remote.env, remote.env.find_record(run_id)) == []


def test_env_cleanup_groups_one_environment_across_display_host_labels(tmp_path: Path) -> None:
    """The owning server counts shared bytes once despite hub/local display labels."""
    with remote_hub(tmp_path) as remote:
        artifact = tmp_path / "host-artifacts" / "shared.pt"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"shared" * 2000)
        for run_id in ("first", "second"):
            _owner(remote.env, run_id, [Artifact(kind="checkpoint", path=str(artifact))])
        wait_until(lambda: {"first", "second"} <= set(remote.hub.index.run_ids()), timeout=30)
        response = remote.client.post("/api/v1/storage/plan", json={})
        assert response.status_code == 200
        plan = response.json()
        assert len(plan["items"]) == 2
        plan["items"][0]["host"] = "local"
        with httpx.Client(base_url=remote.env_url, trust_env=False) as env_client:
            response = env_client.post(
                "/api/v1/storage/delete",
                json={
                    "items": plan["items"],
                    "older_than_days": 30,
                    "plan_id": plan["plan_id"],
                    "actor": "human",
                },
            )
        assert response.status_code == 200
        result = response.json()
        assert result["freed_bytes"] == plan["total_bytes"], result
        assert {item["run_id"] for item in result["deleted"]} == {"first", "second"}
        assert result["skipped"] == result["errors"] == []
        for run_id in ("first", "second"):
            assert len(cleaned_artifacts(remote.env, remote.env.find_record(run_id))) == 1


def test_remote_cleanup_refuses_lexical_child_outside_physical_parent(tmp_path: Path) -> None:
    """A symlink escape cannot hide selected physical bytes from hub confirmation."""
    with remote_hub(tmp_path) as remote:
        folder = tmp_path / "host-artifacts" / "selected"
        folder.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        artifact = outside / "weights.pt"
        artifact.write_bytes(b"outside shared weights" * 2000)
        alias = folder / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        _owner(remote.env, "parent", [Artifact(kind="checkpoint", path=str(folder))])
        _owner(remote.env, "child", [Artifact(kind="checkpoint", path=str(alias / artifact.name))])
        wait_until(lambda: {"parent", "child"} <= set(remote.hub.index.run_ids()), timeout=30)
        response = remote.client.post("/api/v1/storage/plan", json={})
        assert response.status_code == 200
        plan = response.json()
        assert plan["items"] == [] and plan["total_bytes"] == 0, plan
        assert {item["run_id"] for item in plan["refused"]} == {"parent", "child"}
        assert folder.exists() and artifact.read_bytes() == b"outside shared weights" * 2000
        for run_id in ("parent", "child"):
            assert cleaned_artifacts(remote.env, remote.env.find_record(run_id)) == []


@pytest.mark.parametrize("nested", [False, True])
def test_remote_cleanup_marks_all_owners_and_counts_physical_bytes_once(
    tmp_path: Path, nested: bool
) -> None:
    """One host deletion records every selected owner on both host and mirrored hub."""
    with remote_hub(tmp_path) as remote:
        folder = tmp_path / "host-artifacts" / "shared"
        folder.mkdir(parents=True)
        leaf = folder / "weights.pt"
        leaf.write_bytes(b"shared weights" * 2000)
        first_path = folder if nested else leaf
        expected_bytes = measure_path(first_path)[0]
        _owner(remote.env, "first", [Artifact(kind="checkpoint", path=str(first_path))])
        _owner(remote.env, "second", [Artifact(kind="checkpoint", path=str(leaf))])
        wait_until(lambda: {"first", "second"} <= set(remote.hub.index.run_ids()), timeout=30)
        before = remote.env.events.last_sequence()
        response = remote.client.post("/api/v1/storage/plan", json={"kinds": ["checkpoint"]})
        assert response.status_code == 200
        plan = response.json()
        assert {item["run_id"] for item in plan["items"]} == {"first", "second"}
        assert plan["total_bytes"] == expected_bytes
        response = remote.client.post(
            f"/api/v1/storage/plans/{plan['plan_id']}/apply",
            json={"confirm_bytes": plan["total_bytes"]},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["freed_bytes"] == expected_bytes
        assert {item["run_id"] for item in result["deleted"]} == {"first", "second"}
        assert result["skipped"] == result["errors"] == []
        assert not first_path.exists() and not leaf.exists()
        for ctx in (remote.env, remote.hub):
            for run_id, path in (("first", first_path), ("second", leaf)):
                markers = cleaned_artifacts(ctx, ctx.find_record(run_id))
                assert len(markers) == 1
                assert markers[0].path == str(path)
                assert markers[0].environment_id == remote.env.descriptor.environment_id
                assert markers[0].plan_id == plan["plan_id"]
        events = [e for e in remote.env.events.since(before) if e.type == "run.artifacts_cleaned"]
        assert {e.run_id for e in events} == {"first", "second"}
