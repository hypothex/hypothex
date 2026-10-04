import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api import app as app_module
from hypothex.api.app import create_app
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import RunRequest
from hypothex.core.records import ExecutorInfo, RunRecord, RunStatus
from hypothex.remote.config import SlurmDefaults, load_hosts, save_hosts
from tests.api.envserver import remote_hub, wait_until
from tests.factories import git, make_record, seed_finished_run

PY = sys.executable
BASE = "http://127.0.0.1:7777"


def test_launch_on_a_host_runs_there_once_per_command_id(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        body = {
            "repo": str(r.hub_repo),
            "task": "toy-acc",
            "command": [PY, "-c", "print('hi')"],
            "hypothesis": "remote smoke",
            "command_id": "L1",
        }
        first = r.client.post("/api/v1/hosts/gpu1/runs", json=body).json()
        again = r.client.post("/api/v1/hosts/gpu1/runs", json=body).json()
        assert first["run_id"] == again["run_id"]
        assert first["environment_id"] == r.env.descriptor.environment_id
        assert Path(first["cwd"]).resolve() == r.env_repo.resolve()
        assert [x.run_id for x in r.env.index.list_runs(limit=None)] == [first["run_id"]]
        assert control.wait_for_run(r.env, first["run_id"], timeout=60).status == RunStatus.FINISHED
        wait_until(
            lambda: (
                r.client.get(f"/api/v1/runs/{first['run_id']}").json()["record"]["status"]
                == "finished"
            ),
            timeout=30,
        )


def test_launch_on_a_host_sends_diff_slurm_and_gpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[RunRequest] = []

    def fake_launch(c: Context, req: RunRequest) -> RunRecord:
        seen.append(req)
        return c.create_run(make_record("fake1", environment_id=c.descriptor.environment_id))

    monkeypatch.setattr(control, "launch_run", fake_launch)
    defaults = SlurmDefaults(partition="gpu", account="lab", time="04:00:00", gpus=1)
    with remote_hub(tmp_path, kind="slurm", slurm=defaults) as r:
        with (r.hub_repo / "toymetrics.py").open("a") as fh:
            fh.write("# tweak\n")
        out = r.client.post(
            "/api/v1/hosts/gpu1/runs",
            json={
                "repo": str(r.hub_repo),
                "command": ["true"],
                "hypothesis": "h",
                "gpus": 2,
                "queue": True,
                "slurm": {"time": "01:00:00"},
            },
        ).json()
        assert out["run_id"] == "fake1"
        [req] = seen
        assert req.repo.resolve() == r.env_repo.resolve()
        assert req.commit == git(r.hub_repo, "rev-parse", "HEAD")
        assert "+# tweak" in (req.diff or "")
        assert req.slurm == SlurmDefaults(partition="gpu", account="lab", time="01:00:00", gpus=2)
        assert (req.gpus, req.queue) == (2, True)


def test_an_explicit_slurm_gpus_0_overrides_the_host_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[RunRequest] = []

    def fake_launch(c: Context, req: RunRequest) -> RunRecord:
        seen.append(req)
        rid = f"fake{len(seen)}"
        return c.create_run(make_record(rid, environment_id=c.descriptor.environment_id))

    monkeypatch.setattr(control, "launch_run", fake_launch)
    defaults = SlurmDefaults(partition="gpu", time="04:00:00", gpus=1)
    with remote_hub(tmp_path, kind="slurm", slurm=defaults) as r:
        base = {"repo": str(r.hub_repo), "command": ["true"], "hypothesis": "h"}
        for extra in ({"gpus": 0, "slurm": {"gpus": 0}}, {"gpus": 0}):
            resp = r.client.post("/api/v1/hosts/gpu1/runs", json={**base, **extra})
            assert resp.status_code == 200, resp.text
        assert [req.slurm.gpus if req.slurm else None for req in seen] == [0, 1]


def test_slurm_gpus_alone_is_accepted_by_an_ssh_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `hx launch --host H --gpus N` cannot know H's kind, so it always sends slurm.gpus
    seen: list[RunRequest] = []

    def fake_launch(c: Context, req: RunRequest) -> RunRecord:
        seen.append(req)
        return c.create_run(make_record("fake1", environment_id=c.descriptor.environment_id))

    monkeypatch.setattr(control, "launch_run", fake_launch)
    with remote_hub(tmp_path) as r:
        body = {"repo": str(r.hub_repo), "command": ["true"], "hypothesis": "h"}
        resp = r.client.post(
            "/api/v1/hosts/gpu1/runs", json={**body, "gpus": 2, "slurm": {"gpus": 2}}
        )
        assert resp.status_code == 200, resp.text
        [req] = seen
        assert (req.slurm, req.gpus) == (None, 2)


def test_launch_on_a_host_errors_start_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path) as r:
        base = {"repo": str(r.hub_repo), "command": ["true"], "hypothesis": "h"}

        def err(host: str, **extra: object) -> tuple[int, str]:
            resp = r.client.post(f"/api/v1/hosts/{host}/runs", json={**base, **extra})
            return resp.status_code, resp.json()["error"]

        status, msg = err("nope")
        assert status == 400 and "hx hosts add nope" in msg
        status, msg = err("gpu1", slurm={"partition": "gpu"})
        assert status == 400 and "not a SLURM host" in msg
        status, msg = err("gpu1", created_by="agent:x", hypothesis=" ")
        assert status == 400 and "hypothesis" in msg
        metrics = r.hub_repo / "toymetrics.py"
        metrics.write_bytes(metrics.read_bytes() + b"# caf\xe9\n")
        status, msg = err("gpu1")
        assert status == 400 and "not UTF-8" in msg
        git(r.hub_repo, "checkout", "--", "toymetrics.py")
        monkeypatch.setattr(app_module, "DIFF_LIMIT_BYTES", 8)
        with metrics.open("a") as fh:
            fh.write("# big change\n")
        status, msg = err("gpu1")
        assert status == 400 and "larger than 8 bytes" in msg
        git(r.hub_repo, "checkout", "--", "toymetrics.py")
        hosts = load_hosts(r.hub.layout)
        unmapped = hosts.environments["gpu1"].model_copy(update={"projects": {}})
        save_hosts(r.hub.layout, hosts.model_copy(update={"environments": {"gpu1": unmapped}}))
        status, msg = err("gpu1")
        assert status == 400 and "hx hosts map toy gpu1" in msg
        assert r.env.index.list_runs(limit=None) == []


