"""Onboarding API router — templates, plans, and step progress."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.deps import require_permission
from hr_agents.api.onboarding_schemas import (
    PlanStartRequest,
    PlanView,
    StepActionRequest,
    StepLinkDocumentRequest,
    StepWaiveRequest,
    TemplateCreate,
    TemplateDraftView,
    TemplateView,
)
from hr_agents.rbac import Permission
from hr_agents.services.onboarding import (
    OnboardingActorError,
    OnboardingError,
    OnboardingService,
    default_engineering_template,
)

router = APIRouter(
    prefix="/v1/onboarding",
    tags=["onboarding"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)


def get_onboarding(request: Request) -> OnboardingService:
    return request.app.state.onboarding


OnboardingDep = Annotated[OnboardingService, Depends(get_onboarding)]


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _map(exc: OnboardingError) -> HTTPException:
    """Actor problems are 403; everything else the service refuses is a 409."""
    if isinstance(exc, OnboardingActorError):
        return _forbidden(str(exc))
    return _conflict(exc)


@router.post("/templates", status_code=status.HTTP_201_CREATED, response_model=TemplateView)
def create_template(payload: TemplateCreate, onboarding: OnboardingDep) -> TemplateView:
    try:
        template = onboarding.create_template(
            name=payload.name,
            description=payload.description,
            steps=[step.to_model() for step in payload.steps],
            created_by=payload.created_by,
            applies_to_contract_types=payload.applies_to_contract_types,
            applies_to_roles=payload.applies_to_roles,
        )
    except (ValueError, OnboardingError) as exc:
        raise _conflict(exc) from exc
    return TemplateView.from_model(template)


@router.get("/templates", response_model=list[TemplateView])
def list_templates(onboarding: OnboardingDep) -> list[TemplateView]:
    return [TemplateView.from_model(t) for t in onboarding.list_templates()]


@router.get("/templates/default", response_model=TemplateDraftView)
def default_template() -> TemplateDraftView:
    """The built-in starter checklist, ready to save as the operator's first template.

    Served from the domain so the client never retypes the steps; creating a
    template from it stays an explicit, named action.
    """
    return TemplateDraftView.from_model(default_engineering_template())


@router.post("/plans", status_code=status.HTTP_201_CREATED, response_model=PlanView)
def start_plan(payload: PlanStartRequest, onboarding: OnboardingDep) -> PlanView:
    try:
        plan = onboarding.start_plan(
            employee_id=payload.employee_id,
            created_by=payload.created_by,
            template_id=payload.template_id,
        )
    except OnboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.get("/plans", response_model=list[PlanView])
def list_plans(onboarding: OnboardingDep, active_only: bool = False) -> list[PlanView]:
    plans = onboarding.active_plans() if active_only else list(onboarding._plans.values())
    return [PlanView.from_model(plan) for plan in plans]


@router.get("/plans/{plan_id}", response_model=PlanView)
def get_plan(plan_id: UUID, onboarding: OnboardingDep) -> PlanView:
    try:
        return PlanView.from_model(onboarding.get_plan(plan_id))
    except OnboardingError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/plans/{plan_id}/steps/{step_key}/complete", response_model=PlanView)
def complete_step(
    plan_id: UUID, step_key: str, payload: StepActionRequest, onboarding: OnboardingDep
) -> PlanView:
    try:
        plan = onboarding.complete_step(plan_id, step_key, by=payload.by, note=payload.note)
    except OnboardingError as exc:
        raise _map(exc) from exc
    return PlanView.from_model(plan)


@router.post("/plans/{plan_id}/steps/{step_key}/waive", response_model=PlanView)
def waive_step(
    plan_id: UUID, step_key: str, payload: StepWaiveRequest, onboarding: OnboardingDep
) -> PlanView:
    try:
        plan = onboarding.waive_step(plan_id, step_key, by=payload.by, reason=payload.reason)
    except OnboardingError as exc:
        raise _map(exc) from exc
    return PlanView.from_model(plan)


@router.post("/plans/{plan_id}/steps/{step_key}/link-document", response_model=PlanView)
def link_document(
    plan_id: UUID,
    step_key: str,
    payload: StepLinkDocumentRequest,
    onboarding: OnboardingDep,
    request: Request,
) -> PlanView:
    people = request.app.state.people
    document = people.employees.get_document(payload.document_id)
    if document is None:
        raise _not_found(f"unknown document {payload.document_id}")
    try:
        plan = onboarding.link_document(
            plan_id, step_key, document=document, linked_by=payload.linked_by
        )
    except OnboardingError as exc:
        raise _conflict(exc) from exc
    return PlanView.from_model(plan)


@router.get("/plans/{plan_id}/document-status")
def document_status(plan_id: UUID, onboarding: OnboardingDep) -> dict[str, str]:
    try:
        return onboarding.document_step_status(plan_id)
    except OnboardingError as exc:
        raise _not_found(str(exc)) from exc
