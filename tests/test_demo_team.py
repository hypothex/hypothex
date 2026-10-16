import json
import os
import shutil
import stat
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from hypothex.auth.pairing import parse_pairing_url
from hypothex.auth.store import AuthStore
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.notebook import list_days
from hypothex.core.queries import get_leaderboard, show_run
from hypothex.core.settings import StorageSettings, load_settings
from hypothex.core.storage import CleanPolicy, plan_clean
from hypothex.demo import seed_demo
from hypothex.demo_team import (
    PAIRING_FILE,
    SLACK_ENV,
    TEAM_DIR,
    demo_team_running,
    seed_demo_team,
)
from hypothex.notify.notifier import Notifier
from hypothex.remote.config import load_hosts
from tests.factories import git


@pytest.fixture(scope="module")
def team_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    home = tmp_path_factory.mktemp("team") / "home"
    seed_demo(home, kinds=["generic", "training"])
    seed_demo_team(home)
    return home


def test_auth_users_and_settings(team_home: Path) -> None:
    ctx = Context.open(team_home)
    settings = load_settings(ctx.layout)
    assert settings.server.auth == "on" and settings.digest.enabled
    assert settings.notify.projects["toy-classifier"].channels == ["slack", "email"]
    users = {u.name: u.role for u in AuthStore(ctx.layout).users()}
    assert users == {"sv": "admin", "alice": "launch"}


def test_baselines_on_the_toy_task(team_home: Path) -> None:
    board = get_leaderboard(Context.open(team_home), "toy-test", "toy-classifier")
    assert [b.name for b in board.baselines] == ["SVC (Hsu 2003)", "Smith 2024"]
    assert [b.version_match["accuracy"] for b in board.baselines] == [True, False]


def test_storage_fixtures_plan_two_items_and_refuse_two(team_home: Path) -> None:
    ctx = Context.open(team_home)
    plan = plan_clean(ctx, None, CleanPolicy(), created_by="human:sv", settings=StorageSettings())
    assert sorted(i.run_id for i in plan.items) == ["st-a", "st-b"]
    assert {r["run_id"]: r["reason"] for r in plan.refused} == {
        "st-parent": "used by st-child",
        "st-prot": "protected",
    }
    (cleaned,) = show_run(ctx, "st-done").cleaned
    assert cleaned.bytes == 4_200_000_000


def test_notebook_and_weekly_summary(team_home: Path) -> None:
    ctx = Context.open(team_home)
    assert list_days(ctx, "toy-classifier") and list_days(ctx, "rxn-forward")
    texts = "".join(
        (ctx.layout.project_dir("toy-classifier") / "notebook" / f"{d['day']}.md").read_text()
        for d in list_days(ctx, "toy-classifier")
    )
    assert "— digest" in texts and "[[run:st-parent]]" in texts and "— human:alice" in texts


def test_outbox_has_every_state(team_home: Path) -> None:
    ctx = Context.open(team_home)
    statuses = {e.status for e in Notifier(ctx, load_settings(ctx.layout)).recent()}
    assert statuses == {"pending", "sending", "sent", "failed", "skipped"}


def test_shared_fake_host(team_home: Path) -> None:
    marker = json.loads((team_home / "demo-hosts" / "hosts.json").read_text())
    assert "shared" in [h["name"] for h in marker]
    spec = load_hosts(Context.open(team_home).layout).environments["shared"]
    assert (spec.route, spec.token_env) == ("url", "HX_DEMO_SHARED_TOKEN")
    secrets_file = team_home / "secrets.env"
    assert stat.S_IMODE(secrets_file.stat().st_mode) == 0o600
    value = secrets_file.read_text().split("HX_DEMO_SHARED_TOKEN=", 1)[1].splitlines()[0]
    assert value and value not in (team_home / "demo-hosts" / "hosts.json").read_text()


@pytest.mark.parametrize("nested", [False, True])
def test_shared_demo_pins_its_own_project_and_stages_it(tmp_path: Path, nested: bool) -> None:
    from hypothex.core.execution import (
        RunRequest,
        checkout_run_tree,
        prepare_run,
        release_worktree,
    )

    outer_head = None
    if nested:
        git(tmp_path, "init", "-q")
        git(tmp_path, "config", "user.name", "Outer repository")
        git(tmp_path, "config", "user.email", "outer@example.invalid")
        (tmp_path / "outside.txt").write_text("not demo code\n")
        git(tmp_path, "add", "outside.txt")
        git(tmp_path, "commit", "-qm", "outer repository")
        outer_head = git(tmp_path, "rev-parse", "HEAD")
    home = tmp_path / "demo-home"
    seed_demo(home, kinds=["generic", "training"])
    seed_demo_team(home)
    hub = Context.open(home)
    repo = Path(hub.store.load_project("toy-classifier").repo)
    assert Path(git(repo, "rev-parse", "--show-toplevel")).resolve() == repo.resolve()
    commit = git(repo, "rev-parse", "HEAD")
    assert commit != outer_head
    host = Context.open(home / "demo-hosts" / "shared")
    host_repo = Path(host.store.load_project("toy-classifier").repo)
    assert Path(git(host_repo, "rev-parse", "--show-toplevel")).resolve() == host_repo.resolve()
    assert git(host_repo, "rev-parse", "HEAD") == commit
    run = prepare_run(
        host,
        RunRequest(
            repo=host_repo,
            command=["python", "train.py"],
            commit=commit,
            queue=True,
            owner="alice",
        ),
    )
    try:
        tree = checkout_run_tree(host, run)
        assert tree is not None
        assert (tree / "hypothex.yaml").is_file()
        assert (tree / "train.py").is_file()
        assert not (tree / "outside.txt").exists()
        assert run.owner == "alice"
    finally:
        assert release_worktree(host, run)
    if nested:
        assert git(tmp_path, "rev-parse", "HEAD") == outer_head
        assert git(tmp_path, "diff", "--name-only") == ""


