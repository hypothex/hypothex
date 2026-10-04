import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hypothex.api import app as app_module
from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.gpus import GpuInfo
from hypothex.core.ids import utcnow
from hypothex.core.records import CostTotals, RunStatus
from hypothex.remote.config import HostKind, HostSpec, SlurmDefaults, load_hosts, save_hosts
from tests.api.envserver import host_state, remote_hub, wait_until, write_fake_gpus, write_hosts
from tests.factories import make_record, seed_finished_run

BASE_URL = "http://127.0.0.1:7777"


def test_hosts_lists_the_hub_then_each_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpus = write_fake_gpus(tmp_path / "gpus.json", 8, external=(3,))
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(gpus))
    with remote_hub(tmp_path) as r:
        rows = r.client.get("/api/v1/hosts").json()
        assert [row["name"] for row in rows] == ["local", "gpu1"]
        local, gpu1 = rows
        assert local["kind"] == "local" and local["state"]["state"] == "connected"
        assert local["state"]["kind"] == "local"
        assert local["state"]["environment_id"] == r.hub.descriptor.environment_id
        assert local["projects"] == ["toy"] and local["slurm"] is None
        assert gpu1["kind"] == "ssh" and gpu1["state"]["state"] == "connected"
        assert gpu1["state"]["environment_id"] == r.env.descriptor.environment_id
        assert len(gpu1["gpus"]) == 8
        assert [g["index"] for g in gpu1["gpus"] if g["external"]] == [3]
        assert (gpu1["queue"], gpu1["slurm"], gpu1["cost_today_usd"]) == (0, None, 0.0)
        assert gpu1["projects"] == ["toy"]
        assert gpu1["usd_per_gpu_hour"] == 2.0 and local["usd_per_gpu_hour"] is None


