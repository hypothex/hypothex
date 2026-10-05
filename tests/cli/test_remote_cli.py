import json
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.cli import main as cli_main
from hypothex.cli.main import app
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError, RunError, StoreError
from hypothex.core.execution import RunRequest
from hypothex.core.leaderboard import group_id_for
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.sweeps import SweepError
from hypothex.mcp.server import HubUnavailableError
from tests.api.envserver import remote_hub, wait_until
from tests.factories import PREDS_075, git, make_record, seed_finished_run

runner = CliRunner()
PY = sys.executable
SWEEP_CMD = [PY, "-c", "import sys", "{x}", "{seed}"]


def hx(*args: str) -> Any:
    argv = list(args)
    argv.insert(argv.index("--") if "--" in argv else len(argv), "--json")
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _issued_sweep(sweep_id: str) -> dict[str, Any]:
    """Read current CLI sweep state until accepted member issuance completes."""

    def current() -> dict[str, Any] | None:
        summary = hx("sweep", "show", sweep_id)
        state = summary["issuance"]["state"]
        assert state not in {"incomplete", "interrupted"}, summary["issuance"]
        return summary if state == "issued" else None

    return wait_until(current, timeout=30)


@pytest.fixture
def in_repo(toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(toy_repo)
    return toy_repo


def test_launch_on_a_host_and_wait(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        monkeypatch.chdir(r.hub_repo)
        monkeypatch.setattr(cli_main, "REMOTE_POLL_SECONDS", 0.2)
        out = hx(
            "launch", "--host", "gpu1", "-t", "toy-acc", "-H", "remote", "--wait",
            "--", PY, "-c", "print('hi')",
        )  # fmt: skip
        assert out["status"] == "finished"
        assert out["environment_id"] == r.env.descriptor.environment_id


def test_launch_from_another_checkout_sends_its_commit_and_diff(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        laptop = tmp_path / "laptop"  # spec 5.2: the CLI on another machine than the hub
        git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(laptop))
        (laptop / "marker.txt").write_text("laptop commit\n")
        git(laptop, "add", "marker.txt")
        git(laptop, "commit", "-qm", "laptop")
        git(laptop, "push", "-q", "origin", "HEAD:main")
        (laptop / "marker.txt").write_text("laptop diff\n")  # uncommitted: sent as the diff
        (laptop / "new_file.py").write_text("x = 1\n")  # untracked: named, not sent
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        monkeypatch.chdir(laptop)
        monkeypatch.setattr(cli_main, "REMOTE_POLL_SECONDS", 0.2)
        code = "print(open('marker.txt').read().strip())"
        argv = ["launch", "--host", "gpu1", "-H", "laptop", "--wait", "--json"]
        result = runner.invoke(app, [*argv, "--", PY, "-c", code], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "untracked" in result.stderr and "new_file.py" in result.stderr
        out = json.loads(result.stdout)
        assert out["status"] == "finished"
        assert out["git"]["commit"] == git(laptop, "rev-parse", "HEAD")
        log = r.env.run_dir(r.env.find_record(out["run_id"])) / "logs" / "stdout.log"
        assert log.read_text().strip() == "laptop diff"


def test_slurm_options_need_a_host(in_repo: Path) -> None:
    with pytest.raises(RunError, match="--host"):
        runner.invoke(
            app, ["launch", "--partition", "gpu", "--", PY, "-c", "1"], catch_exceptions=False
        )


def test_local_launch_passes_gpus_and_queue(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[RunRequest] = []

    def fake_launch(c: Context, req: RunRequest) -> RunRecord:
        seen.append(req)
        return make_record("fake1")

    monkeypatch.setattr(cli_main, "launch_run", fake_launch)
    assert (
        hx("launch", "--gpus", "2", "--queue", "-H", "h", "--", PY, "-c", "1")["run_id"] == "fake1"
    )
    assert (seen[0].gpus, seen[0].queue) == (2, True)


def test_remote_launch_sends_an_explicit_gpus_0_as_the_slurm_gpus(
    in_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # an omitted --gpus keeps a SLURM host's default; --gpus 0 must override it (Copy as CLI)
    bodies: list[dict[str, Any]] = []

    def fake_hub(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        assert body is not None
        bodies.append(body)
        return make_record("fake1").model_dump(mode="json")

    monkeypatch.setattr(cli_main, "_hub", fake_hub)
    monkeypatch.setattr(cli_main, "_client_checkout", lambda root: {})
    hx("launch", "--host", "mccleary", "--gpus", "0", "-H", "h", "--", PY, "-c", "1")
    hx("launch", "--host", "mccleary", "--gpus", "2", "--partition", "gpu", "-H", "h", "--", "x")
    hx("launch", "--host", "mccleary", "-H", "h", "--", PY, "-c", "1")
    assert [(b["gpus"], b["slurm"]) for b in bodies] == [
        (0, {"gpus": 0}),
        (2, {"partition": "gpu", "gpus": 2}),
        (0, None),
    ]


def test_local_sweep_commands(in_repo: Path, ctx: Context) -> None:
    out = hx(
        "sweep",
        "-t",
        "toy-acc",
        "-H",
        "x helps",
        "--grid",
        "x=1,2",
        "--seeds",
        "2",
        "--",
        *SWEEP_CMD,
    )
    sid, ids = out["spec"]["id"], out["run_ids"]
    assert len(ids) == 4 and out["spec"]["seeds"] == [1, 2]
    for rid in ids:
        control.wait_for_run(ctx, rid, timeout=60)
    assert [s["id"] for s in hx("sweeps")] == [sid]
    assert hx("sweeps", "-p", "toy")[0]["project"] == "toy"
    assert hx("sweep", "show", sid)["spec"]["id"] == sid
    more = hx("sweep", "extend", sid, "--seeds", "3")
    assert more["spec"]["seeds"] == [1, 2, 3] and len(more["run_ids"]) == 6
    for rid in more["run_ids"]:
        control.wait_for_run(ctx, rid, timeout=60)
    assert hx("sweep", "cancel", sid)["spec"]["id"] == sid
    text = runner.invoke(app, ["sweep", "show", sid]).stdout
    assert sid in text and "mean" in text
    assert "show" in runner.invoke(app, ["sweep", "--help"]).stdout


def test_local_sweep_pins_its_commit_and_diff_for_extend(in_repo: Path, ctx: Context) -> None:
    # H-3: an extend after a new commit must run the sweep's code, not the new HEAD
    head = git(in_repo, "rev-parse", "HEAD").strip()
    (in_repo / "infer.py").write_text((in_repo / "infer.py").read_text() + "# edit\n")
    out = hx(
        "sweep", "-t", "toy-acc", "-H", "pinned", "--grid", "x=1", "--seeds", "1",
        "--", *SWEEP_CMD,
    )  # fmt: skip
    assert out["spec"]["commit"] == head and "+# edit" in out["spec"]["diff"]
    for rid in out["run_ids"]:
        control.wait_for_run(ctx, rid, timeout=60)
    git(in_repo, "commit", "-qam", "move HEAD on")
    more = hx("sweep", "extend", out["spec"]["id"], "--seeds", "2")
    [new] = set(more["run_ids"]) - set(out["run_ids"])
    record = control.wait_for_run(ctx, new, timeout=60)
    assert record.git.commit == head
    groups = {group_id_for(ctx.find_record(i)) for i in more["run_ids"]}
    assert len(groups) == 1  # the new seed joined the sweep's seed group


def test_sweep_input_errors(in_repo: Path) -> None:
    with pytest.raises(SweepError, match=r"never uses \{x\}"):
        runner.invoke(
            app,
            ["sweep", "-H", "h", "--grid", "x=1,2", "--", PY, "-c", "1", "{seed}"],
            catch_exceptions=False,
        )
    with pytest.raises(RunError, match="--grid"):
        runner.invoke(app, ["sweep", "-H", "h", "--", PY, "{seed}"], catch_exceptions=False)


def test_run_mutations_of_a_host_run_go_through_the_hub(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        # a hex sha no checkout has: the host's rerun fails naming its own checkout
        seed_finished_run(r.env, r.env_repo, "e1", commit="c0ffee00")
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        assert hx("tag", "e1", "--add", "remote")["tags"] == ["remote"]
        assert r.env.find_record("e1").tags == ["remote"]  # the host's own record
        assert hx("note", "e1", "seen on gpu1") == {"ok": True}
        assert "seen on gpu1" in r.env.store.read_notes("toy", "e1")
        assert hx("star", "e1")["starred"] is True
        with pytest.raises(HypothexError, match="only queued or running"):
            runner.invoke(app, ["stop", "e1"], catch_exceptions=False)  # relayed from gpu1
        with pytest.raises(RunError, match="runs on its host; drop --foreground"):
            runner.invoke(app, ["rerun", "e1", "--foreground"], catch_exceptions=False)
        # the rerun ran on gpu1: its answer names gpu1's checkout, not the hub's
        with pytest.raises(HypothexError, match="gpu1-repo"):
            runner.invoke(app, ["rerun", "e1"], catch_exceptions=False)


def test_sweep_follow_ups_from_another_machine(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # this CLI's home is not the hub's: the sweep file exists only on the hub
    with remote_hub(tmp_path, threaded=True) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        monkeypatch.chdir(r.hub_repo)
        made = hx(
            "sweep", "--host", "gpu1", "-t", "toy-acc", "-H", "from a laptop",
            "--grid", "x=1,2", "--seeds", "1", "--", *SWEEP_CMD,
        )  # fmt: skip
        sid = made["spec"]["id"]
        assert made["issuance"]["state"] == "queued" and made["run_ids"] == []
        assert not (home / "store" / "toy" / "sweeps" / f"{sid}.yaml").exists()
        assert hx("sweep", "show", sid)["spec"]["id"] == sid
        assert hx("sweep", "show", sid, "-p", "toy")["spec"]["host"] == "gpu1"
        assert len(_issued_sweep(sid)["run_ids"]) == 2
        accepted = hx("sweep", "extend", sid, "--seeds", "2")
        assert accepted["issuance"]["state"] == "queued"
        assert accepted["issuance"]["episode"] == 2
        more = _issued_sweep(sid)
        assert more["spec"]["seeds"] == [1, 2] and len(more["run_ids"]) == 4
        assert hx("sweep", "cancel", sid)["spec"]["id"] == sid


def test_sweep_on_a_host_and_pull(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        monkeypatch.chdir(r.hub_repo)
        out = hx(
            "sweep", "--host", "gpu1", "-t", "toy-acc", "-H", "remote sweep",
            "--grid", "x=1,2", "--seeds", "1", "--", *SWEEP_CMD,
        )  # fmt: skip
        assert out["spec"]["host"] == "gpu1"
        assert out["issuance"]["state"] == "queued" and out["run_ids"] == []
        out = _issued_sweep(out["spec"]["id"])
        assert len(out["run_ids"]) == 2
        assert all(r.env.find_record(i).sweep_id == out["spec"]["id"] for i in out["run_ids"])
        record = seed_finished_run(r.env, r.env_repo, "e1", predictions=PREDS_075)
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        pulled = hx("pull", "e1", "--artifact", "predictions/predictions.jsonl")
        expected = (r.env.run_dir(record) / "predictions" / "predictions.jsonl").read_text()
        assert Path(pulled["local_path"]).read_text() == expected


def test_a_cli_on_another_machine_reads_back_what_it_launched(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONF-5: this CLI's home is not the hub's (spec 5.2); show, logs, runs, sweeps and
    # leaderboard ask the hub for what this store does not have
    with remote_hub(tmp_path, threaded=True) as r:
        laptop = tmp_path / "laptop"
        git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(laptop))
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        monkeypatch.chdir(laptop)
        rid = hx(
            "launch", "--host", "gpu1", "-t", "toy-acc", "-H", "from a laptop",
            "--", PY, "-c", "print('hello from gpu1')",
        )["run_id"]  # fmt: skip
        wait_until(lambda: r.hub.index.get_run(rid) is not None, timeout=30)
        assert not (home / "store" / "toy").exists()  # nothing of it in this store
        detail = hx("show", rid)
        assert detail["record"]["run_id"] == rid and "stdout" in str(detail["paths"])
        assert "from a laptop" in runner.invoke(app, ["show", rid]).stdout
        wait_until(lambda: "hello from gpu1" in hx("logs", rid)["text"], timeout=60)
        followed = runner.invoke(app, ["logs", rid, "--follow"], catch_exceptions=False)
        assert followed.exit_code == 0 and "hello from gpu1" in followed.stdout
        assert [row["run_id"] for row in hx("runs")] == [rid]
        assert hx("runs", "--status", "finished", "-p", "toy")[0]["run_id"] == rid
        board = hx("leaderboard", "toy-acc")
        assert board["project"] == "toy" and rid in board["unscored"]
        assert hx("leaderboard", "toy/toy-acc")["task"] == "toy-acc"
        made = hx(
            "sweep", "--host", "gpu1", "-t", "toy-acc", "-H", "s",
            "--grid", "x=1", "--seeds", "1", "--", *SWEEP_CMD,
        )  # fmt: skip
        assert [s["id"] for s in hx("sweeps")] == [made["spec"]["id"]]
        assert hx("sweeps", "-p", "toy")[0]["project"] == "toy"
        assert made["spec"]["id"] in runner.invoke(app, ["sweeps"]).stdout
        # this machine's own runs are listed with the hub's, newest first
        seed_finished_run(Context.open(home), laptop, "l1")
        rows = hx("runs", "--limit", "500")
        assert {"l1", rid} <= {row["run_id"] for row in rows}
        stamps = [(row["created_at"], row["run_id"]) for row in rows]
        assert stamps == sorted(stamps, reverse=True)
        assert len(hx("runs", "--limit", "1")) == 1
    # without a hub, an unknown run is still this store's clean "no run" error
    with pytest.raises(StoreError, match="no run"):
        runner.invoke(app, ["show", "nope"], catch_exceptions=False)
    with pytest.raises(StoreError, match="no run"):
        runner.invoke(app, ["logs", "nope"], catch_exceptions=False)


def test_hub_read_is_quiet_without_a_hub_and_warns_on_a_hub_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        raise errors.pop()

    errors: list[Exception] = [
        HypothexError("hub answered 401"),
        StoreError("no run"),
        HubUnavailableError("down"),
    ]
    monkeypatch.setattr(cli_main, "_hub", refuse)
    assert cli_main._hub_read("/api/v1/runs") is None  # no hub
    assert cli_main._hub_read("/api/v1/runs/x") is None  # 404
    assert capsys.readouterr().err == ""
    assert cli_main._hub_read("/api/v1/runs") is None  # 401: this store's answer still prints
    assert "warning: the hub did not answer /api/v1/runs: hub answered 401" in (
        capsys.readouterr().err
    )


def test_show_and_runs_mark_a_run_whose_host_is_not_connected(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONF-4b: like GET /api/v1/runs/{id}, `hx show` and `hx runs` carry host_state, so
    # a run on a stale or disabled host is not read as known to be running
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        env_id = r.env.descriptor.environment_id
        r.env.create_run(make_record("e1", environment_id=env_id, status=RunStatus.RUNNING))
        seed_finished_run(r.hub, r.hub_repo, "h1")
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        assert hx("show", "e1")["host_state"] == "connected"
        assert hx("show", "h1")["host_state"] is None
        r.client.post("/api/v1/hosts/gpu1/disconnect", json={})
        assert hx("show", "e1")["host_state"] == "disabled"
        assert "[running (host disabled)]" in runner.invoke(app, ["show", "e1"]).stdout
        rows = {row["run_id"]: row["host_state"] for row in hx("runs")}
        assert rows == {"e1": "disabled", "h1": None}
        text = runner.invoke(app, ["runs"]).stdout
        assert "running (host disabled)" in text
        assert "finished (host" not in text


def _score_rows(ctx: Context, run_id: str) -> int:
    path = ctx.run_dir(ctx.find_record(run_id)) / "scores.jsonl"
    return len(path.read_text().splitlines()) if path.exists() else 0


def test_task_reeval_scores_a_mirrored_run_on_its_host(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONF-2b: scores written into the hub's mirror copy would be replaced by the host's
    # scores.jsonl at the next mirror; the hub sends a mirrored run to its host instead
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        seed_finished_run(r.env, r.env_repo, "e1", predictions=PREDS_075)
        seed_finished_run(r.hub, r.hub_repo, "h1", predictions=PREDS_075)
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        out = hx("reeval", "--task", "toy/toy-acc")
        assert sorted(out["evaluated"]) == ["e1", "h1"] and out["skipped"] == {}
        assert _score_rows(r.env, "e1") == 1  # on the host, which owns the file
        assert _score_rows(r.hub, "h1") == 1
        wait_until(lambda: _score_rows(r.hub, "e1") == 1, timeout=30)  # mirrored back
    # no hub: this environment's runs are scored, a host's run is skipped, not written here
    out = hx("reeval", "--task", "toy-acc", "--force")
    assert out["evaluated"] == ["h1"] and out["skipped"] == {"e1": cli_main.HOST_RUN_SKIPPED}
    assert _score_rows(Context.open(home), "e1") == 1 and _score_rows(Context.open(home), "h1") == 2


def test_task_reeval_from_another_machine_goes_to_the_hub(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True) as r:  # this CLI's home is not the hub's
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        seed_finished_run(r.env, r.env_repo, "e1", predictions=PREDS_075)
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        assert hx("reeval", "--task", "toy-acc")["evaluated"] == ["e1"]
        assert hx("reeval", "--task", "toy/toy-acc", "--force")["evaluated"] == ["e1"]
        assert _score_rows(r.env, "e1") == 2
    with pytest.raises(ConfigError, match="unknown task"):  # and no hub: this store's error
        runner.invoke(app, ["reeval", "--task", "toy-acc"], catch_exceptions=False)
    with pytest.raises(StoreError, match="unknown project"):
        runner.invoke(app, ["reeval", "--task", "toy/toy-acc"], catch_exceptions=False)


def test_task_reeval_waits_for_the_hubs_full_scoring_budget(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow task must not fall back locally while the hub is still scoring it."""
    from hypothex.mcp import server

    ctx.register_project(toy_repo)
    observed: list[float] = []

    def hub_call(
        method: str,
        path: str,
        body: dict | None = None,
        *,
        token: str | None = None,
        timeout: float = 120.0,
    ) -> dict:
        observed.append(timeout)
        return {"evaluated": ["remote"], "skipped": {}, "warnings": []}

    monkeypatch.setattr(server, "hub_call", hub_call)
    # An explicit remote project is absent locally, so this takes the CLI-to-hub route.
    report = cli_main._reeval_task(
        ctx, "remote/toy-acc", None, {"metric": None, "force": False, "created_by": "human"}
    )
    assert report.evaluated == ["remote"]
    assert observed == [server.TASK_REEVAL_SECONDS]
