"""Alembic environment — async engine, settings-driven URL."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from hr_agents.config import get_settings
from hr_agents.db import (  # noqa: F401
    compliance,
    growth,
    leave_tables,
    offboarding,
    offers_tables,
    onboarding_tables,
    payroll_tables,
    people,
    tables,
    workspace_tables,
)
from hr_agents.db.base import Base, ensure_tenant_indexes

# The tenant indexes are attached by a hook rather than declared per table, so the
# metadata has to be final before Alembic compares it against the database -- which is
# what `alembic check` does in CI.
ensure_tenant_indexes()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Render SQL without connecting to a database."""
    url = get_url().replace("+asyncpg", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            # Alembic 1.20 creates `alembic_version.version_num` as VARCHAR(32)
            # with no option to widen it, and revision `0037_communication_...`
            # is 33 characters. Create it first (or widen an older one) so a
            # fresh Postgres install can apply the chain instead of dying at 0037.
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version ("
                    "version_num VARCHAR(64) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
            connection.execute(
                text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
            )
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
