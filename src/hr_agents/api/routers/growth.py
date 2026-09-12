"""Growth API router — review cycles, forms, summaries, goals, reminders."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from hr_agents.api.deps import require_permission
from hr_agents.api.growth_schemas import (
    AssignmentCreate,
    AssignmentSkip,
    AssignmentSubmit,
    AssignmentView,
    ByActor,
    CycleAction,
    CycleCreate,
    CycleView,
    GoalAction,
    GoalCreate,
    GoalProgress,
    GoalView,
    RemindersRun,
    ReminderView,
    SummaryDraft,
    SummaryFinalize,
    SummaryView,
)
from hr_agents.models import GoalStatus, ReviewCycleStatus
from hr_agents.rbac import Permission
from hr_agents.services.growth import GrowthError, GrowthService

router = APIRouter(
    prefix="/v1/growth",
    tags=["growth"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)


def get_growth(request: Request) -> GrowthService:
    return request.app.state.growth


GrowthDep = Annotated[GrowthService, Depends(get_growth)]


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# --- cycles -----------------------------------------------------------------


@router.post("/cycles", status_code=status.HTTP_201_CREATED, response_model=CycleView)
def create_cycle(payload: CycleCreate, growth: GrowthDep) -> CycleView:
    try:
        cycle = growth.create_cycle(**payload.model_dump())
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return CycleView.from_model(cycle)


@router.get("/cycles", response_model=list[CycleView])
def list_cycles(
    growth: GrowthDep, cycle_status: ReviewCycleStatus | None = None
) -> list[CycleView]:
    return [CycleView.from_model(item) for item in growth.list_cycles(status=cycle_status)]


@router.get("/cycles/{cycle_id}", response_model=CycleView)
def get_cycle(cycle_id: UUID, growth: GrowthDep) -> CycleView:
    try:
        return CycleView.from_model(growth.get_cycle(cycle_id))
    except GrowthError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/cycles/{cycle_id}/activate", response_model=CycleView)
def activate_cycle(cycle_id: UUID, payload: CycleAction, growth: GrowthDep) -> CycleView:
    try:
        cycle = growth.activate_cycle(cycle_id, by=payload.by)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return CycleView.from_model(cycle)


@router.post("/cycles/{cycle_id}/reviewing", response_model=CycleView)
def advance_cycle(cycle_id: UUID, payload: CycleAction, growth: GrowthDep) -> CycleView:
    try:
        cycle = growth.advance_to_reviewing(cycle_id, by=payload.by)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return CycleView.from_model(cycle)


@router.post("/cycles/{cycle_id}/close", response_model=CycleView)
def close_cycle(cycle_id: UUID, payload: CycleAction, growth: GrowthDep) -> CycleView:
    try:
        cycle = growth.close_cycle(cycle_id, by=payload.by)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return CycleView.from_model(cycle)


@router.post("/cycles/{cycle_id}/cancel", response_model=CycleView)
def cancel_cycle(cycle_id: UUID, payload: CycleAction, growth: GrowthDep) -> CycleView:
    if not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="cancelling a cycle requires a reason",
        )
    try:
        cycle = growth.cancel_cycle(cycle_id, by=payload.by, reason=payload.reason)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return CycleView.from_model(cycle)


# --- assignments ---------------------------------------------------------------


@router.post(
    "/cycles/{cycle_id}/assignments",
    status_code=status.HTTP_201_CREATED,
    response_model=AssignmentView,
)
def add_assignment(cycle_id: UUID, payload: AssignmentCreate, growth: GrowthDep) -> AssignmentView:
    try:
        assignment = growth.add_assignment(
            cycle_id,
            employee_id=payload.employee_id,
            reviewer_id=payload.reviewer_id,
            created_by=payload.created_by,
            reviewer_role=payload.reviewer_role,
            due_on=payload.due_on,
        )
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return AssignmentView.from_model(assignment)


@router.get("/cycles/{cycle_id}/assignments", response_model=list[AssignmentView])
def list_assignments(cycle_id: UUID, growth: GrowthDep) -> list[AssignmentView]:
    try:
        growth.get_cycle(cycle_id)
    except GrowthError as exc:
        raise _not_found(str(exc)) from exc
    return [AssignmentView.from_model(item) for item in growth.list_assignments(cycle_id)]


@router.get("/assignments", response_model=list[AssignmentView])
def assignments_for_reviewer(
    growth: GrowthDep, reviewer_id: Annotated[str, Query(min_length=1)]
) -> list[AssignmentView]:
    return [
        AssignmentView.from_model(item) for item in growth.assignments_for_reviewer(reviewer_id)
    ]


@router.post("/assignments/{assignment_id}/submit", response_model=AssignmentView)
def submit_assignment(
    assignment_id: UUID, payload: AssignmentSubmit, growth: GrowthDep
) -> AssignmentView:
    try:
        assignment = growth.submit_assignment(
            assignment_id, by=payload.by, ratings=payload.ratings, comments=payload.comments
        )
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return AssignmentView.from_model(assignment)


@router.post("/assignments/{assignment_id}/skip", response_model=AssignmentView)
def skip_assignment(
    assignment_id: UUID, payload: AssignmentSkip, growth: GrowthDep
) -> AssignmentView:
    try:
        assignment = growth.skip_assignment(assignment_id, by=payload.by, reason=payload.reason)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return AssignmentView.from_model(assignment)


# --- summaries -----------------------------------------------------------------


@router.post("/summaries", status_code=status.HTTP_201_CREATED, response_model=SummaryView)
def draft_summary(payload: SummaryDraft, growth: GrowthDep) -> SummaryView:
    try:
        summary = growth.draft_summary(
            payload.cycle_id,
            payload.employee_id,
            draft_text=payload.draft_text,
            drafted_by=payload.drafted_by,
        )
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return SummaryView.from_model(summary)


@router.get("/summaries/{summary_id}", response_model=SummaryView)
def get_summary(summary_id: UUID, growth: GrowthDep) -> SummaryView:
    try:
        return SummaryView.from_model(growth.get_summary(summary_id))
    except GrowthError as exc:
        raise _not_found(str(exc)) from exc


@router.get("/cycles/{cycle_id}/summaries", response_model=list[SummaryView])
def list_summaries(cycle_id: UUID, growth: GrowthDep) -> list[SummaryView]:
    try:
        growth.get_cycle(cycle_id)
    except GrowthError as exc:
        raise _not_found(str(exc)) from exc
    return [SummaryView.from_model(item) for item in growth.list_summaries(cycle_id)]


@router.post("/summaries/{summary_id}/finalize", response_model=SummaryView)
def finalize_summary(summary_id: UUID, payload: SummaryFinalize, growth: GrowthDep) -> SummaryView:
    try:
        summary = growth.finalize_summary(summary_id, by=payload.by, final_text=payload.final_text)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return SummaryView.from_model(summary)


# --- goals ----------------------------------------------------------------------


@router.post("/goals", status_code=status.HTTP_201_CREATED, response_model=GoalView)
def create_goal(payload: GoalCreate, growth: GrowthDep) -> GoalView:
    try:
        goal = growth.create_goal(**payload.model_dump())
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return GoalView.from_model(goal)


@router.get("/goals", response_model=list[GoalView])
def list_goals(
    growth: GrowthDep,
    employee_id: UUID | None = None,
    goal_status: GoalStatus | None = None,
) -> list[GoalView]:
    goals = growth.list_goals(employee_id=employee_id, status=goal_status)
    return [GoalView.from_model(item) for item in goals]


@router.get("/goals/overdue", response_model=list[GoalView])
def overdue_goals(growth: GrowthDep) -> list[GoalView]:
    return [GoalView.from_model(item) for item in growth.overdue_goals()]


@router.get("/goals/{goal_id}", response_model=GoalView)
def get_goal(goal_id: UUID, growth: GrowthDep) -> GoalView:
    try:
        return GoalView.from_model(growth.get_goal(goal_id))
    except GrowthError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/goals/{goal_id}/activate", response_model=GoalView)
def activate_goal(goal_id: UUID, payload: ByActor, growth: GrowthDep) -> GoalView:
    try:
        goal = growth.activate_goal(goal_id, by=payload.by)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return GoalView.from_model(goal)


@router.post("/goals/{goal_id}/progress", response_model=GoalView)
def update_goal_progress(goal_id: UUID, payload: GoalProgress, growth: GrowthDep) -> GoalView:
    try:
        goal = growth.update_progress(
            goal_id, percent=payload.percent, by=payload.by, note=payload.note
        )
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return GoalView.from_model(goal)


@router.post("/goals/{goal_id}/complete", response_model=GoalView)
def complete_goal(goal_id: UUID, payload: GoalAction, growth: GrowthDep) -> GoalView:
    try:
        goal = growth.complete_goal(goal_id, by=payload.by, note=payload.note)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return GoalView.from_model(goal)


@router.post("/goals/{goal_id}/cancel", response_model=GoalView)
def cancel_goal(goal_id: UUID, payload: GoalAction, growth: GrowthDep) -> GoalView:
    if not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="cancelling a goal requires a reason",
        )
    try:
        goal = growth.cancel_goal(goal_id, by=payload.by, reason=payload.reason)
    except GrowthError as exc:
        raise _conflict(exc) from exc
    return GoalView.from_model(goal)


# --- reminders -------------------------------------------------------------------


@router.post("/reminders/run", response_model=list[ReminderView])
def run_reminders(payload: RemindersRun, growth: GrowthDep) -> list[ReminderView]:
    created = growth.run_reminders(as_of=payload.as_of, window_days=payload.window_days)
    return [ReminderView.from_model(item) for item in created]
