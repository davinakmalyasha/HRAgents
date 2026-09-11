"""Shared session factory for adapter tests.

Runs on in-memory SQLite by default; set ``HRAGENTS_TEST_DB_URL`` (as the CI
``postgres-adapters`` job does) to run the same suite against PostgreSQL.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
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

TEST_DB_URL = os.environ.get("HRAGENTS_TEST_DB_URL")


@pytest.fixture
def factory() -> Iterator[sessionmaker[Session]]:
    if TEST_DB_URL:
        engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    else:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, autoflush=False)
    engine.dispose()
