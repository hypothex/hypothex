import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import HubManager, create_app
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.records import Artifact, RunStatus
from hypothex.remote.config import HostSpec
from tests.api.envserver import remote_hub, wait_until, write_fake_gpus, write_fake_scp, write_hosts
from tests.factories import PREDS_075, git, make_record, seed_finished_run

PY = sys.executable
CMD = [PY, "-c", "import sys", "{x}", "{seed}"]
BASE = "http://127.0.0.1:7777"


def _body(**over: object) -> dict[str, object]:
    return {
        "project": "toy",
        "task": "toy-acc",
        "grid": [{"name": "x", "values": ["1", "2"]}],
        "seeds": [1, 2],
        "command": CMD,
        "hypothesis": "x helps",
        **over,
    }


@pytest.fixture
def client(home: Path, ctx: Context, toy_repo: Path) -> Iterator[TestClient]:
    ctx.register_project(toy_repo)
    with TestClient(create_app(home, background_repair=False), base_url=BASE) as c:
        yield c


def test_local_sweep_routes(client: TestClient, ctx: Context) -> None:
    first = client.post("/api/v1/sweeps", json=_body(command_id="S1")).json()
    sid = first["spec"]["id"]
    assert len(first["run_ids"]) == 4 and first["spec"]["host"] is None
    assert client.post("/api/v1/sweeps", json=_body(command_id="S1")).json()["spec"]["id"] == sid
    for rid in first["run_ids"]:
        control.wait_for_run(ctx, rid, timeout=60)
    listed = client.get("/api/v1/projects/toy/sweeps").json()
    assert [(s["id"], s["n_runs"]) for s in listed] == [(sid, 4)]
    assert client.get(f"/api/v1/sweeps/toy/{sid}").json()["spec"]["seeds"] == [1, 2]
    more = client.post(f"/api/v1/sweeps/toy/{sid}/extend", json={"seeds": [3]}).json()
    assert more["spec"]["seeds"] == [1, 2, 3] and len(more["run_ids"]) == 6
    again = client.post(f"/api/v1/sweeps/toy/{sid}/extend", json={"seeds": [3]})
    assert again.status_code == 200 and len(again.json()["run_ids"]) == 6  # idempotent
    for rid in more["run_ids"]:
        control.wait_for_run(ctx, rid, timeout=60)
    cancelled = client.post(f"/api/v1/sweeps/toy/{sid}/cancel_queued", json={}).json()
    statuses = {ctx.find_record(rid).status for rid in cancelled["run_ids"]}
    assert statuses == {RunStatus.FINISHED}
    assert client.get("/api/v1/sweeps/toy/s-000000").status_code == 404


def test_a_sweep_is_found_by_id_alone(client: TestClient, ctx: Context) -> None:
    sid = client.post("/api/v1/sweeps", json=_body()).json()["spec"]["id"]
    got = client.get(f"/api/v1/sweeps/{sid}").json()
    assert (got["spec"]["id"], got["spec"]["project"]) == (sid, "toy")
    assert client.get("/api/v1/sweeps/s-0000").status_code == 404


def test_sweep_input_errors(client: TestClient) -> None:
    bad = client.post("/api/v1/sweeps", json=_body(command=[PY, "{seed}"]))
    assert bad.status_code == 400 and "{x}" in bad.json()["error"]
    assert client.post("/api/v1/sweeps", json=_body(seeds=[])).status_code == 422
    unknown = client.post("/api/v1/sweeps", json=_body(host="nope"))
    assert unknown.status_code == 400 and "hx hosts add nope" in unknown.json()["error"]
    blank = client.post("/api/v1/sweeps", json=_body(created_by="agent:x", hypothesis=" "))
    assert blank.status_code == 400 and "agents must give a hypothesis" in blank.json()["error"]
    assert client.get("/api/v1/projects/toy/sweeps").json() == []


