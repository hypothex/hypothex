"""The hub's ``<home>/config.yaml``: server, notification, digest, and storage settings.

Secrets never live in this file: it names the environment variables that hold
them (``webhook_env``, ``password_env``, ``index_password_env``). A literal
secret is refused before validation, and validation errors are printed without
input values, so a mistake never echoes a secret.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator, model_validator

from hypothex.core.config import YAML_CYCLE, has_cycle, scan_yaml
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout

SETTINGS_FILENAME = "config.yaml"
ENV_NAME = r"^[A-Z_][A-Z0-9_]{0,63}$"
NotifyEvent = Literal["finished", "failed", "lost", "killed"]
Channel = Literal["slack", "email"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LITERAL_SECRET_KEYS = ("webhook", "webhook_url", "password", "token", "secret", "url")
"""Keys under ``notify.slack``/``notify.email`` that would hold a secret value."""
_SECRET_FIELD = {"slack": "webhook_env", "email": "password_env"}


def is_loopback_host(host: str) -> bool:
    """
    Tell whether a host name or address stays on this machine.

    Parameters
    ----------
    host : str
        A name or an IP literal.

    Returns
    -------
    bool
        True for ``localhost`` and loopback addresses.

    Examples
    --------
    >>> is_loopback_host("127.0.0.1"), is_loopback_host("smtp.lab.org")
    (True, False)
    """
    name = host.strip().strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


PASSWORD_PARAMS = frozenset({"password", "sslpassword"})
"""Query parameters libpq reads as a secret (compared lowercased and percent-decoded)."""


def _param_key(piece: str) -> str:
    return unquote(piece.split("=", 1)[0]).lower()


def url_holds_password(url: str) -> bool:
    """
    Tell whether a URL carries a password, as ``user:pw@`` or a query parameter.

    Parameters
    ----------
    url : str
        Any URL.

    Returns
    -------
    bool
        True for ``user:pw@`` or a ``password``/``sslpassword`` parameter (any
        case, percent-encoded or not); True for a URL that cannot be parsed.

    Examples
    --------
    >>> url_holds_password("postgresql://hx@db/hx?password=x")
    True
    >>> url_holds_password("postgresql://hx@db/hx?sslmode=require")
    False
    """
    try:
        parts = urlsplit(url)
        if parts.password is not None:
            return True
    except ValueError:
        return True  # never echoed, never trusted
    return any(_param_key(p) in PASSWORD_PARAMS for p in parts.query.split("&") if p)


def redact_url(url: str) -> str:
    """
    Replace the password of a URL with ``***``.

    Parameters
    ----------
    url : str
        Any URL.

    Returns
    -------
    str
        The URL with ``user:***@`` and ``<password param>=***`` where it held
        a password, else unchanged; ``***`` when it cannot be parsed.

    Examples
    --------
    >>> redact_url("postgresql+psycopg://hx:pw@db:5432/hx")
    'postgresql+psycopg://hx:***@db:5432/hx'
    >>> redact_url("postgresql://hx@db/hx?password=pw&sslmode=require")
    'postgresql://hx@db/hx?password=***&sslmode=require'
    """
    try:
        parts = urlsplit(url)
        password = parts.password
    except ValueError:
        return "***"
    pieces = parts.query.split("&") if parts.query else []
    hidden = [
        f"{p.split('=', 1)[0]}=***" if _param_key(p) in PASSWORD_PARAMS else p for p in pieces
    ]
    if password is None and hidden == pieces:
        return url
    netloc = parts.netloc
    if password is not None:
        netloc = f"{parts.username}:***@{netloc.rsplit('@', 1)[1]}"
    return urlunsplit(parts._replace(netloc=netloc, query="&".join(hidden)))


class SlackSettings(BaseModel, extra="forbid"):
    """Slack incoming webhook: the variable that holds its URL."""

    webhook_env: str = Field("HYPOTHEX_SLACK_WEBHOOK", pattern=ENV_NAME)


class EmailSettings(BaseModel, extra="forbid"):
    """SMTP delivery; the password comes from ``password_env``."""

    host: str = Field(min_length=1)
    port: int = Field(587, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str | None = None
    password_env: str | None = Field("HYPOTHEX_SMTP_PASSWORD", pattern=ENV_NAME)
    sender: str = Field(min_length=3)
    to: list[str] = Field(min_length=1)
    timeout: float = Field(20, gt=0, le=120)

    @model_validator(mode="after")
    def _no_clear_text_login(self) -> EmailSettings:
        """Refuse a login over plain SMTP to another machine."""
        if self.security == "none" and self.username and not is_loopback_host(self.host):
            raise ValueError(
                "security none with a username sends the password in clear text; "
                "use starttls or ssl"
            )
        return self


class ProjectRule(BaseModel, extra="forbid"):
    """Which run endings of one project notify, and where."""

    events: list[NotifyEvent] = Field(
        default_factory=lambda: list[NotifyEvent](["finished", "failed", "lost"])
    )
    channels: list[Channel] = Field(default_factory=lambda: list[Channel](["slack"]), min_length=1)
    min_seconds: float = Field(0, ge=0)
    fold_sweeps: bool = True


class NotifySettings(BaseModel, extra="forbid"):
    """Channels and per-project rules; unlisted projects get nothing unless ``default``."""

    slack: SlackSettings | None = None
    email: EmailSettings | None = None
    projects: dict[str, ProjectRule] = Field(default_factory=dict)
    default: ProjectRule | None = None
    max_age_hours: float = Field(24, gt=0)


class DigestSettings(BaseModel, extra="forbid"):
    """When and where the weekly digest goes."""

    enabled: bool = False
    weekday: Weekday = "mon"
    hour: int = Field(9, ge=0, le=23)
    timezone: str | None = None
    channels: list[Channel] = Field(default_factory=lambda: list[Channel](["slack"]))
    projects: list[str] | Literal["all"] = "all"
    save_to_notebook: bool = True
    top_notes: int = Field(5, ge=0, le=20)

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        """Accept only IANA zone names this machine knows."""
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("unknown timezone (use an IANA name)") from None
        return value


class ServerSettings(BaseModel, extra="forbid"):
    """Auth, public URL, sessions, and where the index lives."""

    auth: Literal["off", "on"] = "off"
    public_url: str | None = Field(None, pattern=r"^https?://[^/\s]+$")
    session_days: int = Field(90, ge=1, le=365)
    index_url: str | None = None
    index_password_env: str = Field("HYPOTHEX_INDEX_PASSWORD", pattern=ENV_NAME)

    @field_validator("auth", mode="before")
    @classmethod
    def _yaml_bool(cls, value: object) -> object:
        """YAML reads a bare ``off``/``on`` as a boolean."""
        if value is False:
            return "off"
        if value is True:
            return "on"
        return value

    @field_validator("index_url")
    @classmethod
    def _postgres_without_password(cls, value: str | None) -> str | None:
        """Only Postgres URLs, and never with a password in them."""
        if value is None:
            return None
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("index_url must start with postgresql+psycopg://")
        if url_holds_password(value):
            raise ValueError("index_url must not hold a password; set index_password_env")
        return value


class StorageSettings(BaseModel, extra="forbid"):
    """Defaults of ``hx storage clean``."""

    older_than_days: int = Field(30, ge=0)
    kinds: list[str] = Field(default_factory=lambda: ["checkpoint"])
    plan_ttl_minutes: int = Field(60, ge=1, le=1440)


class Settings(BaseModel, extra="forbid"):
    """The whole ``config.yaml``."""

    server: ServerSettings = Field(default_factory=ServerSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)
    digest: DigestSettings = Field(default_factory=DigestSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)


def settings_path(layout: Layout) -> Path:
    """
    Return the path of the settings file.

    Parameters
    ----------
    layout : Layout
        Home layout.

    Returns
    -------
    Path
        ``<home>/config.yaml``.
    """
    return layout.home / SETTINGS_FILENAME


def _key_line(text: str, keys: tuple[str, ...]) -> int | None:
    """The 1-based line of a nested mapping key, found on the composed YAML nodes."""
    try:
        node: Any = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None
    line = None
    for key in keys:
        if not isinstance(node, yaml.MappingNode):
            return None
        match = next((pair for pair in node.value if pair[0].value == key), None)
        if match is None:
            return None
        line = match[0].start_mark.line + 1
        node = match[1]
    return line


def _refuse_literal_secrets(path: Path, text: str, data: dict[str, Any]) -> None:
    notify = data.get("notify")
    if not isinstance(notify, dict):
        return
    for section, field in _SECRET_FIELD.items():
        block = notify.get(section)
        if not isinstance(block, dict):
            continue
        for key in block:
            if key in LITERAL_SECRET_KEYS:
                line = _key_line(text, ("notify", section, key))
                where = "" if line is None else f" (line {line})"
                raise ConfigError(
                    f"{path}: notify.{section}.{key} holds a secret{where}; "
                    f"use {field}: NAME (the variable holding it)"
                )


def _refuse_index_password(path: Path, data: dict[str, Any]) -> None:
    server = data.get("server")
    url = server.get("index_url") if isinstance(server, dict) else None
    if isinstance(url, str) and url_holds_password(url):
        raise ConfigError(
            f"{path}: server.index_url {redact_url(url)} holds a password; "
            "remove it and set index_password_env"
        )


def _settings_errors(exc: ValidationError) -> str:
    """``path: message`` for each error, never the input value."""
    parts = []
    for error in exc.errors(include_input=False, include_url=False):
        where = ".".join(str(p) for p in error["loc"])
        parts.append(f"{where}: {error['msg']}")
    return "; ".join(parts)


def load_settings(layout: Layout) -> Settings:
    """
    Load and validate ``<home>/config.yaml``.

    A missing file gives the defaults (auth off, no notices, no digest). The
    text is pre-scanned like ``hypothex.yaml`` (depth, size, alias cycles).

    Parameters
    ----------
    layout : Layout
        Home layout.

    Returns
    -------
    Settings
        The settings.

    Raises
    ------
    ConfigError
        Invalid YAML, a literal secret (with its line and the ``*_env`` hint), a
        password in ``index_url``, or a value that does not match the schema.
        No message holds a value from the file.
    """
    path = settings_path(layout)
    if not path.is_file():
        return Settings()
    text = path.read_text(encoding="utf-8")
    try:
        scan = scan_yaml(text)
        data = None if scan.problem is not None else yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = "" if mark is None else f" (line {mark.line + 1})"
        raise ConfigError(f"{path}: invalid YAML{where}") from None
    if scan.problem is not None:
        message, line = scan.problem
        raise ConfigError(f"{path}: {message} (line {line})")
    if has_cycle(data):
        where = "" if scan.cycle is None else f" (line {scan.cycle})"
        raise ConfigError(f"{path}: {YAML_CYCLE}{where}")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    _refuse_literal_secrets(path, text, data)
    _refuse_index_password(path, data)
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {_settings_errors(exc)}") from None


def write_private(path: Path, text: str) -> None:
    """
    Atomically write ``path`` as mode 0600 inside a 0700 folder.

    The parent folder is set to 0700 on every call: the first ``config.yaml``
    write makes the Hypothex home 0700 (``docs/team.rst`` says so).

    Parameters
    ----------
    path : Path
        Destination file.
    text : str
        Full content (UTF-8).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)  # a stale tmp keeps its old mode, which os.replace carries
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def save_settings(layout: Layout, settings: Settings) -> None:
    """
    Atomically write ``config.yaml`` (mode 0600), leaving defaults out.

    Parameters
    ----------
    layout : Layout
        Home layout.
    settings : Settings
        Settings to write.
    """
    data = settings.model_dump(mode="json", exclude_defaults=True)
    write_private(settings_path(layout), yaml.safe_dump(data, sort_keys=False))


