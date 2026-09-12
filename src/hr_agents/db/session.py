"""Database session management.

Async helpers serve Alembic (asyncpg). Sync helpers serve the application's
store adapters (psycopg) — see ADR 0005.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import Engine
from sqlalchemy import create_engine as create_sync_engine_from_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.config import Settings, get_settings


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create an async engine from settings."""
    settings = settings or get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=settings.debug,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Provide a transactional session scope."""
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def create_sync_engine(settings: Settings | None = None) -> Engine:
    """Create the application's synchronous engine (store adapters)."""
    settings = settings or get_settings()
    return create_sync_engine_from_url(
        settings.sync_database_url,
        pool_pre_ping=True,
        echo=settings.debug,
    )


def create_sync_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the given sync engine."""
    return sessionmaker(engine, expire_on_commit=False, autoflush=False)


@contextmanager
def sync_session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional session scope for store adapters."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