def test_remote_sweep_runs_on_the_host(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        out = r.client.post("/api/v1/sweeps", json=_body(host="gpu1", command_id="RS")).json()
        sid, ids = out["spec"]["id"], out["run_ids"]
        assert len(ids) == 4 and out["spec"]["host"] == "gpu1"
        assert set(ids) <= r.hub.index.run_ids()
        head = git(r.hub_repo, "rev-parse", "HEAD")
        for rid in ids:
            record = r.env.find_record(rid)
            owner = r.hub.descriptor.environment_id[:8]
            assert record.sweep_id == sid and f"sweep:{owner}:{sid}" in record.tags
            assert Path(record.cwd).resolve() == r.env_repo.resolve()
            assert record.git.commit == head  # every run pinned to the hub's commit


def test_remote_cancel_queued_stops_queued_runs_on_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # one GPU, busy with another user's process: the runs wait in gpu1's queue
    gpus = write_fake_gpus(tmp_path / "busy.json", 1, external=(0,))
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(gpus))
    with remote_hub(tmp_path) as r:
        body = _body(host="gpu1", seeds=[1], gpus=1, queue=True)
        out = r.client.post("/api/v1/sweeps", json=body).json()
        sid, ids = out["spec"]["id"], out["run_ids"]
        assert len(ids) == 2
        wait_until(lambda: all(r.hub.find_record(i).status == RunStatus.QUEUED for i in ids))
        r.client.post(f"/api/v1/sweeps/toy/{sid}/cancel_queued", json={"command_id": "C1"})
        wait_until(
            lambda: all(r.env.find_record(i).status == RunStatus.KILLED for i in ids), timeout=60
        )


