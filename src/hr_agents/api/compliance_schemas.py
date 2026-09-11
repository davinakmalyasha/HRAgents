"""Compliance API schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from hr_agents.models import (
    AuditVerificationReport,
    BreachChecklistTemplate,
    BreachImpact,
    BreachIncident,
    BreachNotification,
    BreachStatus,
    BreachStepState,
    ConsentGrant,
    DispositionAction,
    ErasureDisposition,
    ErasureRequest,
    ErasureStatus,
    LawfulBasis,
    NotificationRecipient,
    OverdueBreachStep,
    PurgeAction,
    PurgeOutcome,
    PurgeReport,
    RecordEntity,
    RetentionDue,
    RetentionPolicy,
    RetentionRecord,
    RetentionScanReport,
    StrictModel,
    SubjectKind,
    UtcDateTime,
)

# --- consent -----------------------------------------------------------------


class ConsentCreate(StrictModel):
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=120)
    captured_by: str = Field(min_length=1, max_length=200)
    granted: bool = True
    lawful_basis: LawfulBasis = LawfulBasis.CONSENT
    capture_method: str = Field(default="manual", max_length=60)
    policy_version: str = Field(default="1.0", max_length=40)
    expires_at: UtcDateTime | None = None
    note: str | None = Field(default=None, max_length=1000)


class ConsentRevoke(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class ConsentView(StrictModel):
    id: UUID
    subject_kind: SubjectKind
    subject_id: str
    purpose: str
    lawful_basis: LawfulBasis
    granted: bool
    active: bool
    granted_at: UtcDateTime
    expires_at: UtcDateTime | None
    revoked_at: UtcDateTime | None
    revoked_reason: str | None
    policy_version: str
    capture_method: str
    captured_by: str
    note: str | None

    @classmethod
    def from_model(cls, record: ConsentGrant) -> ConsentView:
        return cls(
            id=record.id,
            subject_kind=record.subject_kind,
            subject_id=record.subject_id,
            purpose=record.purpose,
            lawful_basis=record.lawful_basis,
            granted=record.granted,
            active=record.active,
            granted_at=record.granted_at,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
            revoked_reason=record.revoked_reason,
            policy_version=record.policy_version,
            capture_method=record.capture_method,
            captured_by=record.captured_by,
            note=record.note,
        )


class ConsentStatusView(StrictModel):
    subject_kind: SubjectKind
    subject_id: str
    active_purposes: list[str]
    records: list[ConsentView]


# --- retention ---------------------------------------------------------------


class PolicySet(StrictModel):
    entity: RecordEntity
    name: str = Field(min_length=1, max_length=160)
    retention_months: int = Field(ge=1, le=600)
    updated_by: str = Field(min_length=1, max_length=200)
    expiry_action: PurgeAction = PurgeAction.ANONYMIZE
    jurisdiction: str = Field(default="ID", max_length=2)
    active: bool = True
    note: str | None = Field(default=None, max_length=1000)


class PolicyView(StrictModel):
    id: UUID
    entity: RecordEntity
    name: str
    retention_months: int
    expiry_action: PurgeAction
    jurisdiction: str
    active: bool
    updated_by: str
    updated_at: UtcDateTime
    note: str | None

    @classmethod
    def from_model(cls, policy: RetentionPolicy) -> PolicyView:
        return cls(**policy.model_dump())


class RecordTrack(StrictModel):
    entity: RecordEntity
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    label: str = Field(default="", max_length=200)
    anchor_at: UtcDateTime | None = None
    retention_months_override: int | None = Field(default=None, ge=1, le=600)


class RecordView(StrictModel):
    id: UUID
    entity: RecordEntity
    subject_kind: SubjectKind
    subject_id: str
    label: str
    anchor_at: UtcDateTime
    retention_months_override: int | None
    legal_hold: bool
    legal_hold_reason: str | None
    held_by: str | None
    purged_at: UtcDateTime | None
    purge_action: PurgeAction | None

    @classmethod
    def from_model(cls, record: RetentionRecord) -> RecordView:
        return cls(
            id=record.id,
            entity=record.entity,
            subject_kind=record.subject_kind,
            subject_id=record.subject_id,
            label=record.label,
            anchor_at=record.anchor_at,
            retention_months_override=record.retention_months_override,
            legal_hold=record.legal_hold,
            legal_hold_reason=record.legal_hold_reason,
            held_by=record.held_by,
            purged_at=record.purged_at,
            purge_action=record.purge_action,
        )


class LegalHoldRequest(StrictModel):
    held: bool
    by: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class DueView(StrictModel):
    record: RecordView
    expires_at: UtcDateTime
    action: PurgeAction

    @classmethod
    def from_model(cls, due: RetentionDue) -> DueView:
        return cls(
            record=RecordView.from_model(due.record),
            expires_at=due.expires_at,
            action=due.action,
        )


class ScanView(StrictModel):
    as_of: UtcDateTime
    due: list[DueView]
    held: list[RecordView]
    uncovered: list[RecordView]
    tracked_count: int
    purged_count: int

    @classmethod
    def from_model(cls, report: RetentionScanReport) -> ScanView:
        return cls(
            as_of=report.as_of,
            due=[DueView.from_model(item) for item in report.due],
            held=[RecordView.from_model(item) for item in report.held],
            uncovered=[RecordView.from_model(item) for item in report.uncovered],
            tracked_count=report.tracked_count,
            purged_count=report.purged_count,
        )


class PurgeRequest(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    as_of: UtcDateTime | None = None
    dry_run: bool = False


class PurgeOutcomeView(StrictModel):
    record_id: UUID
    entity: RecordEntity
    subject_kind: SubjectKind
    subject_id: str
    action: PurgeAction
    detail: str

    @classmethod
    def from_model(cls, outcome: PurgeOutcome) -> PurgeOutcomeView:
        return cls(**outcome.model_dump())


class PurgeReportView(StrictModel):
    executed_at: UtcDateTime
    dry_run: bool
    by: str
    purged: list[PurgeOutcomeView]
    held: list[UUID]
    uncovered: list[UUID]

    @classmethod
    def from_model(cls, report: PurgeReport) -> PurgeReportView:
        return cls(
            executed_at=report.executed_at,
            dry_run=report.dry_run,
            by=report.by,
            purged=[PurgeOutcomeView.from_model(item) for item in report.purged],
            held=report.held,
            uncovered=report.uncovered,
        )


# --- erasure -----------------------------------------------------------------


class ErasureCreate(StrictModel):
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    requested_by: str = Field(min_length=1, max_length=200)
    channel: str = Field(default="manual", max_length=60)


class ErasureVerify(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    method: str = Field(min_length=1, max_length=120)


class ErasureAction(StrictModel):
    by: str = Field(min_length=1, max_length=200)


class DispositionView(StrictModel):
    record_id: UUID
    entity: RecordEntity
    action: DispositionAction
    detail: str

    @classmethod
    def from_model(cls, disposition: ErasureDisposition) -> DispositionView:
        return cls(**disposition.model_dump())


class ErasureView(StrictModel):
    id: UUID
    subject_kind: SubjectKind
    subject_id: str
    reason: str
    requested_by: str
    channel: str
    received_at: UtcDateTime
    identity_verified_by: str | None
    identity_verified_at: UtcDateTime | None
    identity_method: str | None
    status: ErasureStatus
    approval_id: UUID | None
    decided_by: str | None
    decided_at: UtcDateTime | None
    decision_reason: str | None
    executed_at: UtcDateTime | None
    executed_by: str | None
    dispositions: list[DispositionView]
    consents_revoked: int

    @classmethod
    def from_model(cls, request: ErasureRequest) -> ErasureView:
        return cls(
            id=request.id,
            subject_kind=request.subject_kind,
            subject_id=request.subject_id,
            reason=request.reason,
            requested_by=request.requested_by,
            channel=request.channel,
            received_at=request.received_at,
            identity_verified_by=request.identity_verified_by,
            identity_verified_at=request.identity_verified_at,
            identity_method=request.identity_method,
            status=request.status,
            approval_id=request.approval_id,
            decided_by=request.decided_by,
            decided_at=request.decided_at,
            decision_reason=request.decision_reason,
            executed_at=request.executed_at,
            executed_by=request.executed_by,
            dispositions=[DispositionView.from_model(item) for item in request.dispositions],
            consents_revoked=request.consents_revoked,
        )


class BreachStepTemplateView(StrictModel):
    key: str
    title: str
    offset_hours: int
    required: bool


class BreachTemplateView(StrictModel):
    name: str
    description: str
    steps: list[BreachStepTemplateView] = Field(default_factory=list)

    @classmethod
    def from_model(cls, template: BreachChecklistTemplate) -> BreachTemplateView:
        return cls(
            name=template.name,
            description=template.description,
            steps=[BreachStepTemplateView(**step.model_dump()) for step in template.steps],
        )


# --- breach ------------------------------------------------------------------


class BreachCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    impact: BreachImpact = BreachImpact.MEDIUM
    discovered_by: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    discovered_at: UtcDateTime | None = None


class StepComplete(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class NotificationCreate(StrictModel):
    recipient_kind: NotificationRecipient
    recipient: str = Field(min_length=1, max_length=200)
    sent_by: str = Field(min_length=1, max_length=200)
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class BreachTransition(StrictModel):
    status: BreachStatus
    by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class StepView(StrictModel):
    key: str
    title: str
    offset_hours: int
    required: bool
    due_at: UtcDateTime
    completed: bool
    completed_by: str | None
    completed_at: UtcDateTime | None
    note: str | None

    @classmethod
    def from_model(cls, step: BreachStepState) -> StepView:
        return cls(
            key=step.key,
            title=step.title,
            offset_hours=step.offset_hours,
            required=step.required,
            due_at=step.due_at,
            completed=step.completed,
            completed_by=step.completed_by,
            completed_at=step.completed_at,
            note=step.note,
        )


class NotificationView(StrictModel):
    recipient_kind: NotificationRecipient
    recipient: str
    sent_at: UtcDateTime
    sent_by: str
    reference: str | None
    note: str | None

    @classmethod
    def from_model(cls, notification: BreachNotification) -> NotificationView:
        return cls(**notification.model_dump())


class BreachView(StrictModel):
    id: UUID
    title: str
    description: str
    impact: BreachImpact
    status: BreachStatus
    discovered_at: UtcDateTime
    discovered_by: str
    template_name: str
    steps: list[StepView]
    notifications: list[NotificationView]
    contained_at: UtcDateTime | None
    notified_at: UtcDateTime | None
    closed_at: UtcDateTime | None
    closed_by: str | None
    closure_note: str | None

    @classmethod
    def from_model(cls, incident: BreachIncident) -> BreachView:
        return cls(
            id=incident.id,
            title=incident.title,
            description=incident.description,
            impact=incident.impact,
            status=incident.status,
            discovered_at=incident.discovered_at,
            discovered_by=incident.discovered_by,
            template_name=incident.template_name,
            steps=[StepView.from_model(step) for step in incident.steps],
            notifications=[NotificationView.from_model(item) for item in incident.notifications],
            contained_at=incident.contained_at,
            notified_at=incident.notified_at,
            closed_at=incident.closed_at,
            closed_by=incident.closed_by,
            closure_note=incident.closure_note,
        )


class OverdueStepView(StrictModel):
    incident_id: UUID
    incident_title: str
    status: BreachStatus
    step: StepView

    @classmethod
    def from_model(cls, overdue: OverdueBreachStep) -> OverdueStepView:
        return cls(
            incident_id=overdue.incident_id,
            incident_title=overdue.incident_title,
            status=overdue.status,
            step=StepView.from_model(overdue.step),
        )


# --- audit -------------------------------------------------------------------


class AuditVerifyRequest(StrictModel):
    checked_by: str = Field(default="system", max_length=200)


class AuditVerifyView(StrictModel):
    intact: bool
    entry_count: int
    first_invalid_seq: int | None
    head_hash: str | None
    checked_at: UtcDateTime
    checked_by: str

    @classmethod
    def from_model(cls, report: AuditVerificationReport) -> AuditVerifyView:
        return cls(**report.model_dump())
