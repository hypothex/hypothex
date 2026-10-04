import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex._version import __version__
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.environment import PROTOCOL_VERSION
from hypothex.core.errors import ConfigError
from hypothex.mcp.server import HubUnavailableError
from hypothex.remote import bootstrap
from hypothex.remote.bootstrap import ProbeResult, ServerInfo
from hypothex.remote.config import EnvironmentsFile, HostSpec, load_hosts, save_hosts
from hypothex.remote.ssh import SshTarget
from tests.api.envserver import env_server, host_state, remote_hub, serve_app, wait_until

runner = CliRunner()
WHEEL = Path("/tmp/hx.whl")
GPU1 = HostSpec(route="url", url="http://127.0.0.1:9")


def hx(*args: str) -> Any:
    result = runner.invoke(app, [*args, "--json"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@dataclass
class FakeBootstrap:
    """Records the bootstrap steps; the alias ``plain`` has no ``sbatch``."""

    calls: list[tuple[Any, ...]] = field(default_factory=list)
    hx_version: str = __version__
    has_uv: bool = True  # False: install fails as install.sh does unless install_uv


@pytest.fixture
def fake_bootstrap(monkeypatch: pytest.MonkeyPatch) -> FakeBootstrap:
    """Stand-ins for probe, build_wheel, install, stop_server, ensure_server: no ssh at all."""
    fake = FakeBootstrap()

    def probe(target: SshTarget, remote_home: str) -> ProbeResult:
        fake.calls.append(("probe", target.alias, remote_home))
        slurm = None if target.alias == "plain" else "23.02.7"
        return ProbeResult(
            os="linux", arch="x86_64", python="3.12.7", uv="0.8.22", gpus=0, slurm=slurm,
            home="/home/sv/.hypothex",
        )  # fmt: skip

    def build_wheel(cache: Path) -> Path:
        fake.calls.append(("wheel", cache))
        return WHEEL

    def install(
        target: SshTarget, remote_home: str, wheel: Path, *, install_uv: bool = False
    ) -> None:
        fake.calls.append(("install", target.alias, remote_home, wheel, install_uv))
        if not fake.has_uv and not install_uv:
            raise bootstrap.BootstrapError(
                f"{target.alias}: install failed: uv is missing on the host; install uv "
                "(https://docs.astral.sh/uv/) on the host and retry, or allow hx to run the "
                "official installer from https://astral.sh/uv/install.sh"
            )

    def stop_server(target: SshTarget, remote_home: str) -> bool:
        fake.calls.append(("stop", target.alias, remote_home))
        return True

    def ensure_server(
        target: SshTarget, remote_home: str, *, kind: str | None = None
    ) -> ServerInfo:
        fake.calls.append(("start", target.alias, remote_home, kind))
        return ServerInfo(
            pid=42,
            port=5000,
            managed=True,
            hx_version=fake.hx_version,
            protocol_version=PROTOCOL_VERSION,
        )

    for name, fn in {
        "probe": probe,
        "build_wheel": build_wheel,
        "install": install,
        "stop_server": stop_server,
        "ensure_server": ensure_server,
    }.items():
        monkeypatch.setattr(bootstrap, name, fn)
    return fake


def test_add_list_map_rm_without_a_hub(home: Path, fake_bootstrap: FakeBootstrap) -> None:
    out = hx("hosts", "add", "gpu1", "--ssh", "gpu1-alias", "--usd-per-gpu-hour", "2.1")
    assert out["state"] is None and out["host"]["ssh_alias"] == "gpu1-alias"
    assert out["server"]["port"] == 5000
    hx(
        "hosts",
        "add",
        "cluster",
        "--ssh",
        "login",
        "--slurm",
        "--partition",
        "gpu",
        "--time",
        "08:00:00",
    )
    cache = Context.open(home).layout.home / "cache" / "wheels"
    assert fake_bootstrap.calls == [
        ("probe", "gpu1-alias", "~/.hypothex"),
        ("wheel", cache),
        ("install", "gpu1-alias", "/home/sv/.hypothex", WHEEL, False),
        ("start", "gpu1-alias", "/home/sv/.hypothex", "ssh"),
        ("probe", "login", "~/.hypothex"),
        ("wheel", cache),
        ("install", "login", "/home/sv/.hypothex", WHEEL, False),
        ("start", "login", "/home/sv/.hypothex", "slurm"),
    ]
    assert hx("hosts", "map", "toy", "gpu1", "/home/sv/toy")["path"] == "/home/sv/toy"
    listed = {h["name"]: h for h in hx("hosts", "list")}
    assert listed["gpu1"]["projects"] == {"toy": "/home/sv/toy"}
    assert listed["gpu1"]["usd_per_gpu_hour"] == 2.1 and listed["gpu1"]["route"] == "ssh"
    assert listed["cluster"]["kind"] == "slurm"
    assert listed["cluster"]["slurm"]["partition"] == "gpu"
    assert listed["cluster"]["slurm"]["time"] == "08:00:00"
    assert hx("hosts", "rm", "gpu1") == {"removed": "gpu1"}
    assert set(load_hosts(Context.open(home).layout).environments) == {"cluster"}
    text = runner.invoke(app, ["hosts", "list"]).stdout
    assert "cluster" in text and "login" in text


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["add", "Bad Name", "--ssh", "x"], "host name"),
        (["add", "local", "--ssh", "x"], "host name"),
        (["add", "g", "--ssh", "x", "--url", "http://127.0.0.1:1"], "exactly one"),
        (["add", "g"], "exactly one"),
        (["add", "g", "--ssh", "x", "--partition", "gpu"], "--slurm"),
        (["add", "g", "--ssh", "x", "--usd-per-gpu-hour", "-1"], "invalid host g"),
        (["map", "toy", "nope", "/x"], "unknown host nope"),
        (["map", "toy", "gpu1", "relative/path"], "invalid mapping"),
        (["map", "bad name", "gpu1", "/srv/x"], "invalid mapping"),
        (["rm", "nope"], "unknown host nope"),
    ],
)
def test_hosts_input_errors(
    home: Path, fake_bootstrap: FakeBootstrap, args: list[str], message: str
) -> None:
    save_hosts(Context.open(home).layout, EnvironmentsFile(environments={"gpu1": GPU1}))
    with pytest.raises(ConfigError, match=message):
        runner.invoke(app, ["hosts", *args], catch_exceptions=False)
    assert fake_bootstrap.calls == []
    # nothing bad was saved: host commands still work
    assert [h["name"] for h in hx("hosts", "list")] == ["gpu1"]


