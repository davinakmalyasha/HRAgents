"""Payroll preparation service — compute, verify, flag, export. Never pay.

Computation rules:

- Every monetary rate comes from a **verified** rate table. If a required table
  is missing or unverified, computation refuses to produce numbers for that
  component and records a blocking anomaly instead of guessing.
- Overtime uses the standard structure (first hour 1.5x, subsequent hours 2x)
  with multipliers read from the overtime rate table; the hourly base is
  ``base_salary / 173`` (the common monthly-to-hourly divisor; HR can confirm).
- PPh 21 is computed only when a TER-style table with brackets is provided;
  otherwise the run flags ``pph21_rate_table_missing`` for HR to handle in their
  own tax workflow.
- Sign-off goes through the approval engine (named human only). Export produces
  an XLSX review packet — the deliverable HR takes to their payroll provider.
"""

from __future__ import annotations

import calendar
import io
from collections.abc import Iterator
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from openpyxl import Workbook

from hr_agents.errors import DomainCode, DomainError
from hr_agents.identity import ActorRef, deciding_actor
from hr_agents.models import (
    AnomalySeverity,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    Employee,
    PayrollAnomaly,
    PayrollInput,
    PayrollLine,
    PayrollRun,
    PayrollRunKind,
    PayrollRunStatus,
    RateEntry,
    RateTable,
    RateTableKind,
    Urgency,
    utc_now,
)
from hr_agents.models.money import ZERO, add, money, percent_of, sub
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.rate_tables import RateTableError, RateTableService

NET_DEVIATION_THRESHOLD = 0.30
MAX_OVERTIME_HOURS = 60.0

OVERTIME_FIRST_HOURS_PER_DAY = Decimal("1")
"""UU 13/2003 Pasal 56(2): the 1.5x tier is one hour *per day*, not per month.

The previous code applied it to one hour for the whole month, so 24 overtime hours
in a month were priced as 1 hour at 1.5x and 23 at 2.0x. Per-day it is 24 separate
days of 1 hour at 1.5x and 1 at 2.0x. On a Rp 12,000,000 wage that is a
Rp 381,502 difference -- currently in the employee's favour, which is still a
reconciliation failure.
"""

MONTHLY_HOURS_KEY = "monthly_hours"
OVERTIME_FIRST_TIER_KEY = "first_hour"
OVERTIME_REST_TIER_KEY = "subsequent_hour"
PTKP_SELF_KEY = "personal"
PTKP_DEPENDENT_KEY = "dependent"

REQUIRED_TABLES: tuple[RateTableKind, ...] = (
    RateTableKind.BPJS_KESEHATAN,
    RateTableKind.BPJS_KETENAGAKERJAAN_JHT,
    RateTableKind.BPJS_KETENAGAKERJAAN_JP,
    RateTableKind.BPJS_JKK,
    RateTableKind.BPJS_JKM,
    RateTableKind.OVERTIME_PREMIUM,
    RateTableKind.PPH21_PTKP,
    RateTableKind.MINIMUM_WAGE,
)


class PayrollError(DomainError, RuntimeError):
    """Raised for invalid payroll operations."""


def _entry_for(table: RateTable | None, key: str | None) -> RateEntry | None:
    """The row that answers to ``key``, or the table's keyless default row.

    Replaces ``_first_entry``, which read ``entries[0]`` and therefore applied the
    first risk class to every employee regardless of their job. An operator who
    entered all four BPJS JKK classes had three of them ignored, and a class-IV
    industrial worker was charged 0.24% instead of 1.74% -- a Rp 300,000/month
    under-declaration that is also a BPJS compliance failure.

    The lookup is exact-key first, then a row with no key at all. The second step is
    what keeps every single-rate table working: most operators enter one row and
    leave `key` empty, and requiring a key on those would silently zero their
    contributions. When every row in a table carries a key and none matches, the
    result is `None` -- a missing rate is an anomaly, never a zero.
    """
    if table is None or not table.entries:
        return None
    if key is None:
        return table.entries[0] if len(table.entries) == 1 else None
    for entry in table.entries:
        if entry.key == key:
            return entry
    for entry in table.entries:
        if entry.key is None:
            return entry
    return None


def _share(entry: RateEntry | None, *, employer: bool, wage: Decimal) -> Decimal:
    """Apply a table entry's percentage share with its wage cap."""
    if entry is None:
        return ZERO
    percent = entry.employer_share_percent if employer else entry.employee_share_percent
    if percent is None:
        return ZERO
    cap = entry.wage_cap
    effective_wage = min(wage, cap) if cap is not None else wage
    return percent_of(effective_wage, percent)


def _risk_key(employee: Employee | None) -> str | None:
    """The BPJS JKK risk class to charge, as a table key.

    ``None`` when the employee's role carries no class -- which is every employee
    today, because `Employee` has no such field yet. That is a gap rather than an
    answer, so the caller raises an anomaly when it matters instead of guessing.
    """
    level = getattr(employee, "jkk_risk_level", None) if employee else None
    if not level:
        return None
    return f"class_{int(level)}"


def _is_keyed(table: RateTable | None) -> bool:
    """Whether a table distinguishes rows by ``key``.

    A single-row table is a flat rate and needs no key. A table where *any* row
    carries a key is discriminating, and charging its first row to everyone is the
    bug `_entry_for` replaced.
    """
    return table is not None and any(entry.key for entry in table.entries)


