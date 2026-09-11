"""Cross-backend conformance suite for the queue capability.

Every queue backend must pass the same behavior contract. Run this file
whenever a backend is added — if it passes, the platform runtime can treat the
backends as interchangeable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hr_agents.providers.queue import MemoryQueueBackend, QueueError
from hr_agents.providers.queue.postgres import PostgresQueueBackend
from hr_agents.providers.queue.redis import RedisQueueBackend


@pytest_asyncio.fixture(params=["memory", "redis", "postgres"])
async def backend(request: pytest.FixtureRequest) -> AsyncIterator[object]:
    if request.param == "memory":
        yield MemoryQueueBackend()
        return

    if request.param == "redis":
        client = fakeredis.aioredis.FakeRedis()
        yield RedisQueueBackend(client)
        await client.aclose()
        return

    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
    postgres_like = PostgresQueueBackend(engine)
    yield postgres_like
    await engine.dispose()


TOPIC = "tests.echo"


async def test_publish_claim_ack_roundtrip(backend: object) -> None:
    message_id = await backend.publish(TOPIC, {"value": 1})  # type: ignore[attr-defined]
    claimed = await backend.claim(TOPIC)  # type: ignore[attr-defined]

    assert len(claimed) == 1
    assert claimed[0].id == message_id
    assert claimed[0].payload == {"value": 1}

    await backend.ack(message_id)  # type: ignore[attr-defined]
    stats = await backend.stats(TOPIC)  # type: ignore[attr-defined]
    assert stats.pending == 0
    assert stats.inflight == 0


async def test_claim_empty_returns_empty_list(backend: object) -> None:
    assert await backend.claim("tests.empty") == []  # type: ignore[attr-defined]


async def test_claim_respects_max_messages(backend: object) -> None:
    for index in range(5):
        await backend.publish(TOPIC, {"i": index})  # type: ignore[attr-defined]

    first = await backend.claim(TOPIC, max_messages=2)  # type: ignore[attr-defined]
    second = await backend.claim(TOPIC, max_messages=10)  # type: ignore[attr-defined]

    assert len(first) == 2
    assert len(second) == 3
    all_payloads = {m.payload["i"] for m in [*first, *second]}
    assert all_payloads == {0, 1, 2, 3, 4}


async def test_claim_excludes_inflight_messages(backend: object) -> None:
    await backend.publish(TOPIC, {"value": 1})  # type: ignore[attr-defined]
    await backend.publish(TOPIC, {"value": 2})  # type: ignore[attr-defined]

    first = await backend.claim(TOPIC)  # type: ignore[attr-defined]
    second = await backend.claim(TOPIC)  # type: ignore[attr-defined]

    assert first[0].id != second[0].id


async def test_ack_unknown_message_raises(backend: object) -> None:
    with pytest.raises(QueueError, match="not in flight"):
        await backend.ack("nonexistent-id")  # type: ignore[attr-defined]


async def test_nack_requeues_with_attempt_increment(backend: object) -> None:
    message_id = await backend.publish(TOPIC, {"value": 1})  # type: ignore[attr-defined]
    claimed = await backend.claim(TOPIC)  # type: ignore[attr-defined]
    assert claimed[0].attempts == 0

    await backend.nack(message_id, requeue=True)  # type: ignore[attr-defined]
    reclaimed = await backend.claim(TOPIC)  # type: ignore[attr-defined]

    assert reclaimed[0].id == message_id
    assert reclaimed[0].attempts == 1


async def test_fail_dead_letters_with_reason(backend: object) -> None:
    message_id = await backend.publish(TOPIC, {"value": 1})  # type: ignore[attr-defined]
    await backend.claim(TOPIC)  # type: ignore[attr-defined]
    await backend.fail(message_id, "unrecoverable")  # type: ignore[attr-defined]

    stats = await backend.stats(TOPIC)  # type: ignore[attr-defined]
    assert stats.dead == 1
    assert stats.inflight == 0

    dead = await backend.dead_letters(TOPIC)  # type: ignore[attr-defined]
    assert [m.id for m in dead] == [message_id]


async def test_nack_without_requeue_dead_letters(backend: object) -> None:
    message_id = await backend.publish(TOPIC, {"value": 1})  # type: ignore[attr-defined]
    await backend.claim(TOPIC)  # type: ignore[attr-defined]
    await backend.nack(message_id, requeue=False)  # type: ignore[attr-defined]

    dead = await backend.dead_letters(TOPIC)  # type: ignore[attr-defined]
    assert [m.id for m in dead] == [message_id]


async def test_dead_letters_filtered_by_topic(backend: object) -> None:
    first = await backend.publish("tests.one", {"a": 1})  # type: ignore[attr-defined]
    second = await backend.publish("tests.two", {"b": 2})  # type: ignore[attr-defined]
    await backend.claim("tests.one")  # type: ignore[attr-defined]
    await backend.claim("tests.two")  # type: ignore[attr-defined]
    await backend.fail(first, "x")  # type: ignore[attr-defined]
    await backend.fail(second, "y")  # type: ignore[attr-defined]

    dead_one = await backend.dead_letters("tests.one")  # type: ignore[attr-defined]
    dead_all = await backend.dead_letters()  # type: ignore[attr-defined]

    assert [m.id for m in dead_one] == [first]
    assert {m.id for m in dead_all} == {first, second}


async def test_lease_expiry_recovers_message(backend: object) -> None:
    message_id = await backend.publish(TOPIC, {"value": 1})  # type: ignore[attr-defined]
    claimed = await backend.claim(TOPIC, lease_seconds=0.01)  # type: ignore[attr-defined]
    assert claimed[0].id == message_id

    await asyncio.sleep(0.05)

    reclaimed = await backend.claim(TOPIC, lease_seconds=30.0)  # type: ignore[attr-defined]
    assert len(reclaimed) == 1
    assert reclaimed[0].id == message_id
    assert reclaimed[0].attempts == 1


async def test_stats_reflect_states(backend: object) -> None:
    await backend.publish(TOPIC, {"value": 1})  # type: ignore[attr-defined]
    await backend.publish(TOPIC, {"value": 2})  # type: ignore[attr-defined]
    claimed = await backend.claim(TOPIC)  # type: ignore[attr-defined]
    await backend.fail(claimed[0].id, "boom")  # type: ignore[attr-defined]

    stats = await backend.stats(TOPIC)  # type: ignore[attr-defined]
    assert stats.topic == TOPIC
    assert stats.pending == 1
    assert stats.inflight == 0
    assert stats.dead == 1


async def test_invalid_max_messages_rejected(backend: object) -> None:
    with pytest.raises(QueueError, match="max_messages"):
        await backend.claim(TOPIC, max_messages=0)  # type: ignore[attr-defined]
