import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from hypothex.auth.store import AuthStore
from hypothex.cli.main import owner_name
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from hypothex.core.settings import ServerSettings, Settings, save_settings
from tests.api.envserver import wait_until
from tests.fakes import install_fake_tailscale
from tests.fakes.network import pg_child_environment

HX = [sys.executable, "-m", "hypothex.cli.main"]


@pytest.fixture(autouse=True)
def final_child_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Capture every actual exec environment after overlays and demand PG isolation."""
    original = subprocess.Popen
    captured: list[dict[str, str]] = []
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.9")
    monkeypatch.setenv("PGSERVICE", "must-not-cross-exec")

    def checked(*args: Any, **kwargs: Any) -> Any:
        if args[0][0] != sys.executable:
            return original(*args, **kwargs)
        environment = kwargs.get("env")
        assert isinstance(environment, dict), "serve tests must supply the final environment"
        captured.append(dict(environment))
        assert not any(name.startswith("PG") for name in environment)
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", checked)
    yield
    assert all(not any(name.startswith("PG") for name in env) for env in captured)


def start(home: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    full = {k: v for k, v in os.environ.items() if k != "HYPOTHEX_SERVE_TOKEN"}
    full.update(env or {})
    full = pg_child_environment(full)
    return subprocess.Popen(
        [*HX, "--home", str(home), "serve", "--port", "0", *args],
        env=full,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def info_of(home: Path) -> dict:
    # the home is claimed first and the minted token written right after: wait for the token
    def ready() -> dict | None:
        info = json.loads((home / "serve" / "server.json").read_text())
        return info if info.get("token") else None

    return wait_until(ready, timeout=30)


def stop(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    proc.wait(timeout=30)


def test_owner_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER", "Alice.Smith")
    assert owner_name() == "alicesmith"
    monkeypatch.setenv("USER", "9bad")
    assert owner_name() == "owner"


def test_serve_with_auth_mints_a_local_owner_session(tmp_path: Path) -> None:
    home = tmp_path / "h"
    proc = start(home, "--auth", env={"USER": "sv"})
    try:
        info = info_of(home)
        assert info["token"].startswith("hxs_")
        base = f"http://127.0.0.1:{info['port']}"
        wait_until(
            lambda: httpx.get(f"{base}/.well-known/hypothex/environment", timeout=2), timeout=30
        )
        assert httpx.get(f"{base}/api/v1/projects", timeout=5).status_code == 401
        auth = {"Authorization": f"Bearer {info['token']}"}
        me = httpx.get(f"{base}/api/v1/auth/me", headers=auth, timeout=5).json()
        assert (me["user"], me["scope"], me["client"], me["auth"]) == ("sv", "admin", "local", "on")
    finally:
        stop(proc)
    sessions = AuthStore(Layout(home)).sessions("sv")
    assert [s for s in sessions if s.client == "local"] == []  # revoked at stop


def test_tailscale_needs_auth(tmp_path: Path) -> None:
    done = subprocess.run(
        [*HX, "--home", str(tmp_path / "h"), "serve", "--tailscale"],
        env=pg_child_environment(dict(os.environ)),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1 and "tailscale needs server.auth: on" in done.stderr


def test_tailscale_publishes_and_unpublishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_fake_tailscale(tmp_path / "ts", monkeypatch)
    home = tmp_path / "h"
    proc = start(home, "--auth", "--tailscale", env={"USER": "sv"})
    try:
        info = info_of(home)
        port = info["port"]
        wait_until(lambda: fake.state()["serve"].get("443"), timeout=30)
        assert fake.state()["serve"] == {"443": f"http://127.0.0.1:{port}"}
        auth = {"Authorization": f"Bearer {info['token']}"}
        me = wait_until(
            lambda: httpx.get(
                f"http://127.0.0.1:{port}/api/v1/auth/me", headers=auth, timeout=2
            ).json(),
            timeout=30,
        )
        assert me["public_url"] == "https://hub.tail1234.ts.net"
    finally:
        stop(proc)
    assert fake.state()["serve"] == {}


def test_a_second_start_leaves_the_running_server_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_fake_tailscale(tmp_path / "ts", monkeypatch)
    home = tmp_path / "h"
    proc = start(home, "--auth", "--tailscale", env={"USER": "sv"})
    try:
        info = info_of(home)
        wait_until(lambda: fake.state()["serve"].get("443"), timeout=30)
        mapping = fake.state()["serve"]
        auth = {"Authorization": f"Bearer {info['token']}"}
        base = f"http://127.0.0.1:{info['port']}"
        wait_until(lambda: httpx.get(f"{base}/api/v1/auth/me", headers=auth, timeout=2), timeout=30)
        second = subprocess.run(
            [*HX, "--home", str(home), "serve", "--auth", "--tailscale", "--port", "0"],
            env=pg_child_environment({**os.environ, "USER": "sv"}),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert second.returncode == 1 and "already serves this home" in second.stderr
        assert fake.state()["serve"] == mapping  # the first server's mapping is untouched
        me = httpx.get(f"{base}/api/v1/auth/me", headers=auth, timeout=5)
        assert me.status_code == 200 and me.json()["user"] == "sv"  # its session still works
    finally:
        stop(proc)


def test_a_start_that_fails_before_serving_undoes_its_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_fake_tailscale(tmp_path / "ts", monkeypatch)
    home = tmp_path / "h"
    dead = "postgresql+psycopg://hx@127.0.0.1:1/hypothex"  # create_app cannot open the index
    save_settings(Layout(home), Settings(server=ServerSettings(index_url=dead)))
    done = subprocess.run(
        [*HX, "--home", str(home), "serve", "--auth", "--tailscale", "--port", "0"],
        env=pg_child_environment({**os.environ, "USER": "sv"}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1 and "does not answer" in done.stderr
    assert fake.state()["serve"] == {}  # unpublished
    assert [s for s in AuthStore(Layout(home)).sessions("sv") if s.client == "local"] == []
    assert not (home / "serve" / "server.json").exists()


def test_readable_secrets_file_stops_the_start(tmp_path: Path) -> None:
    home = tmp_path / "h"
    home.mkdir()
    secrets = home / "secrets.env"
    secrets.write_text("HYPOTHEX_SLACK_WEBHOOK=https://hooks.example/SECRET\n")
    secrets.chmod(0o640)
    done = subprocess.run(
        [*HX, "--home", str(home), "serve", "--port", "0"],
        env=pg_child_environment(dict(os.environ)),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1 and f"chmod 600 {secrets}" in done.stderr
    assert "SECRET" not in done.stderr.replace(str(secrets), "")


def test_scoped_claim_exposes_no_provisional_root_and_preserves_record(tmp_path: Path) -> None:
    from hypothex import __version__
    from hypothex.cli.main import _server_file, local_server_token
    from hypothex.core.environment import PROTOCOL_VERSION, load_descriptor
    from hypothex.remote.bootstrap import ServerInfo

    layout = Layout(tmp_path)
    layout.ensure()
    descriptor = load_descriptor(layout)
    info = ServerInfo(
        pid=os.getpid(),
        port=19991,
        managed=False,
        hx_version=__version__,
        protocol_version=PROTOCOL_VERSION,
        environment_id=descriptor.environment_id,
        token=None,  # scoped local claim has not minted its owner session yet
    )
    with _server_file(tmp_path, info) as set_token:
        path = tmp_path / "serve" / "server.json"
        before = json.loads(path.read_text())
        assert before["token"] is None
        with pytest.raises(ConfigError, match="no verifiable authenticated local server"):
            local_server_token(tmp_path)
        before["extra"] = {"preserved": True}
        path.write_text(json.dumps(before))
        store = AuthStore(layout)
        store.ensure_owner("sv")
        session, token = store.mint_local("sv")
        set_token(token)
        after = json.loads(path.read_text())
        assert {key: value for key, value in after.items() if key != "token"} == {
            key: value for key, value in before.items() if key != "token"
        }
        assert local_server_token(tmp_path) == token
        principal = store.authenticate(token)
        assert principal is not None and principal.session_id == session.id
        assert principal.user == "sv" and principal.client == "local"


def test_restart_cli_token_and_stdio_discovery_select_owner(tmp_path: Path) -> None:
    """Fresh and restarted scoped servers expose only their current owner session."""
    home = tmp_path / "restart"
    previous: str | None = None
    for _ in range(2):
        proc = start(home, "--auth", env={"USER": "sv"})
        try:
            info = info_of(home)
            base = f"http://127.0.0.1:{info['port']}"
            wait_until(
                lambda base=base: httpx.get(f"{base}/.well-known/hypothex/environment", timeout=2)
            )
            env = pg_child_environment({**os.environ, "HYPOTHEX_HUB_URL": base})
            env.pop("HYPOTHEX_HUB_TOKEN", None)
            token = subprocess.run(
                [*HX, "--home", str(home), "token"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout.strip()
            assert token == info["token"] and token != previous
            who = subprocess.run(
                [*HX, "--home", str(home), "whoami", "--json"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            me = json.loads(who.stdout)
            assert (me["user"], me["scope"], me["client"]) == ("sv", "admin", "local")
            # The stdio MCP entrypoint uses this resolver with the selected home.
            code = (
                "from pathlib import Path; import sys; "
                "from hypothex.mcp.server import resolve_hub_token; "
                "print(resolve_hub_token(sys.argv[1], Path(sys.argv[2])))"
            )
            discovered = subprocess.run(
                [sys.executable, "-c", code, base, str(home)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            assert discovered.stdout.strip() == token
            previous = token
        finally:
            stop(proc)
        assert AuthStore(Layout(home)).authenticate(previous) is None


@pytest.mark.parametrize("args,override", [(("--kind", "ssh"), None), ((), "explicit-host-token")])
def test_scoped_host_credential_keeps_host_provenance(
    tmp_path: Path, args: tuple[str, ...], override: str | None
) -> None:
    """An explicit override and env-server default remain host credentials."""
    home = tmp_path / "host-auth"
    env = {"USER": "sv"}
    if override is not None:
        env["HYPOTHEX_SERVE_TOKEN"] = override
    proc = start(home, "--auth", *args, env=env)
    try:
        info = info_of(home)
        auth = {"Authorization": f"Bearer {info['token']}"}
        base = f"http://127.0.0.1:{info['port']}"
        me = wait_until(lambda: httpx.get(f"{base}/api/v1/auth/me", headers=auth, timeout=2).json())
        assert (me["user"], me["scope"], me["client"]) == ("hub", "admin", "host")
        if override is not None:
            assert info["token"] == override
    finally:
        stop(proc)
    assert not AuthStore(Layout(home)).sessions("sv")


def test_start_scrubs_final_pg_environment_after_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Child isolation applies after scenario overrides, not only to the parent."""
    captured: list[dict[str, str]] = []

    class Captured(Exception):
        """Stop before a child is launched."""

    def capture(*args: object, **kwargs: object) -> None:
        captured.append(dict(kwargs["env"]))  # type: ignore[arg-type]
        raise Captured

    monkeypatch.setenv("PGSERVICE", "ambient-must-go")
    monkeypatch.setattr(subprocess, "Popen", capture)
    with pytest.raises(Captured):
        start(tmp_path / "isolated", env={"PGHOSTADDR": "override-must-go", "USER": "sv"})
    assert captured[0]["USER"] == "sv"
    assert not any(key.startswith("PG") for key in captured[0])


