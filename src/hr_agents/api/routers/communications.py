"""Candidate communication endpoints — the gated rejection/offer outbox.

Messages are queued behind a named human. Dispatch is either manual (``/sent``
records the human's own send) or carried by the configured email transport,
which records its own evidence; the queue is the only source of messages either
way, and nothing is sent before a human approved it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.deps import require_permission
from hr_agents.api.recruitment_schemas import (
    CommunicationPreviewView,
    CommunicationSentRequest,
    CommunicationView,
    OfferQueueRequest,
    RejectionPreviewRequest,
    RejectionQueueRequest,
    ReplyView,
    WhatsappDispatchLinkRequest,
    WhatsappDispatchLinkView,
)
from hr_agents.messaging.store import ReplyStore
from hr_agents.messaging.whatsapp import ManualWhatsappLinks, WhatsappLinkError
from hr_agents.rbac import Permission
from hr_agents.services.recruiting import CommunicationService, RecruitingError

router = APIRouter(
    prefix="/v1",
    tags=["communications"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)


def get_communications(request: Request) -> CommunicationService:
    return request.app.state.recruiting.communications


def get_replies(request: Request) -> ReplyStore:
    return request.app.state.messaging.replies


CommunicationsDep = Annotated[CommunicationService, Depends(get_communications)]
RepliesDep = Annotated[ReplyStore, Depends(get_replies)]


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get(
    "/candidates/{candidate_id}/communications",
    response_model=list[CommunicationView],
    summary="Candidate communication history (queued and sent)",
)
def list_communications(
    candidate_id: UUID, communications: CommunicationsDep
) -> list[CommunicationView]:
    return [CommunicationView.from_model(item) for item in communications.list_for(candidate_id)]


@router.get(
    "/candidates/{candidate_id}/replies",
    response_model=list[ReplyView],
    summary="Inbound candidate replies captured by the messaging transport",
)
def list_replies(candidate_id: UUID, replies: RepliesDep) -> list[ReplyView]:
    return [ReplyView.from_model(item) for item in replies.list_for(candidate_id)]


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
            to_email=payload.to_email,
            to_phone=payload.to_phone,
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
    "/candidates/{candidate_id}/communications/rejection/preview",
    response_model=CommunicationPreviewView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_OVERRIDE))],
    summary="Preview the rejection message and the reasons it cannot be queued",
)
def preview_rejection(
    candidate_id: UUID, payload: RejectionPreviewRequest, communications: CommunicationsDep
) -> CommunicationPreviewView:
    """Render the message a queue would store without storing anything.

    A preview is a read: it writes no message, no audit entry, and no approval.
    ``blockers`` is exactly what the queue endpoint will refuse with, because
    both read the same gates.
    """
    preview = communications.preview_rejection(
        candidate_id,
        by=payload.by,
        channel=payload.channel,
        language=payload.language,
        to_email=payload.to_email,
        to_phone=payload.to_phone,
    )
    return CommunicationPreviewView.from_model(preview)


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
            to_email=payload.to_email,
            to_phone=payload.to_phone,
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
    "/communications/{communication_id}/dispatch-link",
    response_model=WhatsappDispatchLinkView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
    summary="Compose a wa.me link for a queued WhatsApp message (the human sends it)",
)
def compose_dispatch_link(
    communication_id: UUID,
    payload: WhatsappDispatchLinkRequest,
    communications: CommunicationsDep,
) -> WhatsappDispatchLinkView:
    try:
        message = communications.get(communication_id)
        transport = ManualWhatsappLinks()
        prepared = communications.prepare_manual_dispatch(
            communication_id,
            by=payload.by,
            provider=transport.provider_id,
            recipient_phone=payload.to_phone,
        )
        link = transport.compose(prepared.recipient_phone or "", prepared.body)
    except RecruitingError as exc:
        message_text = str(exc)
        if message_text.startswith("unknown communication"):
            raise _not_found(message_text) from exc
        if "named human" in message_text:
            raise _forbidden(message_text) from exc
        raise _conflict(exc) from exc
    except WhatsappLinkError as exc:
        raise _bad_request(str(exc)) from exc
    return WhatsappDispatchLinkView(
        communication_id=message.id,
        provider=link.provider,
        phone=link.phone,
        url=link.url,
        body=message.body,
    )


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
