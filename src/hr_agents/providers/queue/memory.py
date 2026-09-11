"""In-memory queue backend — development, tests, and tiny single-process installs."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from hr_agents.providers.queue.base import (
    QueueError,
    QueueMessage,
    QueueStats,
    lease_deadline,
)


class MemoryQueueBackend:
    """Asyncio-safe, lease-based in-memory queue. Not persistent across restarts."""

    def __init__(self) -> None:
        self._pending: dict[str, deque[QueueMessage]] = defaultdict(deque)
        self._inflight: dict[str, QueueMessage] = {}
        self._dead: list[tuple[str, QueueMessage, str]] = []
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, payload: dict[str, Any]) -> str:
        message = QueueMessage(topic=topic, payload=payload)
        async with self._lock:
            self._pending[topic].append(message)
        return message.id

    async def claim(
        self, topic: str, *, max_messages: int = 1, lease_seconds: float = 60.0
    ) -> list[QueueMessage]:
        if max_messages <= 0:
            raise QueueError("max_messages must be positive")
        deadline = lease_deadline(lease_seconds)

        async with self._lock:
            self._recover_expired(topic)
            claimed: list[QueueMessage] = []
            queue = self._pending[topic]
            while queue and len(claimed) < max_messages:
                message = queue.popleft()
                message = message.model_copy(update={"lease_expires_at": deadline})
                self._inflight[message.id] = message
                claimed.append(message)
            return claimed

    async def ack(self, message_id: str) -> None:
        async with self._lock:
            if message_id not in self._inflight:
                raise QueueError(f"message {message_id!r} is not in flight")
            del self._inflight[message_id]

    async def nack(self, message_id: str, *, requeue: bool = True) -> None:
        async with self._lock:
            message = self._inflight.pop(message_id, None)
            if message is None:
                raise QueueError(f"message {message_id!r} is not in flight")
            message = message.model_copy(
                update={"attempts": message.attempts + 1, "lease_expires_at": None}
            )
            if requeue:
                self._pending[message.topic].appendleft(message)
            else:
                self._dead.append((message.topic, message, "nacked"))

    async def fail(self, message_id: str, reason: str = "") -> None:
        async with self._lock:
            message = self._inflight.pop(message_id, None)
            if message is None:
                raise QueueError(f"message {message_id!r} is not in flight")
            self._dead.append((message.topic, message, reason))

    async def stats(self, topic: str) -> QueueStats:
        async with self._lock:
            return QueueStats(
                topic=topic,
                pending=len(self._pending[topic]),
                inflight=sum(1 for m in self._inflight.values() if m.topic == topic),
                dead=sum(1 for t, _, _ in self._dead if t == topic),
            )

    async def dead_letters(self, topic: str | None = None) -> list[QueueMessage]:
        async with self._lock:
            return [
                message
                for entry_topic, message, _ in self._dead
                if topic is None or entry_topic == topic
            ]

    # --- internals ------------------------------------------------------

    def _recover_expired(self, topic: str) -> None:
        now = datetime.now(UTC)
        expired = [
            message
            for message in self._inflight.values()
            if message.topic == topic
            and message.lease_expires_at is not None
            and message.lease_expires_at <= now
        ]
        for message in expired:
            del self._inflight[message.id]
            requeued = message.model_copy(
                update={"attempts": message.attempts + 1, "lease_expires_at": None}
            )
            self._pending[topic].appendleft(requeued)
