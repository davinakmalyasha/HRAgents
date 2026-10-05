"""Postgres-backed stores for the Ask HR transcript and the handoff queue.

Both subclasses override only the persistence primitives their service already
exposes -- `_load`, `_persist`, `_iter` -- so every semantic (ordering, ownership
authorisation, status filtering) stays in the service class where it is testable
without a database.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.session import sync_session_scope
from hr_agents.db.workspace_tables import ChatConversationRecord, WorkspaceRequestRecord
from hr_agents.services.chat import ChatTurn, ConversationRecord, ConversationStore
from hr_agents.services.workspace_requests import (
    RequestStatus,
    WorkspaceRequest,
    WorkspaceRequestStore,
)
from hr_agents.workspaces import WorkspaceId


def _aware(moment: datetime) -> datetime:
    """Stamp a naive datetime as UTC.

    SQLite hands back naive datetimes even for a `DateTime(timezone=True)` column,
    while Postgres returns aware ones. Comparing or serialising the two mixed ways
    raises deep inside Pydantic with a message about tzinfo rather than about the
    database, so every timestamp is normalised on the way out.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class DbConversationStore(ConversationStore):
    """Durable Ask HR transcript on the ``chat_conversations`` table."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def _load(self, conversation_id: UUID) -> ConversationRecord | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(ChatConversationRecord, conversation_id)
            return None if row is None else self._to_record(row)

    def _iter(self) -> Iterator[ConversationRecord]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(ChatConversationRecord)).scalars().all()
            # Materialised inside the session: a lazy iterator would read through a
            # closed session.
            return iter([self._to_record(row) for row in rows])

    def _persist(self, record: ConversationRecord) -> None:
        with sync_session_scope(self._session_factory) as session:
            existing = session.get(ChatConversationRecord, record.id)
            if existing is None:
                session.add(ChatConversationRecord(**self._values(record)))
            else:
                for column, value in self._values(record).items():
                    setattr(existing, column, value)

    @staticmethod
    def _values(record: ConversationRecord) -> dict[str, object]:
        return {
            "id": record.id,
            "workspace": record.workspace.value,
            "owner": record.owner,
            # `mode="json"` so `ChatTurn` becomes plain dicts the JSON column
            # accepts, instead of SQLAlchemy failing to bind a Pydantic model.
            "turns": [turn.model_dump(mode="json") for turn in record.turns],
            "created_at": _aware(record.created_at),
            "updated_at": _aware(record.updated_at),
        }

    @staticmethod
    def _to_record(row: ChatConversationRecord) -> ConversationRecord:
        return ConversationRecord(
            id=row.id,
            workspace=WorkspaceId(row.workspace),
            owner=row.owner,
            turns=[ChatTurn.model_validate(turn) for turn in row.turns],
            created_at=_aware(row.created_at),
            updated_at=_aware(row.updated_at),
        )


class DbWorkspaceRequestStore(WorkspaceRequestStore):
    """Durable handoff queue on the ``workspace_requests`` table."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def _load(self, request_id: UUID) -> WorkspaceRequest | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(WorkspaceRequestRecord, request_id)
            return None if row is None else self._to_record(row)

    def _iter(self) -> Iterator[WorkspaceRequest]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(WorkspaceRequestRecord)).scalars().all()
            return iter([self._to_record(row) for row in rows])

    def _persist(self, record: WorkspaceRequest) -> None:
        with sync_session_scope(self._session_factory) as session:
            existing = session.get(WorkspaceRequestRecord, record.id)
            values = {
                "source_workspace": record.source_workspace.value,
                "target_workspace": record.target_workspace.value,
                "text": record.text,
                "status": record.status.value,
                "requested_by": record.requested_by,
                "created_at": _aware(record.created_at),
                "updated_at": _aware(record.updated_at),
            }
            if existing is None:
                session.add(WorkspaceRequestRecord(id=record.id, **values))
            else:
                for column, value in values.items():
                    setattr(existing, column, value)

    @staticmethod
    def _to_record(row: WorkspaceRequestRecord) -> WorkspaceRequest:
        return WorkspaceRequest(
            id=row.id,
            source_workspace=WorkspaceId(row.source_workspace),
            target_workspace=WorkspaceId(row.target_workspace),
            text=row.text,
            status=RequestStatus(row.status),
            requested_by=row.requested_by,
            created_at=_aware(row.created_at),
            updated_at=_aware(row.updated_at),
        )
