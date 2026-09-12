"""Shared session factory for adapter tests.

Runs on in-memory SQLite by default. When ``HRAGENTS_TEST_DB_URL`` is set (as
the CI ``postgres-adapters`` job does), the same suite runs on PostgreSQL with
row-level security enabled — connect with a **non-superuser** role so the RLS
policies actually apply (see ``scripts/prepare_test_db.py``).
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from hr_agents.db import (  # noqa: F401
    compliance_tables,
    growth_tables,
    offboarding_tables,
    people_tables,
    tables,
)
from hr_agents.db.base import Base
from hr_agents.db.rls import enable_tenant_rls_sql

TEST_DB_URL = os.environ.get("HRAGENTS_TEST_DB_URL")


@pytest.fixture(scope="session")
def pg_factory() -> Iterator[sessionmaker[Session] | None]:
    if not TEST_DB_URL:
        yield None
        return
    engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table in sorted(Base.metadata.tables):
            for statement in enable_tenant_rls_sql(table):
                connection.execute(text(statement))
    yield sessionmaker(engine, expire_on_commit=False, autoflush=False)
    engine.dispose()


@pytest.fixture
def factory(pg_factory: sessionmaker[Session] | None) -> Iterator[sessionmaker[Session]]:
    if pg_factory is not None:
        table_list = ", ".join(f'"{name}"' for name in sorted(Base.metadata.tables))
        with pg_factory() as session:
            session.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))
            session.commit()
        yield pg_factory
        return

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, autoflush=False)
    engine.dispose()
