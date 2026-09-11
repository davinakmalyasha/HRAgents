"""Queue capability: contract and built-in backends."""

from hr_agents.providers.queue.base import (
    QueueBackend,
    QueueError,
    QueueMessage,
    QueueStats,
)
from hr_agents.providers.queue.memory import MemoryQueueBackend

__all__ = [
    "MemoryQueueBackend",
    "QueueBackend",
    "QueueError",
    "QueueMessage",
    "QueueStats",
]
