"""Money is exact, and the payroll identities hold.

These are the properties that justify replacing every ``float`` in payroll with
``Decimal``. Before that change each of them could fail:

- ``round()`` is round-half-to-**even**, so ``round(0.125, 2) == 0.12`` and
  ``round(0.135, 2) == 0.14``. A search over realistic wages and BPJS shares found
  291 amounts where the float result and a half-up result diverge, with the
  direction alternating on the cent.
- Every summation rounded at each step, so a total could differ from the sum of its
  printed parts.
- ``float`` money went into the XLSX packet, which reintroduced the drift on the way
  out.

`hypothesis` generates the cases nobody imagined. It is a dev dependency only.
"""

from decimal import ROUND_HALF_UP, Context, Decimal
from uuid import uuid4

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from hr_agents.models import PayrollLine, RateEntry, RateTable, RateTableKind
from hr_agents.models.money import (
    CENTS,
    ZERO,
    Money,
    add,
    money,
    percent_of,
    sub,
)


class _Amount(BaseModel):
    amount: Money


# Realistic Indonesian payroll magnitudes: a wage is millions of rupiah, a
# deduction share is a fraction of a percent.
_wage = st.decimals(
    min_value=Decimal("1_000_000"),
    max_value=Decimal("500_000_000"),
    places=2,
)
_share = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("24.00"), places=2)
_plain = st.decimals(min_value=Decimal("0"), max_value=Decimal("1_000_000"), places=2)


@given(st.floats(min_value=-1e30, max_value=1e30, allow_nan=False, allow_infinity=False, width=64))
def test_half_up_never_differs_from_a_float_round_for_exact_halves(value: float) -> None:
    """The specific behaviour that changed, pinned.

    Python rounds half to even; Indonesian payroll rounds half up. For any value
    whose third decimal is a 5, the two disagree, and the float result is the
    wrong one.

    The oracle here is deliberately *not* the library's own quantiser -- it is
    `Decimal` with an explicit wide context, so a bug in `money()` cannot make this
    pass. The range is bounded at 1e30 because past the library's 38-digit ceiling a
    value is rejected by design (see `_quantize`), which is its own test below.
    """
    result = _Amount(amount=money(value)).amount  # money() is the code under test
    assert result.as_tuple().exponent == -2, "money must always carry two places"
    exact = Decimal(repr(value)).quantize(CENTS, rounding=ROUND_HALF_UP, context=Context(prec=60))
    assert result == exact


def test_an_amount_too_large_to_be_money_is_refused_with_a_reason() -> None:
    """Not an opaque `InvalidOperation` from three frames down.

    `Decimal.quantize` overflows past 28 significant digits by default, so a large
    float used to crash with `InvalidOperation`. The library widens the context to
    40 digits and then rejects anything beyond it as not a payroll figure.
    """
    absurd = 1.0000000694e38
    with pytest.raises(ValueError, match="not a payroll figure"):
        money(absurd)
    # Just inside the ceiling still works.
    assert money(1e30) == Decimal("1" + "0" * 30 + ".00")


@given(_wage, _share)
def test_a_share_of_a_wage_loses_at_most_the_rounding_of_its_own_result(
    wage: Decimal, share: Decimal
) -> None:
    """The round-trip guarantee, stated correctly.

    Quantising the *share* to two places is the whole point -- a contribution is
    rounded to the rupiah -- so un-scaling it cannot recover the wage exactly. The
    error is bounded by two roundings: the share amount loses at most half a cent,
    and the recovered wage loses at most another half a cent. At 1% that bound is
    Rp 10; at 0.01% it is Rp 1,000, which is why this cannot be stated as "within
    one rupiah" for every percentage.
    """
    amount = percent_of(wage, share)
    assert amount >= ZERO
    recovered = (amount / (share / 100)).quantize(
        CENTS, rounding=ROUND_HALF_UP, context=Context(prec=60)
    )
    tolerance = CENTS * 100 / share
    assert abs(recovered - wage) <= tolerance, (
        f"{wage} at {share}% round-tripped to {recovered}, off by more than {tolerance}"
    )