SECRETS_FILENAME = "secrets.env"
DEFAULT_SECRET_VARS = (
    "HYPOTHEX_SLACK_WEBHOOK",
    "HYPOTHEX_SMTP_PASSWORD",
    "HYPOTHEX_INDEX_PASSWORD",
    "HYPOTHEX_SERVE_TOKEN",
    "HYPOTHEX_HUB_TOKEN",
)
"""Variable names that always count as secrets, whatever ``config.yaml`` says."""


class SecretsFileError(ConfigError):
    """``secrets.env`` is readable by others, not the user's, or malformed."""


def secrets_path(layout: Layout) -> Path:
    """
    Return the path of the optional secrets file.

    Parameters
    ----------
    layout : Layout
        Home layout.

    Returns
    -------
    Path
        ``<home>/secrets.env``.
    """
    return layout.home / SECRETS_FILENAME


def _read_secrets(layout: Layout) -> dict[str, str]:
    """Parse ``secrets.env`` after checking its owner and mode; ``{}`` when absent."""
    path = secrets_path(layout)
    try:
        info = path.stat()
    except FileNotFoundError:
        return {}
    if info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise SecretsFileError(f"{path} is readable by others or not yours; run: chmod 600 {path}")
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not re.fullmatch(ENV_NAME, name):
            raise SecretsFileError(f"{path}: line {number}: expected NAME=value")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[name] = value
    return values


