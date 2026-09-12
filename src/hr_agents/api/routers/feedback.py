"""Candidate-facing feedback endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from hr_agents.api.deps import require_permission
from hr_agents.api.recruitment_schemas import FeedbackView
from hr_agents.rbac import Permission
from hr_agents.services.recruiting import EvaluationService, RecruitingError

router = APIRouter(
    prefix="/v1/candidates",
    tags=["feedback"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)


def get_evaluations(request: Request) -> EvaluationService:
    return request.app.state.recruiting.evaluations


EvaluationsDep = Annotated[EvaluationService, Depends(get_evaluations)]


@router.get(
    "/{candidate_id}/feedback",
    response_model=FeedbackView,
    summary="Candidate-facing feedback report",
)
def get_feedback(
    candidate_id: UUID,
    evaluations: EvaluationsDep,
    language: Annotated[str, Query(pattern="^(en|id)$")] = "en",
) -> FeedbackView:
    try:
        report = evaluations.feedback_for(candidate_id, language=language)
    except RecruitingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FeedbackView.from_report(candidate_id, report, generated_at=datetime.now(UTC))