def _ptkp(employee: Employee | None, table: RateTable | None) -> Decimal:
    """Personal tax exemption plus dependent allowances, from a verified table.

    Both figures are statutory, so both come from the operator's `pph21_ptkp`
    table: a `personal` row and a `dependent` row. Returns zero when there is no
    table at all, but the caller treats that as blocking -- withholding without an
    exemption over-collects every month and the employee is owed the difference at
    year end, which is a payroll failure discovered by an auditor.
    """
    if table is None:
        return ZERO
    personal = _entry_for(table, PTKP_SELF_KEY)
    dependent = _entry_for(table, PTKP_DEPENDENT_KEY)
    if personal is None or personal.flat_amount is None:
        return ZERO
    allowance = ZERO
    claimed = employee.dependents if employee is not None else 0
    if claimed and dependent is not None and dependent.flat_amount is not None:
        allowance = money(Decimal(claimed) * dependent.flat_amount)
    return add(personal.flat_amount, allowance)


def _overtime_rules(table: RateTable | None) -> tuple[Decimal, Decimal, Decimal] | None:
    """``(monthly_hours, first_tier_multiplier, rest_tier_multiplier)`` or ``None``.

    Every part of overtime pricing is statutory, so all three come from the verified
    `overtime_premium` table. This returns ``None`` -- never a default -- when any of
    them is absent, because falling back to a hardcoded 173/1.5/2.0 is precisely the
    practice `AGENTS.md` forbids and the reason `overtime_premium` cannot be
    half-configured without anyone noticing.
    """
    hours = _entry_for(table, MONTHLY_HOURS_KEY)
    first = _entry_for(table, OVERTIME_FIRST_TIER_KEY)
    rest = _entry_for(table, OVERTIME_REST_TIER_KEY)
    if hours is None or hours.hours_per_month is None:
        return None
    if first is None or first.multiplier is None or rest is None or rest.multiplier is None:
        return None
    return (
        Decimal(str(hours.hours_per_month)),
        Decimal(str(first.multiplier)),
        Decimal(str(rest.multiplier)),
    )


def _thr_months_entitlement(service_months: int, table: RateTable | None) -> Decimal | None:
    """Months of wages owed on termination, from the verified `thr_formula` table.

    The service-length ladder (1 month under a year of service, more the longer the
    employee stayed) is statutory, so the rows come from the operator's table keyed
    ``under_1y``, ``1y``, ``2y`` ... ``8y_plus``. ``None`` when the employee's
    service length is not covered, which the caller treats as blocking rather than
    paying zero.
    """
    if table is None:
        return None
    key = "under_1y" if service_months < 12 else f"{service_months // 12}y"
    entry = _entry_for(table, key)
    if entry is None and service_months >= 96:
        entry = _entry_for(table, "8y_plus")
    if entry is None or entry.multiplier is None:
        return None
    return Decimal(str(entry.multiplier))


def _working_days_in_month(year: int, month: int) -> int:
    """Working days in the period, for proration.

    Weekends only. Indonesian public holidays are operator-set on the leave
    calendar and are not reachable from the payroll service without a dependency it
    does not have; the count is recorded so a proration is auditable rather than
    implicit.
    """
    total = date(year, month, calendar.monthrange(year, month)[1]).day
    first_weekday = date(year, month, 1).weekday()
    days = 0
    for offset in range(total):
        if (first_weekday + offset) % 7 < 5:
            days += 1
    return days


