"""Evaluation read endpoints and append-only human overrides."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.deps import require_permission
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


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/applications/{application_id}/evaluation",
    response_model=EvaluationView,
    summary="Deterministic evaluation result for an application",
)
def get_application_evaluation(application_id: UUID, evaluations: EvaluationsDep) -> EvaluationView:
    try:
        return EvaluationView.from_record(evaluations.get_by_application(application_id))
    except RecruitingError as exc:
        raise _not_found(str(exc)) from exc


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=EvaluationView,
    summary="Evaluation by id",
)
def get_evaluation(evaluation_id: UUID, evaluations: EvaluationsDep) -> EvaluationView:
    try:
        return EvaluationView.from_record(evaluations.get(evaluation_id))
    except RecruitingError as exc:
        raise _not_found(str(exc)) from exc


@router.get(
    "/evaluations/{evaluation_id}/overrides",
    response_model=list[OverrideView],
    summary="Override history (append-only)",
)
def list_overrides(evaluation_id: UUID, evaluations: EvaluationsDep) -> list[OverrideView]:
    try:
        overrides = evaluations.list_overrides(evaluation_id)
    except RecruitingError as exc:
        raise _not_found(str(exc)) from exc
    return [OverrideView.from_model(item) for item in overrides]


@router.post(
    "/evaluations/{evaluation_id}/overrides",
    status_code=status.HTTP_201_CREATED,
    response_model=AuditReceipt,
    summary="Human-in-the-loop override (mandatory for gated rejections)",
    dependencies=[Depends(require_permission(Permission.RECRUITING_OVERRIDE))],
)
def record_override(
    evaluation_id: UUID, payload: OverrideCreate, evaluations: EvaluationsDep
) -> AuditReceipt:
    try:
        outcome = evaluations.record_override(
            evaluation_id,
            reviewer_id=payload.reviewer_id,
            reviewer_role=payload.reviewer_role,
            override_decision=payload.override_decision,
            reason_code=payload.reason_code,
            notes=payload.notes,
        )
    except RecruitingError as exc:
        message = str(exc)
        if message.startswith("unknown evaluation"):
            raise _not_found(message) from exc
        if "named human" in message or "cannot override" in message:
            raise _forbidden(message) from exc
        raise _conflict(exc) from exc
    return AuditReceipt.from_entry(outcome.receipt)
