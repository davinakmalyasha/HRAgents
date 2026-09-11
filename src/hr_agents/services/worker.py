"""Queue worker: claim, process, ack — with retries and dead-lettering.

Transport-agnostic: works with any :class:`QueueBackend` provider. The handler
is injected (the pipeline in production, fakes in tests). Failed messages are
retried up to ``max_attempts`` and then dead-lettered with a reason.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from hr_agents.providers.queue import QueueBackend, QueueMessage

Handler = Callable[[QueueMessage], Awaitable[Any]]


@dataclass
class WorkerConfig:
    topic: str
    max_attempts: int = 3
    lease_seconds: float = 120.0
    batch_size: int = 1


@dataclass
class WorkerStats:
    processed: int = 0
    failed: int = 0
    requeued: int = 0
    dead_lettered: int = 0
    errors: list[str] = field(default_factory=list)


class Worker:
    """Single-topic worker with bounded attempts."""

    def __init__(
        self,
        queue: QueueBackend,
        handler: Handler,
        *,
        config: WorkerConfig | None = None,
    ) -> None:
        if config is None:
            raise ValueError("WorkerConfig is required")
        self._queue = queue
        self._handler = handler
        self._config = config
        self.stats = WorkerStats()

    async def run_once(self) -> int:
        """Process one batch; returns the number of messages handled."""
        messages = await self._queue.claim(
            self._config.topic,
            max_messages=self._config.batch_size,
            lease_seconds=self._config.lease_seconds,
        )
        for message in messages:
            try:
                await self._handler(message)
            except Exception as exc:
                self.stats.failed += 1
                self.stats.errors.append(f"{message.id}: {type(exc).__name__}: {exc}")
                if message.attempts + 1 >= self._config.max_attempts:
                    await self._queue.fail(message.id, reason=str(exc))
                    self.stats.dead_lettered += 1
                else:
                    await self._queue.nack(message.id, requeue=True)
                    self.stats.requeued += 1
                continue

            await self._queue.ack(message.id)
            self.stats.processed += 1
        return len(messages)
