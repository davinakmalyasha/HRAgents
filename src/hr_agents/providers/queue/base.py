"""Queue capability: contract shared by every queue backend.

All backends implement lease-based claiming: a claimed message is invisible to
other workers until acked, nacked (requeued), or failed (dead-lettered). A
conformance test suite runs identical scenarios against every backend.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import Field

from hr_agents.models import StrictModel, UtcDateTime, utc_now


class QueueMessage(StrictModel):
    """A unit of work in a topic queue."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    topic: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    attempts: int = Field(default=0, ge=0)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    lease_expires_at: UtcDateTime | None = None


class QueueStats(StrictModel):
    topic: str
    pending: int = Field(ge=0)
    inflight: int = Field(ge=0)
    dead: int = Field(ge=0)


class QueueError(RuntimeError):
    """Raised for invalid queue operations."""


@runtime_checkable
class QueueBackend(Protocol):
    """Lease-based work queue contract."""

    async def publish(self, topic: str, payload: dict[str, Any]) -> str:
        """Enqueue a message; returns its id."""
        ...

    async def claim(
        self, topic: str, *, max_messages: int = 1, lease_seconds: float = 60.0
    ) -> list[QueueMessage]:
        """Claim up to ``max_messages`` pending messages (recovering expired leases)."""
        ...

    async def ack(self, message_id: str) -> None:
        """Mark a message complete and remove it."""
        ...

    async def nack(self, message_id: str, *, requeue: bool = True) -> None:
        """Return a message; ``requeue=False`` dead-letters it."""
        ...

    async def fail(self, message_id: str, reason: str = "") -> None:
        """Dead-letter a message with a reason."""
        ...

    async def stats(self, topic: str) -> QueueStats:
        """Counts per state for one topic."""
        ...

    async def dead_letters(self, topic: str | None = None) -> list[QueueMessage]:
        """List dead-lettered messages, optionally filtered by topic."""
        ...


def lease_deadline(lease_seconds: float) -> datetime:
    if lease_seconds <= 0:
        raise QueueError("lease_seconds must be positive")
    return datetime.now(UTC) + timedelta(seconds=lease_seconds)
