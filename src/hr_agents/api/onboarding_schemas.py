"""Onboarding API schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from hr_agents.models import (
    ApproverRole,
    ContractType,
    DocumentKind,
    OnboardingPlan,
    OnboardingStepState,
    OnboardingTemplate,
    StepKind,
    StepStatus,
    StrictModel,
    TemplateStep,
)


class TemplateStepInput(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    kind: StepKind
    description: str = Field(default="", max_length=1000)
    document_kind: DocumentKind | None = None
    assignee_role: ApproverRole = ApproverRole.HR_ADMIN
    due_days_after_hire: int | None = Field(default=None, ge=-30, le=365)
    required: bool = True
    requires_human_signoff: bool = False

    def to_model(self) -> TemplateStep:
        return TemplateStep(**self.model_dump())


class TemplateCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    steps: list[TemplateStepInput] = Field(min_length=1)
    applies_to_contract_types: list[ContractType] = Field(default_factory=list)
    applies_to_roles: list[str] = Field(default_factory=list)


class TemplateView(StrictModel):
    id: UUID
    name: str
    description: str
    active: bool
    applies_to_contract_types: list[ContractType]
    applies_to_roles: list[str]
    step_count: int

    @classmethod
    def from_model(cls, template: OnboardingTemplate) -> TemplateView:
        return cls(
            id=template.id,
            name=template.name,
            description=template.description,
            active=template.active,
            applies_to_contract_types=template.applies_to_contract_types,
            applies_to_roles=template.applies_to_roles,
            step_count=len(template.steps),
        )


class PlanStartRequest(StrictModel):
    employee_id: UUID
    created_by: str = Field(min_length=1, max_length=200)
    template_id: UUID | None = None


class StepActionRequest(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class StepWaiveRequest(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)


class StepLinkDocumentRequest(StrictModel):
    document_id: UUID
    linked_by: str = Field(min_length=1, max_length=200)


class StepView(StrictModel):
    key: str
    title: str
    kind: StepKind
    required: bool
    requires_human_signoff: bool
    assignee_role: ApproverRole
    status: StepStatus
    document_kind: DocumentKind | None
    due_on: date | None
    is_overdue: bool
    linked_document_id: UUID | None
    linked_task_id: UUID | None

    @classmethod
    def from_model(cls, step: OnboardingStepState) -> StepView:
        return cls(
            key=step.key,
            title=step.title,
            kind=step.kind,
            required=step.required,
            requires_human_signoff=step.requires_human_signoff,
            assignee_role=step.assignee_role,
            status=step.status,
            document_kind=step.document_kind,
            due_on=step.due_on,
            is_overdue=step.is_overdue,
            linked_document_id=step.linked_document_id,
            linked_task_id=step.linked_task_id,
        )


class PlanView(StrictModel):
    id: UUID
    employee_id: UUID
    template_id: UUID
    template_name: str
    template_version_hash: str
    progress: float
    is_complete: bool
    started_at: datetime
    completed_at: datetime | None
    steps: list[StepView]
    blockers: list[str]

    @classmethod
    def from_model(cls, plan: OnboardingPlan) -> PlanView:
        return cls(
            id=plan.id,
            employee_id=plan.employee_id,
            template_id=plan.template_id,
            template_name=plan.template_name,
            template_version_hash=plan.template_version_hash,
            progress=plan.progress,
            is_complete=plan.is_complete,
            started_at=plan.started_at,
            completed_at=plan.completed_at,
            steps=[StepView.from_model(step) for step in plan.steps],
            blockers=[step.key for step in plan.blockers()],
        )
