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
from hr_agents.models.money import Money


class RateTableKind(StrEnum):
    BPJS_KESEHATAN = "bpjs_kesehatan"
    BPJS_KETENAGAKERJAAN_JHT = "bpjs_ketenagakerjaan_jht"
    BPJS_KETENAGAKERJAAN_JP = "bpjs_ketenagakerjaan_jp"
    BPJS_JKK = "bpjs_jkk"
    BPJS_JKM = "bpjs_jkm"
    PPH21_TER = "pph21_ter"
    PPH21_PTKP = "pph21_ptkp"
    OVERTIME_PREMIUM = "overtime_premium"
    THR_FORMULA = "thr_formula"
    MINIMUM_WAGE = "minimum_wage"
    OTHER = "other"


class RateEntry(StrictModel):
    """One row in a rate table (e.g., a bracket, a risk class, a cap).

    Amounts are exact :data:`~hr_agents.models.money.Money`; percentages and the
    overtime multiplier are ratios and stay ``float``, because they are never
    summed into a total and turning them into ``Decimal`` would mean a
    ``/ Decimal(100)`` at every use site for no accuracy gain.

    ``key`` is the machine-readable selector for tables that have variants -- the
    BPJS JKK risk classes (I-IV), the JHT normal-vs-accelerated split, overtime
    tiers. ``payroll.py`` used to read ``entries[0]`` and apply it to every
    employee, which silently charged a class-IV industrial worker the class-I rate;
    an operator entering four risk classes had three of them ignored.
    """

    key: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    employee_share_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    employer_share_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    wage_cap: Money | None = Field(default=None, ge=0.0)
    lower_bound: Money | None = Field(default=None, ge=0.0)
    upper_bound: Money | None = Field(default=None, ge=0.0)
    multiplier: float | None = Field(default=None, ge=0.0)
    flat_amount: Money | None = Field(default=None, ge=0.0)
    hours_per_month: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Monthly hours divisor, in the `overtime_premium` table's `monthly_hours` "
            "row. Statutory, so it is operator-entered and verified rather than a "
            "constant in the payroll service."
        ),
    )
    notes: str | None = Field(default=None, max_length=500)

    def selected_by(self, key: str | None) -> bool:
        """Whether this row answers to ``key``, or is the table's only row."""
        return key is None or self.key == key


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
