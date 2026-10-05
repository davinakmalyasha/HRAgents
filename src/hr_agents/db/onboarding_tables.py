"""SQLAlchemy tables for onboarding: checklist templates and per-hire plans.

``OnboardingService`` held both in plain dicts. The loss that matters is a *waived*
step: a hire whose document check HR had already waived, with a recorded reason, comes
back as not-waived after a restart, and the next person to open the plan sees a
blocker that was already resolved. The waiver reason is the record.

``onboarding_plans.completed_at`` is indexed because ``active_plans`` is the
"everything still in flight" view every onboarding dashboard reads, and it was a full
read of the tenant's plans. The service still derives completion from the required
steps rather than trusting the column -- the two cannot disagree, since a step only
ever moves to a terminal status, but deriving it means a hand-edited row cannot
report a finished hire as outstanding.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hr_agents.db.base import Base, TenantScoped

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class OnboardingTemplateRecord(TenantScoped, Base):
    """A reusable checklist definition, e.g. 'Engineering PKWT'."""

    __tablename__ = "onboarding_templates"
    __table_args__ = (
        Index("ix_onboarding_templates_tenant", "tenant_id"),
        # `list_templates` sorts by lowercased name, which is not indexable without a
        # functional index; the tenant index is the one that keeps the read scoped.
        Index("ix_onboarding_templates_tenant_active", "tenant_id", "active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    applies_to_contract_types: Mapped[list[Any]] = mapped_column(
        JSONVariant, nullable=False, default=list
    )
    applies_to_roles: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OnboardingPlanRecord(TenantScoped, Base):
    """One hire's instantiated checklist, including per-step waivers."""

    __tablename__ = "onboarding_plans"
    __table_args__ = (
        Index("ix_onboarding_plans_tenant", "tenant_id"),
        Index("ix_onboarding_plans_tenant_employee", "tenant_id", "employee_id"),
        # `active_plans` and `plans_for_employee` are the two read paths.
        Index(
            "ix_onboarding_plans_tenant_inflight",
            "tenant_id",
            "completed_at",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    template_name: Mapped[str] = mapped_column(Text, nullable=False)
    template_version_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
