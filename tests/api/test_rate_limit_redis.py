"""The shared rate-limit window: one budget across replicas, fail-open on outage."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from hr_agents.api.hardening import RedisRateLimitStore


def make_store(client: object, *, limit: int = 3, clock: object = None) -> RedisRateLimitStore:
    kwargs: dict[str, object] = {"limit": limit, "window_seconds": 60.0}
    if callable(clock):
        kwargs["clock"] = clock
    return RedisRateLimitStore(client, **kwargs)  # type: ignore[arg-type]


async def test_two_stores_on_one_client_share_the_budget() -> None:
    """Two API processes must not each get their own copy of the limit."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    replica_a = make_store(client, limit=2)
    replica_b = make_store(client, limit=2)

    assert (await replica_a.hit("actor:riana"))[0] is True
    assert (await replica_b.hit("actor:riana"))[0] is True

    allowed, retry_after = await replica_a.hit("actor:riana")

    assert allowed is False
    assert 0 < retry_after <= 60


async def test_different_keys_do_not_share_a_budget() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = make_store(client, limit=1)

    assert (await store.hit("actor:a"))[0] is True
    assert (await store.hit("actor:b"))[0] is True


async def test_the_window_slides_forward_with_the_clock() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    now = [1_000.0]
    store = make_store(client, limit=1, clock=lambda: now[0])

    assert (await store.hit("ip:1.2.3.4"))[0] is True
    assert (await store.hit("ip:1.2.3.4"))[0] is False

    now[0] += 61
    assert (await store.hit("ip:1.2.3.4"))[0] is True


async def test_an_unreachable_store_fails_open() -> None:
    """Redis down means the rest of the stack is degraded; do not 429 everyone."""

    class Broken:
        def pipeline(self) -> object:
            raise ConnectionError("redis is down")

    store = make_store(Broken(), limit=1)

    assert (await store.hit("actor:a")) == (True, 0.0)


@pytest.mark.parametrize("limit", [1, 5])
async def test_the_refusal_reports_when_to_retry(limit: int) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    now = [500.0]
    store = make_store(client, limit=limit, clock=lambda: now[0])
    for _ in range(limit):
        assert (await store.hit("actor:a"))[0] is True

    now[0] += 20
    allowed, retry_after = await store.hit("actor:a")

    assert allowed is False
    assert 39 <= retry_after <= 40.1
