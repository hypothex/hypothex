import os
import sys
from pathlib import Path

import pytest

from hypothex.api import app as app_module
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import RunRequest
from hypothex.core.records import ExecutorInfo, RunRecord, RunStatus
from hypothex.remote.config import SlurmDefaults, load_hosts, save_hosts
from tests.api.envserver import remote_hub, wait_until
from tests.factories import PREDS_075, git, make_record, seed_finished_run

PY = sys.executable


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


def test_run_lists_carry_the_host_state_of_each_run(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        seed_finished_run(r.env, r.env_repo, "e1")
        seed_finished_run(r.hub, r.hub_repo, "h1")
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)

        def states() -> dict[str, str | None]:
            rows = r.client.get("/api/v1/runs").json()
            return {row["run_id"]: row["host_state"] for row in rows}

        assert states() == {"e1": "connected", "h1": None}
        r.client.post("/api/v1/hosts/gpu1/disconnect", json={})
        assert states() == {"e1": "disabled", "h1": None}
        assert r.client.get("/api/v1/runs/e1").json()["host_state"] == "disabled"


def test_runs_of_unknown_environments_act_locally(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        r.hub.create_run(make_record("d1", environment_id="demo:mac", status=RunStatus.FINISHED))
        out = r.client.post("/api/v1/runs/d1/tags", json={"add": ["mine"]})
        assert out.json()["tags"] == ["mine"]
        assert r.client.get("/api/v1/runs/d1").json()["host_state"] is None


def test_curation_of_a_run_mirrored_from_a_removed_host_is_refused(tmp_path: Path) -> None:
    # the host is gone from environments.yaml, but its mirror cursor stays: when it is
    # added back, the host's run.yaml and notes.md replace the hub's copies
    with remote_hub(tmp_path) as r:
        r.hub.create_run(make_record("m1", environment_id="env-old", status=RunStatus.FINISHED))
        r.hub.index.set_cursor("gpu-old", "env-old", 7)
        for action, body in (
            ("tags", {"add": ["hub-only"]}),
            ("star", {"on": True}),
            ("archive", {"on": True}),
            ("notes", {"text": "hub-only note"}),
        ):
            resp = r.client.post(f"/api/v1/runs/m1/{action}", json=body)
            assert resp.status_code == 503, action
            assert "mirrored from host gpu-old" in resp.json()["error"]
        record = r.hub.find_record("m1")
        assert (record.tags, record.starred, record.archived) == ([], False, False)
        assert "hub-only note" not in r.hub.store.read_notes("toy", "m1")


def _score_rows(ctx: Context, run_id: str) -> int:
    path = ctx.run_dir(ctx.find_record(run_id)) / "scores.jsonl"
    return len(path.read_text().splitlines()) if path.exists() else 0


def test_task_reeval_scores_mirrored_runs_on_their_host(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        seed_finished_run(r.env, r.env_repo, "e1", predictions=PREDS_075)
        seed_finished_run(r.hub, r.hub_repo, "h1", predictions=PREDS_075)
        for rid, env in (("d1", "demo:mac"), ("m1", "env-old")):
            done = make_record(rid, task="toy-acc", environment_id=env, status=RunStatus.FINISHED)
            r.hub.create_run(done)
        r.hub.index.set_cursor("gpu-old", "env-old", 3)  # mirrored from a host since removed
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        body = {"force": True, "command_id": "E1"}
        out = r.client.post("/api/v1/tasks/toy/toy-acc/reeval", json=body).json()
        assert sorted(out["evaluated"]) == ["e1", "h1"]
        assert "gpu-old" in out["skipped"]["m1"] and "d1" in out["skipped"]  # scored here
        # the host scored its own run; the hub's copy only changes through the mirror
        assert _score_rows(r.env, "e1") == 1
        wait_until(lambda: _score_rows(r.hub, "e1") == 1, timeout=30)
        assert _score_rows(r.hub, "h1") == 1 and _score_rows(r.hub, "m1") == 0
        # one more host score: the mirror copies the host's file, and nothing is lost
        r.client.post("/api/v1/runs/e1/reeval", json={"force": True, "command_id": "E2"})
        wait_until(lambda: _score_rows(r.hub, "e1") == 2, timeout=30)
        again = r.client.post("/api/v1/tasks/toy/toy-acc/reeval", json=body).json()
        assert again == out  # the receipt: nothing is scored twice
        assert _score_rows(r.env, "e1") == 2
        r.client.post("/api/v1/hosts/gpu1/disconnect", json={})
        down = r.client.post("/api/v1/tasks/toy/toy-acc/reeval", json={"force": True}).json()
        assert down["evaluated"] == ["h1"] and "hx hosts connect gpu1" in down["skipped"]["e1"]


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
