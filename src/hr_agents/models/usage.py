"""Model usage: tokens are the unit of AI cost, so they are recorded, not guessed.

A provider bills tokens; an operator who cannot see them cannot answer "what did
this candidate cost" or "which model is doing the work". The usage rides on the
evaluation (so the record explains itself) and lands in a small ledger that the
operations page aggregates by provider and model.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field, computed_field

from hr_agents.models.common import StrictModel, UtcDateTime, Versioned, utc_now


class UsageTotals(StrictModel):
    """Token counts without attribution."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    requests: int = Field(default=0, ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def plus(self, other: UsageTotals) -> UsageTotals:
        return UsageTotals(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            requests=self.requests + other.requests,
        )


class LlmUsage(UsageTotals):
    """What one provider/model consumed for one evaluation."""

    provider_id: str = Field(default="unknown", min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=200)

    def totals(self) -> UsageTotals:
        return UsageTotals(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            requests=self.requests,
        )


def sum_usage(items: list[LlmUsage]) -> LlmUsage | None:
    """Sum usages from the same provider/model, or the first one's identity.

    The pipeline runs k extractions with one provider, so the sum is honest; if a
    mixed list ever arrives, the first attribution is kept and the operator sees
    the aggregate under it. That is a reporting label, never a correctness input.
    """
    if not items:
        return None
    first = items[0]
    totals = first.totals()
    for item in items[1:]:
        totals = totals.plus(item.totals())
    return LlmUsage(
        provider_id=first.provider_id,
        model=first.model,
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        cache_read_tokens=totals.cache_read_tokens,
        requests=totals.requests,
    )


class UsageSummary(StrictModel):
    """What the operations page shows: totals and the split by model."""

    since: UtcDateTime
    totals: UsageTotals
    by_model: list[LlmUsage] = Field(default_factory=list)


class LlmUsageEntry(Versioned):
    """One ledger row: an evaluation's usage, attributable to a model."""

    id: UUID = Field(default_factory=uuid4)
    evaluation_id: UUID | None = None
    application_id: str = Field(min_length=1, max_length=64)
    provider_id: str = Field(min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    requests: int = Field(default=0, ge=0)
    created_at: UtcDateTime = Field(default_factory=utc_now)

    def as_usage(self) -> LlmUsage:
        return LlmUsage(
            provider_id=self.provider_id,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            requests=self.requests,
        )
