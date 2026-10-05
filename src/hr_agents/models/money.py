"""Exact money arithmetic for statutory payroll.

Indonesian payroll has no rounding tolerance. A payslip that is off by one rupiah
per employee is a payslip an HR department cannot reconcile against a bank
transfer, and the failure shows up as a query, not as an exception.

Every monetary field in this project was a ``float`` with Python's ``round()``,
which is round-half-to-*even*: ``round(0.125, 2) == 0.12`` and
``round(0.135, 2) == 0.14``. No Indonesian payroll vendor reconciles to that, and
the direction of the error alternates with the cent, so it cannot be corrected by
a rounding convention applied afterwards.

So money is a :class:`~decimal.Decimal` quantised to two places with
``ROUND_HALF_UP`` at construction, and stays one through every operation. The JSON
wire format is unchanged -- ``Money`` serialises back to a JSON number -- so the
OpenAPI document and the generated dashboard client are unaffected.

Rates, percentages and multipliers are deliberately **not** money: they are ratios,
they are never summed into a total, and keeping them as floats avoids a
``Decimal(percent) / Decimal(100)`` dance at every use site. The one place a ratio
touches money, :func:`percent_of`, does the conversion in one line.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

__all__ = [
    "CENTS",
    "ZERO",
    "Money",
    "add",
    "money",
    "percent_of",
    "sub",
    "sum_money",
]

CENTS = Decimal("0.01")
"""Two decimal places. Rupiah has no sub-unit in practice."""

ZERO = Decimal("0.00")

# `Decimal`'s default context carries 28 significant digits, so `quantize` raises
# `InvalidOperation` for anything needing more. A float well outside the plausible
# range does exactly that: `1.0e26` needs 28 digits plus two decimal places.
#
# 40 leaves room for a 38-digit amount -- roughly a hundred times Indonesian GDP in
# rupiah -- and keeps `InvalidOperation` for input that is genuinely nonsense rather
# than merely enormous. Without this, `PayrollInput(base_salary=1e30)` crashes with
# an opaque arithmetic error instead of either working or explaining itself.
_QUANTIZE_CONTEXT = Context(prec=40)


def _quantize(value: Decimal) -> Decimal:
    """Quantise to two places, or name the ceiling that was exceeded.

    Past `_QUANTIZE_CONTEXT.prec` the input is not a payroll figure, so it is
    rejected here with a message a person can act on rather than surfacing as an
    `InvalidOperation` from three frames down.
    """
    try:
        return value.quantize(CENTS, rounding=ROUND_HALF_UP, context=_QUANTIZE_CONTEXT)
    except InvalidOperation as exc:
        exponent = value.as_tuple().exponent
        # `as_tuple().exponent` is typed as `int | Literal['n', 'N', 'F']` -- the
        # literals are the sentinels for NaN and Infinity, which `quantize` has
        # already rejected by the time this runs.
        places = -exponent if isinstance(exponent, int) else 0
        digits = len(value.as_tuple().digits) + places
        raise ValueError(
            f"{value} needs {digits} significant digits, more than a monetary amount "
            f"can hold ({_QUANTIZE_CONTEXT.prec} minus 2 for the decimal places). "
            "This is not a payroll figure."
        ) from exc


def money(value: object) -> Decimal:
    """Coerce anything numeric to a two-place ``Decimal``, rounding half up.

    ``float`` input goes through ``repr`` rather than ``str`` deliberately.
    ``Decimal(0.1)`` is the binary double nearest 0.1, which is slightly *above*
    0.1, so a value that should round down can round up. ``Decimal(str(0.1))`` is
    the decimal the caller meant. This is the documented conversion for exactly
    this reason.
    """
    if isinstance(value, Decimal):
        return _quantize(value)
    if isinstance(value, float):
        return _quantize(Decimal(repr(value)))
    try:
        return _quantize(Decimal(value))  # type: ignore[arg-type]
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{value!r} is not a monetary amount") from exc


Money = Annotated[
    Decimal,
    BeforeValidator(money),
    PlainSerializer(float, return_type=float, when_used="json"),
]
"""A monetary amount: exact, two places, ``ROUND_HALF_UP``, JSON number on the wire."""


def _coerce(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return money(value)


def add(*amounts: object) -> Decimal:
    """Sum amounts, quantising once at the end.

    Summing already-quantised values is exact, so this is belt-and-braces for the
    case where a caller passed a bare float. The rounding happens once, at the end,
    which is where a payslip's total must be rounded -- not at every intermediate
    addition.
    """
    return money(sum((_coerce(item) for item in amounts), ZERO))


def sub(left: object, right: object) -> Decimal:
    return money(_coerce(left) - _coerce(right))


def sum_money(amounts: list[Decimal] | None) -> Decimal:
    return add(*(amounts or []))


def percent_of(amount: object, percent: object) -> Decimal:
    """``percent`` of ``amount``, quantised once.

    The only boundary where a ratio meets money.
    """
    rate = Decimal(str(percent))
    return money(_coerce(amount) * rate / Decimal(100))
