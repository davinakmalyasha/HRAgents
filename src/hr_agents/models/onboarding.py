"""Onboarding domain models — template-driven checklists instantiated per hire.

A template defines the steps (documents to collect, tasks to complete, contracts
to sign). A plan is the per-employee instance that tracks progress. Agents may
extract and validate documents and chase missing ones, but humans sign contracts
and confirm sensitive data.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.approval import ApproverRole
from hr_agents.models.common import StrictModel, UtcDateTime, utc_now
from hr_agents.models.contract import ContractType
from hr_agents.models.employee import DocumentKind


class StepKind(StrEnum):
    """What kind of work an onboarding step represents."""

    DOCUMENT = "document"  # collect + validate a document
    TASK = "task"  # generic checklist item
    CONTRACT = "contract"  # prepare/sign the employment contract
    ACCOUNT_SETUP = "account_setup"  # email, tools, equipment
    ORIENTATION = "orientation"  # intro sessions, buddy, training
    CONFIRMATION = "confirmation"  # human confirms a fact/decision


class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    WAIVED = "waived"  # deliberately not required (human decision, audited)


TERMINAL_STEP_STATUSES = frozenset({StepStatus.DONE, StepStatus.WAIVED})


class TemplateStep(StrictModel):
    """One step definition inside an onboarding template."""

    key: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        min_length=1,
        max_length=60,
        description="Stable step key within the template, e.g. 'collect_ktp'.",
    )
    title: str = Field(min_length=1, max_length=200)
    kind: StepKind
    description: str = Field(default="", max_length=1000)

    document_kind: DocumentKind | None = None
    assignee_role: ApproverRole = ApproverRole.HR_ADMIN
    due_days_after_hire: int | None = Field(default=None, ge=-30, le=365)
    required: bool = True
    requires_human_signoff: bool = False

    @model_validator(mode="after")
    def _validate(self) -> TemplateStep:
        if self.kind is StepKind.DOCUMENT and self.document_kind is None:
            raise ValueError(f"step {self.key!r}: DOCUMENT steps require document_kind")
        if self.kind is not StepKind.DOCUMENT and self.document_kind is not None:
            raise ValueError(f"step {self.key!r}: document_kind only applies to DOCUMENT steps")
        return self


class OnboardingTemplate(StrictModel):
    """A reusable checklist definition (e.g., 'Engineering PKWT', 'Finance PKWTT')."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)

    applies_to_contract_types: list[ContractType] = Field(default_factory=list)
    applies_to_roles: list[str] = Field(
        default_factory=list,
        description="Optional free-text role match (e.g. 'engineering', 'finance'); "
        "empty = applies to all roles.",
    )
    steps: list[TemplateStep] = Field(min_length=1)

    active: bool = True
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _unique_keys(self) -> OnboardingTemplate:
        keys = [step.key for step in self.steps]
        if len(keys) != len(set(keys)):
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            raise ValueError(f"duplicate step keys: {', '.join(duplicates)}")
        return self

    def matches(
        self,
        *,
        contract_type: ContractType | None,
        role_text: str | None = None,
    ) -> bool:
        """True when this template applies to the given hire."""
        if not self.active:
            return False
        if (
            self.applies_to_contract_types
            and contract_type is not None
            and contract_type not in self.applies_to_contract_types
        ):
            return False
        if self.applies_to_roles and role_text:
            haystack = role_text.lower()
            if not any(role.lower() in haystack for role in self.applies_to_roles):
                return False
        return True


class OnboardingStepState(StrictModel):
    """Per-employee state of one template step."""

    key: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    kind: StepKind
    required: bool
    requires_human_signoff: bool
    assignee_role: ApproverRole

    status: StepStatus = StepStatus.PENDING
    document_kind: DocumentKind | None = None
    due_on: date | None = None
    linked_document_id: UUID | None = None
    linked_task_id: UUID | None = None
    completed_by: str | None = Field(default=None, max_length=200)
    completed_at: UtcDateTime | None = None
    note: str | None = Field(default=None, max_length=1000)

    @property
    def complete(self) -> bool:
        return self.status in TERMINAL_STEP_STATUSES

    @property
    def is_overdue(self) -> bool:
        return (
            self.required
            and not self.complete
            and self.due_on is not None
            and self.due_on < date.today()
        )


class OnboardingPlan(StrictModel):
    """An onboarding checklist instance for one employee."""

    id: UUID = Field(default_factory=uuid4)
    employee_id: UUID
    template_id: UUID
    template_name: str = Field(min_length=1, max_length=200)
    template_version_hash: str = Field(
        min_length=64,
        max_length=64,
        description="Hash of the template at instantiation time (audit-reconstructible).",
    )

    steps: list[OnboardingStepState] = Field(min_length=1)
    started_at: UtcDateTime = Field(default_factory=utc_now)
    completed_at: UtcDateTime | None = None

    @property
    def required_steps(self) -> list[OnboardingStepState]:
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

    def blockers(self) -> list[OnboardingStepState]:
        return [step for step in self.required_steps if not step.complete]
