"""Postgres-backed model usage ledger.

Aggregation happens in SQL: the operations page and the metrics endpoint read
this often enough that summing every row in Python would turn a 15-second scrape
into a full table scan.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.mapping import add_model, list_models
from hr_agents.db.session import sync_session_scope
from hr_agents.models import (
    LlmUsage,
    LlmUsageEntry,
    UsageRollup,
    UsageSummary,
    UsageTotals,
)
from hr_agents.services.usage import LlmUsageStore


class DbLlmUsageStore(LlmUsageStore):
    """Usage rows in ``llm_usage``."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add(self, entry: LlmUsageEntry) -> None:
        add_model(self._session_factory, entry, t.LlmUsageRecord)

    def list_all(self) -> list[LlmUsageEntry]:
        records = list_models(self._session_factory, LlmUsageEntry, t.LlmUsageRecord)
        return sorted(records, key=lambda item: (item.created_at, str(item.id)))

    def summary(self, *, since: datetime) -> UsageSummary:
        row = t.LlmUsageRecord
        with sync_session_scope(self._session_factory) as session:
            grouped = session.execute(
                select(
                    row.provider_id,
                    row.model,
                    func.coalesce(func.sum(row.input_tokens), 0),
                    func.coalesce(func.sum(row.output_tokens), 0),
                    func.coalesce(func.sum(row.cache_read_tokens), 0),
                    func.coalesce(func.sum(row.requests), 0),
                )
                .where(row.created_at >= since)
                .group_by(row.provider_id, row.model)
            ).all()
        totals: dict[str, int] = defaultdict(int)
        by_model: list[LlmUsage] = []
        for provider, model, inputs, outputs, cached, requests in grouped:
            by_model.append(
                LlmUsage(
                    provider_id=provider,
                    model=model,
                    input_tokens=int(inputs),
                    output_tokens=int(outputs),
                    cache_read_tokens=int(cached),
                    requests=int(requests),
                )
            )
            totals["input"] += int(inputs)
            totals["output"] += int(outputs)
            totals["cache"] += int(cached)
            totals["requests"] += int(requests)
        by_model.sort(key=lambda item: (item.total_tokens, item.requests), reverse=True)
        return UsageSummary(
            since=since,
            totals=UsageTotals(
                input_tokens=totals["input"],
                output_tokens=totals["output"],
                cache_read_tokens=totals["cache"],
                requests=totals["requests"],
            ),
            by_model=by_model,
        )

    def recent(self, *, limit: int = 50) -> list[LlmUsageEntry]:
        row = t.LlmUsageRecord
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    select(row).order_by(row.created_at.desc(), row.id.desc()).limit(limit)
                )
                .scalars()
                .all()
            )
        return [_entry(item) for item in rows]

    def rollup(self, application_ids: Sequence[str]) -> UsageRollup:
        wanted = sorted(set(application_ids))
        if not wanted:
            return UsageRollup(totals=UsageTotals())
        row = t.LlmUsageRecord
        with sync_session_scope(self._session_factory) as session:
            grouped = session.execute(
                select(
                    row.provider_id,
                    row.model,
                    func.coalesce(func.sum(row.input_tokens), 0),
                    func.coalesce(func.sum(row.output_tokens), 0),
                    func.coalesce(func.sum(row.cache_read_tokens), 0),
                    func.coalesce(func.sum(row.requests), 0),
                    func.count(),
                    func.coalesce(func.sum(row.cost_usd), 0),
                    func.count(row.cost_usd),
                )
                .where(row.application_id.in_(wanted))
                .group_by(row.provider_id, row.model)
            ).all()
        totals: dict[str, int] = defaultdict(int)
        by_model: list[LlmUsage] = []
        entries = 0
        costed = 0
        cost = 0.0
        for (
            provider,
            model,
            inputs,
            outputs,
            cached,
            requests,
            count,
            cost_sum,
            cost_count,
        ) in grouped:
            entries += int(count)
            costed += int(cost_count)
            cost += float(cost_sum)
            by_model.append(
                LlmUsage(
                    provider_id=provider,
                    model=model,
                    input_tokens=int(inputs),
                    output_tokens=int(outputs),
                    cache_read_tokens=int(cached),
                    requests=int(requests),
                )
            )
            totals["input"] += int(inputs)
            totals["output"] += int(outputs)
            totals["cache"] += int(cached)
            totals["requests"] += int(requests)
        by_model.sort(key=lambda item: (item.total_tokens, item.requests), reverse=True)
        return UsageRollup(
            totals=UsageTotals(
                input_tokens=totals["input"],
                output_tokens=totals["output"],
                cache_read_tokens=totals["cache"],
                requests=totals["requests"],
            ),
            cost_usd=round(cost, 6) if entries and costed == entries else None,
            uncosted_entries=entries - costed,
            entries=entries,
            by_model=by_model,
        )


def _entry(record: t.LlmUsageRecord) -> LlmUsageEntry:
    created = record.created_at
    return LlmUsageEntry(
        id=record.id,
        evaluation_id=record.evaluation_id,
        application_id=record.application_id,
        provider_id=record.provider_id,
        model=record.model,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cache_read_tokens=record.cache_read_tokens,
        requests=record.requests,
        cost_usd=float(record.cost_usd) if record.cost_usd is not None else None,
        created_at=created.replace(tzinfo=UTC) if created.tzinfo is None else created,
        version=record.version,
    )