def test_team_refuses_an_unrelated_registered_repo_before_writing(tmp_path: Path) -> None:
    from hypothex.core.errors import ConfigError

    home = tmp_path / "home"
    seed_demo(home, kinds=["generic", "training"])
    ctx = Context.open(home)
    entry = ctx.store.load_project("toy-classifier")
    outside = tmp_path / "user-project"
    shutil.copytree(entry.repo, outside)
    config = (outside / "hypothex.yaml").read_bytes()
    ctx.store.save_project(entry.model_copy(update={"repo": str(outside)}))
    with pytest.raises(ConfigError, match="generated.*demo repository"):
        seed_demo_team(home)
    assert (outside / "hypothex.yaml").read_bytes() == config
    assert not (outside / ".git").exists()
    assert not (outside / "train.py").exists()
    assert not (home / TEAM_DIR).exists()


def test_running_team_gives_links_and_working_channels(team_home: Path) -> None:
    ctx = Context.open(team_home)
    with demo_team_running(team_home, "http://127.0.0.1:7777") as links:
        assert set(links) == {"sv", "alice"}
        assert parse_pairing_url(links["alice"])[0] == "http://127.0.0.1:7777"
        path = team_home / TEAM_DIR / PAIRING_FILE
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        notifier = Notifier(ctx, load_settings(ctx.layout))
        assert notifier.send_test("slack") == {"ok": True, "error_class": None}
        assert notifier.send_test("email") == {"ok": True, "error_class": None}
    assert SLACK_ENV not in os.environ


def test_demo_hosts_start_the_shared_host(team_home: Path) -> None:
    from hypothex.demo import demo_hosts_running

    with demo_hosts_running(team_home, ready_timeout=60) as started:
        assert started == []  # no fake GPU host: no live sweep runs
        url = load_hosts(Context.open(team_home).layout).environments["shared"].url
        assert url is not None and url.startswith("http://127.0.0.1:")
        # a token, not --no-auth: the hub's forwards keep each run's owner on the host
        assert httpx.get(f"{url}/api/v1/projects", timeout=5).status_code == 401


@pytest.mark.parametrize("team", [False, True])
def test_default_demo_keeps_all_current_kinds_and_extras(tmp_path: Path, team: bool) -> None:
    from hypothex.demo import DEMO_EXTRAS, DEMO_TASKS

    home = tmp_path / "default-demo"
    args = ["--home", str(home), "demo", "--json"]
    if team:
        args.append("--with-team")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    expected = {**DEMO_TASKS, **DEMO_EXTRAS}
    assert set(data) == set(expected) | ({"team"} if team else set())
    assert {key: data[key] for key in expected} == {
        key: f"{project}/{task}" for key, (project, task) in expected.items()
    }
    ctx = Context.open(home)
    assert all(ctx.store.load_project(project) for project, _ in expected.values())


def test_cli_seeds_the_team(tmp_path: Path) -> None:
    home = tmp_path / "cli-home"
    result = CliRunner().invoke(
        app, ["--home", str(home), "demo", "--kinds", "generic,training", "--with-team", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["team"]["users"] == {"sv": "admin", "alice": "launch"}
    assert set(json.loads(result.stdout)) == {"generic", "training", "team"}
    refused = CliRunner().invoke(
        app, ["--home", str(tmp_path / "x"), "demo", "--kinds", "generic", "--with-team"]
    )
    assert refused.exit_code == 1 and "--with-team needs" in str(refused.exception)


def test_demo_channel_environment_restored_on_failure(
    team_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = "http://127.0.0.1:9/previous-synthetic-sink"
    monkeypatch.setenv(SLACK_ENV, previous)
    with (
        pytest.raises(RuntimeError, match="synthetic body failure"),
        demo_team_running(team_home, "http://127.0.0.1:7777"),
    ):
        assert os.environ[SLACK_ENV] != previous
        raise RuntimeError("synthetic body failure")
    assert os.environ[SLACK_ENV] == previous


def test_partial_demo_channel_start_closes_first_sink(
    team_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex import demo_team

    stopped: list[bool] = []

    class Sink:
        def stop(self) -> None:
            stopped.append(True)

    def fail_smtp() -> None:
        raise OSError("synthetic bind failure")

    monkeypatch.setattr(demo_team, "_Webhook", Sink)
    monkeypatch.setattr(demo_team, "_Smtp", fail_smtp)
    with (
        pytest.raises(OSError, match="synthetic bind failure"),
        demo_team_running(team_home, "http://127.0.0.1:7777"),
    ):
        pytest.fail("partial startup must not yield")
    assert stopped == [True]


def test_configured_demo_host_token_cannot_fall_back_to_no_auth(tmp_path: Path) -> None:
    from hypothex.core.errors import StoreError
    from hypothex.core.layout import Layout
    from hypothex.demo import _DemoHost, _start_demo_host

    host = _DemoHost(
        name="shared",
        kind="ssh",
        home=str(tmp_path / "host"),
        repo=str(tmp_path / "repo"),
        token_env="HX_MISSING_DEMO_TOKEN",
    )
    with pytest.raises(StoreError, match="token is unavailable"):
        _start_demo_host(host, Layout(tmp_path / "hub"))
