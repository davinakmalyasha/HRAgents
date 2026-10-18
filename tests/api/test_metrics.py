"""Queue gauges: dead letters and depth are what alerting can act on."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from hr_agents.api.metrics import render_async
from hr_agents.providers.queue import QueueStats


class _Queue:
    def __init__(self, *, pending: int, inflight: int, dead: int) -> None:
        self._stats = QueueStats(
            topic="evaluation.evaluate", pending=pending, inflight=inflight, dead=dead
        )

    async def stats(self, topic: str) -> QueueStats:
        assert topic == "evaluation.evaluate"
        return self._stats


class _BrokenQueue:
    async def stats(self, topic: str) -> QueueStats:
        raise RuntimeError("backend unreachable")


def _state(queue: object) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(queue=queue, store=None, audit=None))


def test_queue_gauges_render_when_a_backend_is_resolved() -> None:
    payload = asyncio.run(render_async(_state(_Queue(pending=3, inflight=1, dead=2))))

    assert 'hragents_queue_pending{topic="evaluation.evaluate"} 3' in payload
    assert 'hragents_queue_inflight{topic="evaluation.evaluate"} 1' in payload
    assert 'hragents_queue_dead{topic="evaluation.evaluate"} 2' in payload


def test_no_queue_series_before_the_lifespan_resolves_a_backend() -> None:
    payload = asyncio.run(render_async(_state(None)))

    assert "hragents_queue_" not in payload


def test_a_failing_backend_never_breaks_the_scrape() -> None:
    payload = asyncio.run(render_async(_state(_BrokenQueue())))

    assert "hragents_queue_" not in payload
    assert "hragents_build_info" in payload
