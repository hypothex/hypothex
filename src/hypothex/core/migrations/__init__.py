"""Alembic migrations of the Postgres index (server mode). SQLite never migrates."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.pool import NullPool

from hypothex.core.errors import ConfigError
from hypothex.core.index import IndexUnavailableError
from hypothex.core.layout import Layout
from hypothex.core.settings import ServerSettings, redact_url, resolve_secret

SCRIPT_DIR = Path(__file__).resolve().parent
NO_MIGRATIONS = "the SQLite index needs no migrations (it rebuilds itself from files)"


def alembic_config(index_url: str, password: SecretStr | None) -> Config:
    """
    Build an Alembic config for an index URL.

    Parameters
    ----------
    index_url : str
        ``postgresql+psycopg://user@host:port/db`` (tests also pass ``sqlite:///``).
    password : SecretStr or None

    Returns
    -------
    alembic.config.Config
        ``script_location`` is this package; the URL with its password is in
        ``config.attributes["url"]`` only, never in an option.
    """
    config = Config()
    config.set_main_option("script_location", str(SCRIPT_DIR))
    url = make_url(index_url)
    if url.get_backend_name() == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if password is not None:
        url = url.set(password=password.get_secret_value())
    config.attributes["url"] = url
    return config


def _postgres(layout: Layout, settings: ServerSettings) -> Config:
    if settings.index_url is None:
        raise ConfigError(NO_MIGRATIONS)
    return alembic_config(settings.index_url, resolve_secret(layout, settings.index_password_env))


def current(layout: Layout, settings: ServerSettings) -> str | None:
    """
    Return the Postgres index's Alembic revision.

    Parameters
    ----------
    layout : Layout
    settings : ServerSettings

    Returns
    -------
    str or None
        None when the database was never upgraded.

    Raises
    ------
    ConfigError
        The index is SQLite.
    IndexUnavailableError
        Postgres does not answer.
    """
    config = _postgres(layout, settings)
    try:
        engine = create_engine(config.attributes["url"], poolclass=NullPool)
    except ImportError:
        raise ConfigError(
            "a Postgres index needs psycopg: uv tool install 'hypothex[server]'"
        ) from None
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    except (OperationalError, InterfaceError):
        shown = redact_url(str(settings.index_url))
        raise IndexUnavailableError(f"the index at {shown} does not answer") from None
    finally:
        engine.dispose()


def upgrade(layout: Layout, settings: ServerSettings) -> str:
    """
    Upgrade the Postgres index to the newest revision.

    Parameters
    ----------
    layout : Layout
    settings : ServerSettings

    Returns
    -------
    str
        The revision after the upgrade.

    Raises
    ------
    ConfigError
        The index is SQLite.
    IndexUnavailableError
        Postgres does not answer.
    """
    config = _postgres(layout, settings)
    try:
        command.upgrade(config, "head")
    except ImportError:
        raise ConfigError(
            "a Postgres index needs psycopg: uv tool install 'hypothex[server]'"
        ) from None
    except (OperationalError, InterfaceError):
        shown = redact_url(str(settings.index_url))
        raise IndexUnavailableError(f"the index at {shown} does not answer") from None
    found = current(layout, settings)
    assert found is not None
    return found
