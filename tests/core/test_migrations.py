from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from hypothex.core.errors import ConfigError
from hypothex.core.index import HEAD_REVISION, SCHEMA_VERSION, Base
from hypothex.core.layout import Layout
from hypothex.core.migrations import alembic_config, current, upgrade
from hypothex.core.settings import ServerSettings


def test_head_creates_exactly_the_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config = alembic_config(url, None)
    assert ScriptDirectory.from_config(config).get_current_head() == HEAD_REVISION
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
        assert SCHEMA_VERSION == 5
        assert "name" in Base.metadata.tables["runs"].columns
        assert "owner" in Base.metadata.tables["runs"].columns
        assert {"ix_runs_name", "ix_runs_parent", "ix_runs_owner"} <= {
            index.name for index in Base.metadata.tables["runs"].indexes
        }
        version = conn.execute(text("SELECT value FROM meta WHERE key = 'schema_version'"))
        assert version.scalar() == str(SCHEMA_VERSION)
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD_REVISION
        )


def test_password_never_lands_in_alembic_options() -> None:
    from pydantic import SecretStr

    config = alembic_config("postgresql+psycopg://hx@db:5432/hx", SecretStr("p%w-SECRET"))
    assert "SECRET" not in str(config.get_main_option("sqlalchemy.url"))
    assert config.attributes["url"].password == "p%w-SECRET"


def test_sqlite_needs_no_migrations(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="the SQLite index needs no migrations"):
        upgrade(Layout(tmp_path), ServerSettings())
    with pytest.raises(ConfigError, match="the SQLite index needs no migrations"):
        current(Layout(tmp_path), ServerSettings())


@pytest.mark.parametrize("operation", [current, upgrade])
def test_unavailable_database_errors_do_not_expose_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[Layout, ServerSettings], str | None],
) -> None:
    from hypothex.core.index import IndexUnavailableError

    monkeypatch.setenv("HYPOTHEX_INDEX_PASSWORD", "synthetic-SECRET")
    settings = ServerSettings(index_url="postgresql://hx@127.0.0.1:1/hypothex")
    with pytest.raises(IndexUnavailableError) as info:
        operation(Layout(tmp_path), settings)
    assert "127.0.0.1:1" in str(info.value) and "SECRET" not in str(info.value)


@pytest.mark.parametrize("operation", [current, upgrade])
def test_missing_driver_is_an_actionable_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[Layout, ServerSettings], str | None],
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "psycopg", None)
    settings = ServerSettings(index_url="postgresql+psycopg://hx@127.0.0.1:1/hypothex")
    with pytest.raises(ConfigError, match="needs psycopg"):
        operation(Layout(tmp_path), settings)


def test_plain_postgresql_url_uses_the_installed_psycopg_driver() -> None:
    config = alembic_config("postgresql://hx@127.0.0.1/hypothex", None)
    assert config.attributes["url"].drivername == "postgresql+psycopg"
