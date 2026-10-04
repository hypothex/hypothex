"""SLURM host end to end against a small Docker SLURM cluster (never the user's hosts)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypothex import __version__
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.remote.config import SlurmDefaults, load_hosts
from tests.docker.conftest import (
    BOOTSTRAP_TIMEOUT,
    DESCRIPTOR_PY,
    REMOTE_PROJECT,
    REMOTE_STORE,
    REMOTE_TOY,
    WRITE_PREDS_075,
    HubThread,
    SlurmCluster,
    add_host,
    board_row,
    hub_app,
    launch,
    mirrored_text,
    remote_record,
    wait_mirrored,
    wait_remote_status,
    wait_until,
    write_scored_toy_project,
)
from tests.factories import git
from tests.fakes import DEAD_HUB

pytestmark = pytest.mark.docker

runner = CliRunner()
# the test cluster has no GPUs; 0 keeps `--gpus` out of the sbatch script
DEFAULTS = SlurmDefaults(partition="normal", time="00:05:00", gpus=0)
SLURM_POLL = 30.0  # the env server polls squeue/sacct every 30 s


def test_hosts_add_slurm_bootstraps_the_login_node(
    slurm_cluster: SlurmCluster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "hub"
    monkeypatch.setenv("HYPOTHEX_HOME", str(home))
    for key, value in slurm_cluster.access.env().items():
        monkeypatch.setenv(key, value)
    alias = slurm_cluster.access.alias
    argv = ["--home", str(home), "hosts", "add", "cluster", "--ssh", alias]
    argv += ["--slurm", "--partition", "normal", "--json"]
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output

    spec = load_hosts(Context.open(home).layout).environments["cluster"]
    assert (spec.route, spec.kind, spec.ssh_alias) == ("ssh", "slurm", "hx-docker-slurm")
    assert spec.slurm is not None and spec.slurm.partition == "normal"

    info = json.loads(slurm_cluster.sh("cat ~/.hypothex/serve/server.json"))
    assert info["managed"] is True
    assert info["hx_version"] == __version__
    # the env server shows its host facts only to a caller with its token
    port, token = str(info["port"]), info["token"]
    public = json.loads(slurm_cluster.exec("python3", "-c", DESCRIPTOR_PY, port))
    assert "kind" not in public and public["hx_version"] == __version__
    descriptor = json.loads(slurm_cluster.exec("python3", "-c", DESCRIPTOR_PY, port, token))
    assert descriptor["kind"] == "slurm"
    assert descriptor["hostname"] == "slurmctld"
    # the runtime sits on the shared /home, so the compute node sees the same install
    runtime = slurm_cluster.sh("ls ~/.hypothex/runtime/wheels")
    assert slurm_cluster.exec("sh", "-c", "ls ~/.hypothex/runtime/wheels", service="c1") == runtime


@pytest.fixture(scope="module")
def slurm_hub(
    slurm_cluster: SlurmCluster, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[HubThread]:
    """
    One hub, connected to the cluster's login node, shared by this module.

    The fixture installs hx on the login node itself (`hx hosts add --slurm`), so
    each test also runs alone (`-k lost`), not only after the hosts-add test.
    """
    with pytest.MonkeyPatch.context() as mp:
        home = tmp_path_factory.mktemp("slurm-hub")
        mp.setenv("HYPOTHEX_HOME", str(home))
        # module fixture: set the hub URL here too (`hosts add|map` must never reach a real hub)
        mp.setenv("HYPOTHEX_HUB_URL", DEAD_HUB)
        for key, value in slurm_cluster.access.env().items():
            mp.setenv(key, value)
        alias = slurm_cluster.access.alias
        argv = ["--home", str(home), "hosts", "add", "cluster", "--ssh", alias, "--slurm"]
        argv += ["--partition", "normal", "--time", "00:05:00", "--gpus", "0", "--json"]
        added = runner.invoke(app, argv, catch_exceptions=False)
        assert added.exit_code == 0, added.output
        mapping = ["--home", str(home), "hosts", "map", "dock", "cluster", REMOTE_PROJECT]
        mapped = runner.invoke(app, mapping, catch_exceptions=False)
        assert mapped.exit_code == 0, mapped.output
        ctx = Context.open(home)
        assert load_hosts(ctx.layout).environments["cluster"].slurm == DEFAULTS
        with HubThread(ctx) as hub:
            hub.wait_connected("cluster", timeout=BOOTSTRAP_TIMEOUT)
            yield hub


def submit(hub: HubThread, command: list[str]) -> str:
    return launch(hub.client("cluster"), command, gpus=0, slurm=DEFAULTS.model_dump())["run_id"]


def job_id_of(hub: HubThread, run_id: str) -> str:
    return wait_until(
        lambda: remote_record(hub, "cluster", run_id)["executor"].get("slurm_job_id"),
        timeout=60,
        what=f"slurm job id of {run_id}",
    )


def test_submit_runs_on_the_compute_node_and_mirrors(
    slurm_cluster: SlurmCluster, slurm_hub: HubThread
) -> None:
    run_id = submit(slurm_hub, ["sh", "-c", "echo slurm-ok; hostname"])
    job_id = job_id_of(slurm_hub, run_id)
    wait_until(
        lambda: slurm_cluster.job_state(job_id) == "COMPLETED",
        timeout=120,
        what=f"job {job_id} COMPLETED",
    )

    def accounted_name() -> str | None:
        # slurmdbd shows a new job for a few seconds as a placeholder named "allocation"
        name = slurm_cluster.sacct(job_id, "JobName")
        return name if name not in ("", "allocation") else None

    name = wait_until(accounted_name, timeout=60, what=f"sacct record of job {job_id}")
    assert name == f"hx-{run_id}"
    assert slurm_cluster.sacct(job_id, "Partition") == "normal"

    record = wait_remote_status(slurm_hub, "cluster", run_id, "finished", timeout=4 * SLURM_POLL)
    assert record["executor"]["slurm_job_id"] == job_id
    assert record["executor"]["node"] == "c1"
    run_dir = f"{REMOTE_STORE}/dock/runs/{run_id}"
    assert slurm_cluster.exec("cat", f"{run_dir}/logs/stdout.log") == "slurm-ok\nc1\n"
    slurm_cluster.exec("test", "-f", f"{run_dir}/logs/slurm-{job_id}.out")

    mirrored = wait_mirrored(slurm_hub.ctx, run_id, "finished", timeout=120)
    assert mirrored.executor.slurm_job_id == job_id
    assert mirrored.executor.node == "c1"
    text = mirrored_text(slurm_hub.ctx, run_id, "logs/stdout.log", "slurm-ok", timeout=60)
    assert text == "slurm-ok\nc1\n"


def test_a_job_launched_through_the_hub_is_scored_on_its_leaderboard(
    slurm_cluster: SlurmCluster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # spec 13, phase 2 done: launched through the hub's route (as the UI does), run as
    # a SLURM job on c1, scored on the cluster, mirrored, and on the hub's leaderboard
    home = tmp_path / "hub"
    monkeypatch.setenv("HYPOTHEX_HOME", str(home))
    ctx = Context.open(home)
    repo = write_scored_toy_project(tmp_path / "toy")
    slurm_cluster.put(repo, REMOTE_TOY)  # shared /home: the login node and c1 see it
    ctx.register_project(repo)
    options = ["--slurm", "--partition", "normal", "--time", "00:05:00", "--gpus", "0"]
    alias = slurm_cluster.access.alias
    add_host(home, "cluster", alias, *options, projects={"toy": REMOTE_TOY})
    assert load_hosts(ctx.layout).environments["cluster"].slurm == DEFAULTS
    with hub_app(ctx, "cluster", timeout=BOOTSTRAP_TIMEOUT) as client:
        body = {
            "project": "toy",
            "task": "toy-acc",
            "command": ["python3", "-c", WRITE_PREDS_075],
            "hypothesis": "scored on the cluster",
        }
        resp = client.post("/api/v1/hosts/cluster/runs", json=body)
        assert resp.status_code == 200, resp.text
        run = resp.json()
        run_id = run["run_id"]
        assert run["git"]["commit"] == git(repo, "rev-parse", "HEAD")
        row = wait_until(
            lambda: board_row(client, "toy", "toy-acc", run_id),
            timeout=6 * SLURM_POLL,
            what=f"{run_id} on the hub leaderboard",
        )
        assert row["primary"]["mean"] == 0.75  # references 0 1 0 0, predictions 0 1 0 1
        mirrored = ctx.store.read_record("toy", run_id)
        assert mirrored.executor.node == "c1" and mirrored.executor.slurm_job_id
        scores = slurm_cluster.exec("cat", f"{REMOTE_STORE}/toy/runs/{run_id}/scores.jsonl")
        assert len(scores.splitlines()) == 1  # scored once, on the cluster


def test_env_server_restart_keeps_the_job_and_stop_cancels_it(
    slurm_cluster: SlurmCluster, slurm_hub: HubThread
) -> None:
    run_id = submit(slurm_hub, ["sleep", "300"])
    job_id = job_id_of(slurm_hub, run_id)
    wait_until(
        lambda: slurm_cluster.job_state(job_id) == "RUNNING",
        timeout=120,
        what=f"job {job_id} RUNNING",
    )
    wait_remote_status(slurm_hub, "cluster", run_id, "running", timeout=4 * SLURM_POLL)

    # kill the env server: the hub restarts it; startup repair must keep the job
    before = slurm_hub.hub.state("cluster")
    info = json.loads(slurm_cluster.sh("cat ~/.hypothex/serve/server.json"))
    slurm_cluster.exec("kill", str(info["pid"]))
    slurm_hub.wait_connected("cluster", timeout=180, after=before)
    assert remote_record(slurm_hub, "cluster", run_id)["status"] == "running"
    assert slurm_cluster.job_state(job_id) == "RUNNING"

    body = {"command_id": uuid.uuid4().hex}
    slurm_hub.client("cluster").post_json(f"/api/v1/runs/{run_id}/stop", body)
    wait_until(
        lambda: slurm_cluster.job_state(job_id).startswith("CANCELLED"),
        timeout=60,
        what=f"job {job_id} CANCELLED by scancel",
    )
    wait_remote_status(slurm_hub, "cluster", run_id, "killed", timeout=4 * SLURM_POLL)
    wait_mirrored(slurm_hub.ctx, run_id, "killed", timeout=120)


def test_job_lost_with_its_node_is_marked_lost(
    slurm_cluster: SlurmCluster, slurm_hub: HubThread
) -> None:
    run_id = submit(slurm_hub, ["sleep", "300"])
    job_id = job_id_of(slurm_hub, run_id)
    wait_until(
        lambda: slurm_cluster.job_state(job_id) == "RUNNING",
        timeout=120,
        what=f"job {job_id} RUNNING",
    )
    try:
        slurm_cluster.compose("kill", "c1")  # the node dies: no exit record is ever written
        wait_until(
            lambda: slurm_cluster.job_state(job_id) == "NODE_FAIL",
            timeout=120,
            what=f"job {job_id} NODE_FAIL",
        )
        record = wait_remote_status(slurm_hub, "cluster", run_id, "lost", timeout=5 * SLURM_POLL)
        assert record["executor"]["slurm_job_id"] == job_id
        wait_mirrored(slurm_hub.ctx, run_id, "lost", timeout=120)
    finally:
        slurm_cluster.compose("start", "c1")
        slurm_cluster.exec(
            "scontrol", "update", "nodename=c1", "state=resume", user="root", check=False
        )
        wait_until(lambda: slurm_cluster.node_state() == "idle", timeout=180, what="c1 idle")
