"""Evaluation read endpoints and append-only human overrides."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from hr_agents.api.deps import ActorDep, require_permission
from hr_agents.api.problem import domain_problem, not_found
from hr_agents.api.recruitment_schemas import (
    AuditReceipt,
    EvaluationView,
    OverrideCreate,
    OverrideView,
)
from hr_agents.rbac import Permission
from hr_agents.services.recruiting import EvaluationService, RecruitingError

router = APIRouter(
    prefix="/v1",
    tags=["evaluations"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)


def get_evaluations(request: Request) -> EvaluationService:
    return request.app.state.recruiting.evaluations


EvaluationsDep = Annotated[EvaluationService, Depends(get_evaluations)]


@router.get(
    "/applications/{application_id}/evaluation",
    response_model=EvaluationView,
    summary="Deterministic evaluation result for an application",
)
def get_application_evaluation(application_id: UUID, evaluations: EvaluationsDep) -> EvaluationView:
    try:
        return EvaluationView.from_record(evaluations.get_by_application(application_id))
    except RecruitingError as exc:
        raise not_found(str(exc)) from exc


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=EvaluationView,
    summary="Evaluation by id",
)
def get_evaluation(evaluation_id: UUID, evaluations: EvaluationsDep) -> EvaluationView:
    try:
        return EvaluationView.from_record(evaluations.get(evaluation_id))
    except RecruitingError as exc:
        raise not_found(str(exc)) from exc


@router.get(
    "/evaluations/{evaluation_id}/overrides",
    response_model=list[OverrideView],
    summary="Override history (append-only)",
)
def list_overrides(evaluation_id: UUID, evaluations: EvaluationsDep) -> list[OverrideView]:
    try:
        overrides = evaluations.list_overrides(evaluation_id)
    except RecruitingError as exc:
        raise not_found(str(exc)) from exc
    return [OverrideView.from_model(item) for item in overrides]


@router.post(
    "/evaluations/{evaluation_id}/overrides",
    status_code=status.HTTP_201_CREATED,
    response_model=AuditReceipt,
    summary="Human-in-the-loop override (mandatory for gated rejections)",
    dependencies=[Depends(require_permission(Permission.RECRUITING_OVERRIDE))],
)
def record_override(
    evaluation_id: UUID, payload: OverrideCreate, evaluations: EvaluationsDep, actor: ActorDep
) -> AuditReceipt:
    try:
        outcome = evaluations.record_override(
            evaluation_id,
            actor=actor,
            reviewer_role=payload.reviewer_role,
            override_decision=payload.override_decision,
            reason_code=payload.reason_code,
            notes=payload.notes,
        )
    except RecruitingError as exc:
        message = str(exc)
        if message.startswith("unknown evaluation"):
            raise not_found(message) from exc
        raise domain_problem(exc) from exc
    return AuditReceipt.from_entry(outcome.receipt)
