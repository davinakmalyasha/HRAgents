"""Database adapters for the messaging bridge.

Only persistence lives here: the reply store keeps the same deduplication
contract in ``candidate_replies`` (one row per provider/digest pair), and the
candidate directory reads the recorded address from ``candidates``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.session import sync_session_scope
from hr_agents.messaging.contacts import CandidateDirectory, InMemoryCandidateDirectory
from hr_agents.messaging.store import ReplyStore
from hr_agents.models import CandidateReply, Channel


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class DbReplyStore(ReplyStore):
    """Inbound candidate replies in ``candidate_replies``."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def _load(self, reply_id: UUID) -> CandidateReply | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.CandidateReplyRecord, reply_id)
            return None if row is None else self._to_reply(row)

    def _iter(self) -> Iterator[CandidateReply]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(t.CandidateReplyRecord)).scalars().all()
            return iter([self._to_reply(row) for row in rows])

    def _persist(self, reply: CandidateReply) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.CandidateReplyRecord, reply.id)
            if row is None:
                row = t.CandidateReplyRecord(id=reply.id, provider=reply.provider)
                session.add(row)
            row.candidate_id = reply.candidate_id
            row.communication_id = reply.communication_id
            row.channel = reply.channel.value
            row.sender = reply.sender
            row.subject = reply.subject
            row.body = reply.body
            row.provider_message_id = reply.provider_message_id
            row.dedup_key = reply.dedup_key
            row.received_at = reply.received_at
            session.flush()
        super()._persist(reply)

    def find(self, *, provider: str, dedup_key: str) -> CandidateReply | None:
        """Deduplication consults the database, so a fresh process stays idempotent."""
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(t.CandidateReplyRecord).where(
                    t.CandidateReplyRecord.provider == provider,
                    t.CandidateReplyRecord.dedup_key == dedup_key,
                )
            ).scalar_one_or_none()
            return None if row is None else self._to_reply(row)

    def add(self, reply: CandidateReply) -> CandidateReply:
        """Store a reply unless this provider message is already captured."""
        existing = self.find(provider=reply.provider, dedup_key=reply.dedup_key)
        if existing is not None:
            return existing
        self._persist(reply)
        return reply

    @staticmethod
    def _to_reply(row: t.CandidateReplyRecord) -> CandidateReply:
        return CandidateReply(
            id=row.id,
            candidate_id=row.candidate_id,
            communication_id=row.communication_id,
            channel=Channel(row.channel),
            sender=row.sender,
            subject=row.subject,
            body=row.body,
            provider=row.provider,
            provider_message_id=row.provider_message_id,
            dedup_key=row.dedup_key,
            received_at=_aware(row.received_at),
        )


class DbCandidateDirectory:
    """Candidate addresses as recorded on the candidate record."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def primary_email(self, candidate_id: UUID) -> str | None:
        with sync_session_scope(self._session_factory) as session:
            return session.execute(
                select(t.Candidate.primary_email).where(t.Candidate.id == candidate_id)
            ).scalar_one_or_none()

    def candidate_for_email(self, address: str) -> UUID | None:
        target = address.strip().casefold()
        with sync_session_scope(self._session_factory) as session:
            return session.execute(
                select(t.Candidate.id).where(
                    func.lower(func.trim(t.Candidate.primary_email)) == target
                )
            ).scalar_one_or_none()


def candidate_directory(session_factory: sessionmaker[Session] | None) -> CandidateDirectory:
    """Database directory when a session factory exists, else an empty in-memory one."""
    if session_factory is None:
        return InMemoryCandidateDirectory()
    return DbCandidateDirectory(session_factory)


def reply_store(session_factory: sessionmaker[Session] | None) -> ReplyStore:
    """Database reply store when a session factory exists, else the in-memory one."""
    if session_factory is None:
        return ReplyStore()
    return DbReplyStore(session_factory)
