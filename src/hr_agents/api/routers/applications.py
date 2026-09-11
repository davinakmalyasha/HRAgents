"""Application ingestion endpoints (single, batch, status)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from hr_agents.api.deps import get_audit, get_store, require_api_key
from hr_agents.api.schemas import (
    ApplicationAccepted,
    ApplicationStatusResponse,
    ApplicationSubmission,
    BatchAccepted,
    BatchItemResult,
    BatchSubmissionRequest,
)
from hr_agents.services import ApplicationStore, AuditChain, SubmissionConflictError

router = APIRouter(
    prefix="/v1/applications",
    tags=["applications"],
    dependencies=[Depends(require_api_key)],
)


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
)
async def submit_application(
    submission: ApplicationSubmission,
    store: Annotated[ApplicationStore, Depends(get_store)],
    audit: Annotated[AuditChain, Depends(get_audit)],
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
)
async def submit_batch(
    payload: BatchSubmissionRequest,
    store: Annotated[ApplicationStore, Depends(get_store)],
    audit: Annotated[AuditChain, Depends(get_audit)],
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
    "/{application_id}",
    response_model=ApplicationStatusResponse,
    summary="Application status and timeline",
)
async def get_application(
    application_id: UUID,
    store: Annotated[ApplicationStore, Depends(get_store)],
) -> ApplicationStatusResponse:
    record = store.get(application_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"application {application_id} not found",
        )
    return ApplicationStatusResponse.from_record(record)