class PayrollService:
    """Assemble inputs, compute lines, flag anomalies, and gate sign-off."""

    def __init__(
        self,
        *,
        employees: EmployeeService,
        rate_tables: RateTableService,
        approvals: ApprovalEngine,
        audit: AuditChain | None = None,
    ) -> None:
        self._employees = employees
        self._rate_tables = rate_tables
        self._approvals = approvals
        self._audit = audit or AuditChain()
        self._runs: dict[UUID, PayrollRun] = {}

    # --- persistence primitives -----------------------------------------
    #
    # Adapters override only these; every rule about what a run may become next,
    # who may sign it off and when it blocks stays above.
    #
    # This seam matters more here than anywhere else. A payroll run that does not
    # survive a restart is not a lost convenience: `compute()` resolves the rate
    # tables in force for the period, so a re-run of a March 2025 payroll after the
    # 2026 decree was loaded produces *different figures* from the same inputs --
    # and records the new table ids as the provenance for them.

    def _load_run(self, run_id: UUID) -> PayrollRun | None:
        return self._runs.get(run_id)

    def _iter_runs(self) -> Iterator[PayrollRun]:
        return iter(list(self._runs.values()))

    def _save_run(self, run: PayrollRun) -> None:
        self._runs[run.id] = run

    # --- run lifecycle ---------------------------------------------------

    def create_run(
        self,
        *,
        period_year: int,
        period_month: int,
        actor: ActorRef,
        kind: PayrollRunKind = PayrollRunKind.MONTHLY,
    ) -> PayrollRun:
        if not 1 <= period_month <= 12:
            raise PayrollError("period_month must be 1-12")
        run = PayrollRun(
            period_year=period_year,
            period_month=period_month,
            kind=kind,
            status=PayrollRunStatus.DRAFT,
        )
        self._save_run(run)
        self._record(
            run,
            action="payroll.run_created",
            actor=actor,
            payload={"year": period_year, "month": period_month, "kind": kind.value},
        )
        return run

    def get_run(self, run_id: UUID) -> PayrollRun:
        run = self._load_run(run_id)
        if run is None:
            raise PayrollError(
                f"unknown payroll run {run_id}",
                code=DomainCode.UNKNOWN_RECORD,
                status=404,
            )
        return run

    def list_runs(self) -> list[PayrollRun]:
        return sorted(
            self._iter_runs(),
            key=lambda run: (run.period_year, run.period_month, run.created_at),
        )

    def set_inputs(
        self, run_id: UUID, *, inputs: list[PayrollInput], actor: ActorRef
    ) -> PayrollRun:
        run = self._require_editable(run_id)
        updated = run.model_copy(
            update={
                "inputs": inputs,
                "status": PayrollRunStatus.ASSEMBLING,
                "updated_at": utc_now(),
            }
        )
        self._save_run(updated)
        self._record(
            updated,
            action="payroll.inputs_set",
            actor=actor,
            payload={"employee_count": len(inputs)},
        )
        return updated

    # --- computation -----------------------------------------------------

    def compute(self, run_id: UUID, *, actor: ActorRef) -> PayrollRun:
        """Compute all lines from verified rate tables + detected anomalies."""
        run = self._require_editable(run_id)
        if not run.inputs:
            raise PayrollError("run has no inputs; call set_inputs first")

        # The rate table in force on the period being paid, not today. A March 2025
        # run computed in 2026 must use the 2025 rates.
        period = date(run.period_year, run.period_month, 1)
        extra = (RateTableKind.THR_FORMULA,) if run.kind is PayrollRunKind.THR else ()
        tables, table_ids, table_anomalies = self._resolve_tables(period=period, extra_kinds=extra)

        working_days = _working_days_in_month(run.period_year, run.period_month)
        lines: list[PayrollLine] = []
        anomalies: list[PayrollAnomaly] = list(table_anomalies)

        for payroll_input in run.inputs:
            employee = self._try_employee(payroll_input.employee_id)
            if run.kind is PayrollRunKind.THR:
                line, line_anomalies = self._compute_thr(
                    payroll_input, employee, tables, working_days=working_days
                )
            else:
                line, line_anomalies = self._compute_line(
                    payroll_input, employee, tables, working_days=working_days
                )
            lines.append(line)
            anomalies.extend(line_anomalies)

        previous = self._previous_run(run)
        if previous is not None:
            anomalies.extend(self._deviation_anomalies(lines, previous))

        updated = run.model_copy(
            update={
                "lines": lines,
                "anomalies": anomalies,
                "rate_table_ids": table_ids,
                "status": PayrollRunStatus.READY_FOR_REVIEW,
                "updated_at": utc_now(),
            }
        )
        self._save_run(updated)
        self._record(
            updated,
            action="payroll.computed",
            actor=actor,
            payload={
                "employees": len(lines),
                "anomalies": len(anomalies),
                "blocking": len(updated.blocking_anomalies),
                "rate_tables": table_ids,
            },
        )
        return updated

    def _resolve_tables(
        self, *, period: date, extra_kinds: tuple[RateTableKind, ...] = ()
    ) -> tuple[dict[RateTableKind, RateTable], dict[str, str], list[PayrollAnomaly]]:
        """Fetch the table in force for each kind, on the payroll period's date.

        This used to filter `list_all()` by kind and take `candidates[-1]`, on a
        list `RateTableStore.list_all()` returns **sorted by name**. So with two
        versions of a table the alphabetically-later *name* won -- regardless of
        verification, effective dates, or creation order. `require_usable` exists
        to answer this question properly, and its own docstring warns that "ordering
        by name or by list position would silently pick an arbitrary table"; payroll
        was the one caller not using it, so it had zero production call sites.

        The consequence was silent and material: back-running a March 2025 payroll
        after the 2026 decree was loaded used the 2026 BPJS rates, and recorded the
        2026 table id as the provenance for the figures -- which defeats the point
        of recording it at all.
        """
        tables: dict[RateTableKind, RateTable] = {}
        table_ids: dict[str, str] = {}
        anomalies: list[PayrollAnomaly] = []

        wanted = [*REQUIRED_TABLES, RateTableKind.PPH21_TER]
        if extra_kinds:
            wanted.extend(extra_kinds)
        for kind in dict.fromkeys(wanted):
            try:
                table = self._rate_tables.require_usable(kind, as_of=period)
            except RateTableError as exc:
                anomalies.append(
                    PayrollAnomaly(
                        code=f"rate_table_unusable:{kind.value}",
                        severity=AnomalySeverity.ERROR,
                        detail=(
                            f"{kind.value}: {exc} The rate in force on "
                            f"{period.isoformat()} is what this payroll must use."
                        ),
                    )
                )
                continue
            tables[kind] = table
            table_ids[kind.value] = str(table.id)
        return tables, table_ids, anomalies

    def _compute_thr(
        self,
        payroll_input: PayrollInput,
        employee: Employee | None,
        tables: dict[RateTableKind, RateTable],
        *,
        working_days: int,
    ) -> tuple[PayrollLine, list[PayrollAnomaly]]:
        """Termination pay: months of wages owed, from the verified `thr_formula` table.

        Until this existed, `PayrollRunKind.THR` was a label with no effect on the
        arithmetic: a THR run computed an identical monthly payslip and called it a
        termination payout, so the review packet showed a departing employee one
        month's salary and an HR reviewer had no signal that anything was wrong.

        The entitlement ladder is statutory, so it comes from the operator's table
        (`under_1y`, `1y` .. `8y_plus`, each row's `multiplier` = months of wages).
        Nothing is defaulted: an uncovered service length blocks, because paying a
        departing employee less than the law requires is a labour dispute.

        BPJS treatment of THR is *not* modelled -- which contributions apply to a
        termination payout, and at what proration, depends on the operator's
        arrangement and is not derivable from the monthly tables. Rather than
        silently applying monthly rules to a termination, the line carries an
        ERROR anomaly so sign-off cannot proceed until a human decides. That is the
        one deliberate gap left in this service, and it is loud.
        """
        anomalies: list[PayrollAnomaly] = []
        monthly_wage = add(payroll_input.base_salary, payroll_input.fixed_allowances)

        anomalies.append(
            PayrollAnomaly(
                code="thr_bpjs_unmodelled",
                severity=AnomalySeverity.ERROR,
                employee_id=payroll_input.employee_id,
                detail=(
                    "BPJS contributions are not computed on this termination payout: which "
                    "contributions apply to THR, and at what proration, depends on the "
                    "employer's arrangement and is not derivable from the monthly tables. "
                    "No contribution has been withheld. A named human must settle this "
                    "before sign-off."
                ),
            )
        )

        absence_days = payroll_input.absence_days
        paid_fraction = Decimal(1)
        if absence_days >= working_days:
            paid_fraction = ZERO
        else:
            paid_fraction = Decimal(working_days - absence_days) / Decimal(working_days)

        thr_table = tables.get(RateTableKind.THR_FORMULA)
        entitlement = _thr_months_entitlement(payroll_input.service_months, thr_table)
        if entitlement is None:
            anomalies.append(
                PayrollAnomaly(
                    code="thr_entitlement_missing",
                    severity=AnomalySeverity.ERROR,
                    employee_id=payroll_input.employee_id,
                    detail=(
                        f"no usable thr_formula row covers {payroll_input.service_months} "
                        "months of service, so the termination entitlement cannot be "
                        "determined without inventing a statutory figure. Enter and "
                        "verify the table (keys: under_1y, 1y .. 8y_plus)."
                    ),
                )
            )
            line = self._thr_line(payroll_input, employee, ZERO, 0, paid_fraction, anomalies)
            return line, anomalies

        # Whole-month entitlement, prorated for the days actually worked in the
        # final month. Adding a separate "partial month" term on top double-counted:
        # with no absence it paid 4 months' wages against a 3-month entitlement.
        thr_pay = percent_of(money(monthly_wage * entitlement), paid_fraction * 100)

        line = self._thr_line(
            payroll_input, employee, thr_pay, int(entitlement), paid_fraction, anomalies
        )
        return line, anomalies

    @staticmethod
    def _thr_line(
        payroll_input: PayrollInput,
        employee: Employee | None,
        thr_pay: Decimal,
        months: int,
        paid_fraction: Decimal,
        anomalies: list[PayrollAnomaly],
    ) -> PayrollLine:
        """Assemble a termination payslip.

        Deductions the employee elected -- loans, other deductions -- still come off
        a termination payout, so they are honoured here. BPJS is not, by design; see
        `_compute_thr`.
        """
        total_deductions = add(payroll_input.other_deductions, payroll_input.loan_deduction)
        line = PayrollLine(
            employee_id=payroll_input.employee_id,
            employee_name=employee.full_name if employee else "",
            base_salary=thr_pay,
            gross=thr_pay,
            total_deductions=total_deductions,
            net=sub(thr_pay, total_deductions),
            thr_months=months,
            other_deductions=total_deductions,
            notes=[note for note in [payroll_input.note] if note],
        )
        line.check_invariants()
        return line

    def _compute_line(
        self,
        payroll_input: PayrollInput,
        employee: Employee | None,
        tables: dict[RateTableKind, RateTable],
        *,
        working_days: int,
    ) -> tuple[PayrollLine, list[PayrollAnomaly]]:
        anomalies: list[PayrollAnomaly] = []
        wage = add(payroll_input.base_salary, payroll_input.fixed_allowances)

        # --- unpaid absence -------------------------------------------------
        # `absence_days` was collected, range-validated, persisted, exposed in
        # OpenAPI and the generated dashboard client -- and never read by any
        # computation. An employee absent 15 days was paid in full, with their own
        # acknowledgement note printed on the payslip.
        absence_days = payroll_input.absence_days
        paid_fraction = Decimal(1)
        if absence_days > 0:
            if absence_days >= working_days:
                anomalies.append(
                    PayrollAnomaly(
                        code="absence_exceeds_period",
                        severity=AnomalySeverity.ERROR,
                        employee_id=payroll_input.employee_id,
                        detail=(
                            f"{absence_days} absence days is the whole "
                            f"{working_days}-day period; check the inputs."
                        ),
                    )
                )
                paid_fraction = ZERO
            else:
                # Deliberately *not* run through `money()`. That quantises to two
                # places, and a ratio is not money: 14/22 of a month came out as
                # 0.64, which on a Rp 10,000,000 wage pays Rp 6,400,000 instead of
                # Rp 6,363,636.36 -- a Rp 36,364 overpayment per proration. The
                # fraction stays exact and `percent_of` quantises the money once.
                paid_fraction = Decimal(working_days - absence_days) / Decimal(working_days)

        # --- overtime -------------------------------------------------------
        # Priced per day: the 1.5x tier is one hour per day (UU 13/2003 Pasal
        # 56(2)), not one hour per month. Every number comes from the verified
        # `overtime_premium` table; there is no fallback, because a silent default
        # is how a statutory rate ends up being a constant nobody can audit.
        overtime_table = tables.get(RateTableKind.OVERTIME_PREMIUM)
        overtime_rules = _overtime_rules(overtime_table)
        hourly = ZERO
        hours = Decimal(str(payroll_input.overtime_hours))
        overtime_pay = ZERO
        if overtime_rules is None:
            anomalies.append(
                PayrollAnomaly(
                    code="overtime_rules_missing",
                    severity=AnomalySeverity.ERROR,
                    employee_id=payroll_input.employee_id,
                    detail=(
                        "the overtime_premium table has no complete set of "
                        f"'{MONTHLY_HOURS_KEY}' (hours_per_month), "
                        f"'{OVERTIME_FIRST_TIER_KEY}' and "
                        f"'{OVERTIME_REST_TIER_KEY}' (multiplier) rows, so overtime "
                        "cannot be priced without inventing a statutory rate."
                    ),
                )
            )
        else:
            monthly_hours, first_multiplier, rest_multiplier = overtime_rules
            hourly = wage / monthly_hours
            if hours > 0:
                # Days the employee worked at all: the full period less absences. The
                # 1.5x tier is one hour *per day* (UU 13/2003 Pasal 56(2)). Rounded,
                # not truncated -- `int()` turns 14.999 into 14 days of first-tier
                # hours.
                days_worked = max(
                    1,
                    int(
                        (Decimal(working_days) * paid_fraction).quantize(
                            Decimal("1"), ROUND_HALF_UP
                        )
                    ),
                )
                first_hours = min(hours, Decimal(days_worked) * OVERTIME_FIRST_HOURS_PER_DAY)
                # Hours are a ratio, not money, so no two-place quantisation here.
                rest_hours = max(hours - first_hours, ZERO)
                overtime_pay = add(
                    hourly * first_multiplier * first_hours,
                    hourly * rest_multiplier * rest_hours,
                )

        if payroll_input.overtime_hours > MAX_OVERTIME_HOURS:
            anomalies.append(
                PayrollAnomaly(
                    code="overtime_excessive",
                    severity=AnomalySeverity.WARNING,
                    employee_id=payroll_input.employee_id,
                    detail=(
                        f"{payroll_input.overtime_hours} overtime hours exceeds "
                        f"{MAX_OVERTIME_HOURS}; verify with the manager."
                    ),
                )
            )

        # Wages and fixed allowances scale with the days actually paid; overtime
        # does not, because it is already an hours count.
        #
        # `contribution_wage` is base + fixed, which is what BPJS contributions are
        # assessed on. `base_paid` and `fixed_paid` are kept apart so the line's
        # components sum to its gross exactly once -- an earlier version folded
        # fixed into `base_salary` *and* listed it in `allowances`, which
        # `PayrollLine.check_invariants` caught as a one-allowance double count.
        base_paid = percent_of(payroll_input.base_salary, paid_fraction * 100)
        fixed_paid = percent_of(payroll_input.fixed_allowances, paid_fraction * 100)
        paid_variable = percent_of(payroll_input.variable_allowances, paid_fraction * 100)
        contribution_wage = add(base_paid, fixed_paid)

        # --- minimum wage ---------------------------------------------------
        # The regional minimum is statutory and sits in a verified table nobody was
        # reading. Paying below it is a labour-law breach, so the comparison is on
        # the *paid* wage, and a shortfall blocks rather than warns.
        minimum_table = tables.get(RateTableKind.MINIMUM_WAGE)
        minimum_row = _entry_for(minimum_table, None)
        minimum = minimum_row.wage_cap if minimum_row is not None else None
        if minimum_row is not None and minimum_row.flat_amount is not None:
            minimum = minimum_row.flat_amount
        if minimum is not None and contribution_wage < minimum:
            anomalies.append(
                PayrollAnomaly(
                    code="below_minimum_wage",
                    severity=AnomalySeverity.ERROR,
                    employee_id=payroll_input.employee_id,
                    detail=(
                        f"paid wage {contribution_wage} is below the configured minimum "
                        f"{minimum}; paying it is a labour-law breach. Correct the input "
                        "or the rate table."
                    ),
                )
            )

        gross = add(
            base_paid,
            fixed_paid,
            paid_variable,
            overtime_pay,
            payroll_input.bonus,
        )

        # --- BPJS -----------------------------------------------------------
        # The rate keys off the employee's risk class, not the table's first row.
        risk_key = _risk_key(employee)
        kes = tables.get(RateTableKind.BPJS_KESEHATAN)
        jht = tables.get(RateTableKind.BPJS_KETENAGAKERJAAN_JHT)
        jp = tables.get(RateTableKind.BPJS_KETENAGAKERJAAN_JP)
        jkk = tables.get(RateTableKind.BPJS_JKK)
        jkm = tables.get(RateTableKind.BPJS_JKM)

        def usable(table: RateTable | None) -> RateTable | None:
            return table if table is not None and table.usable else None

        kes_employee = _share(_entry_for(usable(kes), None), employer=False, wage=contribution_wage)
        kes_employer = _share(_entry_for(usable(kes), None), employer=True, wage=contribution_wage)
        jht_employee = _share(
            _entry_for(usable(jht), "normal"), employer=False, wage=contribution_wage
        )
        jht_employer = _share(
            _entry_for(usable(jht), "normal"), employer=True, wage=contribution_wage
        )
        jp_employee = _share(_entry_for(usable(jp), None), employer=False, wage=contribution_wage)
        jp_employer = _share(_entry_for(usable(jp), None), employer=True, wage=contribution_wage)
        jkk_employer = _share(
            _entry_for(usable(jkk), risk_key), employer=True, wage=contribution_wage
        )
        jkm_employer = _share(_entry_for(usable(jkm), None), employer=True, wage=contribution_wage)

        usable_jkk = usable(jkk)
        if _is_keyed(usable_jkk):
            # A keyed JKK table is discriminating, and `Employee` carries no risk
            # class to select with. Charging the first row would under-declare a
            # high-risk role; charging nothing would under-declare too. Either way
            # the operator has to record the class, so block and say so.
            row = _entry_for(usable_jkk, risk_key)
            if row is None:
                anomalies.append(
                    PayrollAnomaly(
                        code="jkk_risk_class_unrecorded",
                        severity=AnomalySeverity.ERROR,
                        employee_id=payroll_input.employee_id,
                        detail=(
                            "the JKK table is keyed by risk class but this employee has no "
                            "recorded class, so no employer share could be selected. Record "
                            "the employee's BPJS JKK risk class before paying."
                        ),
                    )
                )
                jkk_employer = ZERO

        # --- PPh 21 ---------------------------------------------------------
        pph21 = ZERO
        pph_table = tables.get(RateTableKind.PPH21_TER)
        if pph_table is not None and pph_table.usable:
            ptkp_table = tables.get(RateTableKind.PPH21_PTKP)
            exemption = _ptkp(employee, ptkp_table)
            pph21 = self._compute_pph21(pph_table, gross, exemption)
            if exemption <= ZERO:
                anomalies.append(
                    PayrollAnomaly(
                        code="pph21_ptkp_missing",
                        severity=AnomalySeverity.ERROR,
                        employee_id=payroll_input.employee_id,
                        detail=(
                            f"TER withheld {pph21} with no personal exemption applied, "
                            "because the pph21_ptkp table has no usable "
                            f"'{PTKP_SELF_KEY}' row. Without it the employee is "
                            "over-collected every month and is owed the difference at "
                            "year end. Enter and verify the PTKP table."
                        ),
                    )
                )

        total_deductions = add(
            kes_employee,
            jht_employee,
            jp_employee,
            pph21,
            payroll_input.other_deductions,
            payroll_input.loan_deduction,
        )
        net = sub(gross, total_deductions)

        if net < 0:
            anomalies.append(
                PayrollAnomaly(
                    code="negative_net",
                    severity=AnomalySeverity.ERROR,
                    employee_id=payroll_input.employee_id,
                    detail=f"Computed net pay is negative ({net:,.2f}); correct the inputs.",
                )
            )

        employer_cost = add(kes_employer, jht_employer, jp_employer, jkk_employer, jkm_employer)

        line = PayrollLine(
            employee_id=payroll_input.employee_id,
            employee_name=employee.full_name if employee else "",
            base_salary=base_paid,
            allowances=add(fixed_paid, paid_variable),
            overtime_pay=overtime_pay,
            bonus=payroll_input.bonus,
            gross=gross,
            bpjs_kesehatan_employee=kes_employee,
            bpjs_jht_employee=jht_employee,
            bpjs_jp_employee=jp_employee,
            pph21=pph21,
            other_deductions=add(payroll_input.other_deductions, payroll_input.loan_deduction),
            total_deductions=total_deductions,
            net=net,
            bpjs_kesehatan_employer=kes_employer,
            bpjs_jht_employer=jht_employer,
            bpjs_jp_employer=jp_employer,
            bpjs_jkk_employer=jkk_employer,
            bpjs_jkm_employer=jkm_employer,
            employer_cost=employer_cost,
            notes=[payroll_input.note] if payroll_input.note else [],
        )
        line.check_invariants()
        return line, anomalies

    @staticmethod
    def _compute_pph21(table: RateTable, gross: Decimal, exemption: Decimal = ZERO) -> Decimal:
        """Progressive TER over the operator's brackets, less the employee's PTKP.

        This used to apply the first matching bracket's rate to the *whole* gross.
        PMK 168/2023's TER is progressive, so on a Rp 20,000,000 monthly gross the
        old code withheld Rp 7,000,000 where progressive accumulation gives
        Rp 5,510,000 -- Rp 17,880,000 per employee per year.

        It also fell off the end of the bracket table and returned ``0.0`` when
        gross exceeded the top bracket. Silent zero tax on the people who earn the
        most is the worst possible failure mode for this function, so an uncovered
        gross raises rather than returning a number.

        ``exemption`` is PTKP plus dependent allowances from the verified
        `pph21_ptkp` table. It defaults to zero so the pure bracket maths is
        testable on its own; the service never calls it that way without also
        raising `pph21_ptkp_missing`.
        """
        taxable = sub(gross, exemption)
        if taxable <= ZERO:
            return ZERO

        brackets = sorted(
            (item for item in table.entries if item.lower_bound is not None),
            key=lambda item: item.lower_bound or ZERO,
        )
        if not brackets:
            return ZERO

        tax = ZERO
        for entry in brackets:
            lower = entry.lower_bound or ZERO
            upper = entry.upper_bound
            if taxable <= lower:
                break
            slab_top = min(taxable, upper) if upper is not None else taxable
            if slab_top <= lower:
                continue
            slab = sub(slab_top, lower)
            if entry.flat_amount is not None:
                tax = add(tax, entry.flat_amount)
            else:
                tax = add(tax, percent_of(slab, entry.employee_share_percent or 0.0))
            if upper is not None and taxable <= upper:
                break

        top = brackets[-1].upper_bound
        if top is not None and taxable > top:
            # Never silently zero: the highest earners are exactly the people a
            # truncated bracket table quietly exempts.
            raise PayrollError(
                f"TER brackets cover up to {top} but taxable income is {taxable}; "
                "extend the table before paying this period"
            )
        return tax

    def _previous_run(self, run: PayrollRun) -> PayrollRun | None:
        candidate: PayrollRun | None = None
        for other in self._iter_runs():
            if other.id == run.id or other.kind is not run.kind or not other.lines:
                continue
            if (other.period_year, other.period_month) >= (run.period_year, run.period_month):
                continue
            if candidate is None or (other.period_year, other.period_month) > (
                candidate.period_year,
                candidate.period_month,
            ):
                candidate = other
        return candidate

    def _deviation_anomalies(
        self, lines: list[PayrollLine], previous: PayrollRun
    ) -> list[PayrollAnomaly]:
        anomalies: list[PayrollAnomaly] = []
        for line in lines:
            old = previous.line_for(line.employee_id)
            if old is None or old.net <= 0:
                continue
            deviation = abs(line.net - old.net) / old.net
            if deviation > NET_DEVIATION_THRESHOLD:
                anomalies.append(
                    PayrollAnomaly(
                        code="net_deviation",
                        severity=AnomalySeverity.WARNING,
                        employee_id=line.employee_id,
                        detail=(
                            f"Net pay changed {deviation:.0%} vs last run "
                            f"({old.net:,.0f} → {line.net:,.0f}); verify."
                        ),
                    )
                )
        return anomalies

    # --- sign-off --------------------------------------------------------

    def submit_for_signoff(self, run_id: UUID, *, actor: ActorRef) -> PayrollRun:
        """Send the computed run to the Finance approver. Humans only."""
        run = self.get_run(run_id)
        if run.status is not PayrollRunStatus.READY_FOR_REVIEW:
            raise PayrollError(f"run is {run.status.value}; compute it first")
        if not run.lines:
            raise PayrollError("run has no computed lines")
        if run.blocking_anomalies:
            raise PayrollError(
                "run has blocking anomalies; resolve them before requesting sign-off"
            )

        approval = self._approvals.create(
            subject=ApprovalSubject.PAYROLL_RUN,
            subject_id=str(run.id),
            title=(
                f"Payroll sign-off: {run.period_year}-{run.period_month:02d} "
                f"({run.totals.employees} employees, net {run.totals.net:,.0f})"
            ),
            assignee_role=ApproverRole.FINANCE,
            actor=actor,
            summary="Review packet prepared. No payments are executed by the system.",
            payload={
                "year": run.period_year,
                "month": run.period_month,
                "net": run.totals.net,
            },
            urgency=Urgency.HIGH if run.kind is PayrollRunKind.MONTHLY else Urgency.NORMAL,
        )
        updated = run.model_copy(
            update={
                "status": PayrollRunStatus.PENDING_SIGNOFF,
                "approval_id": approval.id,
                "updated_at": utc_now(),
            }
        )
        self._save_run(updated)
        self._record(
            updated,
            action="payroll.submitted_for_signoff",
            actor=actor,
            payload={"approval_id": str(approval.id)},
        )
        return updated

    def apply_decision(self, approval_id: UUID, *, actor: ActorRef) -> PayrollRun:
        """Sync the run with the approver's decision."""
        run = next(
            (item for item in self._iter_runs() if item.approval_id == approval_id),
            None,
        )
        if run is None:
            raise PayrollError(f"no payroll run linked to approval {approval_id}")

        approval = self._approvals._store.get(approval_id)
        if approval is None:
            raise PayrollError(
                f"unknown approval {approval_id}",
                code=DomainCode.UNKNOWN_RECORD,
                status=404,
            )
        if approval.status not in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
        }:
            raise PayrollError(
                f"approval {approval_id} is {approval.status.value}; no run transition"
            )

        approved = approval.status is ApprovalStatus.APPROVED
        if approved and not approval.decided_by:
            raise PayrollError("approval has no named human decider")
        if approved:
            can, reason = run.can_sign_off()
            if not can:
                raise PayrollError(f"cannot approve run: {reason}")

        updated = run.model_copy(
            update={
                "status": (PayrollRunStatus.APPROVED if approved else PayrollRunStatus.REJECTED),
                "signed_off_by": approval.decided_by if approved else None,
                "signed_off_at": utc_now() if approved else None,
                "updated_at": utc_now(),
            }
        )
        self._save_run(updated)
        self._record(
            updated,
            action="payroll.run_approved" if approved else "payroll.run_rejected",
            # The approver is the actor: the sign-off is theirs. The caller only
            # triggered the sync, so it is recorded beside the decision rather
            # than in place of it.
            actor=deciding_actor(approval.decided_by),
            payload={"approval_id": str(approval_id), "synced_by": actor.actor_id},
        )
        return updated

    def mark_exported(self, run_id: UUID, *, actor: ActorRef) -> PayrollRun:
        actor.require_human("exporting a payroll run", PayrollError)
        run = self.get_run(run_id)
        if run.status is not PayrollRunStatus.APPROVED:
            raise PayrollError(f"run is {run.status.value}; only approved runs may be exported")
        updated = run.model_copy(
            update={"status": PayrollRunStatus.EXPORTED, "exported_at": utc_now()}
        )
        self._save_run(updated)
        self._record(
            updated,
            action="payroll.packet_exported",
            actor=actor,
            payload={
                "net": run.totals.net,
                "employees": run.totals.employees,
                "note": "review packet only; no payments executed",
            },
        )
        return updated

    def cancel_run(self, run_id: UUID, *, actor: ActorRef, reason: str) -> PayrollRun:
        actor.require_human("cancelling a payroll run", PayrollError)
        run = self.get_run(run_id)
        if run.status in {PayrollRunStatus.APPROVED, PayrollRunStatus.EXPORTED}:
            raise PayrollError(f"run is {run.status.value}; cannot cancel")
        if not reason.strip():
            raise PayrollError("cancelling a run requires a reason")
        updated = run.model_copy(
            update={"status": PayrollRunStatus.CANCELLED, "updated_at": utc_now()}
        )
        self._save_run(updated)
        self._record(
            updated, action="payroll.run_cancelled", actor=actor, payload={"reason": reason}
        )
        return updated

    # --- export ----------------------------------------------------------

    def build_review_packet_xlsx(self, run_id: UUID) -> bytes:
        """XLSX review packet: the human deliverable. Contains no payment instructions."""
        run = self.get_run(run_id)
        if not run.lines:
            raise PayrollError("run has no computed lines to export")

        workbook = Workbook()
        sheet = workbook.active
        assert sheet is not None
        sheet.title = f"Payroll {run.period_year}-{run.period_month:02d}"

        headers = [
            "Employee ID",
            "Name",
            "Base salary",
            "Allowances",
            "Overtime",
            "Bonus",
            "Gross",
            "BPJS Kesehatan (employee)",
            "BPJS JHT (employee)",
            "BPJS JP (employee)",
            "PPh 21",
            "Other deductions",
            "Total deductions",
            "Net pay",
            "Employer BPJS (total)",
            "Notes",
        ]
        sheet.append(headers)
        for line in run.lines:
            # `line.employer_cost`, not a re-sum here: `check_invariants` already
            # proved it equals the sum of the five employer shares, and recomputing
            # it with `round()` is how it drifted before.
            employer_bpjs = line.employer_cost
            sheet.append(
                [
                    str(line.employee_id),
                    line.employee_name,
                    line.base_salary,
                    line.allowances,
                    line.overtime_pay,
                    line.bonus,
                    line.gross,
                    line.bpjs_kesehatan_employee,
                    line.bpjs_jht_employee,
                    line.bpjs_jp_employee,
                    line.pph21,
                    line.other_deductions,
                    line.total_deductions,
                    line.net,
                    employer_bpjs,
                    "; ".join(line.notes),
                ]
            )

        totals = run.totals
        sheet.append([])
        sheet.append(
            [
                "TOTALS",
                "",
                "",
                "",
                "",
                "",
                totals.gross,
                "",
                "",
                "",
                "",
                "",
                totals.total_deductions,
                totals.net,
                totals.employer_cost,
                "",
            ]
        )

        info = workbook.create_sheet("Run info")
        assert info is not None
        info.append(["Period", f"{run.period_year}-{run.period_month:02d}"])
        info.append(["Kind", run.kind.value])
        info.append(["Status", run.status.value])
        info.append(["Signed off by", run.signed_off_by or "(pending)"])
        info.append(
            ["Rate tables used", ", ".join(f"{k}={v}" for k, v in run.rate_table_ids.items())]
        )
        info.append(
            [
                "Anomalies",
                "; ".join(f"[{a.severity.value}] {a.code}" for a in run.anomalies) or "none",
            ]
        )
        info.append(
            [
                "Notice",
                "REVIEW PACKET ONLY — HRAgents does not execute payments. Verify all "
                "figures against current regulations before disbursing.",
            ]
        )

        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    # --- internals -------------------------------------------------------

    def _require_editable(self, run_id: UUID) -> PayrollRun:
        run = self.get_run(run_id)
        if run.status in {
            PayrollRunStatus.APPROVED,
            PayrollRunStatus.EXPORTED,
            PayrollRunStatus.CANCELLED,
            PayrollRunStatus.PENDING_SIGNOFF,
        }:
            raise PayrollError(f"run is {run.status.value}; it can no longer be edited")
        return run

    def _try_employee(self, employee_id: UUID) -> Employee | None:
        try:
            return self._employees.get(employee_id)
        except Exception:
            return None

    def _record(
        self,
        run: PayrollRun,
        *,
        action: str,
        actor: ActorRef,
        payload: dict[str, object],
    ) -> None:
        self._audit.append(
            actor=actor.audit_actor(),
            action=action,
            subject_type="payroll_run",
            subject_id=str(run.id),
            payload={
                "period": f"{run.period_year}-{run.period_month:02d}",
                "status": run.status.value,
                **payload,
            },
        )


def current_period() -> tuple[int, int]:
    today = date.today()
    return today.year, today.month
