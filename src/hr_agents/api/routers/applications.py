"""Application ingestion and pipeline endpoints (single, batch, list, status)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from hr_agents.api.deps import get_audit, get_store, require_permission
from hr_agents.api.schemas import (
    ApplicationAccepted,
    ApplicationStatusResponse,
    ApplicationSubmission,
    ApplicationSummary,
    BatchAccepted,
    BatchItemResult,
    BatchSubmissionRequest,
)
from hr_agents.rbac import Permission
from hr_agents.services import ApplicationStore, AuditChain, SubmissionConflictError

router = APIRouter(
    prefix="/v1/applications",
    tags=["applications"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)

StoreDep = Annotated[ApplicationStore, Depends(get_store)]
AuditDep = Annotated[AuditChain, Depends(get_audit)]


def _submit_one(
    submission: ApplicationSubmission,
    store: ApplicationStore,
    audit: AuditChain,
    idempotency_key: str | None,
) -> ApplicationAccepted:
    record, created = store.submit(submission.to_input(), idempotency_key=idempotency_key)
    if created:
        audit.append_system(
            action="application.received",
            subject_type="application",
            subject_id=str(record.id),
            payload={
                "job_id": str(record.job_id),
                "candidate_id": str(record.candidate_id),
                "source_channel": record.source_channel,
                "idempotency_key": idempotency_key,
            },
        )
    return ApplicationAccepted(
        application_id=record.id,
        candidate_id=record.candidate_id,
        status=record.status.value,
        queued_at=record.received_at,
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApplicationAccepted,
    summary="Ingest a single application",
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)
def submit_application(
    submission: ApplicationSubmission,
    store: StoreDep,
    audit: AuditDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApplicationAccepted:
    try:
        return _submit_one(submission, store, audit, idempotency_key)
    except SubmissionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BatchAccepted,
    summary="Ingest up to 500 applications",
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)
def submit_batch(
    payload: BatchSubmissionRequest, store: StoreDep, audit: AuditDep
) -> BatchAccepted:
    results: list[BatchItemResult] = []
    accepted = 0
    for submission in payload.items:
        try:
            response = _submit_one(submission, store, audit, idempotency_key=None)
        except SubmissionConflictError as exc:
            results.append(BatchItemResult(status="conflict", error=str(exc)))
            continue
        results.append(
            BatchItemResult(application_id=response.application_id, status=response.status)
        )
        accepted += 1

    return BatchAccepted(accepted=accepted, items=results)


@router.get(
    "",
    response_model=list[ApplicationSummary],
    summary="Pipeline applications, ranked by priority",
)
def list_applications(
    store: StoreDep,
    job_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ApplicationSummary]:
    now = datetime.now(UTC)
    records = store.list_for_job(job_id) if job_id is not None else store.list_all()
    ranked = sorted(records, key=lambda record: record.priority_score, reverse=True)
    return [ApplicationSummary.from_record(record, now=now) for record in ranked[:limit]]


@router.get(
    "/{application_id}",
    response_model=ApplicationStatusResponse,
    summary="Application status and timeline",
)
def get_application(application_id: UUID, store: StoreDep) -> ApplicationStatusResponse:
    record = store.get(application_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"application {application_id} not found",
        )
    return ApplicationStatusResponse.from_record(record)
