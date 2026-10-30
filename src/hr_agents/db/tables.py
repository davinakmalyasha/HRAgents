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
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
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
        Index("ix_evaluations_application", "application_id"),
        CheckConstraint("s_tech BETWEEN 0 AND 1", name="ck_evaluations_s_tech_range"),
        CheckConstraint("sigma >= 0", name="ck_evaluations_sigma_nonneg"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("applications.id", name="fk_evaluations_application", ondelete="SET NULL"),
        index=True,
    )
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


class RubricVersionRecord(TenantScoped, Base):
    """One stored rubric version. The payload is canonical JSON, digest-addressed."""

    __tablename__ = "rubric_versions"
    __table_args__ = (
        Index("ix_rubric_versions_tenant", "tenant_id"),
        UniqueConstraint(
            "tenant_id", "family", "revision", name="uq_rubric_versions_family_revision"
        ),
        UniqueConstraint("tenant_id", "family", "digest", name="uq_rubric_versions_family_digest"),
        CheckConstraint("revision >= 1", name="ck_rubric_versions_revision"),
        CheckConstraint("length(digest) = 64", name="ck_rubric_versions_digest_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    family: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    template: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(200))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
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
    supersedes_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedule_proposals.id", name="fk_schedule_proposals_supersedes"),
    )
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class CandidateCommunicationRecord(TenantScoped, Base):
    __tablename__ = "candidate_communications"
    __table_args__ = (
        Index("ix_candidate_communications_candidate", "candidate_id"),
        Index("ix_candidate_communications_status_created", "status", "created_at"),
        Index("ix_candidate_communications_message_id", "provider_message_id_normalized"),
        CheckConstraint("send_attempts >= 0", name="ck_candidate_communications_send_attempts"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL")
    )
    evaluation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evaluations.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_by: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipient: Mapped[str | None] = mapped_column(String(320))
    recipient_phone: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(500))
    provider_message_id_normalized: Mapped[str | None] = mapped_column(String(500))
    send_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CandidateReplyRecord(TenantScoped, Base):
    __tablename__ = "candidate_replies"
    __table_args__ = (
        Index("ix_candidate_replies_candidate", "candidate_id"),
        UniqueConstraint("provider", "dedup_key", name="uq_candidate_replies_provider_dedup"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    communication_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("candidate_communications.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="email")
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(500))
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailApplicationDraftRecord(TenantScoped, Base):
    __tablename__ = "email_application_drafts"
    __table_args__ = (
        Index("ix_email_application_drafts_tenant", "tenant_id"),
        Index("ix_email_application_drafts_status", "tenant_id", "status"),
        UniqueConstraint(
            "provider", "dedup_key", name="uq_email_application_drafts_provider_dedup"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(500))
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attachment_names: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    document_ids: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    refused_attachments: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    suggested_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL")
    )
    decided_by: Mapped[str | None] = mapped_column(String(200))
    discard_reason: Mapped[str | None] = mapped_column(String(1000))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PushSubscriptionRecord(TenantScoped, Base):
    """One browser's Web Push endpoint. Referenced by nobody; owned by one actor."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (
        Index("ix_push_subscriptions_tenant", "tenant_id"),
        UniqueConstraint(
            "tenant_id", "actor_id", "endpoint", name="uq_push_subscriptions_actor_endpoint"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    p256dh: Mapped[str] = mapped_column(String(500), nullable=False)
    auth: Mapped[str] = mapped_column(String(200), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderSettingRecord(TenantScoped, Base):
    """One capability's operator-chosen provider. The config is sealed."""

    __tablename__ = "provider_settings"
    __table_args__ = (
        Index("ix_provider_settings_tenant", "tenant_id"),
        UniqueConstraint("tenant_id", "capability", name="uq_provider_settings_capability"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(120), nullable=False)
    config_sealed: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CredentialRegistryRecord(TenantScoped, Base):
    """Operator-verified credential rows, one registry per issuer and name."""

    __tablename__ = "credential_registries"
    __table_args__ = (
        Index("ix_credential_registries_tenant", "tenant_id"),
        UniqueConstraint(
            "tenant_id", "issuer", "name", name="uq_credential_registries_issuer_name"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(200))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LlmUsageRecord(TenantScoped, Base):
    """One evaluation's provider usage, for the operations aggregate."""

    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_tenant", "tenant_id"),
        Index("ix_llm_usage_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    evaluation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evaluations.id", ondelete="SET NULL")
    )
    application_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpServerRecord(Base):
    """A dashboard-managed MCP server configuration.

    Install-wide rather than tenant-scoped: MCP tools are registered into one
    process-wide registry, so a per-tenant row would promise an isolation the
    runtime does not provide. Admin-only routes guard the table.
    """

    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
