"""Payroll helpers: the defensive edges that keep a bad table from paying wrongly."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from hr_agents.models import RateEntry, RateTable, RateTableKind
from hr_agents.models.money import ZERO
from hr_agents.models.money import money as m
from hr_agents.services.payroll import (
    PayrollService,
    _days_in_period,
    _overtime_rules,
    _ptkp,
    _share,
    _thr_months_entitlement,
)


def table(kind: RateTableKind, *entries: RateEntry) -> RateTable:
    return RateTable(kind=kind, name=kind.value, entries=list(entries))


def test_a_share_with_no_percentage_is_zero() -> None:
    entry = RateEntry(label="no share", employer_share_percent=None)

    assert _share(entry, employer=True, wage=m(1_000_000)) == ZERO


def test_a_missing_ptkp_table_is_zero_not_an_exemption() -> None:
    assert _ptkp(None, None) == ZERO


def test_overtime_rules_require_every_tier() -> None:
    hours_only = table(
        RateTableKind.OVERTIME_PREMIUM,
        RateEntry(key="monthly_hours", label="Hours", hours_per_month=173.0),
    )

    assert _overtime_rules(hours_only) is None


def test_thr_entitlement_is_none_without_a_table() -> None:
    assert _thr_months_entitlement(12, None) is None


def test_thr_entitlement_falls_back_to_the_eight_year_band() -> None:
    formula = table(
        RateTableKind.THR_FORMULA,
        RateEntry(key="8y_plus", label="Eight years or more", multiplier=3.0),
    )

    assert _thr_months_entitlement(120, formula) == Decimal("3")


def test_days_in_period_drops_a_range_outside_the_month() -> None:
    assert (
        _days_in_period(
            date(2026, 1, 1),
            date(2026, 1, 31),
            period_year=2026,
            period_month=2,
        )
        == []
    )


def test_pph21_with_no_brackets_is_zero() -> None:
    assert PayrollService._compute_pph21(table(RateTableKind.PPH21_TER), m(1_000_000)) == ZERO


def test_pph21_below_the_lowest_bracket_is_zero() -> None:
    brackets = table(
        RateTableKind.PPH21_TER,
        RateEntry(label="high", lower_bound=m(100), employee_share_percent=5.0),
    )

    assert PayrollService._compute_pph21(brackets, m(50)) == ZERO


def test_pph21_skips_an_inverted_slab_instead_of_charging_it() -> None:
    brackets = table(
        RateTableKind.PPH21_TER,
        RateEntry(
            label="first",
            lower_bound=ZERO,
            upper_bound=m(100),
            employee_share_percent=5.0,
        ),
        RateEntry(
            label="inverted",
            lower_bound=m(100),
            upper_bound=m(50),
            employee_share_percent=5.0,
        ),
        RateEntry(
            label="last",
            lower_bound=m(150),
            upper_bound=m(200),
            employee_share_percent=5.0,
        ),
    )

    # 5% of the first 100 plus 5% of the final 50; the inverted slab adds nothing.
    assert PayrollService._compute_pph21(brackets, m(200)) == m(7.5)


def test_pph21_adds_a_flat_amount_when_the_bracket_carries_one() -> None:
    brackets = table(
        RateTableKind.PPH21_TER,
        RateEntry(label="flat", lower_bound=ZERO, flat_amount=m(1_000)),
    )

    assert PayrollService._compute_pph21(brackets, m(1_000_000)) == m(1_000)
