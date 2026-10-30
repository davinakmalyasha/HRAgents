"""Email application drafts — the consent gate for CVs arriving by email."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from hr_agents.api.deps import (
    ActorDep,
    PaginationDep,
    get_audit,
    get_compliance,
    get_dispatcher,
    get_store,
    require_permission,
)
from hr_agents.api.email_draft_schemas import DraftConfirm, DraftDiscard, EmailDraftView
from hr_agents.api.problem import conflict, not_found
from hr_agents.api.routers.applications import _submit_one
from hr_agents.api.schemas import (
    ApplicationAccepted,
    ApplicationSubmission,
    CandidateInput,
    ConsentInput,
    DocumentRef,
    Page,
)
from hr_agents.messaging.drafts import EmailDraftStatus, EmailDraftStore
from hr_agents.models import utc_now
from hr_agents.rbac import Permission
from hr_agents.services import AuditChain, SubmissionConflictError
from hr_agents.services.compliance import ComplianceService
from hr_agents.services.dispatch import EvaluationDispatcher
from hr_agents.services.ingestion import ApplicationStore
from hr_agents.services.recruiting import DocumentService, JobService, RecruitingError

router = APIRouter(
    prefix="/v1/applications/email-drafts",
    tags=["applications"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)


def get_drafts(request: Request) -> EmailDraftStore:
    return request.app.state.messaging.drafts


def get_jobs(request: Request) -> JobService:
    return request.app.state.recruiting.jobs


def get_documents(request: Request) -> DocumentService:
    return request.app.state.recruiting.documents


DraftsDep = Annotated[EmailDraftStore, Depends(get_drafts)]
JobsDep = Annotated[JobService, Depends(get_jobs)]
DocumentsDep = Annotated[DocumentService, Depends(get_documents)]
StoreDep = Annotated[ApplicationStore, Depends(get_store)]
AuditDep = Annotated[AuditChain, Depends(get_audit)]
DispatcherDep = Annotated[EvaluationDispatcher, Depends(get_dispatcher)]
ComplianceDep = Annotated[ComplianceService, Depends(get_compliance)]


@router.get("", response_model=Page[EmailDraftView], summary="List email application drafts")
def list_drafts(
    drafts: DraftsDep,
    paging: PaginationDep,
    draft_status: Annotated[EmailDraftStatus | None, Query(alias="status")] = None,
) -> Page[EmailDraftView]:
    items, total = drafts.page(status=draft_status, limit=paging.limit, offset=paging.offset)
    return Page.of(
        [EmailDraftView.from_draft(draft) for draft in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/{draft_id}", response_model=EmailDraftView, summary="Read one email draft")
def get_draft(draft_id: UUID, drafts: DraftsDep) -> EmailDraftView:
    draft = drafts.get(draft_id)
    if draft is None:
        raise not_found(f"unknown email draft {draft_id}")
    return EmailDraftView.from_draft(draft)


@router.post(
    "/{draft_id}/confirm",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApplicationAccepted,
    summary="Confirm a draft into an application with explicit consent",
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)
async def confirm_draft(
    draft_id: UUID,
    payload: DraftConfirm,
    drafts: DraftsDep,
    jobs: JobsDep,
    documents: DocumentsDep,
    store: StoreDep,
    audit: AuditDep,
    dispatcher: DispatcherDep,
    compliance: ComplianceDep,
    actor: ActorDep,
) -> ApplicationAccepted:
    draft = drafts.get(draft_id)
    if draft is None:
        raise not_found(f"unknown email draft {draft_id}")
    if draft.status is not EmailDraftStatus.PENDING:
        raise conflict(f"draft {draft_id} is {draft.status.value}, not pending")
    if not payload.consent_granted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confirming a draft requires consent_granted=true from the candidate",
        )
    try:
        jobs.get(payload.job_id)
    except RecruitingError as exc:
        raise not_found(str(exc)) from exc
    if not draft.document_ids:
        raise conflict(
            f"draft {draft_id} has no stored documents; ask the candidate to resend the CV"
        )
    try:
        for document_id in draft.document_ids:
            documents.get(document_id)
    except RecruitingError as exc:
        raise conflict(f"draft {draft_id} references a missing document: {exc}") from exc
    name = (payload.candidate_name or draft.sender_name or "").strip()
    submission = ApplicationSubmission(
        job_id=payload.job_id,
        source_channel="email",
        consent=ConsentInput(granted=True),
        candidate=CandidateInput(full_name=name, emails=[draft.sender]),
        documents=[DocumentRef(document_id=item) for item in draft.document_ids],
        metadata={
            "email_draft_id": str(draft.id),
            "provider_message_id": draft.provider_message_id,
            "subject": draft.subject,
        },
    )
    try:
        accepted = await _submit_one(
            submission,
            store,
            audit,
            dispatcher,
            compliance,
            idempotency_key=f"mail:{draft.provider}:{draft.dedup_key}",
        )
    except SubmissionConflictError as exc:
        raise conflict(exc) from exc
    drafts.save(
        draft.model_copy(
            update={
                "status": EmailDraftStatus.CONFIRMED,
                "application_id": accepted.application_id,
                "decided_by": actor.actor_id,
                "updated_at": utc_now(),
            }
        )
    )
    audit.append(
        actor=actor.audit_actor(),
        action="application.draft_confirmed",
        subject_type="email_application_draft",
        subject_id=str(draft.id),
        payload={
            "application_id": str(accepted.application_id),
            "job_id": str(payload.job_id),
        },
    )
    return accepted


@router.post(
    "/{draft_id}/discard",
    response_model=EmailDraftView,
    summary="Discard an email draft with a reason",
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)
def discard_draft(
    draft_id: UUID, payload: DraftDiscard, drafts: DraftsDep, actor: ActorDep
) -> EmailDraftView:
    draft = drafts.get(draft_id)
    if draft is None:
        raise not_found(f"unknown email draft {draft_id}")
    if draft.status is not EmailDraftStatus.PENDING:
        raise conflict(f"draft {draft_id} is {draft.status.value}, not pending")
    updated = draft.model_copy(
        update={
            "status": EmailDraftStatus.DISCARDED,
            "decided_by": actor.actor_id,
            "discard_reason": payload.reason.strip(),
            "updated_at": utc_now(),
        }
    )
    drafts.save(updated)
    return EmailDraftView.from_draft(updated)
