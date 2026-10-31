"""Payroll API schemas."""

from __future__ import annotations

import base64
from uuid import UUID

from pydantic import Field, field_validator, model_validator

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
    UtcDateTime,
)
from hr_agents.services.attendance import STANDARD_HOURS_PER_DAY, ColumnMapping


class RunCreate(StrictModel):
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)
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


class RunAction(StrictModel):
    reason: str | None = Field(default=None, max_length=1000)


class AttendanceCommit(StrictModel):
    """One attendance source: pasted/small CSV text, or an uploaded workbook.

    Exactly one of ``csv_text`` and ``file_base64`` must be present. The
    workbook path carries a mapping because machine exports name their columns
    whatever the installer chose; the base64 is validated here so a corrupt
    upload is a 422 rather than a 500 inside the parser.
    """

    csv_text: str | None = Field(default=None, max_length=500_000)
    file_base64: str | None = Field(default=None, max_length=14_000_000)
    filename: str | None = Field(default=None, max_length=320)
    sheet: str | None = Field(default=None, max_length=120)
    header_row: int = Field(default=1, ge=1, le=50)
    mapping: ColumnMapping | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> AttendanceCommit:
        if (self.csv_text is None) == (self.file_base64 is None):
            raise ValueError("provide exactly one of csv_text or file_base64")
        return self

    @field_validator("file_base64")
    @classmethod
    def _base64_decodes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise ValueError("file_base64 is not valid base64") from exc
        return value

    def content(self) -> bytes | None:
        """The uploaded bytes, or None when the request carried CSV text."""
        if self.file_base64 is None:
            return None
        return base64.b64decode(self.file_base64, validate=True)


class AttendanceErrorView(StrictModel):
    row: int
    employee_number: str | None = None
    code: str
    detail: str


class AttendanceRowView(StrictModel):
    employee_number: str
    employee_id: UUID | None = None
    days_present: int
    overtime_hours: float
    absence_days: float
    on_leave_days: int = 0
    flags: list[str] = Field(default_factory=list)


class AttendancePreviewView(StrictModel):
    period_year: int
    period_month: int
    working_days: int
    file_hash: str
    rows: list[AttendanceRowView]
    errors: list[AttendanceErrorView]
    standard_hours_per_day: float = STANDARD_HOURS_PER_DAY


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
        # Money is an exact `Decimal` in the domain and a JSON number on the wire.
        # The conversion happens here and nowhere else, so the arithmetic upstream
        # stays exact and the OpenAPI document is unchanged.
        return cls(
            employee_id=line.employee_id,
            employee_name=line.employee_name,
            base_salary=float(line.base_salary),
            allowances=float(line.allowances),
            overtime_pay=float(line.overtime_pay),
            bonus=float(line.bonus),
            gross=float(line.gross),
            bpjs_kesehatan_employee=float(line.bpjs_kesehatan_employee),
            bpjs_jht_employee=float(line.bpjs_jht_employee),
            bpjs_jp_employee=float(line.bpjs_jp_employee),
            pph21=float(line.pph21),
            other_deductions=float(line.other_deductions),
            total_deductions=float(line.total_deductions),
            net=float(line.net),
            employer_cost=float(line.employer_cost),
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
            gross=float(totals.gross),
            total_deductions=float(totals.total_deductions),
            net=float(totals.net),
            employer_cost=float(totals.employer_cost),
        )


class RunView(StrictModel):
    id: UUID
    period_year: int
    period_month: int
    kind: PayrollRunKind
    status: PayrollRunStatus
    approval_id: UUID | None
    supersedes_id: UUID | None = None
    signed_off_by: str | None
    cancelled_at: UtcDateTime | None = None
    cancel_reason: str | None = None
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
            supersedes_id=run.supersedes_id,
            signed_off_by=run.signed_off_by,
            cancelled_at=run.cancelled_at,
            cancel_reason=run.cancel_reason,
            totals=TotalsView.from_model(run.totals),
            anomalies=[AnomalyView.from_model(item) for item in run.anomalies],
            blocking_count=len(run.blocking_anomalies),
            lines=[LineView.from_model(line) for line in run.lines],
        )
