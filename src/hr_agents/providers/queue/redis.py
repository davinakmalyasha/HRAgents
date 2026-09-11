"""Redis queue backend — the default in Docker Compose deployments.

Uses a reliable-queue pattern: pending list + in-flight hash with lease
deadlines. Serialized with Pydantic's JSON codec so messages are portable.

Accepts any Redis client (``redis.asyncio.Redis`` in production, ``fakeredis``
in tests) as long as it implements the standard command surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from hr_agents.providers.queue.base import (
    QueueError,
    QueueMessage,
    QueueStats,
    lease_deadline,
)

DEFAULT_PREFIX = "hragents:queue"


class RedisQueueBackend:
    """Lease-based queue on Redis lists + hashes."""

    def __init__(self, client: Redis, *, prefix: str = DEFAULT_PREFIX) -> None:
        self._redis = client
        self._prefix = prefix

    @classmethod
    def from_url(cls, url: str, *, prefix: str = DEFAULT_PREFIX) -> RedisQueueBackend:
        return cls(Redis.from_url(url), prefix=prefix)

    # --- keys -----------------------------------------------------------

    def _pending_key(self, topic: str) -> str:
        return f"{self._prefix}:{topic}:pending"

    def _inflight_key(self, topic: str) -> str:
        return f"{self._prefix}:{topic}:inflight"

    def _dead_key(self, topic: str) -> str:
        return f"{self._prefix}:{topic}:dead"

    def _topics_key(self) -> str:
        return f"{self._prefix}:topics"

    # --- operations -----------------------------------------------------

    async def publish(self, topic: str, payload: dict[str, Any]) -> str:
        message = QueueMessage(topic=topic, payload=payload)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.sadd(self._topics_key(), topic)
            pipe.lpush(self._pending_key(topic), message.model_dump_json())
            await pipe.execute()
        return message.id

    async def claim(
        self, topic: str, *, max_messages: int = 1, lease_seconds: float = 60.0
    ) -> list[QueueMessage]:
        if max_messages <= 0:
            raise QueueError("max_messages must be positive")
        deadline = lease_deadline(lease_seconds)
        await self._recover_expired(topic)

        claimed: list[QueueMessage] = []
        for _ in range(max_messages):
            raw = await self._redis.rpop(self._pending_key(topic))
            if raw is None:
                break
            if not isinstance(raw, (bytes, str)):
                raise QueueError(f"unexpected queue payload type: {type(raw).__name__}")
            text = raw.decode() if isinstance(raw, bytes) else raw
            message = QueueMessage.model_validate_json(text)
            message = message.model_copy(update={"lease_expires_at": deadline})
            await self._redis.hset(self._inflight_key(topic), message.id, message.model_dump_json())
            claimed.append(message)
        return claimed

    async def ack(self, message_id: str) -> None:
        topic = await self._find_inflight_topic(message_id)
        if topic is None:
            raise QueueError(f"message {message_id!r} is not in flight")
        await self._redis.hdel(self._inflight_key(topic), message_id)

    async def nack(self, message_id: str, *, requeue: bool = True) -> None:
        found = await self._find_inflight(message_id)
        if found is None:
            raise QueueError(f"message {message_id!r} is not in flight")
        topic, raw = found
        message = QueueMessage.model_validate_json(raw.decode() if isinstance(raw, bytes) else raw)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hdel(self._inflight_key(topic), message_id)
            if requeue:
                requeued = message.model_copy(
                    update={"attempts": message.attempts + 1, "lease_expires_at": None}
                )
                pipe.lpush(self._pending_key(topic), requeued.model_dump_json())
            else:
                pipe.lpush(self._dead_key(topic), message.model_dump_json())
            await pipe.execute()

    async def fail(self, message_id: str, reason: str = "") -> None:
        found = await self._find_inflight(message_id)
        if found is None:
            raise QueueError(f"message {message_id!r} is not in flight")
        topic, raw = found
        message = QueueMessage.model_validate_json(raw.decode() if isinstance(raw, bytes) else raw)
        entry = {"message": message.model_dump(mode="json"), "reason": reason}
        import json

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hdel(self._inflight_key(topic), message_id)
            pipe.lpush(self._dead_key(topic), json.dumps(entry))
            await pipe.execute()

    async def stats(self, topic: str) -> QueueStats:
        pending = await self._redis.llen(self._pending_key(topic))
        inflight = await self._redis.hlen(self._inflight_key(topic))
        dead = await self._redis.llen(self._dead_key(topic))
        return QueueStats(
            topic=topic,
            pending=int(pending),
            inflight=int(inflight),
            dead=int(dead),
        )

    async def dead_letters(self, topic: str | None = None) -> list[QueueMessage]:
        import json

        topics = (
            [topic]
            if topic is not None
            else [
                value.decode() if isinstance(value, bytes) else str(value)
                for value in await self._redis.smembers(self._topics_key())
            ]
        )
        messages: list[QueueMessage] = []
        for entry_topic in sorted(topics):
            raw_entries = await self._redis.lrange(self._dead_key(entry_topic), 0, -1)
            for raw in raw_entries:
                text = raw.decode() if isinstance(raw, bytes) else raw
                if text.startswith("{"):
                    parsed = json.loads(text)
                    if isinstance(parsed, dict) and "message" in parsed:
                        messages.append(QueueMessage.model_validate(parsed["message"]))
                        continue
                messages.append(QueueMessage.model_validate_json(text))
        return messages

    # --- internals ------------------------------------------------------

    async def _find_inflight(self, message_id: str) -> tuple[str, str | bytes] | None:
        topics = [
            value.decode() if isinstance(value, bytes) else str(value)
            for value in await self._redis.smembers(self._topics_key())
        ]
        for topic in sorted(topics):
            raw = await self._redis.hget(self._inflight_key(topic), message_id)
            if raw is not None:
                return topic, raw
        return None

    async def _find_inflight_topic(self, message_id: str) -> str | None:
        found = await self._find_inflight(message_id)
        return found[0] if found else None

    async def _recover_expired(self, topic: str) -> None:
        now = datetime.now(UTC)
        entries = await self._redis.hgetall(self._inflight_key(topic))
        for raw_id, raw in entries.items():
            text = raw.decode() if isinstance(raw, bytes) else raw
            message = QueueMessage.model_validate_json(text)
            if message.lease_expires_at is not None and message.lease_expires_at <= now:
                message_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
                requeued = message.model_copy(
                    update={"attempts": message.attempts + 1, "lease_expires_at": None}
                )
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.hdel(self._inflight_key(topic), message_id)
                    pipe.lpush(self._pending_key(topic), requeued.model_dump_json())
                    await pipe.execute()
