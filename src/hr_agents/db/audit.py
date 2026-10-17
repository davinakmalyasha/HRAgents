"""Postgres-backed audit chain.

Same hash-chain semantics as the in-memory ``AuditChain``; the chain lives in
``audit_log`` so tamper evidence survives restarts. Appends take a transaction
advisory lock before reading the tail, so two writers cannot claim the same
``seq`` (``seq`` is the primary key, so a bypassed lock still cannot corrupt the
chain — it just fails the append). Verification streams the chain in pages: it
never holds the whole log in memory.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from hr_agents.db.session import sync_session_scope
from hr_agents.db.tables import AuditLog
from hr_agents.models import AuditActor, AuditEntry
from hr_agents.services.audit import AuditChain, ChainCursor, chain_is_linked

AUDIT_CHAIN_LOCK_ID = 918_273_645
"""Advisory-lock key for the append path (PostgreSQL only)."""

VERIFY_PAGE_SIZE = 500
"""Entries per page while streaming verification."""


def _is_postgres(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload as the JSON column and the hash both understand it.

    ``AuditEntry.compute_hash`` canonicalises with ``default=str``, so a
    Decimal, date or UUID in a payload enters the hash as its string form; the
    JSON column has no such fallback and would refuse the write. Round-tripping
    through ``json.dumps(default=str)`` stores exactly what the hash covered --
    the same convention ``canonical_json`` uses -- so verification still matches
    after a restart.
    """
    return json.loads(json.dumps(payload, default=str))


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
            if _is_postgres(session):
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": AUDIT_CHAIN_LOCK_ID},
                )
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
                    payload=_json_payload(entry.payload),
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

    def entry_count(self) -> int:
        """Count the chain with a single aggregate, never a full read.

        ``entries`` selects and validates every row. Using it for a count turned
        a Prometheus scrape into 20,000 ORM loads, and turned an audit
        verification report into a second full pass over the log after ``verify()``
        had already streamed it.
        """
        with sync_session_scope(self._session_factory) as session:
            return session.execute(select(func.count()).select_from(AuditLog)).scalar_one()

    def page_entries(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditEntry], int]:
        """Newest-first slice with filters, ORDER BY and LIMIT/OFFSET in SQL.

        The viewer used to materialize and validate the whole chain on every
        read; the count runs over the same predicate in the same session, so a
        page and its total cannot disagree. The actor filter reads the JSON
        snapshot by its id, which is the only stable key an entry carries.
        """
        where: list[ColumnElement[bool]] = []
        if actor is not None:
            where.append(AuditLog.actor["actor_id"].as_string() == actor)
        if action is not None:
            where.append(AuditLog.action == action)
        if subject_type is not None:
            where.append(AuditLog.subject_type == subject_type)
        if subject_id is not None:
            where.append(AuditLog.subject_id == subject_id)
        if since is not None:
            where.append(AuditLog.created_at >= since)
        if until is not None:
            where.append(AuditLog.created_at <= until)
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(select(func.count()).select_from(AuditLog).where(*where))
            rows = (
                session.execute(
                    select(AuditLog)
                    .where(*where)
                    .order_by(AuditLog.seq.desc())
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [self._to_entry(row) for row in rows], int(total or 0)

    @property
    def last_hash(self) -> str | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(AuditLog.entry_hash).order_by(AuditLog.seq.desc()).limit(1)
            ).first()
            return row[0] if row is not None else None

    def verify(self) -> int:
        """Verify the chain page by page, returning the first invalid ``seq``.

        The persisted chain grows without bound, so verification streams it
        instead of materializing every entry.
        """
        with sync_session_scope(self._session_factory) as session:
            cursor = ChainCursor()
            while True:
                query = select(AuditLog).order_by(AuditLog.seq).limit(VERIFY_PAGE_SIZE)
                if cursor.last_seq is not None:
                    query = query.where(AuditLog.seq > cursor.last_seq)
                rows = session.execute(query).scalars().all()
                if not rows:
                    return -1
                for row in rows:
                    entry = self._to_entry(row)
                    if not chain_is_linked(entry, cursor):
                        return entry.seq
                    cursor = ChainCursor(expected_prev=entry.entry_hash, last_seq=entry.seq)

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
