"""Compliance API router — consent, retention, erasure, breach, audit verify."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.compliance_schemas import (
    AuditVerifyView,
    BreachCreate,
    BreachTemplateView,
    BreachTransition,
    BreachView,
    ConsentCreate,
    ConsentRevoke,
    ConsentStatusView,
    ConsentView,
    ErasureAction,
    ErasureCreate,
    ErasureVerify,
    ErasureView,
    LegalHoldRequest,
    NotificationCreate,
    OverdueStepView,
    PolicySet,
    PolicyView,
    PurgeReportView,
    PurgeRequest,
    RecordTrack,
    RecordView,
    ScanView,
    StepComplete,
)
from hr_agents.api.deps import require_permission
from hr_agents.models import RecordEntity, SubjectKind, UtcDateTime
from hr_agents.rbac import Permission
from hr_agents.services.compliance import (
    ComplianceError,
    ComplianceService,
    default_breach_template,
)

router = APIRouter(
    prefix="/v1/compliance",
    tags=["compliance"],
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_READ))],
)


def get_compliance(request: Request) -> ComplianceService:
    return request.app.state.compliance


ComplianceDep = Annotated[ComplianceService, Depends(get_compliance)]


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _raise(exc: Exception) -> HTTPException:
    message = str(exc)
    if message.startswith("unknown") or " not found" in message:
        return _not_found(message)
    return _conflict(exc)


# --- consent ----------------------------------------------------------------


@router.post("/consents", status_code=status.HTTP_201_CREATED, response_model=ConsentView)
def record_consent(payload: ConsentCreate, compliance: ComplianceDep) -> ConsentView:
    record = compliance.record_consent(
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        purpose=payload.purpose,
        captured_by=payload.captured_by,
        granted=payload.granted,
        lawful_basis=payload.lawful_basis,
        capture_method=payload.capture_method,
        policy_version=payload.policy_version,
        expires_at=payload.expires_at,
        note=payload.note,
    )
    return ConsentView.from_model(record)


@router.get("/consents", response_model=list[ConsentView])
def list_consents(
    compliance: ComplianceDep,
    subject_kind: SubjectKind | None = None,
    subject_id: str | None = None,
) -> list[ConsentView]:
    records = compliance.list_consents(subject_kind=subject_kind, subject_id=subject_id)
    return [ConsentView.from_model(item) for item in records]


@router.get("/consents/status", response_model=ConsentStatusView)
def consent_status(
    compliance: ComplianceDep,
    subject_kind: SubjectKind,
    subject_id: str,
) -> ConsentStatusView:
    records = compliance.list_consents(subject_kind=subject_kind, subject_id=subject_id)
    return ConsentStatusView(
        subject_kind=subject_kind,
        subject_id=subject_id,
        active_purposes=sorted({item.purpose for item in records if item.active}),
        records=[ConsentView.from_model(item) for item in records],
    )


@router.post("/consents/{consent_id}/revoke", response_model=ConsentView)
def revoke_consent(
    consent_id: UUID, payload: ConsentRevoke, compliance: ComplianceDep
) -> ConsentView:
    try:
        record = compliance.revoke_consent(consent_id, by=payload.by, reason=payload.reason)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ConsentView.from_model(record)


# --- retention --------------------------------------------------------------


@router.put("/retention/policies", response_model=PolicyView)
def set_policy(payload: PolicySet, compliance: ComplianceDep) -> PolicyView:
    try:
        policy = compliance.set_policy(
            entity=payload.entity,
            name=payload.name,
            retention_months=payload.retention_months,
            updated_by=payload.updated_by,
            expiry_action=payload.expiry_action,
            jurisdiction=payload.jurisdiction,
            active=payload.active,
            note=payload.note,
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return PolicyView.from_model(policy)


@router.get("/retention/policies", response_model=list[PolicyView])
def list_policies(compliance: ComplianceDep) -> list[PolicyView]:
    return [PolicyView.from_model(item) for item in compliance.list_policies()]


@router.post("/retention/records", status_code=status.HTTP_201_CREATED, response_model=RecordView)
def track_record(payload: RecordTrack, compliance: ComplianceDep) -> RecordView:
    record = compliance.track_record(
        entity=payload.entity,
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        created_by=payload.created_by,
        label=payload.label,
        anchor_at=payload.anchor_at,
        retention_months_override=payload.retention_months_override,
    )
    return RecordView.from_model(record)


@router.get("/retention/records", response_model=list[RecordView])
def list_records(
    compliance: ComplianceDep,
    subject_kind: SubjectKind | None = None,
    subject_id: str | None = None,
    entity: RecordEntity | None = None,
    include_purged: bool = False,
) -> list[RecordView]:
    records = compliance.list_records(
        subject_kind=subject_kind,
        subject_id=subject_id,
        entity=entity,
        include_purged=include_purged,
    )
    return [RecordView.from_model(item) for item in records]


@router.post("/retention/records/{record_id}/hold", response_model=RecordView)
def set_legal_hold(
    record_id: UUID, payload: LegalHoldRequest, compliance: ComplianceDep
) -> RecordView:
    try:
        record = compliance.set_legal_hold(
            record_id, held=payload.held, by=payload.by, reason=payload.reason
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return RecordView.from_model(record)


@router.get("/retention/scan", response_model=ScanView)
def scan_retention(compliance: ComplianceDep, as_of: UtcDateTime | None = None) -> ScanView:
    return ScanView.from_model(compliance.scan(as_of=as_of))


@router.post(
    "/retention/purge",
    response_model=PurgeReportView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_EXECUTE))],
)
def execute_purge(payload: PurgeRequest, compliance: ComplianceDep) -> PurgeReportView:
    try:
        report = compliance.execute_purge(
            by=payload.by, as_of=payload.as_of, dry_run=payload.dry_run
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return PurgeReportView.from_model(report)


# --- erasure ----------------------------------------------------------------


@router.post("/erasures", status_code=status.HTTP_201_CREATED, response_model=ErasureView)
def create_erasure(payload: ErasureCreate, compliance: ComplianceDep) -> ErasureView:
    request = compliance.create_erasure_request(
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        reason=payload.reason,
        requested_by=payload.requested_by,
        channel=payload.channel,
    )
    return ErasureView.from_model(request)


@router.get("/erasures", response_model=list[ErasureView])
def list_erasures(compliance: ComplianceDep) -> list[ErasureView]:
    return [ErasureView.from_model(item) for item in compliance.list_erasures()]


@router.get("/erasures/{request_id}", response_model=ErasureView)
def get_erasure(request_id: UUID, compliance: ComplianceDep) -> ErasureView:
    try:
        return ErasureView.from_model(compliance.get_erasure(request_id))
    except ComplianceError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/erasures/{request_id}/verify", response_model=ErasureView)
def verify_erasure_identity(
    request_id: UUID, payload: ErasureVerify, compliance: ComplianceDep
) -> ErasureView:
    try:
        request = compliance.verify_identity(request_id, by=payload.by, method=payload.method)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ErasureView.from_model(request)


@router.post("/erasures/{request_id}/submit", response_model=ErasureView)
def submit_erasure(
    request_id: UUID, payload: ErasureAction, compliance: ComplianceDep
) -> ErasureView:
    try:
        request = compliance.submit_for_decision(request_id, by=payload.by)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ErasureView.from_model(request)


@router.post("/erasures/approvals/{approval_id}/sync", response_model=ErasureView)
def sync_erasure_decision(approval_id: UUID, compliance: ComplianceDep) -> ErasureView:
    try:
        request = compliance.apply_decision(approval_id)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ErasureView.from_model(request)


@router.post(
    "/erasures/{request_id}/execute",
    response_model=ErasureView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_EXECUTE))],
)
def execute_erasure(
    request_id: UUID, payload: ErasureAction, compliance: ComplianceDep
) -> ErasureView:
    try:
        request = compliance.execute_erasure(request_id, by=payload.by)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ErasureView.from_model(request)


# --- breach ------------------------------------------------------------------


@router.get("/breaches/template", response_model=BreachTemplateView)
def breach_template() -> BreachTemplateView:
    return BreachTemplateView.from_model(default_breach_template())


@router.post("/breaches", status_code=status.HTTP_201_CREATED, response_model=BreachView)
def create_breach(payload: BreachCreate, compliance: ComplianceDep) -> BreachView:
    incident = compliance.create_incident(
        title=payload.title,
        description=payload.description,
        impact=payload.impact,
        discovered_by=payload.discovered_by,
        created_by=payload.created_by,
        discovered_at=payload.discovered_at,
    )
    return BreachView.from_model(incident)


@router.get("/breaches", response_model=list[BreachView])
def list_breaches(compliance: ComplianceDep) -> list[BreachView]:
    return [BreachView.from_model(item) for item in compliance.list_incidents()]


@router.get("/breaches/overdue", response_model=list[OverdueStepView])
def overdue_breach_steps(
    compliance: ComplianceDep, as_of: UtcDateTime | None = None
) -> list[OverdueStepView]:
    return [OverdueStepView.from_model(item) for item in compliance.overdue_steps(as_of=as_of)]


@router.get("/breaches/{incident_id}", response_model=BreachView)
def get_breach(incident_id: UUID, compliance: ComplianceDep) -> BreachView:
    try:
        return BreachView.from_model(compliance.get_incident(incident_id))
    except ComplianceError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/breaches/{incident_id}/steps/{step_key}/complete", response_model=BreachView)
def complete_breach_step(
    incident_id: UUID, step_key: str, payload: StepComplete, compliance: ComplianceDep
) -> BreachView:
    try:
        incident = compliance.complete_step(
            incident_id, step_key=step_key, by=payload.by, note=payload.note
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return BreachView.from_model(incident)


@router.post("/breaches/{incident_id}/notifications", response_model=BreachView)
def record_breach_notification(
    incident_id: UUID, payload: NotificationCreate, compliance: ComplianceDep
) -> BreachView:
    try:
        incident = compliance.record_notification(
            incident_id,
            recipient_kind=payload.recipient_kind,
            recipient=payload.recipient,
            sent_by=payload.sent_by,
            reference=payload.reference,
            note=payload.note,
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return BreachView.from_model(incident)


@router.post("/breaches/{incident_id}/status", response_model=BreachView)
def transition_breach(
    incident_id: UUID, payload: BreachTransition, compliance: ComplianceDep
) -> BreachView:
    try:
        incident = compliance.transition(
            incident_id, status=payload.status, by=payload.by, note=payload.note
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return BreachView.from_model(incident)


# --- audit -------------------------------------------------------------------


@router.get("/audit/verify", response_model=AuditVerifyView)
def verify_audit(compliance: ComplianceDep, checked_by: str = "system") -> AuditVerifyView:
    return AuditVerifyView.from_model(compliance.verify_audit_chain(checked_by=checked_by))
