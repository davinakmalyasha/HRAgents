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
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from openpyxl import Workbook

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
from hr_agents.models.money import ZERO, add, percent_of, sub
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.rate_tables import RateTableError, RateTableService

HOURLY_DIVISOR = 173.0
DEFAULT_OVERTIME_FIRST_HOUR_MULTIPLIER = 1.5
DEFAULT_OVERTIME_NEXT_HOURS_MULTIPLIER = 2.0
NET_DEVIATION_THRESHOLD = 0.30
MAX_OVERTIME_HOURS = 60.0

OVERTIME_FIRST_HOURS_PER_DAY = 1.0
"""UU 13/2003 Pasal 56(2): the 1.5x tier is one hour *per day*, not per month.

The previous code applied it to one hour for the whole month, so 24 overtime hours
in a month were priced as 1 hour at 1.5x and 23 at 2.0x. Per-day it is 24 separate
days of 1 hour at 1.5x and 1 at 2.0x. On a Rp 12,000,000 wage that is a
Rp 381,502 difference -- currently in the employee's favour, which is still a
reconciliation failure.
"""

REQUIRED_TABLES: tuple[RateTableKind, ...] = (
    RateTableKind.BPJS_KESEHATAN,
    RateTableKind.BPJS_KETENAGAKERJAAN_JHT,
    RateTableKind.BPJS_KETENAGAKERJAAN_JP,
    RateTableKind.BPJS_JKK,
    RateTableKind.BPJS_JKM,
)


