"""Database layer: declarative base, tables, and sessions (sync + async)."""

from hr_agents.db.base import Base
from hr_agents.db.session import (
    create_engine,
    create_session_factory,
    create_sync_engine,
    create_sync_session_factory,
    session_scope,
    sync_session_scope,
)

__all__ = [
    "Base",
    "create_engine",
    "create_session_factory",
    "create_sync_engine",
    "create_sync_session_factory",
    "session_scope",
    "sync_session_scope",
]
