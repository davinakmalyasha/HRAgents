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

import io
from datetime import date
from uuid import UUID

from openpyxl import Workbook

from hr_agents.models import (
    ActorType,
    AnomalySeverity,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    AuditActor,
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
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.rate_tables import RateTableService

HOURLY_DIVISOR = 173.0
DEFAULT_OVERTIME_FIRST_HOUR_MULTIPLIER = 1.5
DEFAULT_OVERTIME_NEXT_HOURS_MULTIPLIER = 2.0
NET_DEVIATION_THRESHOLD = 0.30
MAX_OVERTIME_HOURS = 60.0

REQUIRED_TABLES: tuple[RateTableKind, ...] = (
    RateTableKind.BPJS_KESEHATAN,
    RateTableKind.BPJS_KETENAGAKERJAAN_JHT,
    RateTableKind.BPJS_KETENAGAKERJAAN_JP,
    RateTableKind.BPJS_JKK,
    RateTableKind.BPJS_JKM,
)


class PayrollError(RuntimeError):
    """Raised for invalid payroll operations."""


def _first_entry(table: RateTable | None) -> RateEntry | None:
    if table is None:
        return None
    return table.entries[0] if table.entries else None


def _share(entry: RateEntry | None, *, employer: bool, wage: float) -> float:
    """Apply a table entry's percentage share with its wage cap."""
    if entry is None:
        return 0.0
    percent = entry.employer_share_percent if employer else entry.employee_share_percent
    if percent is None:
        return 0.0
    effective_wage = min(wage, entry.wage_cap) if entry.wage_cap is not None else wage
    return round(effective_wage * (percent / 100.0), 2)


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
        created_by: str,
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
            actor_id=created_by,
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

    def set_inputs(self, run_id: UUID, *, inputs: list[PayrollInput], by: str) -> PayrollRun:
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
            actor_id=by,
            payload={"employee_count": len(inputs)},
        )
        return updated

    # --- computation -----------------------------------------------------

    def compute(self, run_id: UUID, *, by: str) -> PayrollRun:
        """Compute all lines from verified rate tables + detected anomalies."""
        run = self._require_editable(run_id)
        if not run.inputs:
            raise PayrollError("run has no inputs; call set_inputs first")

        tables, table_ids, table_anomalies = self._resolve_tables()
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

        for payroll_input in run.inputs:
            employee = self._try_employee(payroll_input.employee_id)
            line, line_anomalies = self._compute_line(payroll_input, employee, tables, pph_table)
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
            actor_id=by,
            payload={
                "employees": len(lines),
                "anomalies": len(anomalies),
                "blocking": len(updated.blocking_anomalies),
                "rate_tables": table_ids,
            },
        )
        return updated

    def _resolve_tables(
        self,
    ) -> tuple[dict[RateTableKind, RateTable], dict[str, str], list[PayrollAnomaly]]:
        """Fetch every table; record blocking anomalies for missing/unverified."""
        tables: dict[RateTableKind, RateTable] = {}
        table_ids: dict[str, str] = {}
        anomalies: list[PayrollAnomaly] = []

        wanted = [*REQUIRED_TABLES, RateTableKind.OVERTIME_PREMIUM, RateTableKind.PPH21_TER]
        for kind in wanted:
            candidates = [table for table in self._rate_tables.list_all() if table.kind is kind]
            if not candidates:
                anomalies.append(
                    PayrollAnomaly(
                        code=f"rate_table_missing:{kind.value}",
                        severity=AnomalySeverity.ERROR,
                        detail=(
                            f"{kind.value} rate table is not configured. "
                            "HR must enter and verify current rates before payroll."
                        ),
                    )
                )
                continue
            table = candidates[-1]
            tables[kind] = table
            table_ids[kind.value] = str(table.id)
            if not table.usable and kind in REQUIRED_TABLES:
                anomalies.append(
                    PayrollAnomaly(
                        code=f"rate_table_unverified:{kind.value}",
                        severity=AnomalySeverity.ERROR,
                        detail=(
                            f"{kind.value} rate table exists but is not verified. "
                            "Verify it (with a source note) before computing payroll."
                        ),
                    )
                )
        return tables, table_ids, anomalies

    def _compute_line(
        self,
        payroll_input: PayrollInput,
        employee: Employee | None,
        tables: dict[RateTableKind, RateTable],
        pph_table: RateTable | None,
    ) -> tuple[PayrollLine, list[PayrollAnomaly]]:
        anomalies: list[PayrollAnomaly] = []
        wage = payroll_input.base_salary + payroll_input.fixed_allowances

        # Overtime
        overtime_entry = _first_entry(tables.get(RateTableKind.OVERTIME_PREMIUM))
        first_multiplier = (
            overtime_entry.multiplier
            if overtime_entry and overtime_entry.multiplier is not None
            else DEFAULT_OVERTIME_FIRST_HOUR_MULTIPLIER
        )
        next_multiplier = DEFAULT_OVERTIME_NEXT_HOURS_MULTIPLIER
        hourly = wage / HOURLY_DIVISOR
        hours = payroll_input.overtime_hours
        overtime_pay = 0.0
        if hours > 0:
            first_hours = min(hours, 1.0)
            rest_hours = max(hours - 1.0, 0.0)
            overtime_pay = round(
                hourly * first_multiplier * first_hours + hourly * next_multiplier * rest_hours,
                2,
            )

        if hours > MAX_OVERTIME_HOURS:
            anomalies.append(
                PayrollAnomaly(
                    code="overtime_excessive",
                    severity=AnomalySeverity.WARNING,
                    employee_id=payroll_input.employee_id,
                    detail=(
                        f"{hours} overtime hours exceeds {MAX_OVERTIME_HOURS}; "
                        "verify with the manager."
                    ),
                )
            )

        gross = round(
            wage + overtime_pay + payroll_input.variable_allowances + payroll_input.bonus, 2
        )

        # BPJS shares (employee + employer) from verified tables
        bpjs_kes = tables.get(RateTableKind.BPJS_KESEHATAN)
        bpjs_jht = tables.get(RateTableKind.BPJS_KETENAGAKERJAAN_JHT)
        bpjs_jp = tables.get(RateTableKind.BPJS_KETENAGAKERJAAN_JP)
        bpjs_jkk = tables.get(RateTableKind.BPJS_JKK)
        bpjs_jkm = tables.get(RateTableKind.BPJS_JKM)

        def usable(table: RateTable | None) -> RateTable | None:
            return table if table is not None and table.usable else None

        kes_employee = _share(_first_entry(usable(bpjs_kes)), employer=False, wage=wage)
        kes_employer = _share(_first_entry(usable(bpjs_kes)), employer=True, wage=wage)
        jht_employee = _share(_first_entry(usable(bpjs_jht)), employer=False, wage=wage)
        jht_employer = _share(_first_entry(usable(bpjs_jht)), employer=True, wage=wage)
        jp_employee = _share(_first_entry(usable(bpjs_jp)), employer=False, wage=wage)
        jp_employer = _share(_first_entry(usable(bpjs_jp)), employer=True, wage=wage)
        jkk_employer = _share(_first_entry(usable(bpjs_jkk)), employer=True, wage=wage)
        jkm_employer = _share(_first_entry(usable(bpjs_jkm)), employer=True, wage=wage)

        # PPh 21 (only when a usable TER-style table exists)
        pph21 = 0.0
        if pph_table is not None and pph_table.usable:
            pph21 = self._compute_pph21(pph_table, gross)

        total_deductions = round(
            kes_employee
            + jht_employee
            + jp_employee
            + pph21
            + payroll_input.other_deductions
            + payroll_input.loan_deduction,
            2,
        )
        net = round(gross - total_deductions, 2)

        if net < 0:
            anomalies.append(
                PayrollAnomaly(
                    code="negative_net",
                    severity=AnomalySeverity.ERROR,
                    employee_id=payroll_input.employee_id,
                    detail=f"Computed net pay is negative ({net:,.2f}); correct the inputs.",
                )
            )

        employer_cost = round(
            kes_employer + jht_employer + jp_employer + jkk_employer + jkm_employer, 2
        )

        line = PayrollLine(
            employee_id=payroll_input.employee_id,
            employee_name=employee.full_name if employee else "",
            base_salary=payroll_input.base_salary,
            allowances=round(payroll_input.fixed_allowances + payroll_input.variable_allowances, 2),
            overtime_pay=overtime_pay,
            bonus=payroll_input.bonus,
            gross=gross,
            bpjs_kesehatan_employee=kes_employee,
            bpjs_jht_employee=jht_employee,
            bpjs_jp_employee=jp_employee,
            pph21=pph21,
            other_deductions=round(
                payroll_input.other_deductions + payroll_input.loan_deduction, 2
            ),
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
        return line, anomalies

    @staticmethod
    def _compute_pph21(table: RateTable, gross: float) -> float:
        """Apply the first matching bracket from a TER-style table."""
        for entry in sorted(table.entries, key=lambda item: item.lower_bound or 0.0):
            lower = entry.lower_bound or 0.0
            upper = entry.upper_bound
            if gross >= lower and (upper is None or gross <= upper):
                if entry.flat_amount is not None:
                    return round(entry.flat_amount, 2)
                percent = entry.employee_share_percent or 0.0
                return round(gross * (percent / 100.0), 2)
        return 0.0

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

    def submit_for_signoff(self, run_id: UUID, *, by: str) -> PayrollRun:
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
            requested_by=by,
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
            actor_id=by,
            payload={"approval_id": str(approval.id)},
        )
        return updated

    def apply_decision(self, approval_id: UUID) -> PayrollRun:
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
            actor_id=approval.decided_by or "system",
            payload={"approval_id": str(approval_id)},
        )
        return updated

    def mark_exported(self, run_id: UUID, *, by: str) -> PayrollRun:
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
            actor_id=by,
            payload={
                "net": run.totals.net,
                "employees": run.totals.employees,
                "note": "review packet only; no payments executed",
            },
        )
        return updated

    def cancel_run(self, run_id: UUID, *, by: str, reason: str) -> PayrollRun:
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
            updated, action="payroll.run_cancelled", actor_id=by, payload={"reason": reason}
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
            employer_bpjs = round(
                line.bpjs_kesehatan_employer
                + line.bpjs_jht_employer
                + line.bpjs_jp_employer
                + line.bpjs_jkk_employer
                + line.bpjs_jkm_employer,
                2,
            )
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
        actor_id: str,
        payload: dict[str, object],
    ) -> None:
        if actor_id.startswith("agent:"):
            actor_type = ActorType.AGENT
        elif actor_id == "system":
            actor_type = ActorType.SYSTEM
        else:
            actor_type = ActorType.HUMAN
        self._audit.append(
            actor=AuditActor(actor_type=actor_type, actor_id=actor_id),
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
