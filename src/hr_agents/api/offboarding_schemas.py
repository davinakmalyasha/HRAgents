"""Offboarding API schemas."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field

from hr_agents.models import (
    ApproverRole,
    AssetStatus,
    DocumentKind,
    HandoverNote,
    OffboardingAsset,
    OffboardingPlan,
    OffboardingReason,
    OffboardingStepKind,
    OffboardingStepState,
    OffboardingTemplate,
    OffboardingTemplateStep,
    StepStatus,
    StrictModel,
    UtcDateTime,
)

# --- templates -----------------------------------------------------------------


class TemplateStepView(StrictModel):
    key: str
    title: str
    kind: OffboardingStepKind
    description: str
    document_kind: DocumentKind | None
    assignee_role: ApproverRole
    due_days_before_last_day: int | None
    required: bool
    requires_human_signoff: bool

    @classmethod
    def from_model(cls, step: OffboardingTemplateStep) -> TemplateStepView:
        return cls(**step.model_dump())


class TemplateView(StrictModel):
    id: UUID
    name: str
    description: str
    applies_to_reasons: list[OffboardingReason]
    applies_to_roles: list[str]
    steps: list[TemplateStepView]
    active: bool

    @classmethod
    def from_model(cls, template: OffboardingTemplate) -> TemplateView:
        return cls(
            id=template.id,
            name=template.name,
            description=template.description,
            applies_to_reasons=template.applies_to_reasons,
            applies_to_roles=template.applies_to_roles,
            steps=[TemplateStepView.from_model(step) for step in template.steps],
            active=template.active,
        )


class TemplateCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    steps: list[TemplateStepView] = Field(min_length=1)
    created_by: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    applies_to_reasons: list[OffboardingReason] = Field(default_factory=list)
    applies_to_roles: list[str] = Field(default_factory=list)

    def to_steps(self) -> list[OffboardingTemplateStep]:
        return [OffboardingTemplateStep(**step.model_dump()) for step in self.steps]


# --- plans ----------------------------------------------------------------------


class PlanCreate(StrictModel):
    employee_id: UUID
    reason: OffboardingReason
    last_working_day: date
    created_by: str = Field(min_length=1, max_length=200)
    template_id: UUID | None = None


class PlanAction(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class StepAction(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=1000)


class ExitInterviewSchedule(StrictModel):
    scheduled_for: UtcDateTime
    by: str = Field(min_length=1, max_length=200)


class HandoverCreate(StrictModel):
    content: str = Field(min_length=1, max_length=8000)
    authored_by: str = Field(min_length=1, max_length=200)


class StepView(StrictModel):
    key: str
    title: str
    kind: OffboardingStepKind
    required: bool
    requires_human_signoff: bool
    assignee_role: ApproverRole
    status: StepStatus
    document_kind: DocumentKind | None
    due_on: date | None
    linked_task_id: UUID | None
    scheduled_for: UtcDateTime | None
    completed_by: str | None
    completed_at: UtcDateTime | None
    note: str | None

    @classmethod
    def from_model(cls, step: OffboardingStepState) -> StepView:
        return cls(**step.model_dump())


class HandoverView(StrictModel):
    id: UUID
    content: str
    authored_by: str
    created_at: UtcDateTime

    @classmethod
    def from_model(cls, note: HandoverNote) -> HandoverView:
        return cls(**note.model_dump())


class PlanView(StrictModel):
    id: UUID
    employee_id: UUID
    reason: OffboardingReason
    last_working_day: date
    template_id: UUID
    template_name: str
    steps: list[StepView]
    handover_notes: list[HandoverView]
    final_pay_run_id: UUID | None
    progress: float
    is_complete: bool
    started_at: UtcDateTime
    completed_at: UtcDateTime | None

    @classmethod
    def from_model(cls, plan: OffboardingPlan) -> PlanView:
        return cls(
            id=plan.id,
            employee_id=plan.employee_id,
            reason=plan.reason,
            last_working_day=plan.last_working_day,
            template_id=plan.template_id,
            template_name=plan.template_name,
            steps=[StepView.from_model(step) for step in plan.steps],
            handover_notes=[HandoverView.from_model(note) for note in plan.handover_notes],
            final_pay_run_id=plan.final_pay_run_id,
            progress=plan.progress,
            is_complete=plan.completed_at is not None,
            started_at=plan.started_at,
            completed_at=plan.completed_at,
        )


# --- assets ---------------------------------------------------------------------


class AssetCreate(StrictModel):
    employee_id: UUID
    name: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    plan_id: UUID | None = None
    asset_code: str | None = Field(default=None, max_length=80)
    category: str = Field(default="", max_length=80)
    assigned_on: date | None = None


class AssetReturn(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    returned_on: date | None = None


class AssetMissing(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=1000)


class AssetWriteOff(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)


class AssetView(StrictModel):
    id: UUID
    employee_id: UUID
    plan_id: UUID | None
    name: str
    asset_code: str | None
    category: str
    assigned_on: date | None
    status: AssetStatus
    returned_on: date | None
    returned_by: str | None
    note: str | None
    blocks_clearance: bool

    @classmethod
    def from_model(cls, asset: OffboardingAsset) -> AssetView:
        return cls(
            id=asset.id,
            employee_id=asset.employee_id,
            plan_id=asset.plan_id,
            name=asset.name,
            asset_code=asset.asset_code,
            category=asset.category,
            assigned_on=asset.assigned_on,
            status=asset.status,
            returned_on=asset.returned_on,
            returned_by=asset.returned_by,
            note=asset.note,
            blocks_clearance=asset.blocks_clearance,
        )
