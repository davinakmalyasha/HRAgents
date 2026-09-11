"""Compliance domain models — UU PDP / GDPR-equivalent operational pack.

Design rules encoded here:

- **No hardcoded legal numbers.** Retention windows, checklist offsets, and
  notification timing all come from operator-editable policies/templates. The
  engine applies whatever HR enters; it never asserts a statutory figure.
- **Legal holds always win.** Any record under hold is never purged by the
  retention job or an erasure request; it is reported instead.
- **Humans decide, agents request.** Erasure execution, legal holds, breach
  step completion, and status transitions require a named human actor. Agents
  may record evidence (e.g., consent capture) but never decide.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class SubjectKind(StrEnum):
    """Whose data is being processed."""

    CANDIDATE = "candidate"
    EMPLOYEE = "employee"
    OTHER = "other"


class LawfulBasis(StrEnum):
    """UU PDP processing bases (mirrors GDPR Art. 6 structure)."""

    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTEREST = "vital_interest"
    PUBLIC_TASK = "public_task"
    LEGITIMATE_INTEREST = "legitimate_interest"


class ConsentGrant(StrictModel):
    """One consent-registry entry: evidence of a grant, refusal, or revocation.

    ``purpose`` is operator-defined and intentionally free-form (e.g.
    ``recruitment_evaluation``, ``background_check``, ``talent_pool``); consent
    is checked per purpose, never globally.
    """

    id: UUID = Field(default_factory=uuid4)
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=200)

    purpose: str = Field(min_length=1, max_length=120)
    lawful_basis: LawfulBasis = LawfulBasis.CONSENT
    granted: bool = True
    granted_at: UtcDateTime = Field(default_factory=utc_now)
    expires_at: UtcDateTime | None = None

    revoked_at: UtcDateTime | None = None
    revoked_reason: str | None = Field(default=None, max_length=500)

    policy_version: str = Field(default="1.0", max_length=40)
    capture_method: str = Field(default="manual", max_length=60)
    captured_by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)

    created_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def active(self) -> bool:
        if not self.granted or self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > utc_now()


class RecordEntity(StrEnum):
    """Kinds of records the retention engine tracks."""

    CANDIDATE = "candidate"
    APPLICATION = "application"
    EMPLOYEE = "employee"
    DOCUMENT = "document"
    PAYROLL = "payroll"
    CONSENT = "consent"
    OTHER = "other"


class PurgeAction(StrEnum):
    """What happens when a retained record reaches its expiry."""

    DELETE = "delete"
    ANONYMIZE = "anonymize"


class RetentionPolicy(StrictModel):
    """Operator-owned retention rule for one entity kind. No default legal value."""

    id: UUID = Field(default_factory=uuid4)
    entity: RecordEntity
    name: str = Field(min_length=1, max_length=160)
    retention_months: int = Field(
        ge=1,
        le=600,
        description="Months after the record's anchor date before it expires. "
        "HR sets this; the engine never ships a statutory default.",
    )
    expiry_action: PurgeAction = PurgeAction.ANONYMIZE
    jurisdiction: str = Field(default="ID", max_length=2)
    active: bool = True
    updated_by: str = Field(min_length=1, max_length=200)
    updated_at: UtcDateTime = Field(default_factory=utc_now)
    note: str | None = Field(default=None, max_length=1000)


class RetentionRecord(StrictModel):
    """One tracked record awaiting (or past) its retention expiry.

    The compliance ledger is the source of truth for what happened: a record
    is only marked purged after a registered store handler succeeds (or, when
    no handler exists, after the ledger records the disposition).
    """

    id: UUID = Field(default_factory=uuid4)
    entity: RecordEntity
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=200)
    label: str = Field(default="", max_length=200)

    anchor_at: UtcDateTime = Field(
        default_factory=utc_now,
        description="When the retention clock starts (typically record creation).",
    )
    retention_months_override: int | None = Field(default=None, ge=1, le=600)

    legal_hold: bool = False
    legal_hold_reason: str | None = Field(default=None, max_length=500)
    held_by: str | None = Field(default=None, max_length=200)
    held_at: UtcDateTime | None = None

    purged_at: UtcDateTime | None = None
    purge_action: PurgeAction | None = None
    purge_detail: str | None = Field(default=None, max_length=1000)

    created_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def purged(self) -> bool:
        return self.purged_at is not None

    @model_validator(mode="after")
    def _validate_hold_metadata(self) -> RetentionRecord:
        if self.legal_hold and not self.legal_hold_reason:
            raise ValueError("legal_hold requires legal_hold_reason")
        if self.purged_at is not None and self.legal_hold:
            raise ValueError("a record under legal hold cannot be marked purged")
        return self


class RetentionDue(StrictModel):
    """A record whose retention window has elapsed."""

    record: RetentionRecord
    expires_at: UtcDateTime
    action: PurgeAction


class RetentionScanReport(StrictModel):
    """Deterministic scan output — nothing is mutated by a scan."""

    as_of: UtcDateTime
    due: list[RetentionDue] = Field(default_factory=list)
    held: list[RetentionRecord] = Field(
        default_factory=list, description="Expired but under legal hold — never auto-purged."
    )
    uncovered: list[RetentionRecord] = Field(
        default_factory=list, description="Expired but no active policy — needs HR action."
    )
    tracked_count: int = Field(default=0, ge=0)
    purged_count: int = Field(default=0, ge=0)


class PurgeOutcome(StrictModel):
    """What happened to one record during a purge pass."""

    record_id: UUID
    entity: RecordEntity
    subject_kind: SubjectKind
    subject_id: str
    action: PurgeAction
    detail: str = Field(default="", max_length=1000)


class PurgeReport(StrictModel):
    """Result of executing (or dry-running) the retention purge."""

    executed_at: UtcDateTime
    dry_run: bool = False
    by: str
    purged: list[PurgeOutcome] = Field(default_factory=list)
    held: list[UUID] = Field(default_factory=list)
    uncovered: list[UUID] = Field(default_factory=list)


class ErasureStatus(StrEnum):
    RECEIVED = "received"
    PENDING_APPROVAL = "pending_approval"
    DENIED = "denied"
    APPROVED = "approved"
    EXECUTED = "executed"


class DispositionAction(StrEnum):
    DELETED = "deleted"
    ANONYMIZED = "anonymized"
    RETAINED_LEGAL_HOLD = "retained_legal_hold"


class ErasureDisposition(StrictModel):
    """What happened to one record when an erasure was executed."""

    record_id: UUID
    entity: RecordEntity
    action: DispositionAction
    detail: str = Field(default="", max_length=1000)


class ErasureRequest(StrictModel):
    """A data-subject erasure request and its human decision trail."""

    id: UUID = Field(default_factory=uuid4)
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    requested_by: str = Field(min_length=1, max_length=200)
    channel: str = Field(default="manual", max_length=60)
    received_at: UtcDateTime = Field(default_factory=utc_now)

    identity_verified_by: str | None = Field(default=None, max_length=200)
    identity_verified_at: UtcDateTime | None = None
    identity_method: str | None = Field(default=None, max_length=120)

    status: ErasureStatus = ErasureStatus.RECEIVED
    approval_id: UUID | None = None
    decided_by: str | None = Field(default=None, max_length=200)
    decided_at: UtcDateTime | None = None
    decision_reason: str | None = Field(default=None, max_length=500)

    executed_at: UtcDateTime | None = None
    executed_by: str | None = Field(default=None, max_length=200)
    dispositions: list[ErasureDisposition] = Field(default_factory=list)
    consents_revoked: int = Field(default=0, ge=0)

    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def identity_verified(self) -> bool:
        return self.identity_verified_by is not None

    @property
    def active(self) -> bool:
        return self.status in {ErasureStatus.RECEIVED, ErasureStatus.PENDING_APPROVAL}


class BreachStatus(StrEnum):
    OPEN = "open"
    CONTAINED = "contained"
    NOTIFIED = "notified"
    CLOSED = "closed"


class BreachImpact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationRecipient(StrEnum):
    REGULATOR = "regulator"
    DATA_SUBJECT = "data_subject"
    INTERNAL = "internal"
    OTHER = "other"


class BreachTemplateStep(StrictModel):
    """One checklist step in a breach template (operator-editable)."""

    key: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=300)
    offset_hours: int = Field(
        ge=0,
        le=24 * 365,
        description="Hours after discovery when this step is due. Starter default only.",
    )
    required: bool = True


class BreachChecklistTemplate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    steps: list[BreachTemplateStep] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_keys(self) -> BreachChecklistTemplate:
        keys = [step.key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("breach template step keys must be unique")
        return self


class BreachStepState(StrictModel):
    """Materialized checklist step for one incident."""

    key: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=300)
    offset_hours: int = Field(ge=0, le=24 * 365)
    required: bool = True
    due_at: UtcDateTime

    completed_by: str | None = Field(default=None, max_length=200)
    completed_at: UtcDateTime | None = None
    note: str | None = Field(default=None, max_length=1000)

    @property
    def completed(self) -> bool:
        return self.completed_at is not None


class BreachNotification(StrictModel):
    """Recorded notification to a regulator, data subject, or internal party."""

    recipient_kind: NotificationRecipient
    recipient: str = Field(min_length=1, max_length=200)
    sent_at: UtcDateTime = Field(default_factory=utc_now)
    sent_by: str = Field(min_length=1, max_length=200)
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class BreachIncident(StrictModel):
    """A personal-data breach with its checklist and notification log."""

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    impact: BreachImpact = BreachImpact.MEDIUM
    status: BreachStatus = BreachStatus.OPEN

    discovered_at: UtcDateTime = Field(default_factory=utc_now)
    discovered_by: str = Field(min_length=1, max_length=200)
    template_name: str = Field(min_length=1, max_length=160)

    steps: list[BreachStepState] = Field(default_factory=list)
    notifications: list[BreachNotification] = Field(default_factory=list)

    contained_at: UtcDateTime | None = None
    notified_at: UtcDateTime | None = None
    closed_at: UtcDateTime | None = None
    closed_by: str | None = Field(default=None, max_length=200)
    closure_note: str | None = Field(default=None, max_length=1000)

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def required_steps_complete(self) -> bool:
        return all(step.completed for step in self.steps if step.required)

    @property
    def open_steps(self) -> list[BreachStepState]:
        return [step for step in self.steps if not step.completed]


class OverdueBreachStep(StrictModel):
    """An incomplete, past-due breach step with its incident context."""

    incident_id: UUID
    incident_title: str
    status: BreachStatus
    step: BreachStepState


class AuditVerificationReport(StrictModel):
    """Result of verifying the hash-chained audit log end to end."""

    intact: bool
    entry_count: int = Field(ge=0)
    first_invalid_seq: int | None = Field(
        default=None, description="Sequence number of the first broken entry, if any."
    )
    head_hash: str | None = None
    checked_at: UtcDateTime = Field(default_factory=utc_now)
    checked_by: str = Field(default="system", max_length=200)