def test_run_actions_are_forwarded_with_the_same_command_id(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        seed_finished_run(r.env, r.env_repo, "e1")
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        out = r.client.post("/api/v1/runs/e1/tags", json={"add": ["remote"], "command_id": "T1"})
        assert out.json()["tags"] == ["remote"]
        assert r.env.find_record("e1").tags == ["remote"]
        again = r.client.post("/api/v1/runs/e1/tags", json={"add": ["other"], "command_id": "T1"})
        assert again.json()["tags"] == ["remote"]
        assert r.env.find_record("e1").tags == ["remote"]
        note = r.client.post("/api/v1/runs/e1/notes", json={"text": "seen on gpu1"})
        assert note.json() == {"ok": True}
        assert "seen on gpu1" in r.env.store.read_notes("toy", "e1")
        assert r.client.post("/api/v1/runs/e1/star", json={"on": True}).json()["starred"] is True
        wait_until(lambda: r.hub.find_record("e1").tags == ["remote"], timeout=30)
        stop = r.client.post("/api/v1/runs/e1/stop", json={})
        assert stop.status_code == 400 and "only queued or running" in stop.json()["error"]
        r.client.post("/api/v1/hosts/gpu1/disconnect", json={})
        down = r.client.post("/api/v1/runs/e1/tags", json={"add": ["x"]})
        assert down.status_code == 503 and "hx hosts connect gpu1" in down.json()["error"]


def test_runs_of_unknown_environments_act_locally(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        r.hub.create_run(make_record("d1", environment_id="demo:mac", status=RunStatus.FINISHED))
        out = r.client.post("/api/v1/runs/d1/tags", json={"add": ["mine"]})
        assert out.json()["tags"] == ["mine"]
        assert r.client.get("/api/v1/runs/d1").json()["host_state"] is None


def test_launch_on_a_host_runs_the_hub_commit_the_host_lacks(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        (r.hub_repo / "marker.txt").write_text("from the hub\n")
        git(r.hub_repo, "add", "marker.txt")
        git(r.hub_repo, "commit", "-qm", "hub only")
        git(r.hub_repo, "push", "-q", "origin", "HEAD:main")  # gpu1 has not fetched it
        sha = git(r.hub_repo, "rev-parse", "HEAD")
        body = {
            "repo": str(r.hub_repo),
            "command": [PY, "-c", "print(open('marker.txt').read().strip())"],
            "hypothesis": "pinned commit",
        }
        out = r.client.post("/api/v1/hosts/gpu1/runs", json=body).json()
        assert out["git"]["commit"] == sha
        done = control.wait_for_run(r.env, out["run_id"], timeout=60)
        assert done.status == RunStatus.FINISHED
        stdout = (r.env.run_dir(done) / "logs" / "stdout.log").read_text()
        assert stdout.strip() == "from the hub"
        assert not (r.env_repo / "marker.txt").exists()  # the host checkout is untouched


def test_actions_on_a_run_whose_host_is_gone_never_run_here(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signalled: list[int] = []
    monkeypatch.setattr(control, "terminate_group", lambda pid, *a: signalled.append(pid))
    with remote_hub(tmp_path) as r:
        r.hub.create_run(
            make_record(
                "x1",
                environment_id="env-of-a-removed-host",
                status=RunStatus.RUNNING,
                executor=ExecutorInfo(child_pid=os.getpid()),
            )
        )
        for action in ("stop", "rerun", "reinfer", "reeval"):
            resp = r.client.post(f"/api/v1/runs/x1/{action}", json={})
            assert resp.status_code == 503, action
            assert "no configured host" in resp.json()["error"]
        assert r.hub.find_record("x1").status == RunStatus.RUNNING
        star = r.client.post("/api/v1/runs/x1/star", json={"on": True})
        assert star.json()["starred"] is True
        # and the core refuses before any side effect: no signal, no marker, no status change
        for act in (control.stop_run, control.cancel_if_queued, control.rerun):
            with pytest.raises(RunError, match="belongs to environment env-of-a-removed-host"):
                act(r.hub, "x1")
        assert r.hub.find_record("x1").status == RunStatus.RUNNING
        assert not (r.hub.run_dir(r.hub.find_record("x1")) / "stop_requested").exists()
    assert signalled == []


def test_launch_by_project_name_pins_the_hub_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # what the UI sends: the project by name, no path, no diff; a commit only for a rerun
    seen: list[RunRequest] = []

    def fake_launch(c: Context, req: RunRequest) -> RunRecord:
        seen.append(req)
        return c.create_run(
            make_record(f"fake{len(seen)}", environment_id=c.descriptor.environment_id)
        )

    monkeypatch.setattr(control, "launch_run", fake_launch)
    with remote_hub(tmp_path) as r:
        head = git(r.hub_repo, "rev-parse", "HEAD")
        body = {"project": "toy", "command": ["true"], "hypothesis": "h"}
        assert r.client.post("/api/v1/hosts/gpu1/runs", json=body).status_code == 200
        with (r.hub_repo / "toymetrics.py").open("a") as fh:
            fh.write("# local edit\n")
        rerun = {**body, "commit": head}  # "Rerun sweep" of a clean run: commit, no diff
        assert r.client.post("/api/v1/hosts/gpu1/runs", json=rerun).status_code == 200
        client_path = {**body, "repo": "/home/someone-else/checkout/toy"}  # not on the hub
        assert r.client.post("/api/v1/hosts/gpu1/runs", json=client_path).status_code == 200
        first, second, third = seen
        assert (first.commit, first.diff) == (head, None)  # the hub's HEAD, clean
        assert (second.commit, second.diff) == (head, None)  # the given commit, no hub diff
        assert third.commit == head and "+# local edit" in (third.diff or "")
        assert all(req.repo.resolve() == r.env_repo.resolve() for req in seen)


def _copy_from_host(ctx: Context) -> None:
    """Make the hub's toy entry a copy from gpu1; its repo path still exists on the hub."""
    entry = ctx.store.load_project("toy")
    ctx.store.save_project(entry.model_copy(update={"remote_host": "gpu1"}))


def test_a_launch_here_never_runs_in_a_host_copys_repo_path(
    home: Path, ctx: Context, toy_repo: Path
) -> None:
    ctx.register_project(toy_repo)
    _copy_from_host(ctx)
    body = {"project": "toy", "command": [PY, "-c", "pass"], "hypothesis": "h"}
    with TestClient(create_app(home, background_repair=False), base_url=BASE) as client:
        resp = client.post("/api/v1/hosts/local/runs", json=body)
    assert resp.status_code == 400 and "copied from host gpu1" in resp.json()["error"]
    assert ctx.index.list_runs(limit=None) == []
    assert ctx.store.load_project("toy").remote_host == "gpu1"


def test_a_host_sweep_never_sends_the_diff_of_a_host_copys_repo_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # gpu1 reported the hub's own checkout as its repo path: that folder's commit and
    # uncommitted changes must not be read, let alone sent to the host
    seen: list[RunRequest] = []

    def fake_launch(c: Context, req: RunRequest) -> RunRecord:
        seen.append(req)
        return c.create_run(
            make_record(f"fake{len(seen)}", environment_id=c.descriptor.environment_id)
        )

    monkeypatch.setattr(control, "launch_run", fake_launch)
    with remote_hub(tmp_path) as r:
        _copy_from_host(r.hub)
        with (r.hub_repo / "toymetrics.py").open("a") as fh:
            fh.write("# hub secret\n")
        body = {
            "project": "toy",
            "host": "gpu1",
            "grid": [{"name": "x", "values": ["1"]}],
            "seeds": [1],
            "command": [PY, "-c", "import sys", "{x}", "{seed}"],
            "hypothesis": "h",
        }
        resp = r.client.post("/api/v1/sweeps", json=body)
        assert resp.status_code == 200, resp.text
        [req] = seen
        assert (req.commit, req.diff) == (None, None)
