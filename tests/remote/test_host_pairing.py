import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hypothex.api.app import create_app
from hypothex.core.layout import Layout
from hypothex.remote.config import (
    HostSpec,
    forget_host_token,
    host_token,
    load_host_tokens,
    same_origin,
    save_host_token,
)
from tests.api.authkit import token_for
from tests.api.envserver import host_state, serve_app, wait_until, write_hosts

BASE = "http://127.0.0.1:7777"
EXPECTED = "auth failed: hx hosts pair gpu1 <pairing-url>"


def test_token_env_is_for_url_hosts_only() -> None:
    assert HostSpec(route="url", url="http://h:1", token_env="LAB_TOKEN").token_env == "LAB_TOKEN"
    with pytest.raises(ValidationError, match="token_env"):
        HostSpec(route="ssh", ssh_alias="gpu1", token_env="LAB_TOKEN")
    with pytest.raises(ValidationError):
        HostSpec(route="url", url="http://h:1", token_env="lower")


def test_host_token_prefers_the_paired_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = Layout(tmp_path)
    spec = HostSpec(route="url", url="http://h:1", token_env="LAB_TOKEN")
    assert host_token(layout, "lab", spec) is None
    monkeypatch.setenv("LAB_TOKEN", "from-env")
    token = host_token(layout, "lab", spec)
    assert token is not None and token.get_secret_value() == "from-env"
    save_host_token(layout, "lab", "http://h:1/", "hxs_paired")
    path = tmp_path / "auth" / "host-tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_host_tokens(layout) == {"lab": {"url": "http://h:1", "token": "hxs_paired"}}
    paired = host_token(layout, "lab", spec)
    assert paired is not None and paired.get_secret_value() == "hxs_paired"
    forget_host_token(layout, "lab")
    assert load_host_tokens(layout) == {}


def test_a_paired_token_never_goes_to_another_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = Layout(tmp_path)
    save_host_token(layout, "lab", "http://lab-a:8000", "hxs_for_a")
    moved = HostSpec(route="url", url="http://lab-b:8000")
    assert host_token(layout, "lab", moved) is None
    monkeypatch.setenv("LAB_TOKEN", "from-env")
    moved_env = HostSpec(route="url", url="http://lab-b:8000", token_env="LAB_TOKEN")
    token = host_token(layout, "lab", moved_env)
    assert token is not None and token.get_secret_value() == "from-env"
    assert same_origin("http://lab-a:8000/", "HTTP://LAB-A:8000")
    assert not same_origin("http://lab-a:8000", "https://lab-a:8000")


def test_hub_sends_the_token_of_a_url_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = create_app(tmp_path / "gpu1", background_repair=False, kind="ssh", auth_token="T" * 32)
    with serve_app(env) as url:
        hub_home = tmp_path / "hub"
        spec = HostSpec(route="url", url=url, token_env="HX_GPU1_TOKEN")
        write_hosts(hub_home, {"gpu1": spec})
        monkeypatch.setenv("HX_GPU1_TOKEN", "T" * 32)
        with TestClient(create_app(hub_home, background_repair=False), base_url=BASE) as hub:
            wait_until(lambda: host_state(hub, "gpu1") == "connected", timeout=30)


def test_a_rejected_token_asks_to_re_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = create_app(tmp_path / "gpu1", background_repair=False, kind="ssh", auth_token="T" * 32)
    with serve_app(env) as url:
        hub_home = tmp_path / "hub"
        write_hosts(hub_home, {"gpu1": HostSpec(route="url", url=url, token_env="HX_GPU1_TOKEN")})
        monkeypatch.setenv("HX_GPU1_TOKEN", "wrong")
        with TestClient(create_app(hub_home, background_repair=False), base_url=BASE) as hub:
            wait_until(lambda: host_state(hub, "gpu1") == "error", timeout=30)
            row = next(r for r in hub.get("/api/v1/hosts").json() if r["name"] == "gpu1")
    assert row["state"]["message"] == EXPECTED


def test_a_paired_host_session_on_a_lab_server(tmp_path: Path) -> None:
    lab = create_app(tmp_path / "lab", background_repair=False, kind="ssh", auth=True)
    token = token_for(lab.state.auth, "sv", "admin", client="host")
    with serve_app(lab) as url:
        hub_home = tmp_path / "hub"
        write_hosts(hub_home, {"lab": HostSpec(route="url", url=url)})
        save_host_token(Layout(hub_home), "lab", url, token)
        with TestClient(create_app(hub_home, background_repair=False), base_url=BASE) as hub:
            wait_until(lambda: host_state(hub, "lab") == "connected", timeout=30)
