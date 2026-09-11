"""SQLAlchemy tables for the growth pack (review cycles, assignments, goals)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hr_agents.db.base import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class ReviewCycleRecord(Base):
    __tablename__ = "review_cycles"
    __table_args__ = (Index("ix_review_cycles_status", "status"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    rating_scale_min: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    rating_scale_max: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    submission_due_on: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReviewAssignmentRecord(Base):
    __tablename__ = "review_assignments"
    __table_args__ = (
        Index("ix_review_assignments_cycle", "cycle_id"),
        Index("ix_review_assignments_employee", "employee_id"),
        Index("ix_review_assignments_reviewer", "reviewer_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date)
    ratings: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    comments: Mapped[str] = mapped_column(Text, nullable=False, default="")
    submitted_by: Mapped[str | None] = mapped_column(String(200))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skipped_by: Mapped[str | None] = mapped_column(String(200))
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skip_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReviewSummaryRecord(Base):
    __tablename__ = "review_summaries"
    __table_args__ = (
        Index("ix_review_summaries_cycle", "cycle_id"),
        Index("ix_review_summaries_employee", "employee_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    agent_draft: Mapped[str] = mapped_column(Text, nullable=False, default="")
    draft_by: Mapped[str | None] = mapped_column(String(200))
    draft_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_text: Mapped[str | None] = mapped_column(Text)
    finalized_by: Mapped[str | None] = mapped_column(String(200))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GoalRecord(Base):
    __tablename__ = "goals"
    __table_args__ = (
        Index("ix_goals_employee_status", "employee_id", "status"),
        Index("ix_goals_due", "due_on"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metric: Mapped[str | None] = mapped_column(Text)
    cycle_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    start_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updates: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