def test_team_demo_serves_as_seeded_owner_for_a_different_os_user(tmp_path: Path) -> None:
    """The standard demo command starts and pairs with its fixed sv identity."""
    home = tmp_path / "team-demo"
    env = pg_child_environment({**os.environ, "USER": "other-os-user"})
    made = subprocess.run(
        [*HX, "--home", str(home), "demo", "--with-team", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(made.stdout)["team"]["users"] == {"sv": "admin", "alice": "launch"}
    proc = start(home, env={"USER": "other-os-user"})
    try:
        path = home / "serve" / "server.json"
        wait_until(lambda: proc.poll() is not None or path.exists(), timeout=30)
        assert proc.poll() is None, "seeded demo owner must not depend on the OS user"
        info = info_of(home)
        base = f"http://127.0.0.1:{info['port']}"
        auth = {"Authorization": f"Bearer {info['token']}"}
        me = wait_until(lambda: httpx.get(f"{base}/api/v1/auth/me", headers=auth, timeout=2).json())
        assert (me["user"], me["scope"], me["client"]) == ("sv", "admin", "local")
        cli_env = pg_child_environment({**env, "HYPOTHEX_HUB_URL": base})
        for args in (("token",), ("whoami", "--json"), ("pair", "--scope", "read", "--json")):
            result = subprocess.run(
                [*HX, "--home", str(home), *args],
                env=cli_env,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            if args[0] == "token":
                assert result.stdout.strip() == info["token"]
            elif args[0] == "whoami":
                assert json.loads(result.stdout)["user"] == "sv"
            else:
                offer = json.loads(result.stdout)
                assert offer["url"].startswith(base + "/pair#")
                from hypothex.cli.main import _redeem

                _, session = _redeem(offer["url"], "cli", "demo-test")
                assert session["user"] == "sv" and session["scope"] == "read"
    finally:
        stop(proc)


def test_non_demo_home_never_bootstraps_a_different_owner(tmp_path: Path) -> None:
    """Demo recognition does not loosen existing-owner protection in ordinary homes."""
    home = tmp_path / "real-home"
    layout = Layout(home)
    store = AuthStore(layout)
    store.ensure_owner("sv")
    save_settings(layout, Settings(server=ServerSettings(auth="on")))
    result = subprocess.run(
        [*HX, "--home", str(home), "serve", "--port", "0"],
        env=pg_child_environment({**os.environ, "USER": "other-os-user"}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1 and "owner already initialized" in result.stderr
    assert [user.name for user in store.users()] == ["sv"]
    assert not store.sessions()
    assert not (home / "serve" / "server.json").exists()
