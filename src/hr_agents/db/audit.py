"""Postgres-backed audit chain.

Same hash-chain semantics as the in-memory ``AuditChain``; the chain lives in
``audit_log`` so tamper evidence survives restarts. Appends read the current
tail inside the transaction (single-writer per deployment; an advisory lock is
tracked in the polish backlog).
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.session import sync_session_scope
from hr_agents.db.tables import AuditLog
from hr_agents.models import AuditActor, AuditEntry
from hr_agents.services.audit import AuditChain, verify_entries


class DbAuditChain(AuditChain):
    """Append-only hash chain persisted in the ``audit_log`` table."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def append(
        self,
        *,
        actor: AuditActor,
        action: str,
        subject_type: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
    ) -> AuditEntry:
        with sync_session_scope(self._session_factory) as session:
            tail = session.execute(
                select(AuditLog.seq, AuditLog.entry_hash).order_by(AuditLog.seq.desc()).limit(1)
            ).first()
            seq = tail[0] + 1 if tail is not None else 0
            prev_hash = tail[1] if tail is not None else None
            entry = AuditEntry.partial(
                seq=seq,
                actor=actor,
                action=action,
                subject_type=subject_type,
                subject_id=subject_id,
                payload=payload or {},
                prev_hash=prev_hash,
            )
            session.add(
                AuditLog(
                    seq=entry.seq,
                    entry_id=entry.entry_id,
                    created_at=entry.created_at,
                    actor=entry.actor.model_dump(mode="json"),
                    action=entry.action,
                    subject_type=entry.subject_type,
                    subject_id=entry.subject_id,
                    payload=entry.payload,
                    prev_hash=entry.prev_hash,
                    entry_hash=entry.entry_hash,
                )
            )
            session.flush()
            return entry

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(AuditLog).order_by(AuditLog.seq)).scalars().all()
            return tuple(self._to_entry(row) for row in rows)

    @property
    def last_hash(self) -> str | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(AuditLog.entry_hash).order_by(AuditLog.seq.desc()).limit(1)
            ).first()
            return row[0] if row is not None else None

    def verify(self) -> int:
        return verify_entries(self.entries)

    @staticmethod
    def _to_entry(row: AuditLog) -> AuditEntry:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return AuditEntry(
            seq=row.seq,
            entry_id=row.entry_id,
            created_at=created_at,
            actor=AuditActor.model_validate(row.actor),
            action=row.action,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            payload=row.payload,
            prev_hash=row.prev_hash,
            entry_hash=row.entry_hash,
        )
