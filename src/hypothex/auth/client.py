"""The CLI's logins: ``<home>/auth/hub-tokens.json`` (0600), one entry per hub URL."""

from __future__ import annotations

import json
import os
import stat

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from hypothex.auth.scopes import Scope
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from hypothex.core.settings import write_private
from hypothex.core.store import dir_lock

HUB_TOKENS_FILE = "auth/hub-tokens.json"


class HubLogin(BaseModel):
    """A session this CLI holds on one hub (from ``hx login``)."""

    model_config = ConfigDict(hide_input_in_errors=True)

    token: SecretStr
    user: str
    scope: Scope
    session_id: str


def hub_key(url: str) -> str:
    """
    Normalize a hub URL into the key of ``hub-tokens.json``.

    Parameters
    ----------
    url : str
        Hub base URL.

    Returns
    -------
    str
        The URL without trailing slashes.

    Examples
    --------
    >>> hub_key("https://hub.ts.net/")
    'https://hub.ts.net'
    """
    return url.strip().rstrip("/")


def load_hub_logins(layout: Layout) -> dict[str, HubLogin]:
    """
    Read every stored login.

    Parameters
    ----------
    layout : Layout
        The CLI's home.

    Returns
    -------
    dict of str to HubLogin
        Hub URL to login; ``{}`` when the file is missing or unreadable.
    """
    path = layout.home / HUB_TOKENS_FILE
    try:
        if path.parent.is_symlink():
            return {}
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                return {}
            raw = json.load(handle)
        return {str(k): HubLogin.model_validate(v) for k, v in raw.items()}
    except (OSError, ValueError, AttributeError, ValidationError):
        return {}


def hub_login(layout: Layout, url: str) -> HubLogin | None:
    """
    Return the login stored for one hub, or None.

    Parameters
    ----------
    layout : Layout
    url : str

    Returns
    -------
    HubLogin or None
    """
    return load_hub_logins(layout).get(hub_key(url))


def _write(layout: Layout, logins: dict[str, HubLogin]) -> None:
    # This private persistence boundary is the only serialization that unwraps credentials.
    data = {
        k: {**v.model_dump(mode="json"), "token": v.token.get_secret_value()}
        for k, v in sorted(logins.items())
    }
    write_private(layout.home / HUB_TOKENS_FILE, json.dumps(data, indent=2))


def _private_folder(layout: Layout) -> None:
    folder = (layout.home / HUB_TOKENS_FILE).parent
    if folder.is_symlink():
        raise ConfigError("auth directory must not be a symlink")
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)


def save_hub_login(layout: Layout, url: str, login: HubLogin) -> None:
    """
    Store (or replace) the login for one hub.

    Parameters
    ----------
    layout : Layout
    url : str
    login : HubLogin
    """
    _private_folder(layout)
    with dir_lock((layout.home / HUB_TOKENS_FILE).parent):
        logins = load_hub_logins(layout)
        logins[hub_key(url)] = login
        _write(layout, logins)


def forget_hub_login(layout: Layout, url: str) -> HubLogin | None:
    """
    Remove the login of one hub.

    Parameters
    ----------
    layout : Layout
    url : str

    Returns
    -------
    HubLogin or None
        The removed login, or None when there was none.
    """
    _private_folder(layout)
    with dir_lock((layout.home / HUB_TOKENS_FILE).parent):
        logins = load_hub_logins(layout)
        gone = logins.pop(hub_key(url), None)
        if gone is not None:
            _write(layout, logins)
    return gone