def test_add_twice_is_an_error(home: Path, fake_bootstrap: FakeBootstrap) -> None:
    hx("hosts", "add", "gpu1", "--ssh", "a")
    with pytest.raises(ConfigError, match="hx hosts rm gpu1"):
        runner.invoke(app, ["hosts", "add", "gpu1", "--ssh", "b"], catch_exceptions=False)


def test_add_slurm_needs_sbatch_and_saves_nothing(
    home: Path, fake_bootstrap: FakeBootstrap
) -> None:
    with pytest.raises(ConfigError, match="no sbatch"):
        runner.invoke(
            app, ["hosts", "add", "c", "--ssh", "plain", "--slurm"], catch_exceptions=False
        )
    assert load_hosts(Context.open(home).layout).environments == {}


def test_status_needs_the_hub(home: Path) -> None:
    with pytest.raises(HubUnavailableError, match="hx serve"):
        runner.invoke(app, ["hosts", "status"], catch_exceptions=False)


def test_hub_commands_send_the_hub_token(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hypothex.api.app import create_app

    hub_app = create_app(home, background_repair=False, hub=False, auth_token="hub-secret")
    with serve_app(hub_app) as url:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", url)
        refused = runner.invoke(app, ["hosts", "status", "--json"])
        assert refused.exit_code != 0
        monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "hub-secret")
        assert [x["name"] for x in hx("hosts", "status")] == ["local"]
        monkeypatch.delenv("HYPOTHEX_HUB_TOKEN")
        # the hub's own server.json (owner-only) gives the token to a CLI on the same home
        port = int(url.rsplit(":", 1)[1])
        (home / "serve").mkdir(parents=True, exist_ok=True)
        (home / "serve" / "server.json").write_text(
            json.dumps({"pid": 1, "port": port, "managed": False, "token": "hub-secret"})
        )
        assert [x["name"] for x in hx("hosts", "status")] == ["local"]


