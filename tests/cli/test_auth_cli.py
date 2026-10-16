import json
import socket
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.api.app import create_app
from hypothex.auth.pairing import pairing_url
from hypothex.auth.store import AuthStore
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.mcp.server import hub_call
from hypothex.remote.config import HostSpec, load_host_tokens, load_hosts
from tests.api.authkit import OWNER, auth_app, token_for
from tests.api.envserver import serve_app, write_hosts
from tests.factories import make_record, write_toy_project

runner = CliRunner()


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, AuthStore]]:
    home = tmp_path / "hub-home"
    Context.open(home).register_project(write_toy_project(tmp_path / "toy"))
    app_ = auth_app(home)
    with serve_app(app_) as url:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", url)
        yield url, app_.state.auth


def hx(home: Path, *args: str, env: dict[str, str] | None = None) -> Any:
    result = runner.invoke(
        app, ["--home", str(home), *args, "--json"], env=env, catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def fails(home: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = runner.invoke(app, ["--home", str(home), *args], env=env)
    assert result.exit_code == 1
    return str(result.exception)


def owner_env(store: AuthStore) -> dict[str, str]:
    return {"HYPOTHEX_HUB_TOKEN": token_for(store, "sv", "admin")}


def login_alice(tmp_path: Path, url: str, store: AuthStore, **env: str) -> Path:
    new = ["--new-user"] if store.get_user("alice") is None else []
    args = ["pair", *new, "--user", "alice", "--scope", "launch"]
    offer = hx(tmp_path / "owner", *args, env=owner_env(store))
    laptop = tmp_path / "alice-laptop"
    out = hx(laptop, "login", offer["url"], "--device", "MacBook", env=env or None)
    assert (out["hub"], out["user"], out["scope"]) == (url, "alice", "launch")
    return laptop


def test_pair_then_login_from_another_home(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store)
    path = laptop / "auth" / "hub-tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    token = json.loads(path.read_text())[url]["token"]
    me = hx(laptop, "whoami")
    assert (me["user"], me["scope"], me["client"]) == ("alice", "launch", "cli")
    raw = runner.invoke(app, ["--home", str(laptop), "whoami", "--json"])
    assert token not in raw.stdout


def test_pair_prints_a_qr_code_and_the_link(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    _, store = hub
    result = runner.invoke(
        app, ["--home", str(tmp_path / "o"), "pair", "--user", "sv", "--scope", "read"],
        env=owner_env(store),
    )  # fmt: skip
    assert result.exit_code == 0 and "█" in result.stdout and "/pair#p_" in result.stdout
    # a host link must be admin: the hub would refuse to redeem anything less as host
    message = fails(tmp_path / "o", "pair", "--client", "host", "--scope", "launch")
    assert message == "--client host needs --scope admin"


def test_agent_login_is_an_agent_session(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store, HYPOTHEX_AGENT="claude")
    assert hx(laptop, "whoami")["client"] == "agent"


def test_sessions_users_and_disable(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store)
    mine = hx(laptop, "sessions", "list")
    assert [s["user"] for s in mine] == ["alice"]
    owner = owner_env(store)
    every = hx(tmp_path / "owner", "sessions", "list", "--all", env=owner)
    assert {"sv", "alice"} <= {s["user"] for s in every}
    users = hx(tmp_path / "owner", "users", "list", env=owner)
    assert {u["name"]: u["role"] for u in users}["alice"] == "launch"
    assert "admin" in fails(laptop, "users", "list")
    hx(tmp_path / "owner", "users", "disable", "alice", env=owner)
    assert "401" in fails(laptop, "whoami")


def test_revoke_and_logout(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store)
    session = hx(laptop, "whoami")["session_id"]
    hx(tmp_path / "owner", "sessions", "revoke", session, env=owner_env(store))
    assert "401" in fails(laptop, "whoami")
    other = login_alice(tmp_path / "again", url, store)
    assert hx(other, "logout") == {"hub": url, "logged_out": True}
    assert json.loads((other / "auth" / "hub-tokens.json").read_text()) == {}


def test_hub_calls_carry_the_callers_agent(hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    alice = token_for(store, "alice", "launch")
    path = "/api/v1/projects/toy/notebook/today"
    day = hub_call("POST", path, {"text": "from an agent"}, url=url, token=alice, agent="claude")
    assert "— agent:claude@alice" in day["text"]  # not human:alice: the header names the agent
    plain = hub_call("POST", path, {"text": "by hand"}, url=url, token=alice)
    assert "— human:alice" in plain["text"]


def test_a_logged_in_cli_reads_the_hub(tmp_path: Path, hub: tuple[str, AuthStore]) -> None:
    url, store = hub
    laptop = login_alice(tmp_path, url, store)
    assert [p["project"] for p in hx(laptop, "projects")] == ["toy"]
    assert {t["name"] for t in hx(laptop, "tasks")} == {"toy-acc", "toy-broken"}
    hub_ctx = Context.open(tmp_path / "hub-home")
    for run_id, owner in (("a1", "alice"), ("s1", "sv")):
        hub_ctx.create_run(
            make_record(run_id, owner=owner, environment_id=hub_ctx.descriptor.environment_id)
        )
    assert [r["run_id"] for r in hx(laptop, "runs", "--owner", "me")] == ["a1"]
    assert {r["run_id"] for r in hx(laptop, "runs")} == {"a1", "s1"}


def test_owner_me_needs_a_hub(tmp_path: Path) -> None:
    assert "hub" in fails(tmp_path / "solo", "runs", "--owner", "me")


@pytest.mark.parametrize("hostname", ["lab", "h" * 60, "h" * 61, "h" * 64, "h" * 200])
def test_hosts_pair_and_add_with_a_token_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hostname: str
) -> None:
    """Generated host labels fit the pairing API, including their hub prefix."""
    monkeypatch.setattr(socket, "gethostname", lambda: hostname)
    lab = create_app(tmp_path / "lab", background_repair=False, kind="ssh", auth=True)
    lab_store: AuthStore = lab.state.auth
    lab_store.ensure_owner("sv")
    with serve_app(lab) as lab_url:
        hub_home = tmp_path / "hub-home"
        other = HostSpec(route="url", url="http://127.0.0.1:9")
        write_hosts(hub_home, {"lab": HostSpec(route="url", url=lab_url), "other": other})
        offer, secret = lab_store.create_offer(issuer=OWNER, user="sv", scope="admin")
        link = pairing_url(lab_url, offer.id, secret)
        assert "the link is for" in fails(hub_home, "hosts", "pair", "other", link)
        out = hx(hub_home, "hosts", "pair", "lab", link)  # the refused try did not use it
        assert (out["name"], out["user"], out["scope"]) == ("lab", "sv", "admin")
        paired = load_host_tokens(Context.open(hub_home).layout)["lab"]
        assert paired["url"] == lab_url.rstrip("/")
        assert lab_store.authenticate(paired["token"]) is not None
        added = hx(hub_home, "hosts", "add", "lab2", "--url", lab_url, "--token-env", "LAB_TOKEN")
        assert added["host"]["token_env"] == "LAB_TOKEN"
        offer2, secret2 = lab_store.create_offer(issuer=OWNER, user="sv", scope="admin")
        hx(
            hub_home,
            "hosts",
            "add",
            "lab3",
            "--url",
            lab_url,
            "--pair",
            pairing_url(lab_url, offer2.id, secret2),
        )
        sessions = lab_store.sessions()
        assert len(sessions) == 2
        assert all(session.client == "host" for session in sessions)
        assert {session.device for session in sessions} == {f"hub:{hostname}"[:64]}
    layout = Context.open(hub_home).layout
    assert set(load_host_tokens(layout)) == {"lab", "lab3"}
    assert load_hosts(layout).environments["lab2"].token_env == "LAB_TOKEN"


@pytest.mark.parametrize("credential", ["environment", "login"])
def test_authenticated_loopback_runs_merge_and_resolve_raw_owner(
    tmp_path: Path, hub: tuple[str, AuthStore], monkeypatch: pytest.MonkeyPatch, credential: str
) -> None:
    """Both supported credential sources exercise the real authenticated runs route."""
    from hypothex.auth.client import HubLogin, save_hub_login
    from hypothex.mcp import server

    url, store = hub
    laptop = tmp_path / "merge-laptop"
    local = Context.open(laptop)
    remote = Context.open(tmp_path / "hub-home")
    for ctx, rid, owner in (
        (local, "a-local", "alice"),
        (local, "x-local", "sv"),
        (local, "b-dup", "alice"),
        (remote, "b-dup", "alice"),
        (remote, "c-hub", "alice"),
        (remote, "y-hub", "sv"),
    ):
        ctx.create_run(
            make_record(
                rid,
                owner=owner,
                environment_id=ctx.descriptor.environment_id,
                hypothesis="remote" if ctx is remote else "local",
            )
        )
    token = token_for(store, "alice", "read")
    principal = store.authenticate(token)
    assert principal is not None
    if credential == "login":
        save_hub_login(
            local.layout,
            url,
            HubLogin(
                token=token,
                user="stale-display-name",
                scope="read",
                session_id=principal.session_id,
            ),
        )
    else:
        monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", token)
        assert not (laptop / "auth" / "hub-tokens.json").exists()
    monkeypatch.setenv("USER", "different-os-user")
    request = server._hub_request
    calls: list[tuple[str, str | None]] = []

    def capture(method: str, path: str, **kwargs: Any) -> Any:
        calls.append((path, kwargs["headers"].get("Authorization")))
        return request(method, path, **kwargs)

    monkeypatch.setattr(server, "_hub_request", capture)
    rows = hx(laptop, "runs", "--owner", "me")
    assert {r["run_id"] for r in rows} == {"a-local", "b-dup", "c-hub"}
    assert next(r for r in rows if r["run_id"] == "b-dup")["hypothesis"] == "remote"
    assert all("host_state" in r for r in rows)
    assert any("owner=me" in path for path, _ in calls)
    assert all(auth == f"Bearer {token}" for _, auth in calls)
    if credential == "login":
        owner_token = token_for(store, "sv", "admin")
        rows = hx(laptop, "runs", "--owner", "me", env={"HYPOTHEX_HUB_TOKEN": owner_token})
        assert {r["run_id"] for r in rows} == {"x-local", "y-hub"}


def test_saved_login_is_never_sent_to_another_hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different URL never receives the saved session token."""
    from hypothex.auth.client import HubLogin, save_hub_login
    from hypothex.core.layout import Layout
    from hypothex.mcp.server import resolve_hub_token

    home = tmp_path / "isolated-login"
    save_hub_login(
        Layout(home),
        "http://127.0.0.1:19991",
        HubLogin(
            token="only-for-original",
            user="alice",
            scope="read",
            session_id="s_original",
        ),
    )
    monkeypatch.delenv("HYPOTHEX_HUB_TOKEN", raising=False)
    assert resolve_hub_token("http://127.0.0.1:19992", home) is None


@pytest.mark.parametrize(
    "command", ["whoami", "pair", "export_text", "sweep_show", "sweep_cancel", "sweep_extend"]
)
def test_missing_selected_home_token_never_uses_another_home_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """An absent selected-home credential is final, not permission to rediscover."""
    import httpx

    from hypothex.auth.client import HubLogin, save_hub_login
    from hypothex.cli import main as cli_main
    from hypothex.core.layout import Layout
    from hypothex.mcp import server

    base = "http://127.0.0.1:19993"
    selected, other = tmp_path / "selected", tmp_path / "other"
    save_hub_login(
        Layout(other),
        base,
        HubLogin(
            token="different-home-admin",
            user="owner",
            scope="admin",
            session_id="s_other",
        ),
    )
    monkeypatch.setenv("HYPOTHEX_HUB_URL", base)
    monkeypatch.delenv("HYPOTHEX_HUB_TOKEN", raising=False)
    monkeypatch.setattr(server, "default_home", lambda: other)
    calls: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append(kwargs["headers"])
        assert "Authorization" not in kwargs["headers"]
        if command.startswith("sweep_"):
            return httpx.Response(404, json={"error": "missing sweep"})
        return httpx.Response(200, json={"user": "local", "scope": "admin", "auth": "off"})

    monkeypatch.setattr(server, "_hub_request", request)
    if command.startswith("sweep_"):
        from hypothex.core.errors import StoreError

        args = ["sweep", command.removeprefix("sweep_"), "s-missing", "--project", "toy"]
        if command == "sweep_extend":
            args += ["--seeds", "1,2"]
        with pytest.raises(StoreError, match="missing sweep"):
            hx(selected, *args)
    elif command == "export_text":
        monkeypatch.setattr(cli_main._state, "home", selected)
        cli_main._hub_text("/api/v1/tasks/toy/t/export", {})
    else:
        args = [command] if command == "whoami" else ["pair", "--user", "alice", "--scope", "read"]
        hx(selected, *args)
    assert len(calls) == 1
