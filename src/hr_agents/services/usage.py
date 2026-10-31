"""Token accounting: what the models consumed, per evaluation and per model.

The pipeline measures usage from the provider result; this service keeps a small
ledger so the operations page can answer "which model is doing the work and how
much has it consumed" without summing a JSON column across every evaluation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from hr_agents.logging import get_logger
from hr_agents.models import (
    ApplicationUsage,
    CandidateUsage,
    LlmPricing,
    LlmUsage,
    LlmUsageEntry,
    UsageRollup,
    UsageSummary,
    UsageTotals,
    utc_now,
)

logger = get_logger(__name__)

_PRICE_FIELDS = (
    "input_cost_per_million",
    "output_cost_per_million",
    "cache_read_cost_per_million",
)


def active_llm_pricing() -> LlmPricing | None:
    """The active LLM provider's operator-entered prices, or ``None``.

    Pricing is deliberately skipped rather than guessed when no fields are set:
    the ledger still records tokens, and the rollup reports the cost as unknown
    instead of a number the operator never entered.
    """
    from hr_agents.providers.base import Capability
    from hr_agents.providers.settings import resolve_provider_settings

    try:
        resolved = resolve_provider_settings().get(Capability.LLM)
    except Exception:
        logger.warning("usage.pricing_unavailable", exc_info=True)
        return None
    if resolved is None or not any(field in resolved.config for field in _PRICE_FIELDS):
        return None
    return LlmPricing(
        input_cost_per_million=float(resolved.config.get("input_cost_per_million") or 0.0),
        output_cost_per_million=float(resolved.config.get("output_cost_per_million") or 0.0),
        cache_read_cost_per_million=float(
            resolved.config.get("cache_read_cost_per_million") or 0.0
        ),
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

    def rollup(self, application_ids: Sequence[str]) -> UsageRollup:
        """Sum every ledger row for these applications, cost included when priced."""
        wanted = set(application_ids)
        if not wanted:
            return UsageRollup(totals=UsageTotals())
        totals = UsageTotals()
        grouped: dict[tuple[str, str | None], UsageTotals] = defaultdict(UsageTotals)
        costed = 0
        cost = 0.0
        entries = 0
        for entry in self._items:
            if entry.application_id not in wanted:
                continue
            entries += 1
            usage = entry.as_usage()
            totals = totals.plus(usage)
            grouped[(entry.provider_id, entry.model)] = grouped[
                (entry.provider_id, entry.model)
            ].plus(usage)
            if entry.cost_usd is not None:
                costed += 1
                cost += entry.cost_usd
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
        return UsageRollup(
            totals=totals,
            cost_usd=round(cost, 6) if entries and costed == entries else None,
            uncosted_entries=entries - costed,
            entries=entries,
            by_model=rows,
        )

    def recent(self, *, limit: int = 50) -> list[LlmUsageEntry]:
        return list(reversed(self.list_all()))[:limit]


class LlmUsageService:
    """Record one evaluation's usage and read the aggregates."""

    def __init__(
        self,
        store: LlmUsageStore,
        *,
        pricing: Callable[[], LlmPricing | None] | None = None,
    ) -> None:
        self._store = store
        self._pricing = pricing or active_llm_pricing

    def record(
        self,
        *,
        usage: LlmUsage,
        application_id: str,
        evaluation_id: UUID | None = None,
        pricing: LlmPricing | None = None,
    ) -> LlmUsageEntry:
        price = pricing if pricing is not None else self._pricing()
        entry = LlmUsageEntry(
            evaluation_id=evaluation_id,
            application_id=application_id,
            provider_id=usage.provider_id,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            requests=usage.requests,
            cost_usd=price.cost(usage) if price is not None else None,
            created_at=utc_now(),
        )
        self._store.add(entry)
        return entry

    def summary(self, *, since: datetime) -> UsageSummary:
        return self._store.summary(since=since)

    def application_usage(self, application_id: str) -> ApplicationUsage:
        """One application's spend; a missing or empty ledger is honest zeros."""
        rollup = self._store.rollup([application_id])
        return ApplicationUsage(
            application_id=application_id,
            totals=rollup.totals,
            cost_usd=rollup.cost_usd,
            uncosted_entries=rollup.uncosted_entries,
            entries=rollup.entries,
            by_model=rollup.by_model,
        )

    def candidate_usage(self, candidate_id: UUID, application_ids: Sequence[str]) -> CandidateUsage:
        """Every application a candidate has, summed under one candidate id."""
        rollup = self._store.rollup(application_ids)
        return CandidateUsage(
            candidate_id=candidate_id,
            application_ids=sorted(set(application_ids)),
            totals=rollup.totals,
            cost_usd=rollup.cost_usd,
            uncosted_entries=rollup.uncosted_entries,
            entries=rollup.entries,
            by_model=rollup.by_model,
        )

    def recent(self, *, limit: int = 50) -> list[LlmUsageEntry]:
        return self._store.recent(limit=limit)