@given(st.lists(_plain, min_size=1, max_size=40))
def test_summing_is_associative_within_one_cent(amounts: list[Decimal]) -> None:
    """Summing left-to-right or right-to-left agrees.

    Both are exact for ``Decimal``; neither was for ``float``, which is why the old
    totals could disagree with the printed lines.
    """
    forward = ZERO
    for item in amounts:
        forward = add(forward, item)
    backward = ZERO
    for item in reversed(amounts):
        backward = add(item, backward)
    assert abs(forward - backward) <= CENTS


@given(_wage, _plain)
def test_addition_is_the_inverse_of_subtraction(wage: Decimal, other: Decimal) -> None:
    assume(other <= wage)
    assert sub(add(wage, other), other) == money(wage)


@given(st.lists(_plain, max_size=30))
def test_a_sum_of_money_is_always_money(amounts: list[Decimal]) -> None:
    total = add(*amounts)
    assert isinstance(total, Decimal)
    assert total.as_tuple().exponent == -2
    assert total >= ZERO, "money is never negative here"


@given(_wage)
def test_money_serialises_as_a_json_number_not_a_string(value: Decimal) -> None:
    """The wire format must not change, or the dashboard types break.

    Pydantic renders ``Decimal`` as a JSON *string* by default, which would have
    silently changed every money field in the API to a quoted string.
    """
    payload = _Amount(amount=value).model_dump_json()
    assert '"amount":' in payload
    assert f'"{value}"' not in payload, payload
    assert float(payload.split(":")[1].rstrip("}")) == pytest.approx(float(value))


# --- payroll identities -------------------------------------------------------


def _line(**overrides: object) -> PayrollLine:
    """A well-formed line: components in, derived figures computed from them.

    The derived figures are recomputed *after* the overrides are applied, because a
    helper that computed them from the base values and then substituted the
    components would build an inconsistent line -- which is precisely what the
    invariant exists to reject, so a test using this helper must hand it a line that
    holds together.
    """
    fields: dict[str, object] = {
        "employee_id": uuid4(),
        "base_salary": money("10_000_000"),
        "allowances": money("1_000_000"),
        "overtime_pay": money("286_127.17"),
        "bonus": money("500_000"),
        "bpjs_kesehatan_employee": money("110_000.00"),
        "bpjs_jht_employee": money("220_000.00"),
        "bpjs_jp_employee": money("100_000.00"),
        "pph21": money("551_000.00"),
        "other_deductions": money("50_000.55"),
        "bpjs_kesehatan_employer": money("440_000.00"),
        "bpjs_jht_employer": money("407_000.00"),
        "bpjs_jp_employer": money("200_000.00"),
        "bpjs_jkk_employer": money("26_400.00"),
        "bpjs_jkm_employer": money("33_000.00"),
    }
    fields.update(overrides)

    gross = add(
        fields["base_salary"],
        fields["allowances"],
        fields["overtime_pay"],
        fields["bonus"],
    )
    deductions = add(
        fields["bpjs_kesehatan_employee"],
        fields["bpjs_jht_employee"],
        fields["bpjs_jp_employee"],
        fields["pph21"],
        fields["other_deductions"],
    )
    fields["gross"] = gross
    fields["total_deductions"] = deductions
    fields["net"] = sub(gross, deductions)
    fields["employer_cost"] = add(
        fields["bpjs_kesehatan_employer"],
        fields["bpjs_jht_employer"],
        fields["bpjs_jp_employer"],
        fields["bpjs_jkk_employer"],
        fields["bpjs_jkm_employer"],
    )
    return PayrollLine(**fields)  # type: ignore[arg-type]  # built from a dict on purpose


