"""Scheduling endpoints — proposals (policy-gated) and the availability registry."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.deps import ActorDep, require_permission
from hr_agents.api.recruitment_schemas import (
    AvailabilitySet,
    ProposalDecisionRequest,
    ProposalDecisionResponse,
    SchedulingProposalRequest,
    SchedulingProposalView,
)
from hr_agents.models import TimeSlot
from hr_agents.rbac import Permission
from hr_agents.services.recruiting import RecruitingError, SchedulingService

router = APIRouter(
    prefix="/v1/scheduling",
    tags=["scheduling"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)


def get_scheduling(request: Request) -> SchedulingService:
    return request.app.state.recruiting.scheduling


SchedulingDep = Annotated[SchedulingService, Depends(get_scheduling)]


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


@router.post(
    "/availability",
    response_model=list[TimeSlot],
    summary="Ops: register interviewer free slots (calendar provider feeds this later)",
)
def set_availability(
    payload: AvailabilitySet, scheduling: SchedulingDep, actor: ActorDep
) -> list[TimeSlot]:
    return scheduling.set_availability(payload.interviewer_id, slots=payload.slots, actor=actor)


@router.post(
    "/proposals",
    status_code=status.HTTP_201_CREATED,
    response_model=SchedulingProposalView,
    summary="Propose interview slots (auto or HITL-gated)",
)
def create_proposal(
    payload: SchedulingProposalRequest, scheduling: SchedulingDep, actor: ActorDep
) -> SchedulingProposalView:
    try:
        proposal = scheduling.propose(
            candidate_id=payload.candidate_id,
            job_id=payload.job_id,
            interviewer_ids=payload.interviewer_ids,
            actor=actor,
            requested_channels=payload.requested_channels,
            notes=payload.notes,
        )
    except RecruitingError as exc:
        raise _conflict(exc) from exc
    return SchedulingProposalView.from_record(proposal)


@router.get("/proposals", response_model=list[SchedulingProposalView])
def list_proposals(scheduling: SchedulingDep) -> list[SchedulingProposalView]:
    return [SchedulingProposalView.from_record(item) for item in scheduling.list_all()]


@router.get("/proposals/{proposal_id}", response_model=SchedulingProposalView)
def get_proposal(proposal_id: UUID, scheduling: SchedulingDep) -> SchedulingProposalView:
    try:
        return SchedulingProposalView.from_record(scheduling.get(proposal_id))
    except RecruitingError as exc:
        raise _not_found(str(exc)) from exc


@router.post(
    "/proposals/{proposal_id}/decision",
    response_model=ProposalDecisionResponse,
    summary="Confirm, cancel, or reschedule a proposal (named human)",
)
def decide_proposal(
    proposal_id: UUID,
    payload: ProposalDecisionRequest,
    scheduling: SchedulingDep,
    actor: ActorDep,
) -> ProposalDecisionResponse:
    """The single writer for proposal outcomes; confirmations decide the
    linked scheduling approval through the shared approval engine."""
    try:
        proposal, replacement = scheduling.decide(
            proposal_id,
            decision=payload.decision,
            actor=actor,
            reason=payload.reason,
        )
    except RecruitingError as exc:
        message = str(exc)
        if message.startswith("unknown scheduling proposal"):
            raise _not_found(message) from exc
        if "named human" in message:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message) from exc
        raise _conflict(exc) from exc
    return ProposalDecisionResponse(
        proposal=SchedulingProposalView.from_record(proposal),
        replacement=(
            None if replacement is None else SchedulingProposalView.from_record(replacement)
        ),
    )
