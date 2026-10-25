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


def test_usage_gauges_render_per_provider_and_model() -> None:
    from hr_agents.models import LlmUsage
    from hr_agents.services.usage import LlmUsageService, LlmUsageStore

    ledger = LlmUsageService(LlmUsageStore())
    ledger.record(
        usage=LlmUsage(
            provider_id="llm.demo",
            model="model/a",
            input_tokens=10,
            output_tokens=4,
            requests=1,
        ),
        application_id="app-1",
    )
    state = SimpleNamespace(
        state=SimpleNamespace(queue=None, store=None, audit=None, llm_usage=ledger)
    )

    payload = asyncio.run(render_async(state))

    assert 'hragents_llm_tokens{provider="llm.demo",model="model/a",kind="input"} 10' in payload
    assert 'hragents_llm_tokens{provider="llm.demo",model="model/a",kind="output"} 4' in payload
    assert 'hragents_llm_requests{provider="llm.demo",model="model/a"} 1' in payload
