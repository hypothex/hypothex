"""Alembic environment: one online connection; the URL comes from ``config.attributes``."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from hypothex.core.index import Base

config = context.config


def run_migrations_online() -> None:
    """Run the migrations over a connection to ``config.attributes["url"]``."""
    engine = create_engine(config.attributes["url"], poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=Base.metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported; run hx db upgrade")
run_migrations_online()
