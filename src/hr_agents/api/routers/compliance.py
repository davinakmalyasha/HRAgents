"""Compliance API router — consent, retention, erasure, breach, audit verify."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from hr_agents.api.compliance_schemas import (
    AuditEntryView,
    AuditVerifyView,
    BreachCreate,
    BreachTemplateView,
    BreachTransition,
    BreachView,
    CalendarEntryCreate,
    CalendarEntryRemove,
    CalendarItemView,
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
    PurgeJobView,
    PurgeReportView,
    PurgeRequest,
    RecordTrack,
    RecordView,
    ScanView,
    StepComplete,
)
from hr_agents.api.deps import ActorDep, PaginationDep, require_permission
from hr_agents.api.problem import conflict, domain_problem, not_found
from hr_agents.api.schemas import Page
from hr_agents.errors import DomainError
from hr_agents.models import (
    PurgeJobStatus,
    RecordEntity,
    SubjectKind,
    UtcDateTime,
    business_today,
)
from hr_agents.rbac import Permission
from hr_agents.services.calendar import CalendarError, CalendarService
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

# Reading the raw trail is an audit capability, not a compliance one. Keeping the
# entries endpoint on `AUDIT_READ` means a future role can be granted the trail
# without also being handed consent, retention and breach access -- and it gives
# `AUDIT_READ`, which existed but was never referenced, an enforcement point.
audit_router = APIRouter(
    prefix="/v1/compliance/audit",
    tags=["compliance"],
    dependencies=[Depends(require_permission(Permission.AUDIT_READ))],
)


def get_compliance(request: Request) -> ComplianceService:
    return request.app.state.compliance


ComplianceDep = Annotated[ComplianceService, Depends(get_compliance)]


def _raise(exc: Exception) -> HTTPException:
    """Turn a compliance refusal into the response, using the code it carries.

    It used to decide by asking whether the message began with "unknown" or
    contained " not found" -- one shared helper, so every compliance endpoint got
    the same prose test and every one of them had to keep the wording in step
    with it. The refusals now carry `UNKNOWN_RECORD`/404 or the default conflict
    themselves.
    """
    if isinstance(exc, DomainError):
        return domain_problem(exc)
    return conflict(exc)


# --- consent ----------------------------------------------------------------


@router.post(
    "/consents",
    status_code=status.HTTP_201_CREATED,
    response_model=ConsentView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def record_consent(
    payload: ConsentCreate, compliance: ComplianceDep, actor: ActorDep
) -> ConsentView:
    record = compliance.record_consent(
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        purpose=payload.purpose,
        actor=actor,
        granted=payload.granted,
        lawful_basis=payload.lawful_basis,
        capture_method=payload.capture_method,
        policy_version=payload.policy_version,
        expires_at=payload.expires_at,
        note=payload.note,
    )
    return ConsentView.from_model(record)


@router.get("/consents", response_model=Page[ConsentView])
def list_consents(
    compliance: ComplianceDep,
    paging: PaginationDep,
    subject_kind: SubjectKind | None = None,
    subject_id: str | None = None,
) -> Page[ConsentView]:
    items, total = compliance.page_consents(
        subject_kind=subject_kind,
        subject_id=subject_id,
        limit=paging.limit,
        offset=paging.offset,
    )
    return Page.of(
        [ConsentView.from_model(item) for item in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


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


@router.post(
    "/consents/{consent_id}/revoke",
    response_model=ConsentView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def revoke_consent(
    consent_id: UUID,
    payload: ConsentRevoke,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> ConsentView:
    try:
        record = compliance.revoke_consent(consent_id, actor=actor, reason=payload.reason)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ConsentView.from_model(record)


# --- retention --------------------------------------------------------------


@router.put(
    "/retention/policies",
    response_model=PolicyView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def set_policy(payload: PolicySet, compliance: ComplianceDep, actor: ActorDep) -> PolicyView:
    try:
        policy = compliance.set_policy(
            entity=payload.entity,
            name=payload.name,
            retention_months=payload.retention_months,
            actor=actor,
            expiry_action=payload.expiry_action,
            jurisdiction=payload.jurisdiction,
            active=payload.active,
            note=payload.note,
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return PolicyView.from_model(policy)


@router.get("/retention/policies", response_model=Page[PolicyView])
def list_policies(compliance: ComplianceDep, paging: PaginationDep) -> Page[PolicyView]:
    policies = compliance.list_policies()
    ordered = sorted(policies, key=lambda item: (item.entity.value, str(item.id)))
    return Page.slice(
        [PolicyView.from_model(item) for item in ordered],
        limit=paging.limit,
        offset=paging.offset,
    )


@router.post(
    "/retention/records",
    status_code=status.HTTP_201_CREATED,
    response_model=RecordView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def track_record(payload: RecordTrack, compliance: ComplianceDep, actor: ActorDep) -> RecordView:
    record = compliance.track_record(
        entity=payload.entity,
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        actor=actor,
        label=payload.label,
        anchor_at=payload.anchor_at,
        retention_months_override=payload.retention_months_override,
    )
    return RecordView.from_model(record)


@router.get("/retention/records", response_model=Page[RecordView])
def list_records(
    compliance: ComplianceDep,
    paging: PaginationDep,
    subject_kind: SubjectKind | None = None,
    subject_id: str | None = None,
    entity: RecordEntity | None = None,
    include_purged: bool = False,
) -> Page[RecordView]:
    items, total = compliance.page_records(
        subject_kind=subject_kind,
        subject_id=subject_id,
        entity=entity,
        include_purged=include_purged,
        limit=paging.limit,
        offset=paging.offset,
    )
    return Page.of(
        [RecordView.from_model(item) for item in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.post(
    "/retention/records/{record_id}/hold",
    response_model=RecordView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def set_legal_hold(
    record_id: UUID,
    payload: LegalHoldRequest,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> RecordView:
    try:
        record = compliance.set_legal_hold(
            record_id, held=payload.held, actor=actor, reason=payload.reason
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return RecordView.from_model(record)


@router.get("/retention/scan", response_model=ScanView)
def scan_retention(compliance: ComplianceDep, as_of: UtcDateTime | None = None) -> ScanView:
    return ScanView.from_model(compliance.scan(as_of=as_of))


@router.get(
    "/retention/purge-jobs",
    response_model=Page[PurgeJobView],
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_EXECUTE))],
)
def list_purge_jobs(
    compliance: ComplianceDep,
    paging: PaginationDep,
    status_filter: Annotated[PurgeJobStatus | None, Query(alias="status")] = None,
) -> Page[PurgeJobView]:
    """The purge journal: interrupted attempts, retries and completions."""
    jobs = compliance.list_purge_jobs(status=status_filter)
    items = [PurgeJobView.from_model(job) for job in jobs]
    return Page.of(
        items[paging.offset : paging.offset + paging.limit],
        total=len(items),
        limit=paging.limit,
        offset=paging.offset,
    )


@router.post(
    "/retention/purge",
    response_model=PurgeReportView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_EXECUTE))],
)
def execute_purge(
    payload: PurgeRequest, compliance: ComplianceDep, actor: ActorDep
) -> PurgeReportView:
    try:
        report = compliance.execute_purge(actor=actor, as_of=payload.as_of, dry_run=payload.dry_run)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return PurgeReportView.from_model(report)


# --- erasure ----------------------------------------------------------------


@router.post(
    "/erasures",
    status_code=status.HTTP_201_CREATED,
    response_model=ErasureView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def create_erasure(
    payload: ErasureCreate, compliance: ComplianceDep, actor: ActorDep
) -> ErasureView:
    request = compliance.create_erasure_request(
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        reason=payload.reason,
        actor=actor,
        channel=payload.channel,
    )
    return ErasureView.from_model(request)


@router.get("/erasures", response_model=Page[ErasureView])
def list_erasures(compliance: ComplianceDep, paging: PaginationDep) -> Page[ErasureView]:
    items, total = compliance.page_erasures(limit=paging.limit, offset=paging.offset)
    return Page.of(
        [ErasureView.from_model(item) for item in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/erasures/{request_id}", response_model=ErasureView)
def get_erasure(request_id: UUID, compliance: ComplianceDep) -> ErasureView:
    try:
        return ErasureView.from_model(compliance.get_erasure(request_id))
    except ComplianceError as exc:
        raise not_found(str(exc)) from exc


@router.post(
    "/erasures/{request_id}/verify",
    response_model=ErasureView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def verify_erasure_identity(
    request_id: UUID,
    payload: ErasureVerify,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> ErasureView:
    try:
        request = compliance.verify_identity(request_id, actor=actor, method=payload.method)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ErasureView.from_model(request)


@router.post(
    "/erasures/{request_id}/submit",
    response_model=ErasureView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def submit_erasure(
    request_id: UUID,
    payload: ErasureAction,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> ErasureView:
    try:
        request = compliance.submit_for_decision(request_id, actor=actor)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ErasureView.from_model(request)


@router.post(
    "/erasures/approvals/{approval_id}/sync",
    response_model=ErasureView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def sync_erasure_decision(
    approval_id: UUID, compliance: ComplianceDep, actor: ActorDep
) -> ErasureView:
    """Land a decided approval's outcome on the erasure request."""
    try:
        request = compliance.apply_decision(approval_id, actor=actor)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ErasureView.from_model(request)


