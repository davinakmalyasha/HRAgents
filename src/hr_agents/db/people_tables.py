"""SQLAlchemy tables for employee core, approvals, tasks, and rate tables."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hr_agents.db.base import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class EmployeeRecord(Base):
    __tablename__ = "employees"
    __table_args__ = (
        Index("ix_employees_status", "status"),
        Index("ix_employees_org_unit", "org_unit_id"),
        Index("ix_employees_manager", "manager_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_number: Mapped[str | None] = mapped_column(String(40), unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(32))
    job_title: Mapped[str | None] = mapped_column(Text)
    org_unit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("org_units.id", ondelete="SET NULL")
    )
    manager_id: Mapped[UUID | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    work_location: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    hire_date: Mapped[date | None] = mapped_column(Date)
    probation_end_date: Mapped[date | None] = mapped_column(Date)
    offboarded_on: Mapped[date | None] = mapped_column(Date)
    emergency_contact: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    documents: Mapped[list[EmployeeDocumentRecord]] = relationship(back_populates="employee")


class OrgUnitRecord(Base):
    __tablename__ = "org_units"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id", ondelete="SET NULL"))
    cost_center: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmployeeDocumentRecord(Base):
    __tablename__ = "employee_documents"
    __table_args__ = (
        Index("ix_employee_documents_employee", "employee_id"),
        Index("ix_employee_documents_expiry", "expires_on"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    employee: Mapped[EmployeeRecord] = relationship(back_populates="documents")


class ContractRecord(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        Index("ix_contracts_employee", "employee_id"),
        Index("ix_contracts_end_date", "end_date"),
        Index("ix_contracts_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    contract_type: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    probation_end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    signed_on: Mapped[date | None] = mapped_column(Date)
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("employee_documents.id", ondelete="SET NULL")
    )
    compensation_due: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ApprovalRecord(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_role_status", "assignee_role", "status"),
        Index("ix_approvals_subject", "subject", "subject_id"),
        Index("ix_approvals_sla", "sla_deadline"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    subject: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_by_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assignee_role: Mapped[str] = mapped_column(String(40), nullable=False)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_escalations: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_due", "status", "due_on"),
        Index("ix_tasks_assignee", "assignee_role", "status"),
        Index("ix_tasks_related", "related_subject", "related_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    assignee_role: Mapped[str | None] = mapped_column(String(40))
    assignee_id: Mapped[str | None] = mapped_column(String(200))
    due_on: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    related_subject: Mapped[str | None] = mapped_column(String(60))
    related_id: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    completed_by: Mapped[str | None] = mapped_column(String(200))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RateTableRecord(Base):
    __tablename__ = "rate_tables"
    __table_args__ = (Index("ix_rate_tables_kind", "kind", "jurisdiction"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(200))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
