"""Built-in queue provider specs.

Health checks are real reachability probes, not configuration echoes. A queue
that cannot be reached is a stopped pipeline, and the resolver
(:mod:`hr_agents.queue`) falls through to the next provider based on the result.
"""

import asyncio
import contextlib
from typing import Any

from pydantic import Field
from sqlalchemy import text

from hr_agents.config import get_settings
from hr_agents.providers.base import Capability, ProviderConfig, ProviderHealth, ProviderSpec
from hr_agents.providers.queue.memory import MemoryQueueBackend

PROBE_TIMEOUT_SECONDS = 3.0


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
    return ProviderHealth.ok("process-local queue, nothing to reach")


async def _health_redis(config: ProviderConfig) -> ProviderHealth:
    """Ping Redis so an unreachable broker never looks healthy."""
    assert isinstance(config, RedisQueueConfig)
    from redis.asyncio import Redis

    client = Redis.from_url(config.redis_url)
    try:
        await asyncio.wait_for(client.ping(), timeout=PROBE_TIMEOUT_SECONDS)
    except Exception as exc:
        return ProviderHealth.unavailable(
            f"redis unreachable at {config.redis_url}: {type(exc).__name__}"
        )
    finally:
        with contextlib.suppress(Exception):  # best-effort cleanup
            await client.aclose()
    return ProviderHealth.ok(f"redis reachable at {config.redis_url}")


def _health_postgres(config: ProviderConfig) -> ProviderHealth:
    """Run ``SELECT 1`` against the platform database."""
    from hr_agents.db import create_sync_engine

    try:
        engine = create_sync_engine(get_settings())
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except Exception as exc:
        return ProviderHealth.unavailable(f"postgres unreachable: {type(exc).__name__}: {exc}")
    return ProviderHealth.ok("postgres reachable")


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
        health_check=_health_redis,
    ),
    ProviderSpec(
        id="queue.postgres",
        capability=Capability.QUEUE,
        display_name="PostgreSQL",
        description="Queue inside the platform database — no additional service.",
        config_model=PostgresQueueConfig,
        build=_build_postgres,
        health_check=_health_postgres,
    ),
]
