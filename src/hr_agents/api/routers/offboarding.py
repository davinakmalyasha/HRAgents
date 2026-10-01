"""Offboarding API router — exit checklists, assets, handover, final pay."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.deps import ActorDep, require_permission
from hr_agents.api.offboarding_schemas import (
    AssetCreate,
    AssetMissing,
    AssetReturn,
    AssetView,
    AssetWriteOff,
    ExitInterviewSchedule,
    HandoverCreate,
    PlanAction,
    PlanCreate,
    PlanView,
    StepAction,
    TemplateCreate,
    TemplateView,
)
from hr_agents.rbac import Permission
from hr_agents.services.offboarding import (
    OffboardingError,
    OffboardingService,
    default_offboarding_template,
)

router = APIRouter(
    prefix="/v1/offboarding",
    tags=["offboarding"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)


def get_offboarding(request: Request) -> OffboardingService:
    return request.app.state.offboarding


OffboardingDep = Annotated[OffboardingService, Depends(get_offboarding)]


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# --- templates ----------------------------------------------------------------


@router.get("/templates/default", response_model=TemplateView)
def default_template() -> TemplateView:
    return TemplateView.from_model(default_offboarding_template())


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def create_template(
    payload: TemplateCreate, offboarding: OffboardingDep, actor: ActorDep
) -> TemplateView:
    template = offboarding.create_template(
        name=payload.name,
        steps=payload.to_steps(),
        actor=actor,
        description=payload.description,
        applies_to_reasons=payload.applies_to_reasons,
        applies_to_roles=payload.applies_to_roles,
    )
    return TemplateView.from_model(template)


@router.get("/templates", response_model=list[TemplateView])
def list_templates(offboarding: OffboardingDep) -> list[TemplateView]:
    return [TemplateView.from_model(item) for item in offboarding.list_templates()]


@router.get("/templates/{template_id}", response_model=TemplateView)
def get_template(template_id: UUID, offboarding: OffboardingDep) -> TemplateView:
    try:
        return TemplateView.from_model(offboarding.get_template(template_id))
    except OffboardingError as exc:
        raise _not_found(str(exc)) from exc


# --- plans ----------------------------------------------------------------------


@router.post(
    "/plans",
    status_code=status.HTTP_201_CREATED,
    response_model=PlanView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def start_plan(payload: PlanCreate, offboarding: OffboardingDep, actor: ActorDep) -> PlanView:
    try:
        plan = offboarding.start_plan(
            employee_id=payload.employee_id,
            reason=payload.reason,
            last_working_day=payload.last_working_day,
            actor=actor,
            template_id=payload.template_id,
        )
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.get("/plans", response_model=list[PlanView])
def list_plans(offboarding: OffboardingDep) -> list[PlanView]:
    return [PlanView.from_model(item) for item in offboarding.active_plans()]


@router.get("/plans/{plan_id}", response_model=PlanView)
def get_plan(plan_id: UUID, offboarding: OffboardingDep) -> PlanView:
    try:
        return PlanView.from_model(offboarding.get_plan(plan_id))
    except OffboardingError as exc:
        raise _not_found(str(exc)) from exc


@router.get("/employees/{employee_id}/plans", response_model=list[PlanView])
def plans_for_employee(employee_id: UUID, offboarding: OffboardingDep) -> list[PlanView]:
    return [PlanView.from_model(item) for item in offboarding.plans_for_employee(employee_id)]


@router.post(
    "/plans/{plan_id}/steps/{step_key}/complete",
    response_model=PlanView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def complete_step(
    plan_id: UUID,
    step_key: str,
    payload: StepAction,
    offboarding: OffboardingDep,
    actor: ActorDep,
) -> PlanView:
    try:
        plan = offboarding.complete_step(plan_id, step_key, actor=actor, note=payload.note)
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.post(
    "/plans/{plan_id}/steps/{step_key}/waive",
    response_model=PlanView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def waive_step(
    plan_id: UUID,
    step_key: str,
    payload: StepAction,
    offboarding: OffboardingDep,
    actor: ActorDep,
) -> PlanView:
    if not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="waiving a step requires a reason",
        )
    try:
        plan = offboarding.waive_step(plan_id, step_key, actor=actor, reason=payload.reason)
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.post(
    "/plans/{plan_id}/exit-interview",
    response_model=PlanView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def schedule_exit_interview(
    plan_id: UUID,
    payload: ExitInterviewSchedule,
    offboarding: OffboardingDep,
    actor: ActorDep,
) -> PlanView:
    try:
        plan = offboarding.schedule_exit_interview(
            plan_id, scheduled_for=payload.scheduled_for, actor=actor
        )
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.post(
    "/plans/{plan_id}/handover",
    response_model=PlanView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def add_handover(
    plan_id: UUID, payload: HandoverCreate, offboarding: OffboardingDep, actor: ActorDep
) -> PlanView:
    try:
        plan = offboarding.add_handover_note(plan_id, content=payload.content, actor=actor)
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.post(
    "/plans/{plan_id}/final-pay",
    response_model=PlanView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def coordinate_final_pay(
    plan_id: UUID,
    payload: PlanAction,
    offboarding: OffboardingDep,
    actor: ActorDep,
) -> PlanView:
    try:
        plan = offboarding.coordinate_final_pay(plan_id, actor=actor)
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.post(
    "/plans/{plan_id}/complete",
    response_model=PlanView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def complete_plan(
    plan_id: UUID, payload: PlanAction, offboarding: OffboardingDep, actor: ActorDep
) -> PlanView:
    try:
        plan = offboarding.complete_plan(plan_id, actor=actor)
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.post(
    "/plans/{plan_id}/finalize-employee",
    response_model=PlanView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def finalize_employee(
    plan_id: UUID, payload: PlanAction, offboarding: OffboardingDep, actor: ActorDep
) -> PlanView:
    try:
        offboarding.finalize_employee_exit(plan_id, actor=actor)
        plan = offboarding.get_plan(plan_id)
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


# --- assets ----------------------------------------------------------------------


@router.post(
    "/assets",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def register_asset(payload: AssetCreate, offboarding: OffboardingDep, actor: ActorDep) -> AssetView:
    try:
        asset = offboarding.register_asset(actor=actor, **payload.model_dump())
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return AssetView.from_model(asset)


@router.get("/assets", response_model=list[AssetView])
def list_assets(
    offboarding: OffboardingDep,
    employee_id: UUID | None = None,
    plan_id: UUID | None = None,
) -> list[AssetView]:
    assets = offboarding.list_assets(employee_id=employee_id, plan_id=plan_id)
    return [AssetView.from_model(item) for item in assets]


@router.get("/employees/{employee_id}/assets", response_model=list[AssetView])
def employee_assets(employee_id: UUID, offboarding: OffboardingDep) -> list[AssetView]:
    return [AssetView.from_model(item) for item in offboarding.list_assets(employee_id=employee_id)]


@router.get("/employees/{employee_id}/clearance", response_model=list[AssetView])
def asset_clearance(employee_id: UUID, offboarding: OffboardingDep) -> list[AssetView]:
    """Assets that still block exit clearance for this employee."""
    return [AssetView.from_model(item) for item in offboarding.asset_clearance(employee_id)]


@router.post(
    "/assets/{asset_id}/return",
    response_model=AssetView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def return_asset(
    asset_id: UUID, payload: AssetReturn, offboarding: OffboardingDep, actor: ActorDep
) -> AssetView:
    try:
        asset = offboarding.mark_asset_returned(
            asset_id, actor=actor, note=payload.note, returned_on=payload.returned_on
        )
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return AssetView.from_model(asset)


@router.post(
    "/assets/{asset_id}/missing",
    response_model=AssetView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def mark_asset_missing(
    asset_id: UUID,
    payload: AssetMissing,
    offboarding: OffboardingDep,
    actor: ActorDep,
) -> AssetView:
    try:
        asset = offboarding.mark_asset_missing(asset_id, actor=actor, note=payload.note)
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return AssetView.from_model(asset)


@router.post(
    "/assets/{asset_id}/write-off",
    response_model=AssetView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def write_off_asset(
    asset_id: UUID,
    payload: AssetWriteOff,
    offboarding: OffboardingDep,
    actor: ActorDep,
) -> AssetView:
    try:
        asset = offboarding.write_off_asset(asset_id, actor=actor, reason=payload.reason)
    except OffboardingError as exc:
        raise _conflict(exc) from exc
    return AssetView.from_model(asset)
