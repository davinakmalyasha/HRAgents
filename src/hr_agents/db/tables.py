"""SQLAlchemy table definitions.

JSON columns are stored as JSONB on PostgreSQL and as JSON elsewhere (tests use
SQLite in memory). JSONB-specific indexes (e.g. GIN) are added in PostgreSQL-only
migrations when needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hr_agents.db.base import Base, TenantScoped

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Candidate(TenantScoped, Base):
    __tablename__ = "candidates"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    headline: Mapped[str | None] = mapped_column(Text)
    primary_email: Mapped[str | None] = mapped_column(Text)
    location: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    consent: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    field_confidence: Mapped[dict[str, Any]] = mapped_column(
        JSONVariant, nullable=False, default=dict
    )
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    applications: Mapped[list[Application]] = relationship(back_populates="candidate")


class Job(TenantScoped, Base):
    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    seniority: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    dimension_weights: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)

    applications: Mapped[list[Application]] = relationship(back_populates="job")


class Application(TenantScoped, Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_job_priority", "job_id", "priority_score"),
        Index("ix_applications_candidate", "candidate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_channel: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    consent: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    s_tech: Mapped[float | None] = mapped_column(Float)
    sigma: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(String(32))
    timeline: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    priority_score: Mapped[float | None] = mapped_column(Float)
    priority_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship(back_populates="applications")
    job: Mapped[Job] = relationship(back_populates="applications")


class Evaluation(TenantScoped, Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_candidate_job", "candidate_id", "job_id"),
        Index("ix_evaluations_recommendation", "recommendation"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    candidate_name: Mapped[str | None] = mapped_column(Text)
    job_title: Mapped[str | None] = mapped_column(Text)
    s_tech: Mapped[float] = mapped_column(Float, nullable=False)
    sigma: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str | None] = mapped_column(String(32))
    document: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    policy: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ScheduleProposal(TenantScoped, Base):
    __tablename__ = "schedule_proposals"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    requires_human_approval: Mapped[bool | None] = mapped_column(Boolean)
    needs_human_reconciliation: Mapped[bool | None] = mapped_column(Boolean)
    created_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(TenantScoped, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_subject", "subject_type", "subject_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class ConversationRecord(TenantScoped, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_candidate", "candidate_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    response_sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages: Mapped[list[MessageRecord]] = relationship(back_populates="conversation")


class MessageRecord(TenantScoped, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_candidate", "candidate_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[ConversationRecord | None] = relationship(back_populates="messages")


class CandidateDocumentRecord(TenantScoped, Base):
    __tablename__ = "candidate_documents"
    __table_args__ = (Index("ix_candidate_documents_sha256", "sha256"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(200), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvaluationOverrideRecord(TenantScoped, Base):
    __tablename__ = "evaluation_overrides"
    __table_args__ = (Index("ix_evaluation_overrides_evaluation", "evaluation_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(40), nullable=False)
    override_decision: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FeedbackReportRecord(TenantScoped, Base):
    __tablename__ = "feedback_reports"

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    saved_by: Mapped[str] = mapped_column(String(200), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SchedulingAvailabilityRecord(TenantScoped, Base):
    __tablename__ = "scheduling_availability"

    interviewer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    slots: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False, default="system")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
