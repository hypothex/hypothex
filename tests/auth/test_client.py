"""Stored CLI credentials stay private across concurrent updates and diagnostics."""

import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import SecretStr

from hypothex.auth.client import (
    HubLogin,
    forget_hub_login,
    hub_key,
    hub_login,
    load_hub_logins,
    save_hub_login,
)
from hypothex.core.layout import Layout


def login() -> HubLogin:
    return HubLogin(
        token=SecretStr("synthetic-client-secret"),
        user="alice",
        scope="launch",
        session_id="s_0123456789ab",
    )


def test_secret_is_only_unwrapped_in_private_file(tmp_path: Path) -> None:
    value = login()
    assert value.token.get_secret_value() not in repr(value)
    assert value.token.get_secret_value() not in value.model_dump_json()
    layout = Layout(tmp_path)
    save_hub_login(layout, "https://hub/", value)
    path = tmp_path / "auth" / "hub-tokens.json"
    raw = json.loads(path.read_text())
    assert raw["https://hub"]["token"] == value.token.get_secret_value()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert hub_login(layout, "https://hub") == value
    assert hub_key(" https://hub/// ") == "https://hub"


def test_concurrent_client_updates_preserve_other_hubs(tmp_path: Path) -> None:
    layout = Layout(tmp_path)

    def save(index: int) -> None:
        save_hub_login(layout, f"https://hub{index}", login())

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(12)))
    assert len(load_hub_logins(layout)) == 12

    def forget(index: int) -> None:
        assert forget_hub_login(layout, f"https://hub{index}") == login()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(forget, range(6)))
    assert set(load_hub_logins(layout)) == {f"https://hub{i}" for i in range(6, 12)}


@pytest.mark.parametrize("content", ["not json", "[]", "null", '{"hub": {"token": "secret"}}'])
def test_bad_client_state_is_unavailable(tmp_path: Path, content: str) -> None:
    folder = tmp_path / "auth"
    folder.mkdir(mode=0o700)
    path = folder / "hub-tokens.json"
    path.write_text(content)
    path.chmod(0o600)
    assert load_hub_logins(Layout(tmp_path)) == {}


def test_insecure_or_symlinked_client_state_is_unavailable(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    save_hub_login(layout, "https://hub", login())
    path = tmp_path / "auth" / "hub-tokens.json"
    path.chmod(0o644)
    assert load_hub_logins(layout) == {}
    outside = tmp_path / "outside.json"
    path.rename(outside)
    outside.chmod(0o600)
    path.symlink_to(outside)
    assert load_hub_logins(layout) == {}