@router.post(
    "/erasures/{request_id}/execute",
    response_model=ErasureView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_EXECUTE))],
)
def execute_erasure(
    request_id: UUID,
    payload: ErasureAction,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> ErasureView:
    try:
        request = compliance.execute_erasure(request_id, actor=actor)
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return ErasureView.from_model(request)


# --- breach ------------------------------------------------------------------


@router.get("/breaches/template", response_model=BreachTemplateView)
def breach_template() -> BreachTemplateView:
    return BreachTemplateView.from_model(default_breach_template())


@router.post(
    "/breaches",
    status_code=status.HTTP_201_CREATED,
    response_model=BreachView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def create_breach(payload: BreachCreate, compliance: ComplianceDep, actor: ActorDep) -> BreachView:
    incident = compliance.create_incident(
        title=payload.title,
        description=payload.description,
        impact=payload.impact,
        actor=actor,
        discovered_at=payload.discovered_at,
    )
    return BreachView.from_model(incident)


@router.get("/breaches", response_model=Page[BreachView])
def list_breaches(compliance: ComplianceDep, paging: PaginationDep) -> Page[BreachView]:
    items, total = compliance.page_incidents(limit=paging.limit, offset=paging.offset)
    return Page.of(
        [BreachView.from_model(item) for item in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/breaches/overdue", response_model=Page[OverdueStepView])
def overdue_breach_steps(
    compliance: ComplianceDep,
    paging: PaginationDep,
    as_of: UtcDateTime | None = None,
) -> Page[OverdueStepView]:
    overdue = compliance.overdue_steps(as_of=as_of)
    ordered = sorted(
        overdue, key=lambda item: (item.step.due_at, str(item.incident_id), item.step.key)
    )
    return Page.slice(
        [OverdueStepView.from_model(item) for item in ordered],
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/breaches/{incident_id}", response_model=BreachView)
def get_breach(incident_id: UUID, compliance: ComplianceDep) -> BreachView:
    try:
        return BreachView.from_model(compliance.get_incident(incident_id))
    except ComplianceError as exc:
        raise not_found(str(exc)) from exc


@router.post(
    "/breaches/{incident_id}/steps/{step_key}/complete",
    response_model=BreachView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def complete_breach_step(
    incident_id: UUID,
    step_key: str,
    payload: StepComplete,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> BreachView:
    try:
        incident = compliance.complete_step(
            incident_id, step_key=step_key, actor=actor, note=payload.note
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return BreachView.from_model(incident)


@router.post(
    "/breaches/{incident_id}/notifications",
    response_model=BreachView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def record_breach_notification(
    incident_id: UUID,
    payload: NotificationCreate,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> BreachView:
    try:
        incident = compliance.record_notification(
            incident_id,
            recipient_kind=payload.recipient_kind,
            recipient=payload.recipient,
            actor=actor,
            reference=payload.reference,
            note=payload.note,
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return BreachView.from_model(incident)


@router.post(
    "/breaches/{incident_id}/status",
    response_model=BreachView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def transition_breach(
    incident_id: UUID,
    payload: BreachTransition,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> BreachView:
    try:
        incident = compliance.transition(
            incident_id, status=payload.status, actor=actor, note=payload.note
        )
    except ComplianceError as exc:
        raise _raise(exc) from exc
    return BreachView.from_model(incident)


# --- audit -------------------------------------------------------------------


@audit_router.get("/entries", response_model=Page[AuditEntryView])
def list_audit_entries(
    request: Request,
    paging: PaginationDep,
    actor: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    subject_type: Annotated[str | None, Query()] = None,
    subject_id: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> Page[AuditEntryView]:
    """The audit trail itself, newest first.

    Newest first because a viewer is nearly always answering "what just happened" rather
    than reading the chain from the beginning; the sequence number is on every row, so the
    order is never ambiguous. The window comes from the shared pagination dependency:
    the chain grows forever and a viewer that can request all of it in one page is an
    easy way to take the process down.

    Filters are exact matches on the indexed columns. `since`/`until` are inclusive so a
    caller can page by the boundary timestamp it already has.
    """
    entries, total = request.app.state.audit.page_entries(
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        since=since,
        until=until,
        limit=paging.limit,
        offset=paging.offset,
    )
    return Page.of(
        [AuditEntryView.from_model(entry) for entry in entries],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/audit/verify", response_model=AuditVerifyView)
def verify_audit(compliance: ComplianceDep, actor: ActorDep) -> AuditVerifyView:
    """Verify the tamper-evident chain and say who checked it.

    The verifier used to be a query parameter, so the report named whoever the
    caller typed in the URL -- the one place in the compliance surface where a
    self-declared actor could still reach the response unchallenged.
    """
    return AuditVerifyView.from_model(compliance.verify_audit_chain(actor=actor))


# --- calendar ----------------------------------------------------------------


def get_calendar(request: Request) -> CalendarService:
    return request.app.state.people.calendar


CalendarDep = Annotated[CalendarService, Depends(get_calendar)]


@router.get("/calendar", response_model=Page[CalendarItemView])
def list_calendar(
    calendar: CalendarDep,
    paging: PaginationDep,
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
) -> Page[CalendarItemView]:
    """The compliance calendar for a window: derived deadlines plus operator dates.

    Two sources, merged and sorted by due date. Derived deadlines come from
    records the product already keeps; operator entries carry the statutory or
    policy dates the product must not invent. ``overdue`` is computed against
    the business day, so clients do not re-derive the timezone rule.
    """
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end must not be before start",
        )
    today = business_today()
    items = [
        CalendarItemView.from_deadline(deadline, today=today)
        for deadline in calendar.deadlines(start=start, end=end)
    ] + [
        CalendarItemView.from_entry(entry, today=today)
        for entry in calendar.entries(start=start, end=end)
    ]
    ordered = sorted(
        items,
        key=lambda item: (
            item.due_on,
            item.source,
            item.kind,
            str(item.entry_id or item.subject_id or ""),
        ),
    )
    return Page.slice(ordered, limit=paging.limit, offset=paging.offset)


@router.post(
    "/calendar/entries",
    status_code=status.HTTP_201_CREATED,
    response_model=CalendarItemView,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def create_calendar_entry(
    payload: CalendarEntryCreate, calendar: CalendarDep, actor: ActorDep
) -> CalendarItemView:
    try:
        entry = calendar.add_entry(
            title=payload.title,
            due_on=payload.due_on,
            category=payload.category,
            jurisdiction=payload.jurisdiction,
            source_note=payload.source_note,
            notes=payload.notes,
            actor=actor,
        )
    except CalendarError as exc:
        raise domain_problem(exc) from exc
    return CalendarItemView.from_entry(entry, today=business_today())


@router.delete(
    "/calendar/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def remove_calendar_entry(
    entry_id: UUID, payload: CalendarEntryRemove, calendar: CalendarDep, actor: ActorDep
) -> None:
    """Remove one operator date. A reason is required and lands in the trail."""
    try:
        calendar.remove_entry(entry_id=entry_id, actor=actor, reason=payload.reason)
    except CalendarError as exc:
        raise domain_problem(exc) from exc
