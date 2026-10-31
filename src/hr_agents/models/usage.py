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


TOKENS_PER_MILLION = 1_000_000


class LlmPricing(StrictModel):
    """Operator-entered USD prices per million tokens.

    There is no built-in price list: providers change prices, and a hardcoded
    number would silently misstate a deployment's spend. A provider without
    prices records tokens and leaves the cost null.
    """

    input_cost_per_million: float = Field(default=0.0, ge=0)
    output_cost_per_million: float = Field(default=0.0, ge=0)
    cache_read_cost_per_million: float = Field(default=0.0, ge=0)

    def cost(self, usage: UsageTotals) -> float:
        """USD for this usage, rounded to the ledger's six decimals."""
        dollars = (
            usage.input_tokens * self.input_cost_per_million
            + usage.output_tokens * self.output_cost_per_million
            + usage.cache_read_tokens * self.cache_read_cost_per_million
        ) / TOKENS_PER_MILLION
        return round(dollars, 6)


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


class UsageRollup(StrictModel):
    """The spend behind one subject (an application, or all of a candidate's).

    ``cost_usd`` is null when any entry has no price snapshot: a partial sum
    would read as the whole bill. ``uncosted_entries`` says how many are missing.
    """

    totals: UsageTotals
    cost_usd: float | None = Field(default=None, ge=0)
    uncosted_entries: int = Field(default=0, ge=0)
    entries: int = Field(default=0, ge=0)
    by_model: list[LlmUsage] = Field(default_factory=list)


class ApplicationUsage(UsageRollup):
    """One application's evaluation spend."""

    application_id: str = Field(min_length=1, max_length=64)


class CandidateUsage(UsageRollup):
    """Every application a candidate has, summed; the answer to "what did this cost"."""

    candidate_id: UUID
    application_ids: list[str] = Field(default_factory=list)


class LlmUsageEntry(Versioned):
    """One ledger row: an evaluation's usage, attributable to a model."""

    id: UUID = Field(default_factory=uuid4)
    evaluation_id: UUID | None = None
    application_id: str = Field(min_length=1, max_length=64)
    provider_id: str = Field(default="unknown", min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    requests: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
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