def check_secrets_file(layout: Layout) -> None:
    """
    Refuse a ``secrets.env`` that others can read or that is malformed.

    Parameters
    ----------
    layout : Layout
        Home layout.

    Raises
    ------
    SecretsFileError
        The file has group/other permission bits, another owner, or a bad line
        (the message names the line, never a value). No file is fine.
    """
    _read_secrets(layout)


def resolve_secret(layout: Layout, name: str) -> SecretStr | None:
    """
    Read a secret by variable name: the environment first, then ``secrets.env``.

    Parameters
    ----------
    layout : Layout
        Home layout (for ``secrets.env``).
    name : str
        Variable name, e.g. ``HYPOTHEX_SLACK_WEBHOOK``.

    Returns
    -------
    SecretStr or None
        The value, wrapped; None when unset or empty in both places.

    Raises
    ------
    SecretsFileError
        ``secrets.env`` is consulted and is unsafe or malformed.
    """
    value = os.environ.get(name)
    if not value:
        value = _read_secrets(layout).get(name)
    return SecretStr(value) if value else None


def secret_env_names(settings: Settings) -> set[str]:
    """
    Return every variable name that holds a secret for these settings.

    Parameters
    ----------
    settings : Settings
        The hub's settings.

    Returns
    -------
    set of str
        ``DEFAULT_SECRET_VARS`` plus the configured ``webhook_env``,
        ``password_env``, and ``index_password_env``.
    """
    names = set(DEFAULT_SECRET_VARS)
    names.add(settings.server.index_password_env)
    if settings.notify.slack is not None:
        names.add(settings.notify.slack.webhook_env)
    if settings.notify.email is not None and settings.notify.email.password_env:
        names.add(settings.notify.email.password_env)
    return names


def scrub_env(env: Mapping[str, str], names: Iterable[str]) -> dict[str, str]:
    """
    Copy an environment without the given variables.

    Parameters
    ----------
    env : mapping of str to str
        An environment, e.g. ``os.environ``.
    names : iterable of str
        Variables to drop.

    Returns
    -------
    dict of str to str
        The copy.

    Examples
    --------
    >>> scrub_env({"A": "1", "B": "2"}, ["B"])
    {'A': '1'}
    """
    drop = set(names)
    return {k: v for k, v in env.items() if k not in drop}
