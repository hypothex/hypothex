from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.ids import utcnow
from hypothex.core.records import Artifact, RunStatus
from tests.api.envserver import remote_hub, wait_until
from tests.factories import make_record

BASE = "http://127.0.0.1:7777"


def archived(ctx: Context, run_id: str, artifact: Path) -> None:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"x" * 20_000)
    ended = utcnow() - timedelta(days=40)
    ctx.create_run(
        make_record(
            run_id,
            status=RunStatus.FINISHED,
            archived=True,
            started_at=ended - timedelta(hours=1),
            ended_at=ended,
            artifacts=[Artifact(kind="checkpoint", path=str(artifact))],
            environment_id=ctx.descriptor.environment_id,
        )
    )


def test_hub_plans_and_applies_local_cleanup(home: Path, tmp_path: Path) -> None:
    ctx = Context.open(home)
    archived(ctx, "old", tmp_path / "scratch" / "old.pt")
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        report = client.get("/api/v1/storage").json()
        assert report["by_kind"]["artifact"] > 0 and report["errors"] == []
        plan = client.post("/api/v1/storage/plan", json={"older_than_days": 30}).json()
        assert [i["run_id"] for i in plan["items"]] == ["old"] and plan["created_by"] == "human"
        url = f"/api/v1/storage/plans/{plan['plan_id']}/apply"
        wrong = client.post(url, json={"confirm_bytes": plan["total_bytes"] + 1})
        assert wrong.status_code == 400 and wrong.json()["type"] == "CleanRefusedError"
        done = client.post(url, json={"confirm_bytes": plan["total_bytes"]}).json()
    assert (
        done["freed_bytes"] == plan["total_bytes"]
        and not (tmp_path / "scratch" / "old.pt").exists()
    )


