"""PostgreSQL queue backend — for installs that refuse an extra service.

Implements the same lease-based contract with ``FOR UPDATE SKIP LOCKED`` claim
semantics (silently degrades to plain locks on SQLite in tests).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from hr_agents.providers.queue.base import (
    QueueError,
    QueueMessage,
    QueueStats,
    lease_deadline,
)

TABLE_NAME = "provider_queue"


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize DB-returned datetimes to aware UTC (SQLite strips tzinfo)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _require_utc(value: datetime | None, *, column: str) -> datetime:
    """Require a non-null timestamp from a row mapping."""
    result = _as_utc(value)
    if result is None:
        raise QueueError(f"database row is missing required column {column!r}")
    return result


def _define_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        TABLE_NAME,
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("topic", sa.String(200), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, default=0),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


class PostgresQueueBackend:
    """Lease-based queue on a single table."""

    def __init__(self, engine: AsyncEngine, *, table_name: str = TABLE_NAME) -> None:
        self._engine = engine
        self._metadata = sa.MetaData()
        self._table = _define_table(self._metadata)
        if table_name != TABLE_NAME:
            self._table.name = table_name
        self._initialized = False

    async def ensure_schema(self) -> None:
        if self._initialized:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all, checkfirst=True)
        self._initialized = True

    # --- operations -----------------------------------------------------

    async def publish(self, topic: str, payload: dict[str, Any]) -> str:
        await self.ensure_schema()
        message = QueueMessage(topic=topic, payload=payload)
        async with self._engine.begin() as conn:
            await conn.execute(
                self._table.insert().values(
                    id=message.id,
                    topic=topic,
                    payload=payload,
                    status="pending",
                    attempts=0,
                    created_at=message.created_at,
                )
            )
        return message.id

    async def claim(
        self, topic: str, *, max_messages: int = 1, lease_seconds: float = 60.0
    ) -> list[QueueMessage]:
        if max_messages <= 0:
            raise QueueError("max_messages must be positive")
        await self.ensure_schema()
        deadline = lease_deadline(lease_seconds)
        table = self._table

        await self._recover_expired(topic)

        async with self._engine.begin() as conn:
            claim_select = (
                sa.select(table.c.id)
                .where(table.c.topic == topic, table.c.status == "pending")
                .order_by(table.c.created_at, table.c.id)
                .limit(max_messages)
            )
            if self._engine.dialect.name == "postgresql":
                claim_select = claim_select.with_for_update(skip_locked=True)
            candidates = claim_select.subquery()
            update_stmt = (
                sa.update(table)
                .where(table.c.id.in_(sa.select(candidates.c.id)))
                .values(status="inflight", lease_expires_at=deadline)
                .returning(
                    table.c.id,
                    table.c.topic,
                    table.c.payload,
                    table.c.attempts,
                    table.c.created_at,
                    table.c.lease_expires_at,
                )
            )
            rows = (await conn.execute(update_stmt)).mappings().all()

        return [
            QueueMessage(
                id=row["id"],
                topic=row["topic"],
                payload=row["payload"] or {},
                attempts=row["attempts"],
                created_at=_require_utc(row["created_at"], column="created_at"),
                lease_expires_at=_as_utc(row["lease_expires_at"]),
            )
            for row in rows
        ]

    async def ack(self, message_id: str) -> None:
        await self.ensure_schema()
        table = self._table
        async with self._engine.begin() as conn:
            result = await conn.execute(
                sa.delete(table).where(table.c.id == message_id, table.c.status == "inflight")
            )
            if result.rowcount == 0:
                raise QueueError(f"message {message_id!r} is not in flight")

    async def nack(self, message_id: str, *, requeue: bool = True) -> None:
        await self.ensure_schema()
        table = self._table
        async with self._engine.begin() as conn:
            values = (
                {
                    "status": "pending",
                    "attempts": table.c.attempts + 1,
                    "lease_expires_at": None,
                }
                if requeue
                else {"status": "dead", "attempts": table.c.attempts + 1, "reason": "nacked"}
            )
            result = await conn.execute(
                sa.update(table)
                .where(table.c.id == message_id, table.c.status == "inflight")
                .values(**values)
            )
            if result.rowcount == 0:
                raise QueueError(f"message {message_id!r} is not in flight")

    async def fail(self, message_id: str, reason: str = "") -> None:
        await self.ensure_schema()
        table = self._table
        async with self._engine.begin() as conn:
            result = await conn.execute(
                sa.update(table)
                .where(table.c.id == message_id, table.c.status == "inflight")
                .values(
                    status="dead",
                    attempts=table.c.attempts + 1,
                    reason=reason,
                    lease_expires_at=None,
                )
            )
            if result.rowcount == 0:
                raise QueueError(f"message {message_id!r} is not in flight")

    async def stats(self, topic: str) -> QueueStats:
        await self.ensure_schema()
        table = self._table
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    sa.select(table.c.status, sa.func.count().label("count"))
                    .where(table.c.topic == topic)
                    .group_by(table.c.status)
                )
            ).all()
        by_status = {status: count for status, count in rows}
        return QueueStats(
            topic=topic,
            pending=int(by_status.get("pending", 0)),
            inflight=int(by_status.get("inflight", 0)),
            dead=int(by_status.get("dead", 0)),
        )

    async def dead_letters(self, topic: str | None = None) -> list[QueueMessage]:
        await self.ensure_schema()
        table = self._table
        stmt = sa.select(table).where(table.c.status == "dead")
        if topic is not None:
            stmt = stmt.where(table.c.topic == topic)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [
            QueueMessage(
                id=row["id"],
                topic=row["topic"],
                payload=row["payload"] or {},
                attempts=row["attempts"],
                created_at=_require_utc(row["created_at"], column="created_at"),
                lease_expires_at=_as_utc(row["lease_expires_at"]),
            )
            for row in rows
        ]

    # --- internals ------------------------------------------------------

    async def _recover_expired(self, topic: str) -> None:
        now = datetime.now(UTC)
        table = self._table
        async with self._engine.begin() as conn:
            await conn.execute(
                sa.update(table)
                .where(
                    table.c.topic == topic,
                    table.c.status == "inflight",
                    table.c.lease_expires_at.is_not(None),
                    table.c.lease_expires_at < now,
                )
                .values(
                    status="pending",
                    attempts=table.c.attempts + 1,
                    lease_expires_at=None,
                )
            )
