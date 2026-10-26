"""Dashboard-managed MCP configurations in Postgres/SQLite."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.mapping import model_from_row
from hr_agents.db.session import sync_session_scope
from hr_agents.models import McpServerDefinition
from hr_agents.services.mcp_config import McpConfigStore


class DbMcpConfigStore(McpConfigStore):
    """Configurations in ``mcp_servers``, one row per name."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def list_all(self) -> list[McpServerDefinition]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(
                select(t.McpServerRecord).order_by(t.McpServerRecord.name)
            ).scalars()
            return [model_from_row(McpServerDefinition, row) for row in rows]

    def upsert(self, definition: McpServerDefinition) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.McpServerRecord, definition.config.name)
            payload = definition.config.model_dump(mode="json")
            if row is None:
                session.add(
                    t.McpServerRecord(
                        name=definition.config.name,
                        config=payload,
                        updated_by=definition.updated_by,
                        updated_at=definition.updated_at,
                    )
                )
            else:
                row.config = payload
                row.updated_by = definition.updated_by
                row.updated_at = definition.updated_at
            session.flush()

    def delete(self, name: str) -> bool:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.McpServerRecord, name)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True
