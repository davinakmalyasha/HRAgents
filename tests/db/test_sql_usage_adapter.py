"""The usage ledger on SQL: grouped sums and the recent rows."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.usage import DbLlmUsageStore
from hr_agents.models import LlmUsage, utc_now
from hr_agents.services.usage import LlmUsageService


def test_the_summary_groups_in_sql(factory: sessionmaker[Session]) -> None:
    service = LlmUsageService(DbLlmUsageStore(factory))
    service.record(
        usage=LlmUsage(
            provider_id="llm.demo", model="a", input_tokens=100, output_tokens=20, requests=2
        ),
        application_id="app-1",
    )
    service.record(
        usage=LlmUsage(
            provider_id="llm.demo", model="b", input_tokens=10, output_tokens=5, requests=1
        ),
        application_id="app-2",
    )

    summary = service.summary(since=utc_now() - timedelta(hours=1))

    assert summary.totals.input_tokens == 110
    assert summary.totals.requests == 3
    assert [item.model for item in summary.by_model] == ["a", "b"]


def test_recent_reads_newest_first(factory: sessionmaker[Session]) -> None:
    service = LlmUsageService(DbLlmUsageStore(factory))
    service.record(
        usage=LlmUsage(provider_id="llm.demo", model="first", requests=1),
        application_id="app-1",
    )
    service.record(
        usage=LlmUsage(provider_id="llm.demo", model="second", requests=1),
        application_id="app-2",
    )

    recent = service.recent(limit=1)

    assert [entry.model for entry in recent] == ["second"]
