"""Statutory rate tables — structure ships, numbers are operator-owned.

No hardcoded statutory rates. HR enters and verifies values (BPJS shares, PPh 21
brackets, overtime premiums, THR formulas) in the UI; the system warns whenever a
table is unverified and never computes payroll with unverified values without a
recorded human acknowledgment.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class RateTableKind(StrEnum):
    BPJS_KESEHATAN = "bpjs_kesehatan"
    BPJS_KETENAGAKERJAAN_JHT = "bpjs_ketenagakerjaan_jht"
    BPJS_KETENAGAKERJAAN_JP = "bpjs_ketenagakerjaan_jp"
    BPJS_JKK = "bpjs_jkk"
    BPJS_JKM = "bpjs_jkm"
    PPH21_TER = "pph21_ter"
    OVERTIME_PREMIUM = "overtime_premium"
    THR_FORMULA = "thr_formula"
    MINIMUM_WAGE = "minimum_wage"
    OTHER = "other"


class RateEntry(StrictModel):
    """One row in a rate table (e.g., a bracket, a risk class, a cap)."""

    label: str = Field(min_length=1, max_length=200)
    employee_share_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    employer_share_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    wage_cap: float | None = Field(default=None, ge=0.0)
    lower_bound: float | None = Field(default=None, ge=0.0)
    upper_bound: float | None = Field(default=None, ge=0.0)
    multiplier: float | None = Field(default=None, ge=0.0)
    flat_amount: float | None = Field(default=None, ge=0.0)
    notes: str | None = Field(default=None, max_length=500)


class RateTable(StrictModel):
    """A versioned, verifiable set of statutory rates."""

    id: UUID = Field(default_factory=uuid4)
    kind: RateTableKind
    name: str = Field(min_length=1, max_length=200)
    jurisdiction: str = Field(default="ID", min_length=2, max_length=2)

    entries: list[RateEntry] = Field(default_factory=list)
    effective_from: date | None = None
    effective_to: date | None = None

    verified: bool = False
    verified_by: str | None = Field(default=None, max_length=200)
    verified_at: UtcDateTime | None = None
    source_note: str | None = Field(
        default=None,
        max_length=500,
        description="Where the numbers came from (regulation, official page, date fetched)",
    )

    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def usable(self) -> bool:
        """A table may only drive payroll math once a human has verified it."""
        return self.verified and self.verified_at is not None and bool(self.entries)

    def mark_verified(self, *, verified_by: str, source_note: str | None = None) -> RateTable:
        return self.model_copy(
            update={
                "verified": True,
                "verified_by": verified_by,
                "verified_at": utc_now(),
                "source_note": source_note or self.source_note,
                "updated_at": utc_now(),
            }
        )
