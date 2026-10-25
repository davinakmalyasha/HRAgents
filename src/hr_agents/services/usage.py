"""Token accounting: what the models consumed, per evaluation and per model.

The pipeline measures usage from the provider result; this service keeps a small
ledger so the operations page can answer "which model is doing the work and how
much has it consumed" without summing a JSON column across every evaluation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from hr_agents.models import (
    LlmUsage,
    LlmUsageEntry,
    UsageSummary,
    UsageTotals,
    utc_now,
)


class LlmUsageStore:
    """In-memory usage ledger; the database adapter overrides the primitives."""

    def __init__(self) -> None:
        self._items: list[LlmUsageEntry] = []

    def add(self, entry: LlmUsageEntry) -> None:
        self._items.append(entry)

    def list_all(self) -> list[LlmUsageEntry]:
        return sorted(self._items, key=lambda item: (item.created_at, str(item.id)))

    def summary(self, *, since: datetime) -> UsageSummary:
        totals = UsageTotals()
        grouped: dict[tuple[str, str | None], UsageTotals] = defaultdict(UsageTotals)
        for entry in self._items:
            if entry.created_at < since:
                continue
            usage = entry.as_usage()
            totals = totals.plus(usage)
            key = (entry.provider_id, entry.model)
            grouped[key] = grouped[key].plus(usage)
        rows = [
            LlmUsage(
                provider_id=provider,
                model=model,
                input_tokens=value.input_tokens,
                output_tokens=value.output_tokens,
                cache_read_tokens=value.cache_read_tokens,
                requests=value.requests,
            )
            for (provider, model), value in grouped.items()
        ]
        rows.sort(key=lambda item: (item.total_tokens, item.requests), reverse=True)
        return UsageSummary(since=since, totals=totals, by_model=rows)

    def recent(self, *, limit: int = 50) -> list[LlmUsageEntry]:
        return list(reversed(self.list_all()))[:limit]


class LlmUsageService:
    """Record one evaluation's usage and read the aggregate."""

    def __init__(self, store: LlmUsageStore) -> None:
        self._store = store

    def record(
        self,
        *,
        usage: LlmUsage,
        application_id: str,
        evaluation_id: UUID | None = None,
    ) -> LlmUsageEntry:
        entry = LlmUsageEntry(
            evaluation_id=evaluation_id,
            application_id=application_id,
            provider_id=usage.provider_id,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            requests=usage.requests,
            created_at=utc_now(),
        )
        self._store.add(entry)
        return entry

    def summary(self, *, since: datetime) -> UsageSummary:
        return self._store.summary(since=since)

    def recent(self, *, limit: int = 50) -> list[LlmUsageEntry]:
        return self._store.recent(limit=limit)
