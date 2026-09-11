"""SQLAlchemy tables for the offboarding pack (templates, plans, assets)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
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


class OffboardingTemplateRecord(Base):
    __tablename__ = "offboarding_templates"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    applies_to_reasons: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    applies_to_roles: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OffboardingPlanRecord(Base):
    __tablename__ = "offboarding_plans"
    __table_args__ = (
        Index("ix_offboarding_plans_employee", "employee_id"),
        Index("ix_offboarding_plans_lwd", "last_working_day"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    last_working_day: Mapped[date] = mapped_column(Date, nullable=False)
    template_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    template_name: Mapped[str] = mapped_column(Text, nullable=False)
    template_version_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    handover_notes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONVariant, nullable=False, default=list
    )
    final_pay_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OffboardingAssetRecord(Base):
    __tablename__ = "offboarding_assets"
    __table_args__ = (
        Index("ix_offboarding_assets_employee", "employee_id"),
        Index("ix_offboarding_assets_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    plan_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    asset_code: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    assigned_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    returned_on: Mapped[date | None] = mapped_column(Date)
    returned_by: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
