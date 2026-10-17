"""SQLAlchemy tables for payroll: runs and their computed lines.

``PayrollService`` held runs in a plain dict, so a restart lost them -- and losing
a payroll run is not a lost convenience. ``compute()`` resolves the rate tables in
force *for the period being paid*, so a re-run of a March 2025 payroll after a
newer decree was loaded produces different figures from identical inputs, and
records the newer tables as the provenance. The first computation is the only
correct one and it is gone.

Two tables rather than one, and money in ``Numeric`` columns rather than a JSON
document. A payslip is the one artefact in this product an employee's bank
transfer is reconciled against line by line, so the amounts have to be queryable
and comparable in SQL -- a JSON blob would put every reconciliation query in
Python, which is where the rounding bugs came from.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hr_agents.db.base import Base, TenantScoped

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

MONEY = Numeric(18, 2)
"""Two places, matching `models.money.Money`, so the database rejects a third."""


class PayrollRunRecord(TenantScoped, Base):
    """One payroll run: its inputs, its anomalies, and the rate tables it used."""

    __tablename__ = "payroll_runs"
    __table_args__ = (
        Index("ix_payroll_runs_tenant", "tenant_id"),
        # `_previous_run` looks for the most recent earlier period of the same kind,
        # which is an ordered range scan rather than a full read.
        Index(
            "ix_payroll_runs_tenant_period",
            "tenant_id",
            "period_year",
            "period_month",
        ),
        # `apply_decision` resolves the run that owns an approval id.
        Index("ix_payroll_runs_tenant_approval", "tenant_id", "approval_id"),
        CheckConstraint("period_year BETWEEN 2000 AND 2100", name="ck_payroll_runs_period_year"),
        CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_payroll_runs_period_month"),
        # A cancelled run carries both the moment and the why, or neither: the
        # model refuses half a cancellation, and a restore must not smuggle one in.
        CheckConstraint(
            "(cancelled_at IS NULL AND cancel_reason IS NULL) "
            "OR (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL)",
            name="ck_payroll_runs_cancel_pairing",
        ),
        CheckConstraint(
            "status <> 'approved' OR signed_off_by IS NOT NULL",
            name="ck_payroll_runs_approved_signed_off_by",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    inputs: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    anomalies: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONVariant, nullable=False, default=list
    )
    rate_table_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONVariant, nullable=False, default=dict
    )
    approval_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("approvals.id", name="fk_payroll_runs_approval")
    )
    signed_off_by: Mapped[str | None] = mapped_column(String(200))
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A cancelled run explains itself: the packet and the audit trail both carry
    # the reason, so the record is not a status with no why a month later.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lines: Mapped[list[PayrollLineRecord]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class PayrollLineRecord(TenantScoped, Base):
    """One computed payslip line, with every amount in a queryable numeric column."""

    __tablename__ = "payroll_lines"
    __table_args__ = (
        Index("ix_payroll_lines_tenant", "tenant_id"),
        Index("ix_payroll_lines_tenant_run", "tenant_id", "run_id"),
        Index("ix_payroll_lines_tenant_employee", "tenant_id", "employee_id"),
        # One line per employee per run. `PayrollLine` carries no id of its own, so
        # the uniqueness is enforced here rather than assumed.
        UniqueConstraint("run_id", "employee_id", name="uq_payroll_lines_run_employee"),
        # Every component the model declares `ge=0`. A payslip is what a bank
        # reconciliation compares against; a restore must not be able to introduce
        # an amount the arithmetic can no longer explain.
        *[
            CheckConstraint(f"{column} >= 0", name=f"ck_payroll_lines_{column}_nonneg")
            for column in (
                "base_salary",
                "allowances",
                "overtime_pay",
                "bonus",
                "gross",
                "bpjs_kesehatan_employee",
                "bpjs_jht_employee",
                "bpjs_jp_employee",
                "pph21",
                "other_deductions",
                "total_deductions",
                "bpjs_kesehatan_employer",
                "bpjs_jht_employer",
                "bpjs_jp_employer",
                "bpjs_jkk_employer",
                "bpjs_jkm_employer",
                "employer_cost",
            )
        ],
        CheckConstraint("thr_months BETWEEN 0 AND 24", name="ck_payroll_lines_thr_months"),
        # The four identities `PayrollLine.check_invariants` asserts exist here
        # too: the model guards every construction, the database guards every
        # write including a restore that never passes through the model.
        CheckConstraint(
            "round(gross, 2) = round(base_salary + allowances + overtime_pay + bonus, 2)",
            name="ck_payroll_lines_gross_sum",
        ),
        CheckConstraint(
            "round(total_deductions, 2) = round(bpjs_kesehatan_employee + bpjs_jht_employee "
            "+ bpjs_jp_employee + pph21 + other_deductions, 2)",
            name="ck_payroll_lines_deductions_sum",
        ),
        CheckConstraint(
            "round(net, 2) = round(gross - total_deductions, 2)",
            name="ck_payroll_lines_net_identity",
        ),
        CheckConstraint(
            "round(employer_cost, 2) = round(bpjs_kesehatan_employer + bpjs_jht_employer "
            "+ bpjs_jp_employer + bpjs_jkk_employer + bpjs_jkm_employer, 2)",
            name="ck_payroll_lines_employer_cost_sum",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    employee_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    base_salary: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    allowances: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    overtime_pay: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    bonus: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    gross: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    bpjs_kesehatan_employee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    bpjs_jht_employee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    bpjs_jp_employee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    pph21: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    other_deductions: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_deductions: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    bpjs_kesehatan_employer: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    bpjs_jht_employer: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    bpjs_jp_employer: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    bpjs_jkk_employer: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    bpjs_jkm_employer: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    employer_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    thr_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    # The model has no timestamps on a line; these are database-managed only.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    run: Mapped[PayrollRunRecord] = relationship(back_populates="lines")
