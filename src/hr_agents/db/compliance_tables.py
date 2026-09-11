"""SQLAlchemy tables for the compliance pack (consent, retention, erasure, breach)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hr_agents.db.base import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class ConsentRecordTable(Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        Index("ix_consent_subject", "subject_kind", "subject_id"),
        Index("ix_consent_purpose", "purpose"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(120), nullable=False)
    lawful_basis: Mapped[str] = mapped_column(String(40), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0")
    capture_method: Mapped[str] = mapped_column(String(60), nullable=False, default="manual")
    captured_by: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RetentionPolicyTable(Base):
    __tablename__ = "retention_policies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    entity: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    retention_months: Mapped[int] = mapped_column(Integer, nullable=False)
    expiry_action: Mapped[str] = mapped_column(String(16), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RetentionRecordTable(Base):
    __tablename__ = "retention_records"
    __table_args__ = (
        Index("ix_retention_entity_anchor", "entity", "anchor_at"),
        Index("ix_retention_subject", "subject_kind", "subject_id"),
        Index("ix_retention_legal_hold", "legal_hold"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_months_override: Mapped[int | None] = mapped_column(Integer)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    legal_hold_reason: Mapped[str | None] = mapped_column(Text)
    held_by: Mapped[str | None] = mapped_column(String(200))
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_action: Mapped[str | None] = mapped_column(String(16))
    purge_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ErasureRequestTable(Base):
    __tablename__ = "erasure_requests"
    __table_args__ = (
        Index("ix_erasure_status", "status"),
        Index("ix_erasure_subject", "subject_kind", "subject_id"),
        Index("ix_erasure_approval", "approval_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(60), nullable=False, default="manual")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    identity_verified_by: Mapped[str | None] = mapped_column(String(200))
    identity_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identity_method: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_by: Mapped[str | None] = mapped_column(String(200))
    dispositions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONVariant, nullable=False, default=list
    )
    consents_revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BreachIncidentTable(Base):
    __tablename__ = "breach_incidents"
    __table_args__ = (Index("ix_breach_status", "status"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    impact: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discovered_by: Mapped[str] = mapped_column(String(200), nullable=False)
    template_name: Mapped[str] = mapped_column(String(160), nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    notifications: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONVariant, nullable=False, default=list
    )
    contained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[str | None] = mapped_column(String(200))
    closure_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
