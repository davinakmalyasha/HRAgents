"""Onboarding service — template selection, plan instantiation, and progress.

Deterministic: no LLM. The service creates checklist steps and delegates work
items to the task engine; document steps link to the employee's document vault
(for the OnboardingCoordinator agent to extract and pre-validate). Completion
of steps requiring human sign-off is reserved for humans — agent completions
are rejected in the same way approval decisions are.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import date, timedelta
from uuid import UUID

from hr_agents.identity import ActorRef
from hr_agents.models import (
    ApproverRole,
    Contract,
    ContractType,
    DocumentKind,
    Employee,
    EmployeeDocument,
    OnboardingPlan,
    OnboardingStepState,
    OnboardingTemplate,
    StepKind,
    StepStatus,
    TemplateStep,
    VerificationStatus,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.tasks import TaskEngine


class OnboardingError(RuntimeError):
    """Raised for invalid onboarding operations."""


class OnboardingActorError(OnboardingError):
    """Raised when the caller is not a named human (agent/system actors)."""


def template_hash(template: OnboardingTemplate) -> str:
    """Stable content hash of a template (for audit reconstruction)."""
    material = template.model_dump_json(exclude={"id", "created_at", "updated_at"})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class OnboardingService:
    """Templates, plans, and step progress."""

    def __init__(
        self,
        *,
        employees: EmployeeService,
        tasks: TaskEngine,
        audit: AuditChain | None = None,
    ) -> None:
        self._employees = employees
        self._tasks = tasks
        self._audit = audit or AuditChain()
        self._templates: dict[UUID, OnboardingTemplate] = {}
        self._plans: dict[UUID, OnboardingPlan] = {}

    # --- persistence primitives -----------------------------------------
    #
    # Adapters override only these. Waivers, gate enforcement, document linkage and
    # the auto-complete rules all stay above, where they are testable without a
    # database.
    #
    # The loss that matters here is a *waived* step. A hire who had their document
    # check waived by a manager, or a checklist step waived with a recorded reason,
    # would come back as not-waived after a restart -- and the next person to look
    # at the plan would see a blocker that HR had already resolved.

    def _load_template(self, template_id: UUID) -> OnboardingTemplate | None:
        return self._templates.get(template_id)

    def _iter_templates(self) -> Iterator[OnboardingTemplate]:
        return iter(list(self._templates.values()))

    def _save_template(self, template: OnboardingTemplate) -> None:
        self._templates[template.id] = template

    def _load_plan(self, plan_id: UUID) -> OnboardingPlan | None:
        return self._plans.get(plan_id)

    def _iter_plans(self) -> Iterator[OnboardingPlan]:
        return iter(list(self._plans.values()))

    def _save_plan(self, plan: OnboardingPlan) -> None:
        self._plans[plan.id] = plan

    # --- templates ------------------------------------------------------

    def create_template(
        self,
        *,
        name: str,
        steps: list[TemplateStep],
        actor: ActorRef,
        description: str = "",
        applies_to_contract_types: list[ContractType] | None = None,
        applies_to_roles: list[str] | None = None,
    ) -> OnboardingTemplate:
        template = OnboardingTemplate(
            name=name,
            description=description,
            steps=steps,
            applies_to_contract_types=applies_to_contract_types or [],
            applies_to_roles=applies_to_roles or [],
        )
        self._save_template(template)
        self._record(
            action="onboarding.template_created",
            subject_type="onboarding_template",
            subject_id=str(template.id),
            actor=actor,
            payload={"name": name, "step_count": len(steps)},
        )
        return template

    def get_template(self, template_id: UUID) -> OnboardingTemplate:
        template = self._load_template(template_id)
        if template is None:
            raise OnboardingError(f"unknown onboarding template {template_id}")
        return template

    def list_templates(self, *, active_only: bool = True) -> list[OnboardingTemplate]:
        templates = sorted(self._iter_templates(), key=lambda item: item.name.lower())
        if active_only:
            templates = [template for template in templates if template.active]
        return templates

    def select_template(
        self,
        *,
        contract_type: ContractType | None,
        role_text: str | None = None,
    ) -> OnboardingTemplate | None:
        """Pick the first matching template (templates are checked in name order)."""
        for template in self.list_templates():
            if template.matches(contract_type=contract_type, role_text=role_text):
                return template
        return None

    # --- plan instantiation ---------------------------------------------

    def start_plan(
        self,
        *,
        employee_id: UUID,
        actor: ActorRef,
        template_id: UUID | None = None,
        contract: Contract | None = None,
    ) -> OnboardingPlan:
        """Instantiate a plan for an employee and create the underlying tasks."""
        employee = self._require_employee(employee_id)

        template = self._resolve_template(employee, template_id, contract)
        hire_date = employee.hire_date or date.today()

        steps: list[OnboardingStepState] = []
        for template_step in template.steps:
            due_on = (
                hire_date + timedelta(days=template_step.due_days_after_hire)
                if template_step.due_days_after_hire is not None
                else None
            )
            task = self._tasks.create_on_behalf_of(
                title=f"[Onboarding] {template_step.title}",
                actor=actor,
                description=template_step.description
                or f"Onboarding step {template_step.key} for {employee.full_name}.",
                assignee_role=template_step.assignee_role,
                due_on=due_on,
                related_subject="onboarding_step",
                related_id=template_step.key,
            )
            steps.append(
                OnboardingStepState(
                    key=template_step.key,
                    title=template_step.title,
                    kind=template_step.kind,
                    required=template_step.required,
                    requires_human_signoff=template_step.requires_human_signoff,
                    assignee_role=template_step.assignee_role,
                    document_kind=template_step.document_kind,
                    due_on=due_on,
                    linked_task_id=task.id,
                )
            )

        plan = OnboardingPlan(
            employee_id=employee.id,
            template_id=template.id,
            template_name=template.name,
            template_version_hash=template_hash(template),
            steps=steps,
        )
        self._save_plan(plan)
        self._record(
            action="onboarding.plan_started",
            subject_type="onboarding_plan",
            subject_id=str(plan.id),
            actor=actor,
            payload={
                "employee_id": str(employee.id),
                "template_id": str(template.id),
                "template_hash": plan.template_version_hash,
                "step_count": len(steps),
            },
        )
        return plan

    def _resolve_template(
        self,
        employee: Employee,
        template_id: UUID | None,
        contract: Contract | None,
    ) -> OnboardingTemplate:
        if template_id is not None:
            return self.get_template(template_id)
        selected = self.select_template(
            contract_type=contract.contract_type if contract else None,
            role_text=employee.job_title,
        )
        if selected is None:
            raise OnboardingError("no onboarding template matches this hire; provide template_id")
        return selected

    # --- progress -------------------------------------------------------

    def get_plan(self, plan_id: UUID) -> OnboardingPlan:
        plan = self._load_plan(plan_id)
        if plan is None:
            raise OnboardingError(f"unknown onboarding plan {plan_id}")
        return plan

    def plans_for_employee(self, employee_id: UUID) -> list[OnboardingPlan]:
        return [
            plan
            for plan in sorted(self._iter_plans(), key=lambda item: item.started_at)
            if plan.employee_id == employee_id
        ]

    def active_plans(self) -> list[OnboardingPlan]:
        return [plan for plan in self._iter_plans() if not plan.is_complete]

    def complete_step(
        self,
        plan_id: UUID,
        step_key: str,
        *,
        actor: ActorRef,
        note: str | None = None,
    ) -> OnboardingPlan:
        """Complete a step as a human. Steps are human work items by default."""
        actor.require_human("an onboarding step", OnboardingActorError)
        plan = self.get_plan(plan_id)
        step = self._require_step(plan, step_key)
        if step.complete:
            raise OnboardingError(f"step {step_key!r} is already {step.status.value}")

        updated_step = step.model_copy(
            update={
                "status": StepStatus.DONE,
                "completed_by": actor.actor_id,
                "completed_at": utc_now(),
                "note": note or step.note,
            }
        )
        plan = self._replace_step(plan, updated_step)
        if plan.is_complete and plan.completed_at is None:
            plan = plan.model_copy(update={"completed_at": utc_now()})
        self._save_plan(plan)
        self._record(
            action="onboarding.step_completed",
            subject_type="onboarding_plan",
            subject_id=str(plan.id),
            actor=actor,
            payload={"step_key": step_key, "progress": plan.progress},
        )
        return plan

    def auto_complete_document_step(
        self,
        plan_id: UUID,
        step_key: str,
        *,
        document: EmployeeDocument,
        agent_name: str,
    ) -> OnboardingPlan:
        """Auto-tier completion for document steps.

        Allowed only when (a) the linked document is VERIFIED, (b) the step is a
        DOCUMENT step, and (c) the step does not require human sign-off. This is
        the one place an agent may complete a step, and the audit entry records
        the agent plus the document that justified it.
        """
        plan = self.get_plan(plan_id)
        step = self._require_step(plan, step_key)
        if step.kind is not StepKind.DOCUMENT:
            raise OnboardingError(
                f"step {step_key!r} is not a document step; agents cannot auto-complete it"
            )
        if step.requires_human_signoff:
            raise OnboardingError(f"step {step_key!r} requires human sign-off")
        if document.status is not VerificationStatus.VERIFIED:
            raise OnboardingError("document must be verified before the step can auto-complete")
        if step.linked_document_id != document.id:
            raise OnboardingError("document is not linked to this step")
        if step.complete:
            raise OnboardingError(f"step {step_key!r} is already {step.status.value}")

        updated_step = step.model_copy(
            update={
                "status": StepStatus.DONE,
                "completed_by": f"agent:{agent_name}",
                "completed_at": utc_now(),
                "note": f"auto-completed after verifying document {document.id}",
            }
        )
        plan = self._replace_step(plan, updated_step)
        if plan.is_complete and plan.completed_at is None:
            plan = plan.model_copy(update={"completed_at": utc_now()})
        self._save_plan(plan)
        self._record(
            action="onboarding.document_step_auto_completed",
            subject_type="onboarding_plan",
            subject_id=str(plan.id),
            actor=ActorRef.agent(agent_name),
            payload={
                "step_key": step_key,
                "document_id": str(document.id),
                "progress": plan.progress,
            },
        )
        return plan

    def waive_step(
        self,
        plan_id: UUID,
        step_key: str,
        *,
        actor: ActorRef,
        reason: str,
    ) -> OnboardingPlan:
        """Waive a step (required or not) — a human decision, always audited."""
        if not reason.strip():
            raise OnboardingError("waiving a step requires a reason")
        actor.require_human("waiving a step", OnboardingActorError)
        plan = self.get_plan(plan_id)
        step = self._require_step(plan, step_key)
        if step.complete:
            raise OnboardingError(f"step {step_key!r} is already {step.status.value}")

        updated_step = step.model_copy(
            update={
                "status": StepStatus.WAIVED,
                "completed_by": actor.actor_id,
                "completed_at": utc_now(),
                "note": reason,
            }
        )
        plan = self._replace_step(plan, updated_step)
        if plan.is_complete and plan.completed_at is None:
            plan = plan.model_copy(update={"completed_at": utc_now()})
        self._save_plan(plan)
        self._record(
            action="onboarding.step_waived",
            subject_type="onboarding_plan",
            subject_id=str(plan.id),
            actor=actor,
            payload={"step_key": step_key, "reason": reason},
        )
        return plan

    def link_document(
        self,
        plan_id: UUID,
        step_key: str,
        *,
        document: EmployeeDocument,
        actor: ActorRef,
    ) -> OnboardingPlan:
        """Attach a collected document to its document step (pending validation)."""
        plan = self.get_plan(plan_id)
        step = self._require_step(plan, step_key)
        if step.kind is not StepKind.DOCUMENT:
            raise OnboardingError(f"step {step_key!r} is not a document step")
        if step.document_kind is not None and step.document_kind is not document.kind:
            raise OnboardingError(
                f"step {step_key!r} expects {step.document_kind.value}, got {document.kind.value}"
            )
        updated_step = step.model_copy(
            update={
                "linked_document_id": document.id,
                "status": StepStatus.IN_PROGRESS,
            }
        )
        plan = self._replace_step(plan, updated_step)
        self._save_plan(plan)
        self._record(
            action="onboarding.document_linked",
            subject_type="onboarding_plan",
            subject_id=str(plan.id),
            actor=actor,
            payload={"step_key": step_key, "document_id": str(document.id)},
        )
        return plan

    def document_step_status(self, plan_id: UUID, *, verified_only: bool = True) -> dict[str, str]:
        """Document steps and whether their linked document is present/verified."""
        plan = self.get_plan(plan_id)
        result: dict[str, str] = {}
        for step in plan.steps:
            if step.kind is not StepKind.DOCUMENT:
                continue
            if step.complete:
                result[step.key] = "complete"
            elif step.linked_document_id is None:
                result[step.key] = "missing"
            else:
                result[step.key] = "pending_validation" if verified_only else "linked"
        return result

    # --- internals ------------------------------------------------------

    def _require_employee(self, employee_id: UUID) -> Employee:
        try:
            return self._employees.get(employee_id)
        except Exception as exc:
            raise OnboardingError(f"cannot start onboarding: {exc}") from exc

    def _require_step(self, plan: OnboardingPlan, step_key: str) -> OnboardingStepState:
        for step in plan.steps:
            if step.key == step_key:
                return step
        raise OnboardingError(f"unknown step {step_key!r} in plan {plan.id}")

    @staticmethod
    def _replace_step(plan: OnboardingPlan, updated: OnboardingStepState) -> OnboardingPlan:
        steps = [updated if step.key == updated.key else step for step in plan.steps]
        return plan.model_copy(update={"steps": steps})

    def _record(
        self,
        *,
        action: str,
        subject_type: str,
        subject_id: str,
        actor: ActorRef,
        payload: dict[str, object],
    ) -> None:
        self._audit.append(
            actor=actor.audit_actor(),
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )


def default_engineering_template(created_by: str = "system") -> OnboardingTemplate:
    """A sensible starter template (operators edit or replace it in the UI)."""
    return OnboardingTemplate(
        name="Engineering (PKWT/PKWTT) — starter",
        description="Starter checklist; customise per company in Settings.",
        applies_to_roles=["engineer", "developer", "engineering"],
        steps=[
            TemplateStep(
                key="collect_ktp",
                title="Collect KTP",
                kind=StepKind.DOCUMENT,
                document_kind=DocumentKind.KTP,
                due_days_after_hire=-7,
                requires_human_signoff=False,
            ),
            TemplateStep(
                key="collect_npwp",
                title="Collect NPWP",
                kind=StepKind.DOCUMENT,
                document_kind=DocumentKind.NPWP,
                due_days_after_hire=3,
            ),
            TemplateStep(
                key="collect_bank",
                title="Collect bank account details",
                kind=StepKind.DOCUMENT,
                document_kind=DocumentKind.BANK_ACCOUNT,
                due_days_after_hire=3,
            ),
            TemplateStep(
                key="collect_bpjs",
                title="Collect BPJS numbers",
                kind=StepKind.DOCUMENT,
                document_kind=DocumentKind.BPJS_KESEHATAN,
                due_days_after_hire=7,
            ),
            TemplateStep(
                key="sign_contract",
                title="Prepare and sign employment contract",
                kind=StepKind.CONTRACT,
                due_days_after_hire=0,
                requires_human_signoff=True,
            ),
            TemplateStep(
                key="accounts",
                title="Set up email, tools, and equipment",
                kind=StepKind.ACCOUNT_SETUP,
                due_days_after_hire=0,
                assignee_role=ApproverRole.MANAGER,
            ),
            TemplateStep(
                key="orientation",
                title="Schedule orientation and assign a buddy",
                kind=StepKind.ORIENTATION,
                due_days_after_hire=2,
                assignee_role=ApproverRole.MANAGER,
            ),
        ],
    )