class PayrollError(RuntimeError):
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
        self._runs[run.id] = run
        self._record(
            run,
            action="payroll.run_created",
            actor=actor,
            payload={"year": period_year, "month": period_month, "kind": kind.value},
        )
        return run

    def get_run(self, run_id: UUID) -> PayrollRun:
        run = self._runs.get(run_id)
        if run is None:
            raise PayrollError(f"unknown payroll run {run_id}")
        return run

    def list_runs(self) -> list[PayrollRun]:
        return sorted(
            self._runs.values(),
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
        self._runs[run.id] = updated
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
        tables, table_ids, table_anomalies = self._resolve_tables(period=period)
        overtime_table = tables.get(RateTableKind.OVERTIME_PREMIUM)
        pph_table = tables.get(RateTableKind.PPH21_TER)

        if not tables.get(RateTableKind.OVERTIME_PREMIUM) or (
            overtime_table and not overtime_table.usable
        ):
            table_anomalies.append(
                PayrollAnomaly(
                    code="overtime_rate_table_missing",
                    severity=AnomalySeverity.WARNING,
                    detail="Overtime table is not verified; overtime pay computed as zero.",
                )
            )
        if pph_table is None or not pph_table.usable:
            table_anomalies.append(
                PayrollAnomaly(
                    code="pph21_rate_table_missing",
                    severity=AnomalySeverity.WARNING,
                    detail=(
                        "PPh 21 TER table is not verified; income tax is not computed. "
                        "Handle tax in your own workflow until the table is verified."
                    ),
                )
            )

        lines: list[PayrollLine] = []
        anomalies: list[PayrollAnomaly] = list(table_anomalies)
        working_days = _working_days_in_month(run.period_year, run.period_month)

        for payroll_input in run.inputs:
            employee = self._try_employee(payroll_input.employee_id)
            line, line_anomalies = self._compute_line(
                payroll_input,
                employee,
                tables,
                pph_table,
                working_days=working_days,
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
        self._runs[run.id] = updated
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
        self, *, period: date
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

        wanted = [*REQUIRED_TABLES, RateTableKind.OVERTIME_PREMIUM, RateTableKind.PPH21_TER]
        for kind in wanted:
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

    def _compute_line(
        self,
        payroll_input: PayrollInput,
        employee: Employee | None,
        tables: dict[RateTableKind, RateTable],
        pph_table: RateTable | None,
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
        # 56(2)), not one hour per month. `OVERTIME_DAY_HOURS` tiers come from the
        # verified table so the multipliers are operator-owned rather than
        # constants, which `models/payroll.py` claims they already were.
        overtime_table = tables.get(RateTableKind.OVERTIME_PREMIUM)
        first_tier = _entry_for(overtime_table, "first_hour")
        rest_tier = _entry_for(overtime_table, "subsequent_hour")
        first_multiplier = (
            first_tier.multiplier
            if first_tier and first_tier.multiplier is not None
            else DEFAULT_OVERTIME_FIRST_HOUR_MULTIPLIER
        )
        rest_multiplier = (
            rest_tier.multiplier
            if rest_tier and rest_tier.multiplier is not None
            else DEFAULT_OVERTIME_NEXT_HOURS_MULTIPLIER
        )
        hourly = wage / Decimal(str(HOURLY_DIVISOR))
        hours = Decimal(str(payroll_input.overtime_hours))
        overtime_pay = ZERO
        if hours > 0:
            # Days the employee worked at all: the full period less absences. The
            # 1.5x tier is one hour *per day* (UU 13/2003 Pasal 56(2)). Rounded, not
            # truncated -- `int()` turns 14.999 into 14 days of first-tier hours.
            days_worked = max(
                1,
                int((Decimal(working_days) * paid_fraction).quantize(Decimal("1"), ROUND_HALF_UP)),
            )
            first_hours = min(hours, Decimal(days_worked))
            # Hours are a ratio, not money, so no two-place quantisation here.
            rest_hours = max(hours - first_hours, ZERO)
            overtime_pay = add(
                hourly * Decimal(str(first_multiplier)) * first_hours,
                hourly * Decimal(str(rest_multiplier)) * rest_hours,
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
        if pph_table is not None and pph_table.usable:
            pph21 = self._compute_pph21(pph_table, gross)
            anomalies.append(
                PayrollAnomaly(
                    code="ptkp_not_applied",
                    severity=AnomalySeverity.WARNING,
                    employee_id=payroll_input.employee_id,
                    detail=(
                        f"TER withheld {pph21} on gross {gross} with no personal exemption "
                        "(PTKP) or dependent allowance deducted, so this is overstated. "
                        "Record the employee's tax profile and the PTKP rate table."
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
    def _compute_pph21(table: RateTable, gross: Decimal) -> Decimal:
        """Progressive TER over the operator's brackets.

        This used to apply the first matching bracket's rate to the *whole* gross.
        PMK 168/2023's TER is progressive, so on a Rp 20,000,000 monthly gross the
        old code withheld Rp 7,000,000 where progressive accumulation gives
        Rp 5,510,000 -- Rp 17,880,000 per employee per year.

        It also fell off the end of the bracket table and returned ``0.0`` when
        gross exceeded the top bracket. Silent zero tax on the people who earn the
        most is the worst possible failure mode for this function, so an uncovered
        gross raises rather than returning a number.

        PTKP and dependent allowances are **not** applied yet: `Employee` has no tax
        profile, and inventing one is the hardcoded statutory number `AGENTS.md`
        forbids. The caller raises a `ptkp_not_applied` anomaly so the withholding is
        visibly overstated rather than quietly wrong.
        """
        if gross <= ZERO:
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
            if gross <= lower:
                break
            slab_top = min(gross, upper) if upper is not None else gross
            if slab_top <= lower:
                continue
            slab = sub(slab_top, lower)
            if entry.flat_amount is not None:
                tax = add(tax, entry.flat_amount)
            else:
                tax = add(tax, percent_of(slab, entry.employee_share_percent or 0.0))
            if upper is not None and gross <= upper:
                break

        top = brackets[-1].upper_bound
        if top is not None and gross > top:
            # Never silently zero: the highest earners are exactly the people a
            # truncated bracket table quietly exempts.
            raise PayrollError(
                f"TER brackets cover up to {top} but taxable income is {gross}; "
                "extend the table before paying this period"
            )
        return tax

    def _previous_run(self, run: PayrollRun) -> PayrollRun | None:
        candidate: PayrollRun | None = None
        for other in self._runs.values():
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
        self._runs[run.id] = updated
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
            (item for item in self._runs.values() if item.approval_id == approval_id),
            None,
        )
        if run is None:
            raise PayrollError(f"no payroll run linked to approval {approval_id}")

        approval = self._approvals._store.get(approval_id)
        if approval is None:
            raise PayrollError(f"unknown approval {approval_id}")
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
        self._runs[run.id] = updated
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
        self._runs[run.id] = updated
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
        self._runs[run.id] = updated
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
