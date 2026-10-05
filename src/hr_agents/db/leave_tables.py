"""SQLAlchemy tables for leave: requests, policies, balance adjustments, holidays.

Four tables rather than one because the four fail differently on loss. A lost
request is *visible* -- the employee's approved leave disappears from the list. A
lost balance adjustment and a lost holiday calendar are silent: the balance
overstates, or `working_days` counts a public holiday as a working day, and
nothing reports it. Policies fail closed ("no policy configured"), which is the
one acceptable failure mode of the four.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hr_agents.db.base import Base, TenantScoped

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class LeaveRequestRecord(TenantScoped, Base):
    """One leave request and its lifecycle state."""

    __tablename__ = "leave_requests"
    __table_args__ = (
        Index("ix_leave_requests_tenant", "tenant_id"),
        # `requests_for` filters by employee and `overlapping` scans a date range,
        # so both are tenant-leading lookups rather than full scans.
        Index("ix_leave_requests_tenant_employee", "tenant_id", "employee_id"),
        # `apply_decision` resolves the request that owns an approval id.
        Index("ix_leave_requests_tenant_approval", "tenant_id", "approval_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    leave_type: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LeavePolicyRecord(TenantScoped, Base):
    """One operator-set leave policy. `leave_type` is the natural key."""

    __tablename__ = "leave_policies"
    __table_args__ = (Index("ix_leave_policies_tenant", "tenant_id"),)

    # LeaveTypePolicy carries no id, so the row generates one; leave_type is the
    # natural key the service looks up by.
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    leave_type: Mapped[str] = mapped_column(String(32), nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LeaveAdjustmentRecord(TenantScoped, Base):
    """A manual balance adjustment.

    Keyed by (employee, leave type, year) rather than a synthetic id, because that
    triple *is* the identity: HR adjusts one employee's balance for one leave type
    in one year, and a second adjustment to the same triple must accumulate onto
    the same row rather than create a second one.
    """

    __tablename__ = "leave_adjustments"
    __table_args__ = (Index("ix_leave_adjustments_tenant", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    leave_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_year: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LeaveHolidayRecord(TenantScoped, Base):
    """One public holiday, so `working_days` stops counting it as working."""

    __tablename__ = "leave_holidays"
    __table_args__ = (
        Index("ix_leave_holidays_tenant", "tenant_id"),
        Index("ix_leave_holidays_tenant_day", "tenant_id", "day"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
