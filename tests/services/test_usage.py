"""Token accounting: sums, attribution and the time window."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from hr_agents.models import LlmUsage, utc_now
from hr_agents.services.usage import LlmUsageService, LlmUsageStore


def service() -> LlmUsageService:
    return LlmUsageService(LlmUsageStore())


def usage(model: str, *, inputs: int, outputs: int, requests: int = 1) -> LlmUsage:
    return LlmUsage(
        provider_id="llm.demo",
        model=model,
        input_tokens=inputs,
        output_tokens=outputs,
        cache_read_tokens=5,
        requests=requests,
    )


def test_summary_sums_the_window_and_splits_by_model() -> None:
    ledger = service()
    ledger.record(
        usage=usage("model-a", inputs=100, outputs=40),
        application_id="app-1",
        evaluation_id=uuid4(),
    )
    ledger.record(
        usage=usage("model-a", inputs=50, outputs=10),
        application_id="app-2",
        evaluation_id=uuid4(),
    )
    ledger.record(usage=usage("model-b", inputs=10, outputs=5), application_id="app-3")

    summary = ledger.summary(since=utc_now() - timedelta(hours=1))

    assert summary.totals.input_tokens == 160
    assert summary.totals.output_tokens == 55
    assert summary.totals.cache_read_tokens == 15
    assert summary.totals.requests == 3
    assert [item.model for item in summary.by_model] == ["model-a", "model-b"]
    assert summary.by_model[0].total_tokens == 200


def test_the_window_is_exclusive() -> None:
    ledger = service()
    ledger.record(usage=usage("model-a", inputs=10, outputs=1), application_id="app-1")

    summary = ledger.summary(since=utc_now() + timedelta(minutes=1))

    assert summary.totals.input_tokens == 0
    assert summary.by_model == []


def test_recent_returns_the_newest_first() -> None:
    ledger = service()
    ledger.record(usage=usage("first", inputs=1, outputs=1), application_id="app-1")
    ledger.record(usage=usage("second", inputs=1, outputs=1), application_id="app-2")

    recent = ledger.recent(limit=1)

    assert [entry.model for entry in recent] == ["second"]
    assert recent[0].application_id == "app-2"
