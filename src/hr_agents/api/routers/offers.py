"""Offer endpoints — full records behind the approval gate and acceptance tracking.

Nothing here approves, sends, or accepts on its own: every transition carries a
named human, the approval runs through the shared engine, and the offer message
leaves through the candidate communication outbox.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.deps import require_permission
from hr_agents.api.recruitment_schemas import (
    OfferAcceptanceRequest,
    OfferCreate,
    OfferDecisionRequest,
    OfferMessageRequest,
    OfferReviseRequest,
    OfferSubmitRequest,
    OfferView,
)
from hr_agents.rbac import Permission
from hr_agents.services.offers import OfferError, OfferService
from hr_agents.services.recruiting import RecruitingError

router = APIRouter(
    prefix="/v1/offers",
    tags=["offers"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)


def get_offers(request: Request) -> OfferService:
    return request.app.state.recruiting.offers


OffersDep = Annotated[OfferService, Depends(get_offers)]


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=list[OfferView], summary="List offers (filter by application)")
def list_offers(offers: OffersDep, application_id: UUID | None = None) -> list[OfferView]:
    return [OfferView.from_model(offer) for offer in offers.list_all(application_id=application_id)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=OfferView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
    summary="Create a draft offer (named human; terms are human-entered)",
)
def create_offer(payload: OfferCreate, offers: OffersDep) -> OfferView:
    try:
        offer = offers.create(
            payload.application_id, payload.terms, by=payload.by, note=payload.note
        )
    except RecruitingError as exc:
        raise _not_found(str(exc)) from exc
    except OfferError as exc:
        if "named human" in str(exc):
            raise _forbidden(str(exc)) from exc
        raise _conflict(exc) from exc
    return OfferView.from_model(offer)


@router.get("/{offer_id}", response_model=OfferView)
def get_offer(offer_id: UUID, offers: OffersDep) -> OfferView:
    try:
        return OfferView.from_model(offers.get(offer_id))
    except OfferError as exc:
        raise _not_found(str(exc)) from exc


@router.patch(
    "/{offer_id}",
    response_model=OfferView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
    summary="Revise a draft offer (append-only revision)",
)
def revise_offer(offer_id: UUID, payload: OfferReviseRequest, offers: OffersDep) -> OfferView:
    try:
        offer = offers.revise(offer_id, payload.terms, by=payload.by, note=payload.note)
    except OfferError as exc:
        message = str(exc)
        if message.startswith("unknown offer"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    return OfferView.from_model(offer)


@router.post(
    "/{offer_id}/submit",
    response_model=OfferView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
    summary="Submit a draft offer for approval (shared approval queue)",
)
def submit_offer(offer_id: UUID, payload: OfferSubmitRequest, offers: OffersDep) -> OfferView:
    try:
        offer = offers.submit(offer_id, by=payload.by)
    except OfferError as exc:
        message = str(exc)
        if message.startswith("unknown offer"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    return OfferView.from_model(offer)


@router.post(
    "/{offer_id}/decision",
    response_model=OfferView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_OVERRIDE))],
    summary="Approve or withdraw an offer (named human; overrides the approval queue)",
)
def decide_offer(offer_id: UUID, payload: OfferDecisionRequest, offers: OffersDep) -> OfferView:
    try:
        offer = offers.decide(
            offer_id, decision=payload.decision, by=payload.by, reason=payload.reason
        )
    except OfferError as exc:
        message = str(exc)
        if message.startswith("unknown offer"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    return OfferView.from_model(offer)


@router.post(
    "/{offer_id}/message",
    response_model=OfferView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
    summary="Queue the candidate-facing offer message through the outbox",
)
def queue_offer_message(
    offer_id: UUID, payload: OfferMessageRequest, offers: OffersDep
) -> OfferView:
    try:
        offer = offers.queue_message(
            offer_id,
            by=payload.by,
            body=payload.body,
            subject=payload.subject,
            language=payload.language,
            to_email=payload.to_email,
        )
    except OfferError as exc:
        message = str(exc)
        if message.startswith("unknown offer"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    except RecruitingError as exc:
        raise _conflict(exc) from exc
    return OfferView.from_model(offer)


@router.post(
    "/{offer_id}/acceptance",
    response_model=OfferView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
    summary="Record the candidate's acceptance or decline (human-relayed)",
)
def record_acceptance(
    offer_id: UUID, payload: OfferAcceptanceRequest, offers: OffersDep
) -> OfferView:
    try:
        offer = offers.record_acceptance(
            offer_id, by=payload.by, accepted=payload.accepted, reason=payload.reason
        )
    except OfferError as exc:
        message = str(exc)
        if message.startswith("unknown offer"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    return OfferView.from_model(offer)