def test_status_connect_disconnect_and_add_through_the_hub(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        assert [x["name"] for x in hx("hosts", "status")] == ["local", "gpu1"]
        assert hx("hosts", "status", "gpu1")[0]["state"]["state"] == "connected"
        assert hx("hosts", "disconnect", "gpu1")["state"] == "disabled"
        assert hx("hosts", "connect", "gpu1")["name"] == "gpu1"
        wait_until(
            lambda: hx("hosts", "status", "gpu1")[0]["state"]["state"] == "connected", timeout=30
        )
        text = runner.invoke(app, ["hosts", "status"]).stdout
        assert "gpu1" in text and "connected" in text
        with env_server(tmp_path / "box2-home") as (url2, _):
            out = hx("hosts", "add", "box2", "--url", url2)
            assert out["state"]["name"] == "box2"
            wait_until(lambda: host_state(r.client, "box2") == "connected", timeout=30)


def test_map_and_rm_reach_a_running_hub(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        hx("hosts", "map", "toy2", "gpu1", "/srv/toy2")
        row = next(x for x in r.client.get("/api/v1/hosts").json() if x["name"] == "gpu1")
        assert row["projects"] == ["toy", "toy2"]
        assert hx("hosts", "rm", "gpu1") == {"removed": "gpu1"}
        assert [x["name"] for x in r.client.get("/api/v1/hosts").json()] == ["local"]
        disabled = home / "hosts_disabled.json"
        assert not disabled.exists() or "gpu1" not in json.loads(disabled.read_text())


def test_add_slurm_on_a_home_without_flock_saves_nothing(
    home: Path, fake_bootstrap: FakeBootstrap, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the env server refuses to start (Task 31); ensure_server returns its log lines
    def no_flock(target: SshTarget, remote_home: str, *, kind: str | None = None) -> ServerInfo:
        raise bootstrap.BootstrapError(
            "login: hx serve exited during startup\n"
            "hypothex: /home/sv/.hypothex does not support flock, which a SLURM env server "
            "needs for its run locks"
        )

    monkeypatch.setattr(bootstrap, "ensure_server", no_flock)
    with pytest.raises(bootstrap.BootstrapError, match="does not support flock"):
        runner.invoke(
            app, ["hosts", "add", "c", "--ssh", "login", "--slurm"], catch_exceptions=False
        )
    assert load_hosts(Context.open(home).layout).environments == {}


def test_upgrade_reinstalls_over_ssh(home: Path, fake_bootstrap: FakeBootstrap) -> None:
    hx("hosts", "add", "gpu1", "--ssh", "gpu1-alias", "--remote-home", "/scratch/hx")
    fake_bootstrap.calls.clear()
    out = hx("hosts", "upgrade", "gpu1")
    assert out["server"]["pid"] == 42 and out["state"] is None
    assert fake_bootstrap.calls == [
        ("wheel", Context.open(home).layout.home / "cache" / "wheels"),
        ("install", "gpu1-alias", "/scratch/hx", WHEEL, False),
        ("stop", "gpu1-alias", "/scratch/hx"),
        ("start", "gpu1-alias", "/scratch/hx", "ssh"),
    ]
    fake_bootstrap.hx_version = "0.0.1"
    with pytest.raises(ConfigError, match="still runs hx 0.0.1"):
        runner.invoke(app, ["hosts", "upgrade", "gpu1"], catch_exceptions=False)
    hx("hosts", "add", "u", "--url", "http://127.0.0.1:9")
    with pytest.raises(ConfigError, match="by hand"):
        runner.invoke(app, ["hosts", "upgrade", "u"], catch_exceptions=False)


def test_uv_is_installed_on_a_host_only_with_install_uv(
    home: Path, fake_bootstrap: FakeBootstrap
) -> None:
    # SEC-3: adding a host must not run a downloaded installer the user did not ask for
    fake_bootstrap.has_uv = False
    with pytest.raises(bootstrap.BootstrapError, match="add --install-uv"):
        runner.invoke(app, ["hosts", "add", "gpu1", "--ssh", "a"], catch_exceptions=False)
    assert load_hosts(Context.open(home).layout).environments == {}  # nothing saved
    out = hx("hosts", "add", "gpu1", "--ssh", "a", "--install-uv")
    assert out["server"]["pid"] == 42
    installs = [c for c in fake_bootstrap.calls if c[0] == "install"]
    assert [c[-1] for c in installs] == [False, True]
    with pytest.raises(bootstrap.BootstrapError, match="add --install-uv"):
        runner.invoke(app, ["hosts", "upgrade", "gpu1"], catch_exceptions=False)
    fake_bootstrap.calls.clear()
    assert hx("hosts", "upgrade", "gpu1", "--install-uv")["server"]["pid"] == 42
    assert fake_bootstrap.calls[1] == ("install", "a", "~/.hypothex", WHEEL, True)
    with pytest.raises(ConfigError, match="--install-uv needs --ssh"):
        runner.invoke(
            app,
            ["hosts", "add", "u", "--url", "http://127.0.0.1:9", "--install-uv"],
            catch_exceptions=False,
        )
