import stat
from pathlib import Path

import pytest

from hypothex.auth.client import (
    HubLogin,
    forget_hub_login,
    hub_login,
    load_hub_logins,
    save_hub_login,
)
from hypothex.auth.pairing import pairing_url, parse_pairing_url, qr_text
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout

SECRET = "A" * 21 + "-_" + "b" * 20


def test_pairing_url_round_trips() -> None:
    url = pairing_url("https://hub.tail1234.ts.net/", "p_0123456789ab", SECRET)
    assert url == f"https://hub.tail1234.ts.net/pair#p_0123456789ab.{SECRET}"
    assert parse_pairing_url(url) == ("https://hub.tail1234.ts.net", "p_0123456789ab", SECRET)
    local = pairing_url("http://127.0.0.1:7777", "p_0123456789ab", SECRET)
    assert parse_pairing_url(local)[0] == "http://127.0.0.1:7777"


@pytest.mark.parametrize(
    "url",
    [
        "https://hub/pair",
        "https://hub/pair#p_0123456789ab",
        "https://hub/pair#x_0123456789ab." + SECRET,
        "https://hub/login#p_0123456789ab." + SECRET,
        "ftp://hub/pair#p_0123456789ab." + SECRET,
        "https://hub/pair#p_0123456789ab.short",
    ],
)
def test_malformed_links_are_refused(url: str) -> None:
    with pytest.raises(ConfigError, match="pairing link"):
        parse_pairing_url(url)


def test_qr_text_is_plain_half_blocks() -> None:
    text = qr_text(pairing_url("http://127.0.0.1:7777", "p_0123456789ab", SECRET))
    assert "\x1b" not in text
    assert set(text) <= {"█", "▀", "▄", " ", "\n"}
    lines = text.splitlines()
    assert len(lines) > 10 and len({len(line) for line in lines}) == 1


def test_hub_logins_are_private_and_round_trip(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    login = HubLogin(token="hxs_t", user="alice", scope="launch", session_id="s_00000000000a")
    save_hub_login(layout, "https://hub.tail1234.ts.net/", login)
    path = tmp_path / "auth" / "hub-tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_hub_logins(layout) == {"https://hub.tail1234.ts.net": login}
    assert hub_login(layout, "https://hub.tail1234.ts.net") == login
    assert forget_hub_login(layout, "https://hub.tail1234.ts.net") == login
    assert load_hub_logins(layout) == {}
    assert hub_login(Layout(tmp_path / "none"), "https://x") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@hub/pair#p_0123456789ab." + SECRET,
        "https://hub:bad/pair#p_0123456789ab." + SECRET,
        "https://hub/pair?secret=leak#p_0123456789ab." + SECRET,
        "https://hu b/pair#p_0123456789ab." + SECRET,
        "https://hub/pair#p_0123456789ab." + SECRET + "\nextra",
    ],
)
def test_unsafe_pairing_urls_have_secret_free_errors(url: str) -> None:
    with pytest.raises(ConfigError) as error:
        parse_pairing_url(url)
    assert SECRET not in str(error.value)
    assert "password" not in str(error.value)
