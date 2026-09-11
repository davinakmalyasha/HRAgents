"""Built-in queue provider specs."""

from typing import Any

from pydantic import Field

from hr_agents.config import get_settings
from hr_agents.providers.base import Capability, ProviderConfig, ProviderHealth, ProviderSpec
from hr_agents.providers.queue.memory import MemoryQueueBackend


class MemoryQueueConfig(ProviderConfig):
    """In-process queue. Not persistent — use for tests and tiny installs."""


class RedisQueueConfig(ProviderConfig):
    redis_url: str = Field(default="redis://localhost:6379/0")
    key_prefix: str = "hragents:queue"


class PostgresQueueConfig(ProviderConfig):
    """Uses the platform database — no extra service required."""


def _build_memory(config: ProviderConfig) -> MemoryQueueBackend:
    return MemoryQueueBackend()


def _build_redis(config: ProviderConfig) -> Any:
    from hr_agents.providers.queue.redis import RedisQueueBackend

    assert isinstance(config, RedisQueueConfig)
    return RedisQueueBackend.from_url(config.redis_url, prefix=config.key_prefix)


def _build_postgres(config: ProviderConfig) -> Any:
    from hr_agents.db import create_engine
    from hr_agents.providers.queue.postgres import PostgresQueueBackend

    return PostgresQueueBackend(create_engine(get_settings()))


def _health_ok(config: ProviderConfig) -> ProviderHealth:
    return ProviderHealth.ok("configuration valid")


QUEUE_SPECS: list[ProviderSpec] = [
    ProviderSpec(
        id="queue.memory",
        capability=Capability.QUEUE,
        display_name="In-memory queue",
        description="Process-local queue for tests and minimal installs. Lost on restart.",
        config_model=MemoryQueueConfig,
        build=_build_memory,
        health_check=_health_ok,
    ),
    ProviderSpec(
        id="queue.redis",
        capability=Capability.QUEUE,
        display_name="Redis Streams",
        description="Persistent, multi-worker queue. Included in the default Compose stack.",
        docs_url="https://redis.io",
        config_model=RedisQueueConfig,
        build=_build_redis,
        health_check=_health_ok,
    ),
    ProviderSpec(
        id="queue.postgres",
        capability=Capability.QUEUE,
        display_name="PostgreSQL",
        description="Queue inside the platform database — no additional service.",
        config_model=PostgresQueueConfig,
        build=_build_postgres,
        health_check=_health_ok,
    ),
]
