"""Payroll API schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from hr_agents.models import (
    AnomalySeverity,
    PayrollAnomaly,
    PayrollInput,
    PayrollLine,
    PayrollRun,
    PayrollRunKind,
    PayrollRunStatus,
    PayrollTotals,
    StrictModel,
)


class RunCreate(StrictModel):
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)
    created_by: str = Field(min_length=1, max_length=200)
    kind: PayrollRunKind = PayrollRunKind.MONTHLY


class InputLine(StrictModel):
    employee_id: UUID
    base_salary: float = Field(ge=0.0)
    fixed_allowances: float = Field(default=0.0, ge=0.0)
    variable_allowances: float = Field(default=0.0, ge=0.0)
    overtime_hours: float = Field(default=0.0, ge=0.0, le=400.0)
    absence_days: float = Field(default=0.0, ge=0.0, le=31.0)
    other_deductions: float = Field(default=0.0, ge=0.0)
    loan_deduction: float = Field(default=0.0, ge=0.0)
    bonus: float = Field(default=0.0, ge=0.0)
    note: str | None = Field(default=None, max_length=500)

    def to_model(self) -> PayrollInput:
        return PayrollInput(**self.model_dump())


class InputsSet(StrictModel):
    inputs: list[InputLine] = Field(min_length=1)
    by: str = Field(min_length=1, max_length=200)


class RunAction(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class AnomalyView(StrictModel):
    code: str
    severity: AnomalySeverity
    employee_id: UUID | None
    detail: str

    @classmethod
    def from_model(cls, anomaly: PayrollAnomaly) -> AnomalyView:
        return cls(
            code=anomaly.code,
            severity=anomaly.severity,
            employee_id=anomaly.employee_id,
            detail=anomaly.detail,
        )


class LineView(StrictModel):
    employee_id: UUID
    employee_name: str
    base_salary: float
    allowances: float
    overtime_pay: float
    bonus: float
    gross: float
    bpjs_kesehatan_employee: float
    bpjs_jht_employee: float
    bpjs_jp_employee: float
    pph21: float
    other_deductions: float
    total_deductions: float
    net: float
    employer_cost: float
    notes: list[str]

    @classmethod
    def from_model(cls, line: PayrollLine) -> LineView:
        return cls(
            employee_id=line.employee_id,
            employee_name=line.employee_name,
            base_salary=line.base_salary,
            allowances=line.allowances,
            overtime_pay=line.overtime_pay,
            bonus=line.bonus,
            gross=line.gross,
            bpjs_kesehatan_employee=line.bpjs_kesehatan_employee,
            bpjs_jht_employee=line.bpjs_jht_employee,
            bpjs_jp_employee=line.bpjs_jp_employee,
            pph21=line.pph21,
            other_deductions=line.other_deductions,
            total_deductions=line.total_deductions,
            net=line.net,
            employer_cost=line.employer_cost,
            notes=line.notes,
        )


class TotalsView(StrictModel):
    employees: int
    gross: float
    total_deductions: float
    net: float
    employer_cost: float

    @classmethod
    def from_model(cls, totals: PayrollTotals) -> TotalsView:
        return cls(
            employees=totals.employees,
            gross=totals.gross,
            total_deductions=totals.total_deductions,
            net=totals.net,
            employer_cost=totals.employer_cost,
        )


class RunView(StrictModel):
    id: UUID
    period_year: int
    period_month: int
    kind: PayrollRunKind
    status: PayrollRunStatus
    approval_id: UUID | None
    signed_off_by: str | None
    totals: TotalsView
    anomalies: list[AnomalyView]
    blocking_count: int
    lines: list[LineView]

    @classmethod
    def from_model(cls, run: PayrollRun) -> RunView:
        return cls(
            id=run.id,
            period_year=run.period_year,
            period_month=run.period_month,
            kind=run.kind,
            status=run.status,
            approval_id=run.approval_id,
            signed_off_by=run.signed_off_by,
            totals=TotalsView.from_model(run.totals),
            anomalies=[AnomalyView.from_model(item) for item in run.anomalies],
            blocking_count=len(run.blocking_anomalies),
            lines=[LineView.from_model(line) for line in run.lines],
        )