def test_policy_must_stay_archived_only(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        resp = client.post("/api/v1/storage/plan", json={"archived": False})
    assert resp.status_code == 422


def test_env_routes_list_and_delete(home: Path, tmp_path: Path) -> None:
    ctx = Context.open(home)
    archived(ctx, "old", tmp_path / "scratch" / "old.pt")
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui", kind="ssh")
    with TestClient(app, base_url=BASE) as client:
        usage = client.get("/api/v1/storage/usage").json()
        item = next(u for u in usage if u["kind"] == "artifact")
        body = {
            "items": [
                {
                    **{k: item[k] for k in ("project", "run_id", "host", "environment_id")},
                    "kind": "artifact",
                    "artifact_kind": "checkpoint",
                    "path": item["path"],
                    "bytes": item["bytes"],
                    "mtime": item["mtime"],
                    "reason": "archived 40d",
                }
            ],
            "plan_id": "cp-0000000a",
            "actor": "human:sv",
            "older_than_days": 30,
        }
        checked = client.post(
            "/api/v1/storage/check",
            json={
                "items": body["items"],
                "older_than_days": 30,
            },
        )
        assert checked.status_code == 200 and checked.json() == []
        assert Path(item["path"]).exists()  # preflight is read-only
        done = client.post("/api/v1/storage/delete", json=body).json()
    assert [d["run_id"] for d in done["deleted"]] == ["old"] and done["skipped"] == []


@pytest.mark.parametrize("after_plan", [False, True])
def test_host_checks_checkpoint_alias_on_its_own_filesystem(
    tmp_path: Path, after_plan: bool
) -> None:
    with remote_hub(tmp_path) as r:
        checkpoint = tmp_path / "host-data" / "parent.pt"
        archived(r.env, "parent", checkpoint)
        wait_until(lambda: "parent" in r.hub.index.run_ids(), timeout=30)
        alias = tmp_path / "host-alias"
        alias.symlink_to(checkpoint.parent, target_is_directory=True)

        def reader() -> None:
            r.env.create_run(
                make_record(
                    "reader",
                    archived=False,
                    status=RunStatus.QUEUED,
                    environment_id=r.env.descriptor.environment_id,
                    cwd=str(tmp_path),
                    vars={"checkpoint": "host-alias/parent.pt"},
                )
            )

        if not after_plan:
            reader()  # host check must see this without waiting for a mirrored reader
        result = r.client.post("/api/v1/storage/plan", json={}).json()
        if after_plan:
            assert len(result["items"]) == 1
            reader()
            response = r.client.post(
                f"/api/v1/storage/plans/{result['plan_id']}/apply",
                json={
                    "confirm_bytes": result["total_bytes"],
                },
            ).json()
            assert response["deleted"] == []
            assert any(row["reason"] == "used by reader" for row in response["skipped"])
        else:
            assert result["items"] == []
            assert any(row["reason"] == "used by reader" for row in result["refused"])
        assert checkpoint.exists()


def test_hub_cleans_a_hosts_artifacts(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        archived(r.env, "g1", tmp_path / "gpu1-scratch" / "g1.pt")
        wait_until(lambda: "g1" in r.hub.index.run_ids(), timeout=30)
        report = r.client.get("/api/v1/storage").json()
        assert any(i["host"] == "gpu1" and i["run_id"] == "g1" for i in report["items"])
        plan = r.client.post("/api/v1/storage/plan", json={}).json()
        assert [(i["host"], i["run_id"]) for i in plan["items"]] == [("gpu1", "g1")]
        url = f"/api/v1/storage/plans/{plan['plan_id']}/apply"
        done = r.client.post(url, json={"confirm_bytes": plan["total_bytes"]}).json()
        assert [d["host"] for d in done["deleted"]] == ["gpu1"] and done["errors"] == []
        assert not (tmp_path / "gpu1-scratch" / "g1.pt").exists()
        env_record = r.env.find_record("g1")
        assert (r.env.run_dir(env_record) / ".hx" / "cleaned.json").is_file()
        hub_record = r.hub.find_record("g1")
        assert (r.hub.run_dir(hub_record) / ".hx" / "cleaned.json").is_file()
        from hypothex.core.storage import cleaned_artifacts

        target = r.env.descriptor.environment_id
        assert done["deleted"][0]["environment_id"] == target
        assert cleaned_artifacts(r.env, env_record)[0].environment_id == target
        assert cleaned_artifacts(r.hub, hub_record)[0].environment_id == target
        assert target != r.hub.descriptor.environment_id


@pytest.mark.parametrize("kind", ["local", "ssh"])
def test_authenticated_cleanup_refuses_forged_environment_but_accepts_local_pulled(
    home: Path,
    tmp_path: Path,
    kind: str,
) -> None:
    """Owning filesystem identity is checked without normalizing forged input."""
    from hypothex.core.storage import cleaned_artifacts, local_usage, measure_path
    from tests.api.authkit import auth_app, bearer, token_for

    ctx = Context.open(home)
    artifact = tmp_path / "scratch" / "local.pt"
    archived(ctx, "local-source", artifact)
    app = auth_app(home, kind=kind)
    with TestClient(app, base_url=BASE) as client:
        admin = bearer(token_for(app.state.auth, "sv", "admin"))
        item = next(i for i in local_usage(ctx) if i.kind == "artifact")
        candidate = {**item.model_dump(mode="json"), "reason": "archived"}
        forged = {**candidate, "environment_id": "another-environment"}

        def delete(value: dict[str, object]) -> dict[str, object]:
            response = client.post(
                "/api/v1/storage/delete",
                json={
                    "items": [value],
                    "older_than_days": 30,
                    "plan_id": "cp-12345678",
                    "actor": "forged",
                },
                headers=admin,
            )
            assert response.status_code == 200
            return response.json()

        checked = client.post(
            "/api/v1/storage/check", json={"items": [forged], "older_than_days": 30}, headers=admin
        )
        assert checked.status_code == 200 and checked.json()[0]["reason"] == "wrong environment"
        result = delete(forged)
        assert result["freed_bytes"] == 0 and result["deleted"] == []
        assert artifact.read_bytes() == b"x" * 20_000
        assert cleaned_artifacts(ctx, ctx.find_record("local-source")) == []
        foreign = ctx.find_record("local-source").model_copy(
            update={"environment_id": "remote-env"}
        )
        ctx.store.write_record(foreign)
        ctx.index.upsert_run(foreign)
        refused = delete(candidate)
        assert (
            refused["freed_bytes"] == 0
            and refused["skipped"][0]["reason"] == "wrong artifact environment"
        )
        assert artifact.exists()
        pulled = ctx.run_dir(foreign) / "pulled" / "copy.pt"
        pulled.parent.mkdir(parents=True, exist_ok=True)
        pulled.write_bytes(b"pulled-copy")
        size, _, mtime = measure_path(pulled)
        copy = {**candidate, "kind": "pulled", "path": str(pulled), "bytes": size, "mtime": mtime}
        assert (
            client.post(
                "/api/v1/storage/check",
                json={"items": [copy], "older_than_days": 30},
                headers=admin,
            ).json()
            == []
        )
        done = delete(copy)
        assert done["freed_bytes"] == size and not pulled.exists()
        cleaned = cleaned_artifacts(ctx, foreign)
        assert len(cleaned) == 1 and cleaned[0].environment_id == ctx.descriptor.environment_id
        assert cleaned[0].actor == "human:sv"


@pytest.mark.parametrize("leaf", ["run.yaml", "metrics.jsonl", "scores.jsonl"])
def test_env_delete_does_not_follow_parent_replacement_after_policy_check(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    leaf: str,
) -> None:
    """An unrelated writer cannot redirect env deletion into protected metadata."""
    from typing import Any

    from hypothex.core import storage
    from tests.api.authkit import auth_app, bearer, token_for

    ctx = Context.open(home)
    parent = tmp_path / "scratch"
    candidate = parent / leaf
    archived(ctx, "old", candidate)
    run_dir = ctx.run_dir(ctx.find_record("old"))
    protected = run_dir / leaf
    if not protected.exists():
        protected.write_bytes(b"protected metadata")
    original = protected.read_bytes()
    item = next(i for i in storage.local_usage(ctx) if i.kind == "artifact")
    real_recheck = storage._recheck
    swapped = False

    def recheck(*args: Any, **kwargs: Any) -> str | None:
        nonlocal swapped
        reason = real_recheck(*args, **kwargs)
        if reason is None and not swapped:
            parent.rename(tmp_path / "saved-scratch")
            parent.symlink_to(run_dir, target_is_directory=True)
            swapped = True
        return reason

    monkeypatch.setattr(storage, "_recheck", recheck)
    app = auth_app(home, kind="ssh")
    with TestClient(app, base_url=BASE) as client:
        admin = bearer(token_for(app.state.auth, "sv", "admin"))
        response = client.post(
            "/api/v1/storage/delete",
            json={
                "items": [{**item.model_dump(mode="json"), "reason": "archived"}],
                "plan_id": "cp-12345678",
                "actor": "ignored",
                "older_than_days": 30,
            },
            headers=admin,
        )
    assert swapped and response.status_code == 200
    result = response.json()
    assert result["deleted"] == [] and result["freed_bytes"] == 0 and len(result["skipped"]) == 1
    assert protected.read_bytes() == original
    assert storage.cleaned_artifacts(ctx, ctx.find_record("old")) == []


def test_auth_off_local_delete_does_not_accept_body_actor(home: Path, tmp_path: Path) -> None:
    """A local no-auth caller is human; only host forwarding preserves a body actor."""
    from hypothex.core.storage import cleaned_artifacts, local_usage

    ctx = Context.open(home)
    archived(ctx, "old", tmp_path / "scratch" / "old.pt")
    item = next(i for i in local_usage(ctx) if i.kind == "artifact")
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        response = client.post(
            "/api/v1/storage/delete",
            json={
                "items": [{**item.model_dump(mode="json"), "reason": "archived"}],
                "plan_id": "cp-12345678",
                "actor": "human:forged",
                "older_than_days": 30,
            },
        )
    assert response.status_code == 200 and response.json()["deleted"]
    assert cleaned_artifacts(ctx, ctx.find_record("old"))[0].actor == "human"
