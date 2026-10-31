"""Token accounting: sums, attribution and the time window."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from hr_agents.models import LlmPricing, LlmUsage, utc_now
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


PRICING = LlmPricing(
    input_cost_per_million=2.0,
    output_cost_per_million=8.0,
    cache_read_cost_per_million=0.5,
)


def priced_usage(model: str, *, inputs: int, outputs: int) -> LlmUsage:
    return LlmUsage(
        provider_id="llm.demo",
        model=model,
        input_tokens=inputs,
        output_tokens=outputs,
        cache_read_tokens=0,
        requests=1,
    )


def test_record_snapshots_the_operator_price() -> None:
    ledger = LlmUsageService(LlmUsageStore(), pricing=lambda: PRICING)

    entry = ledger.record(
        usage=priced_usage("model-a", inputs=1_000_000, outputs=500_000),
        application_id="app-1",
    )

    # 1M input at $2 + 0.5M output at $8.
    assert entry.cost_usd == 6.0


def test_an_application_rollup_sums_only_that_application() -> None:
    ledger = LlmUsageService(LlmUsageStore(), pricing=lambda: PRICING)
    ledger.record(
        usage=priced_usage("model-a", inputs=1_000_000, outputs=0),
        application_id="app-1",
    )
    ledger.record(
        usage=priced_usage("model-a", inputs=0, outputs=1_000_000),
        application_id="app-1",
    )
    ledger.record(
        usage=priced_usage("model-a", inputs=1_000_000, outputs=0),
        application_id="app-2",
    )

    rollup = ledger.application_usage("app-1")

    assert rollup.application_id == "app-1"
    assert rollup.entries == 2
    assert rollup.totals.input_tokens == 1_000_000
    assert rollup.totals.output_tokens == 1_000_000
    assert rollup.cost_usd == 10.0
    assert rollup.uncosted_entries == 0
    assert [item.model for item in rollup.by_model] == ["model-a"]


def test_an_uncosted_entry_makes_the_cost_unknown_not_partial() -> None:
    ledger = LlmUsageService(LlmUsageStore(), pricing=lambda: None)
    ledger.record(
        usage=priced_usage("model-a", inputs=1_000_000, outputs=0),
        application_id="app-1",
        pricing=PRICING,
    )
    ledger.record(
        usage=priced_usage("model-b", inputs=1_000_000, outputs=0),
        application_id="app-1",
    )

    rollup = ledger.application_usage("app-1")

    assert rollup.cost_usd is None
    assert rollup.uncosted_entries == 1
    assert rollup.totals.input_tokens == 2_000_000


def test_a_candidate_rollup_sums_all_of_their_applications() -> None:
    ledger = LlmUsageService(LlmUsageStore(), pricing=lambda: PRICING)
    ledger.record(
        usage=priced_usage("model-a", inputs=1_000_000, outputs=0),
        application_id="app-1",
    )
    ledger.record(
        usage=priced_usage("model-a", inputs=0, outputs=500_000),
        application_id="app-2",
    )
    candidate_id = uuid4()

    rollup = ledger.candidate_usage(candidate_id, ["app-1", "app-2", "app-1"])

    assert rollup.candidate_id == candidate_id
    assert rollup.application_ids == ["app-1", "app-2"]
    assert rollup.entries == 2
    assert rollup.totals.total_tokens == 1_500_000
    assert rollup.cost_usd == 6.0


def test_an_unknown_application_is_an_honest_zero() -> None:
    rollup = LlmUsageService(LlmUsageStore(), pricing=lambda: PRICING).application_usage("missing")

    assert rollup.totals.total_tokens == 0
    assert rollup.entries == 0
    assert rollup.cost_usd is None
    assert rollup.by_model == []


def test_pricing_is_skipped_when_none_is_configured() -> None:
    ledger = LlmUsageService(LlmUsageStore(), pricing=lambda: None)

    entry = ledger.record(usage=priced_usage("model-a", inputs=10, outputs=5), application_id="a")

    assert entry.cost_usd is None
