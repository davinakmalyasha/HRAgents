"""Offboarding domain models — template-driven exit checklists.

Mirrors the onboarding design with exit-specific steps. Rules encoded here:

- **Humans complete steps.** Agents may chase, remind, and prepare, but step
  completion/sign-off and asset write-offs require a named human.
- **Assets block completion until cleared.** ASSIGNED and MISSING assets are
  clearance blockers; a MISSING asset needs a human write-off with a reason.
- **Final pay is coordinated, never executed.** The plan links to a FINAL
  payroll run (prepare/verify only); payments stay outside the system.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.approval import ApproverRole
from hr_agents.models.common import StrictModel, UtcDateTime, utc_now
from hr_agents.models.employee import DocumentKind
from hr_agents.models.onboarding import StepStatus


class OffboardingReason(StrEnum):
    RESIGNATION = "resignation"
    TERMINATION = "termination"
    CONTRACT_END = "contract_end"
    RETIREMENT = "retirement"
    OTHER = "other"


class OffboardingStepKind(StrEnum):
    TASK = "task"
    DOCUMENT = "document"  # collect/return a document
    ASSET_RETURN = "asset_return"
    ACCOUNT_CLOSURE = "account_closure"
    EXIT_INTERVIEW = "exit_interview"
    HANDOVER = "handover"
    FINAL_PAY = "final_pay"
    APPROVAL = "approval"
    CONFIRMATION = "confirmation"


class OffboardingTemplateStep(StrictModel):
    """One step definition inside an offboarding template."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    kind: OffboardingStepKind
    description: str = Field(default="", max_length=1000)

    document_kind: DocumentKind | None = None
    assignee_role: ApproverRole = ApproverRole.HR_ADMIN
    due_days_before_last_day: int | None = Field(
        default=None,
        ge=0,
        le=365,
        description="Days before the last working day when this step is due.",
    )
    required: bool = True
    requires_human_signoff: bool = False

    @model_validator(mode="after")
    def _validate(self) -> OffboardingTemplateStep:
        if self.kind is OffboardingStepKind.DOCUMENT and self.document_kind is None:
            raise ValueError(f"step {self.key!r}: DOCUMENT steps require document_kind")
        if self.kind is not OffboardingStepKind.DOCUMENT and self.document_kind is not None:
            raise ValueError(f"step {self.key!r}: document_kind only applies to DOCUMENT steps")
        return self


class OffboardingTemplate(StrictModel):
    """A reusable exit checklist (e.g., 'Resignation — standard')."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)

    applies_to_reasons: list[OffboardingReason] = Field(default_factory=list)
    applies_to_roles: list[str] = Field(default_factory=list)
    steps: list[OffboardingTemplateStep] = Field(min_length=1)

    active: bool = True
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _unique_keys(self) -> OffboardingTemplate:
        keys = [step.key for step in self.steps]
        if len(keys) != len(set(keys)):
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            raise ValueError(f"duplicate step keys: {', '.join(duplicates)}")
        return self

    def matches(self, *, reason: OffboardingReason, role_text: str | None = None) -> bool:
        if not self.active:
            return False
        if self.applies_to_reasons and reason not in self.applies_to_reasons:
            return False
        if self.applies_to_roles and role_text:
            haystack = role_text.lower()
            if not any(role.lower() in haystack for role in self.applies_to_roles):
                return False
        return True


class OffboardingStepState(StrictModel):
    """Per-employee state of one exit step."""

    key: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    kind: OffboardingStepKind
    required: bool
    requires_human_signoff: bool
    assignee_role: ApproverRole

    status: StepStatus = StepStatus.PENDING
    document_kind: DocumentKind | None = None
    due_on: date | None = None
    linked_task_id: UUID | None = None
    scheduled_for: UtcDateTime | None = None
    completed_by: str | None = Field(default=None, max_length=200)
    completed_at: UtcDateTime | None = None
    note: str | None = Field(default=None, max_length=1000)

    @property
    def complete(self) -> bool:
        return self.status in {StepStatus.DONE, StepStatus.WAIVED}

    @property
    def is_overdue(self) -> bool:
        return (
            self.required
            and not self.complete
            and self.due_on is not None
            and self.due_on < date.today()
        )


class HandoverNote(StrictModel):
    """A knowledge handover entry attached to the plan."""

    id: UUID = Field(default_factory=uuid4)
    content: str = Field(min_length=1, max_length=8000)
    authored_by: str = Field(min_length=1, max_length=200)
    created_at: UtcDateTime = Field(default_factory=utc_now)


class OffboardingPlan(StrictModel):
    """An exit checklist instance for one employee."""

    id: UUID = Field(default_factory=uuid4)
    employee_id: UUID
    reason: OffboardingReason
    last_working_day: date

    template_id: UUID
    template_name: str = Field(min_length=1, max_length=200)
    template_version_hash: str = Field(min_length=64, max_length=64)

    steps: list[OffboardingStepState] = Field(min_length=1)
    handover_notes: list[HandoverNote] = Field(default_factory=list)

    final_pay_run_id: UUID | None = None
    started_at: UtcDateTime = Field(default_factory=utc_now)
    completed_at: UtcDateTime | None = None

    @property
    def required_steps(self) -> list[OffboardingStepState]:
        return [step for step in self.steps if step.required]

    @property
    def is_complete(self) -> bool:
        return all(step.complete for step in self.required_steps)

    @property
    def progress(self) -> float:
        required = self.required_steps
        if not required:
            return 1.0
        finished = sum(1 for step in required if step.complete)
        return round(finished / len(required), 4)

    def blockers(self) -> list[OffboardingStepState]:
        return [step for step in self.required_steps if not step.complete]


class AssetStatus(StrEnum):
    ASSIGNED = "assigned"
    RETURNED = "returned"
    MISSING = "missing"
    WRITTEN_OFF = "written_off"


class OffboardingAsset(StrictModel):
    """A company asset tracked for return during offboarding."""

    id: UUID = Field(default_factory=uuid4)
    employee_id: UUID
    plan_id: UUID | None = None

    name: str = Field(min_length=1, max_length=200)
    asset_code: str | None = Field(default=None, max_length=80)
    category: str = Field(default="", max_length=80)
    assigned_on: date | None = None

    status: AssetStatus = AssetStatus.ASSIGNED
    returned_on: date | None = None
    returned_by: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def blocks_clearance(self) -> bool:
        return self.status in {AssetStatus.ASSIGNED, AssetStatus.MISSING}