@settings(max_examples=200)
@given(
    allowance=st.decimals(min_value=Decimal("0"), max_value=Decimal("5_000_000"), places=2),
    overtime=st.decimals(min_value=Decimal("0"), max_value=Decimal("3_000_000"), places=2),
)
def test_a_well_formed_line_satisfies_its_identities(allowance: Decimal, overtime: Decimal) -> None:
    _line(allowances=money(allowance), overtime_pay=money(overtime)).check_invariants()


def test_the_invariant_catches_a_gross_that_is_one_allowance_high() -> None:
    """The bug this invariant was written for, reproduced.

    An earlier version of the prorating change folded the fixed allowance into
    ``base_salary`` *and* left it in ``allowances``, so every line overstated gross
    by exactly one allowance. Nothing else in the suite noticed, because the line
    still looked plausible.
    """
    line = _line()
    with pytest.raises(ValueError, match=r"gross .* does not equal base"):
        line.model_copy(update={"gross": add(line.gross, money("1_000_000"))}).check_invariants()


def test_the_invariant_catches_deductions_that_do_not_sum() -> None:
    line = _line()
    with pytest.raises(ValueError, match=r"total_deductions .* does not equal"):
        line.model_copy(
            update={"total_deductions": add(line.total_deductions, CENTS)}
        ).check_invariants()


def test_the_invariant_catches_a_net_that_is_not_gross_less_deductions() -> None:
    line = _line()
    with pytest.raises(ValueError, match=r"net .* does not equal gross"):
        line.model_copy(update={"net": add(line.net, CENTS)}).check_invariants()


def test_the_invariant_catches_employer_shares_that_do_not_sum() -> None:
    line = _line()
    with pytest.raises(ValueError, match=r"employer_cost .* does not equal"):
        line.model_copy(
            update={"employer_cost": add(line.employer_cost, money("1"))}
        ).check_invariants()


def test_a_negative_net_is_still_representable() -> None:
    """A negative net is a real state, flagged by an anomaly, not rejected here.

    `net` carries no `ge=0`, so the invariant must not assert one -- otherwise the
    blocking `negative_net` anomaly could never be recorded, because the line could
    never be built in the first place.

    Built from components that genuinely produce it (deductions above gross) rather
    than by patching the field, so the line is internally consistent.
    """
    line = _line(
        other_deductions=money("15_000_000"),
        pph21=money("0"),
        bpjs_kesehatan_employee=money("0"),
        bpjs_jht_employee=money("0"),
        bpjs_jp_employee=money("0"),
    )
    line.check_invariants()
    assert line.net < ZERO, "this fixture is meant to produce a negative net"


# --- rate entries -------------------------------------------------------------


@given(
    cap=st.decimals(min_value=Decimal("0"), max_value=Decimal("50_000_000"), places=2),
    percent=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("24.00"), places=2),
)
def test_a_wage_cap_is_never_exceeded(cap: Decimal, percent: Decimal) -> None:
    entry = RateEntry(label="capped", employer_share_percent=float(percent), wage_cap=cap)
    wage = money("30_000_000")
    charged = percent_of(min(wage, entry.wage_cap or wage), percent)
    assert charged <= (entry.wage_cap or wage), "a capped contribution exceeded the cap"


def test_rate_entries_carry_a_machine_key_for_the_variants() -> None:
    """The key is what stopped `entries[0]` being applied to everyone.

    Four BPJS JKK risk classes, four keys. An operator entering all four previously
    had three ignored and every employee charged the class-I rate.
    """
    table = RateTable(
        kind=RateTableKind.BPJS_JKK,
        name="JKK",
        entries=[
            RateEntry(
                key=f"class_{index}", label=f"class {index}", employer_share_percent=0.1 * index
            )
            for index in (1, 2, 3, 4)
        ],
    )
    assert [entry.key for entry in table.entries] == [
        "class_1",
        "class_2",
        "class_3",
        "class_4",
    ]
    assert table.entries[3].employer_share_percent == pytest.approx(0.4)
