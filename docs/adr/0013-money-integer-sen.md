# ADR 0013 — Money is integer sen in `i64`; no floats in payroll; rounding is explicit

**Status:** accepted · **Date:** 2026-11-01

## Context

Python money is a 2-decimal `Decimal` with `ROUND_HALF_UP`, and statutory boundaries — BPJS
caps, PPh 21 PTKP/TER, overtime tiers, THR proration — round once each. A Rust port can
represent money as `f64` (drifts), `rust_decimal` (96-bit coefficient, fine for ratios but a
second arithmetic path), or a fixed integer. The database stores integers, JSON crosses IPC, and
JavaScript numbers are IEEE-754 doubles, so the choice constrains every layer at once.

## Decision

- `struct Money(i64)` in **sen** (1/100 IDR) with checked arithmetic, never `f64`.
- `rust_decimal` is allowed only for ratios and multipliers, parsed from the JSON number's text
  — never `as f64` — matching `Decimal(str(percent))`.
- Rounding is `MidpointAwayFromZero`, applied once per statutory boundary and nowhere else,
  matching `ROUND_HALF_UP`.
- Absence proration stays an exact ratio until the boundary; it is never quantised mid-formula.
- Storage is `INTEGER` `*_sen` on `STRICT` tables with `CHECK (col >= 0)` and the identity
  `CHECK (net_sen = gross_sen - total_deductions_sen)`.
- Reject `|amount| > 10^15` rupiah at parse; company-scale lines stay well inside the JavaScript
  safe-integer range.

## Consequences

Easier: parity with Python is exact at the sen; the net identity is enforced by SQLite, not only
by application code; property tests are cheap and fast.

Harder: every new statutory formula needs a documented rounding point and a golden at that
boundary, or a one-sen drift ships; money multiplied by a decimal needs an explicit widening
path; a total above 2^53 sen cannot round-trip through JSON, so IPC must paginate or stringify
rather than emit one enormous number.

Out of scope: `f64` money, multi-currency, sub-sen precision, banker's rounding, payment
execution of any kind.

Guards: the payroll invariants in `10-quality.md` §3 run as runtime checks plus `proptest`; a
golden exists per statutory boundary; `STRICT` rejects float coercion; the 1,000-employee run at
Gate 3 must equal Python to the sen.
