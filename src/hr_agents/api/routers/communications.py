"""Candidate communication endpoints — the gated rejection/offer outbox.

Nothing here dispatches: messages are queued behind a named human, and
``/sent`` records manual dispatch evidence. The transport bridge (Phase 7)
consumes the queue when messaging providers are connected.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.deps import require_permission
from hr_agents.api.recruitment_schemas import (
    CommunicationSentRequest,
    CommunicationView,
    OfferQueueRequest,
    RejectionQueueRequest,
)
from hr_agents.rbac import Permission
from hr_agents.services.recruiting import CommunicationService, RecruitingError

router = APIRouter(
    prefix="/v1",
    tags=["communications"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)


def get_communications(request: Request) -> CommunicationService:
    return request.app.state.recruiting.communications


CommunicationsDep = Annotated[CommunicationService, Depends(get_communications)]


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/candidates/{candidate_id}/communications",
    response_model=list[CommunicationView],
    summary="Candidate communication history (queued and sent)",
)
def list_communications(
    candidate_id: UUID, communications: CommunicationsDep
) -> list[CommunicationView]:
    return [CommunicationView.from_model(item) for item in communications.list_for(candidate_id)]


@router.post(
    "/candidates/{candidate_id}/communications/rejection",
    status_code=status.HTTP_201_CREATED,
    response_model=CommunicationView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_OVERRIDE))],
    summary="Queue the rejection message (documented rejection + named human)",
)
def queue_rejection(
    candidate_id: UUID, payload: RejectionQueueRequest, communications: CommunicationsDep
) -> CommunicationView:
    try:
        item = communications.queue_rejection(
            candidate_id,
            by=payload.by,
            channel=payload.channel,
            language=payload.language,
        )
    except RecruitingError as exc:
        message = str(exc)
        if message.startswith("no evaluation"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    return CommunicationView.from_model(item)


@router.post(
    "/candidates/{candidate_id}/communications/offer",
    status_code=status.HTTP_201_CREATED,
    response_model=CommunicationView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_OVERRIDE))],
    summary="Queue a human-authored offer message",
)
def queue_offer(
    candidate_id: UUID, payload: OfferQueueRequest, communications: CommunicationsDep
) -> CommunicationView:
    try:
        item = communications.queue_offer(
            candidate_id,
            by=payload.by,
            body=payload.body,
            subject=payload.subject,
            channel=payload.channel,
            language=payload.language,
        )
    except RecruitingError as exc:
        message = str(exc)
        if message.startswith("no evaluation"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    return CommunicationView.from_model(item)


@router.post(
    "/communications/{communication_id}/sent",
    response_model=CommunicationView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
    summary="Record manual dispatch evidence for a queued message",
)
def mark_communication_sent(
    communication_id: UUID,
    payload: CommunicationSentRequest,
    communications: CommunicationsDep,
) -> CommunicationView:
    try:
        item = communications.mark_sent(communication_id, by=payload.by)
    except RecruitingError as exc:
        message = str(exc)
        if message.startswith("unknown communication"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    return CommunicationView.from_model(item)