def test_pull_a_run_file_from_a_url_host(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        record = seed_finished_run(r.env, r.env_repo, "e1", predictions=PREDS_075)
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        rel = "predictions/predictions.jsonl"
        out = r.client.post("/api/v1/runs/e1/pull", json={"artifact": rel}).json()
        local = Path(out["local_path"])
        assert local == r.hub.layout.run_dir("toy", "e1") / "pulled" / rel
        assert local.read_text() == (r.env.run_dir(record) / rel).read_text()
        bad = r.client.post("/api/v1/runs/e1/pull", json={"artifact": "../../secret"})
        assert bad.status_code == 400
        missing = r.client.post("/api/v1/runs/e1/pull", json={"artifact": "nope.txt"})
        assert missing.status_code == 400 and "nope.txt" in missing.json()["error"]
        absolute = r.client.post("/api/v1/runs/e1/pull", json={"artifact": "/scratch/ckpt.pt"})
        assert absolute.status_code == 400 and "not an artifact" in absolute.json()["error"]


def _box_run(ctx: Context, home: Path, run_id: str, path: str) -> None:
    ctx.create_run(
        make_record(
            run_id,
            environment_id="env-box",
            status=RunStatus.FINISHED,
            artifacts=[Artifact(kind="checkpoint", path=path, host="box")],
        )
    )
    write_hosts(home, {"box": HostSpec(route="ssh", ssh_alias="box")})


@pytest.mark.parametrize(
    "artifact", ["/x;rm -rf ~", "/", "/etc/passwd", "/scratch/../etc/passwd", "/scratch/ckpt/"]
)
def test_pull_refuses_unsafe_or_foreign_absolute_paths(
    home: Path,
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    ctx.register_project(toy_repo)
    _box_run(ctx, home, "b2", "/scratch/ckpt/step_1.pt")
    scp = write_fake_scp(tmp_path)
    monkeypatch.setenv("HYPOTHEX_SCP", str(scp))
    monkeypatch.setattr(
        HubManager, "host_for_environment", lambda self, eid: "box" if eid == "env-box" else None
    )
    app = create_app(home, background_repair=False, hub=False)
    with TestClient(app, base_url=BASE) as client:
        bad = client.post("/api/v1/runs/b2/pull", json={"artifact": artifact})
    assert bad.status_code == 400
    assert not (ctx.layout.run_dir("toy", "b2") / "pulled").exists()


@pytest.mark.parametrize("path", ["/x;rm -rf ~", "/", "/scratch/../etc/passwd"])
def test_pull_refuses_a_tampered_artifact_path(
    home: Path,
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    # the path comes from the mirrored run.yaml, so it is checked like user input
    ctx.register_project(toy_repo)
    _box_run(ctx, home, "b3", path)
    monkeypatch.setenv("HYPOTHEX_SCP", str(write_fake_scp(tmp_path)))
    monkeypatch.setattr(
        HubManager, "host_for_environment", lambda self, eid: "box" if eid == "env-box" else None
    )
    app = create_app(home, background_repair=False, hub=False)
    with TestClient(app, base_url=BASE) as client:
        bad = client.post("/api/v1/runs/b3/pull", json={"artifact": "checkpoint"})
    assert bad.status_code == 400 and "invalid remote path" in bad.json()["error"]


def test_pull_of_a_run_whose_host_is_gone_is_503(home: Path, ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    _box_run(ctx, home, "b4", "/scratch/ckpt/step_1.pt")
    app = create_app(home, background_repair=False, hub=False)  # no host maps env-box
    with TestClient(app, base_url=BASE) as client:
        gone = client.post("/api/v1/runs/b4/pull", json={"artifact": "checkpoint"})
    assert gone.status_code == 503


def test_pull_a_checkpoint_over_scp(
    home: Path, ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.register_project(toy_repo)
    remote_file = tmp_path / "remote" / "ckpt" / "step_000100.pt"
    remote_file.parent.mkdir(parents=True)
    remote_file.write_bytes(b"weights")
    ctx.create_run(
        make_record(
            "b1",
            environment_id="env-box",
            status=RunStatus.FINISHED,
            artifacts=[Artifact(kind="checkpoint", path=str(remote_file), host="box")],
        )
    )
    write_hosts(home, {"box": HostSpec(route="ssh", ssh_alias="box")})
    monkeypatch.setenv("HYPOTHEX_SCP", str(write_fake_scp(tmp_path)))
    monkeypatch.setattr(
        HubManager, "host_for_environment", lambda self, eid: "box" if eid == "env-box" else None
    )
    app = create_app(home, background_repair=False, hub=False)  # hub=False: nothing dials ssh
    with TestClient(app, base_url=BASE) as client:
        out = client.post("/api/v1/runs/b1/pull", json={"artifact": "checkpoint"}).json()
    local = Path(out["local_path"])
    assert local == ctx.layout.run_dir("toy", "b1") / "pulled" / "step_000100.pt"
    assert local.read_bytes() == b"weights"
    assert sorted(p.name for p in local.parent.iterdir()) == ["step_000100.pt"]  # no pull state
    assert list((home / "pulls" / "txn").iterdir()) == []  # the records live in the hub home


@pytest.mark.parametrize(
    "path", ["/scratch/.hx-pull-0123456789abcdef0123456789abcdef.json", "/scratch/.hx-x"]
)
def test_pull_refuses_a_reserved_destination_name(
    home: Path,
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    ctx.register_project(toy_repo)
    _box_run(ctx, home, "b5", path)
    monkeypatch.setenv("HYPOTHEX_SCP", str(write_fake_scp(tmp_path)))
    monkeypatch.setattr(
        HubManager, "host_for_environment", lambda self, eid: "box" if eid == "env-box" else None
    )
    app = create_app(home, background_repair=False, hub=False)
    with TestClient(app, base_url=BASE) as client:
        bad = client.post("/api/v1/runs/b5/pull", json={"artifact": "checkpoint"})
    assert bad.status_code == 400 and "reserved" in bad.json()["error"]
    assert not (ctx.layout.run_dir("toy", "b5") / "pulled").exists()
