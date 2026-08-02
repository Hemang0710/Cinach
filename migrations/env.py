"""Alembic migration environment (async-aware).

The database URL comes from application settings (``cinch.core.config``), so
migrations target the same database the app uses without duplicating config or
hard-coding secrets. ``target_metadata`` is the ORM metadata, enabling
``--autogenerate`` and the no-drift test in the test suite.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from cinch.core.config import get_settings

# Importing the models module registers every ORM table on the shared metadata;
# referencing it below (models.Base.metadata) makes that dependency explicit.
from cinch.db import models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime database URL (async driver) into Alembic's config.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = models.Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Named constraints + batch mode keep SQLite and PostgreSQL in sync.
        render_as_batch=True,
        compare_type=True,
    )


def run_migrations_offline() -> None:
    """Emit SQL without a live DB connection (``alembic upgrade --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations with a live async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