def test_disconnect_and_connect(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        out = r.client.post("/api/v1/hosts/gpu1/disconnect", json={}).json()
        assert (out["name"], out["state"]) == ("gpu1", "disabled")
        assert host_state(r.client, "gpu1") == "disabled"
        assert r.client.post("/api/v1/hosts/gpu1/connect", json={}).json()["name"] == "gpu1"
        wait_until(lambda: host_state(r.client, "gpu1") == "connected", timeout=30)
        resp = r.client.post("/api/v1/hosts/nope/connect", json={})
        assert resp.status_code == 400 and "hx hosts add nope" in resp.json()["error"]


def test_slurm_counts_and_cost_today(tmp_path: Path) -> None:
    with remote_hub(tmp_path, kind="slurm", slurm=SlurmDefaults(partition="gpu")) as r:
        eid = r.env.descriptor.environment_id
        for run_id, status in (
            ("p1", RunStatus.QUEUED),
            ("p2", RunStatus.QUEUED),
            ("u1", RunStatus.RUNNING),
        ):
            r.hub.create_run(make_record(run_id, environment_id=eid, status=status))
        r.hub.create_run(
            make_record(
                "f1",
                environment_id=eid,
                status=RunStatus.FINISHED,
                ended_at=utcnow(),
                cost=CostTotals(gpu_hours=2.0, gpu_usd=1.0, api_usd=0.25, total_usd=1.25),
            )
        )
        r.hub.create_run(
            make_record(
                "old",
                environment_id=eid,
                status=RunStatus.FINISHED,
                created_at=utcnow() - timedelta(days=3),
                ended_at=utcnow() - timedelta(days=2),
                cost=CostTotals(total_usd=9.0),
            )
        )
        r.hub.create_run(  # an eight-day run that ended today counts today
            make_record(
                "long",
                environment_id=eid,
                status=RunStatus.FINISHED,
                created_at=utcnow() - timedelta(days=8),
                ended_at=utcnow(),
                cost=CostTotals(total_usd=2.0),
            )
        )
        row = next(x for x in r.client.get("/api/v1/hosts").json() if x["name"] == "gpu1")
        # the env server has no SLURM here (the isolation stub refuses scontrol): no comments
        assert row["kind"] == "slurm" and row["slurm"] == {
            "pending": 2,
            "running": 1,
            "comment_accounting": False,
        }
        assert row["cost_today_usd"] == 3.25


def test_run_detail_has_host_state(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        seed_finished_run(r.env, r.env_repo, "e1")
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        assert r.client.get("/api/v1/runs/e1").json()["host_state"] == "connected"
        seed_finished_run(r.hub, r.hub_repo, "h1")
        assert r.client.get("/api/v1/runs/h1").json()["host_state"] is None
        r.client.post("/api/v1/hosts/gpu1/disconnect", json={})
        assert r.client.get("/api/v1/runs/e1").json()["host_state"] == "disabled"


def test_hub_off_shows_hosts_disabled(home: Path) -> None:
    write_hosts(home, {"gpu1": HostSpec(route="url", url="http://127.0.0.1:9")})
    app = create_app(home, background_repair=False, hub=False)
    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        gpu1 = client.get("/api/v1/hosts").json()[1]
        assert gpu1["state"]["state"] == "disabled"
        assert gpu1["state"]["message"] == "hub not started"
        assert gpu1["gpus"] == [] and gpu1["queue"] == 0


def test_local_row_reads_gpus_through_the_cache(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def fake_query() -> list[GpuInfo]:
        calls.append(1)
        return []

    monkeypatch.setattr(app_module, "query_gpus", fake_query)
    app = create_app(home, background_repair=False, hub=False)
    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        for _ in range(3):
            assert client.get("/api/v1/hosts").json()[0]["name"] == "local"
    assert len(calls) == 1  # nvidia-smi at most every GPU_CACHE_SECONDS


def test_a_bad_environments_file_does_not_stop_the_server(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "environments.yaml").write_text("environments: {gpu1: [\n")
    with TestClient(create_app(home, background_repair=False), base_url=BASE_URL) as client:
        rows = client.get("/api/v1/hosts").json()
        assert [r["name"] for r in rows] == ["local"]
        assert "environments.yaml" in rows[0]["state"]["message"]
        assert client.get("/.well-known/hypothex/environment").status_code == 200
        resp = client.post("/api/v1/hosts/gpu1/connect", json={})
        assert resp.status_code == 400 and "environments.yaml" in resp.json()["error"]


def test_every_host_row_carries_the_stale_banner_hours(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        rows = r.client.get("/api/v1/hosts").json()
        assert [row["stale_banner_hours"] for row in rows] == [24.0, 24.0]
        hosts = load_hosts(r.hub.layout)
        save_hosts(r.hub.layout, hosts.model_copy(update={"stale_banner_hours": 6.0}))
        rows = r.client.post("/api/v1/hosts/reload", json={}).json()
        assert [row["stale_banner_hours"] for row in rows] == [6.0, 6.0]


def test_reload_applies_a_removed_host_and_new_project_maps(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        hosts = load_hosts(r.hub.layout)
        spec = hosts.environments["gpu1"]
        mapped = spec.model_copy(update={"projects": {**spec.projects, "toy2": "/srv/toy2"}})
        save_hosts(r.hub.layout, hosts.model_copy(update={"environments": {"gpu1": mapped}}))
        rows = r.client.post("/api/v1/hosts/reload", json={}).json()
        assert rows[1]["projects"] == ["toy", "toy2"]
        save_hosts(r.hub.layout, hosts.model_copy(update={"environments": {}}))
        rows = r.client.post("/api/v1/hosts/reload", json={}).json()
        assert [row["name"] for row in rows] == ["local"]
        assert r.client.get("/api/v1/hosts").json() == rows


def test_runs_filter_by_environment_and_honour_large_limits(home: Path, ctx: Context) -> None:
    for i in range(1005):
        ctx.index.upsert_run(make_record(f"r{i:04d}", environment_id="env-b" if i % 2 else "env-a"))
    with TestClient(create_app(home, background_repair=False, hub=False), base_url=BASE_URL) as c:
        assert len(c.get("/api/v1/runs", params={"limit": 1005}).json()) == 1005
        only_b = c.get("/api/v1/runs", params={"environment_id": "env-b", "limit": 2000}).json()
        assert len(only_b) == 502 and {r["environment_id"] for r in only_b} == {"env-b"}


def test_runs_page_by_keyset_without_gaps_or_repeats(home: Path, ctx: Context) -> None:
    start = utcnow().replace(microsecond=123456)
    for i in range(11):  # pairs share a created_at: run_id breaks the tie
        when = start + timedelta(seconds=i // 2)
        ctx.index.upsert_run(make_record(f"r{i:02d}", environment_id="env-a", created_at=when))
    with TestClient(create_app(home, background_repair=False, hub=False), base_url=BASE_URL) as c:
        everything = [r["run_id"] for r in c.get("/api/v1/runs").json()]
        pages: list[list[str]] = []
        cursor: dict[str, str] = {}
        for _ in range(len(everything) + 1):  # bounded: a cursor that is ignored never ends
            page = c.get("/api/v1/runs", params={"limit": 3, **cursor}).json()
            if not page:
                break
            pages.append([r["run_id"] for r in page])
            last = page[-1]
            cursor = {"before_created_at": last["created_at"], "before_run_id": last["run_id"]}
        assert [len(p) for p in pages] == [3, 3, 3, 2]
        assert [rid for p in pages for rid in p] == everything
        half = c.get("/api/v1/runs", params={"before_run_id": "r05"})
        assert half.status_code == 400 and "together" in half.json()["error"]


def test_disconnected_hosts_stay_disconnected_after_a_restart(tmp_path: Path) -> None:
    with remote_hub(tmp_path) as r:
        r.client.post("/api/v1/hosts/gpu1/disconnect", json={})
        again = create_app(r.hub.layout.home, background_repair=False)
        with TestClient(again, base_url=BASE_URL) as client:
            assert host_state(client, "gpu1") == "disabled"
            client.post("/api/v1/hosts/gpu1/connect", json={})
            wait_until(lambda: host_state(client, "gpu1") == "connected", timeout=30)
        assert not json.loads((r.hub.layout.home / "hosts_disabled.json").read_text())


def _gpu1_row(client: TestClient | httpx.Client) -> dict:
    return next(x for x in client.get("/api/v1/hosts").json() if x["name"] == "gpu1")


@pytest.mark.parametrize("kind", ["ssh", "slurm"])
def test_a_disconnected_host_keeps_its_totals(tmp_path: Path, kind: HostKind) -> None:
    slurm = SlurmDefaults(partition="gpu") if kind == "slurm" else None
    with remote_hub(tmp_path, kind=kind, slurm=slurm) as r:
        eid = r.env.descriptor.environment_id
        seed_finished_run(r.env, r.env_repo, "e1")  # mirrored: the hub keeps gpu1's cursor
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        r.hub.create_run(make_record("q1", environment_id=eid, status=RunStatus.QUEUED))
        r.hub.create_run(
            make_record(
                "f1",
                environment_id=eid,
                status=RunStatus.FINISHED,
                ended_at=utcnow(),
                cost=CostTotals(total_usd=12.0),
            )
        )
        before = _gpu1_row(r.client)
        assert before["cost_today_usd"] >= 12.0
        r.client.post("/api/v1/hosts/gpu1/disconnect", json={})
        after = _gpu1_row(r.client)
        assert after["state"]["state"] == "disabled"
        assert after["cost_today_usd"] == before["cost_today_usd"]
        if kind == "slurm":
            assert after["slurm"]["pending"] == before["slurm"]["pending"] == 1
            assert after["slurm"]["running"] == before["slurm"]["running"]
        # a restarted hub has never seen gpu1 connected: the saved cursor names its env
        again = create_app(r.hub.layout.home, background_repair=False)
        with TestClient(again, base_url=BASE_URL) as client:
            assert _gpu1_row(client)["cost_today_usd"] == before["cost_today_usd"]
