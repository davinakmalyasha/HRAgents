"""Offboarding service — template-driven exit checklists and asset clearance.

Deterministic: no LLM. Steps are delegated to the task engine (as in
onboarding), humans complete them, assets block plan completion until returned
or explicitly written off, and final pay is *coordinated* by linking a FINAL
payroll run — the payroll flow itself still requires human sign-off and never
executes payments.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from hr_agents.models import (
    ActorType,
    ApproverRole,
    AssetStatus,
    AuditActor,
    Employee,
    EmployeeStatus,
    HandoverNote,
    OffboardingAsset,
    OffboardingPlan,
    OffboardingReason,
    OffboardingStepKind,
    OffboardingStepState,
    OffboardingTemplate,
    OffboardingTemplateStep,
    PayrollRunKind,
    StepStatus,
    TaskPriority,
    TaskSource,
    utc_now,
)
from hr_agents.services.approvals import AGENT_ACTOR_PREFIX
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.payroll import PayrollService, current_period
from hr_agents.services.people_store import OffboardingStore
from hr_agents.services.tasks import TaskEngine


class OffboardingError(RuntimeError):
    """Raised for invalid offboarding operations."""


def template_hash(template: OffboardingTemplate) -> str:
    """Stable content hash of a template (for audit reconstruction)."""
    material = template.model_dump_json(exclude={"id", "created_at", "updated_at"})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class OffboardingService:
    """Templates, plans, assets, exit interviews, handover, final pay link."""

    def __init__(
        self,
        store: OffboardingStore | None = None,
        *,
        employees: EmployeeService,
        tasks: TaskEngine,
        payroll: PayrollService,
        audit: AuditChain | None = None,
    ) -> None:
        self._store = store or OffboardingStore()
        self._employees = employees
        self._tasks = tasks
        self._payroll = payroll
        self._audit = audit or AuditChain()

    # --- templates --------------------------------------------------------

    def create_template(
        self,
        *,
        name: str,
        steps: list[OffboardingTemplateStep],
        created_by: str,
        description: str = "",
        applies_to_reasons: list[OffboardingReason] | None = None,
        applies_to_roles: list[str] | None = None,
    ) -> OffboardingTemplate:
        template = OffboardingTemplate(
            name=name,
            description=description,
            steps=steps,
            applies_to_reasons=applies_to_reasons or [],
            applies_to_roles=applies_to_roles or [],
        )
        self._store.add_template(template)
        self._record(
            action="offboarding.template_created",
            actor_id=created_by,
            subject_type="offboarding_template",
            subject_id=str(template.id),
            payload={"name": name, "step_count": len(steps)},
        )
        return template

    def get_template(self, template_id: UUID) -> OffboardingTemplate:
        template = self._store.get_template(template_id)
        if template is None:
            raise OffboardingError(f"unknown offboarding template {template_id}")
        return template

    def list_templates(self, *, active_only: bool = True) -> list[OffboardingTemplate]:
        templates = sorted(self._store.list_templates(), key=lambda item: item.name.lower())
        if active_only:
            templates = [item for item in templates if item.active]
        return templates

    def select_template(
        self, *, reason: OffboardingReason, role_text: str | None = None
    ) -> OffboardingTemplate | None:
        for template in self.list_templates():
            if template.matches(reason=reason, role_text=role_text):
                return template
        return None

    # --- plan lifecycle ---------------------------------------------------

    def start_plan(
        self,
        *,
        employee_id: UUID,
        reason: OffboardingReason,
        last_working_day: date,
        created_by: str,
        template_id: UUID | None = None,
    ) -> OffboardingPlan:
        self._require_human(created_by, "start an offboarding plan")
        employee = self._require_employee(employee_id)
        if employee.status is EmployeeStatus.OFFBOARDED:
            raise OffboardingError("employee is already offboarded")

        template = self._resolve_template(employee, reason, template_id)

        steps: list[OffboardingStepState] = []
        for template_step in template.steps:
            due_on = (
                last_working_day - timedelta(days=template_step.due_days_before_last_day)
                if template_step.due_days_before_last_day is not None
                else None
            )
            task = self._tasks.create_agent_task(
                title=f"[Offboarding] {template_step.title}",
                agent_name="offboarding_coordinator",
                description=template_step.description
                or f"Exit step {template_step.key} for {employee.full_name}.",
                assignee_role=template_step.assignee_role,
                due_on=due_on,
                priority=TaskPriority.HIGH,
                related_subject="offboarding_step",
                related_id=template_step.key,
            )
            steps.append(
                OffboardingStepState(
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

        plan = OffboardingPlan(
            employee_id=employee.id,
            reason=reason,
            last_working_day=last_working_day,
            template_id=template.id,
            template_name=template.name,
            template_version_hash=template_hash(template),
            steps=steps,
        )
        self._store.add_plan(plan)

        if employee.can_transition_to(EmployeeStatus.NOTICE_PERIOD):
            self._employees.transition(
                employee.id, target=EmployeeStatus.NOTICE_PERIOD, by=created_by
            )

        self._record(
            action="offboarding.plan_started",
            actor_id=created_by,
            subject_type="offboarding_plan",
            subject_id=str(plan.id),
            payload={
                "employee_id": str(employee.id),
                "reason": reason.value,
                "last_working_day": last_working_day.isoformat(),
                "template_id": str(template.id),
                "template_hash": plan.template_version_hash,
                "step_count": len(steps),
            },
        )
        return plan

    def _resolve_template(
        self, employee: Employee, reason: OffboardingReason, template_id: UUID | None
    ) -> OffboardingTemplate:
        if template_id is not None:
            return self.get_template(template_id)
        selected = self.select_template(reason=reason, role_text=employee.job_title)
        if selected is None:
            raise OffboardingError("no offboarding template matches; provide template_id")
        return selected

    def get_plan(self, plan_id: UUID) -> OffboardingPlan:
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise OffboardingError(f"unknown offboarding plan {plan_id}")
        return plan

    def plans_for_employee(self, employee_id: UUID) -> list[OffboardingPlan]:
        return [
            plan
            for plan in sorted(self._store.list_plans(), key=lambda item: item.started_at)
            if plan.employee_id == employee_id
        ]

    def active_plans(self) -> list[OffboardingPlan]:
        return [plan for plan in self._store.list_plans() if plan.completed_at is None]

    # --- steps ------------------------------------------------------------

    def complete_step(
        self, plan_id: UUID, step_key: str, *, by: str, note: str | None = None
    ) -> OffboardingPlan:
        self._require_human(by, "complete an offboarding step")
        plan = self.get_plan(plan_id)
        if plan.completed_at is not None:
            raise OffboardingError("plan is already complete")
        step = self._require_step(plan, step_key)
        if step.complete:
            raise OffboardingError(f"step {step_key!r} is already {step.status.value}")

        updated_step = step.model_copy(
            update={
                "status": StepStatus.DONE,
                "completed_by": by,
                "completed_at": utc_now(),
                "note": note or step.note,
            }
        )
        plan = self._replace_step(plan, updated_step)
        self._store.save_plan(plan)
        self._record(
            action="offboarding.step_completed",
            actor_id=by,
            subject_type="offboarding_plan",
            subject_id=str(plan.id),
            payload={"step_key": step_key, "progress": plan.progress},
        )
        return plan

    def waive_step(self, plan_id: UUID, step_key: str, *, by: str, reason: str) -> OffboardingPlan:
        self._require_human(by, "waive an offboarding step")
        if not reason.strip():
            raise OffboardingError("waiving a step requires a reason")
        plan = self.get_plan(plan_id)
        if plan.completed_at is not None:
            raise OffboardingError("plan is already complete")
        step = self._require_step(plan, step_key)
        if step.complete:
            raise OffboardingError(f"step {step_key!r} is already {step.status.value}")

        updated_step = step.model_copy(
            update={
                "status": StepStatus.WAIVED,
                "completed_by": by,
                "completed_at": utc_now(),
                "note": reason,
            }
        )
        plan = self._replace_step(plan, updated_step)
        self._store.save_plan(plan)
        self._record(
            action="offboarding.step_waived",
            actor_id=by,
            subject_type="offboarding_plan",
            subject_id=str(plan.id),
            payload={"step_key": step_key, "reason": reason},
        )
        return plan

    def schedule_exit_interview(
        self, plan_id: UUID, *, scheduled_for: datetime, by: str
    ) -> OffboardingPlan:
        """Schedule the exit interview step. Humans only (a meeting with a person)."""
        self._require_human(by, "schedule the exit interview")
        if scheduled_for.tzinfo is None:
            raise OffboardingError("scheduled_for must be timezone-aware")
        scheduled_for = scheduled_for.astimezone(UTC)
        plan = self.get_plan(plan_id)
        step = next(
            (item for item in plan.steps if item.kind is OffboardingStepKind.EXIT_INTERVIEW),
            None,
        )
        if step is None:
            raise OffboardingError("plan has no exit interview step")
        if step.complete:
            raise OffboardingError("exit interview step is already complete")
        updated_step = step.model_copy(
            update={
                "scheduled_for": scheduled_for,
                "status": StepStatus.IN_PROGRESS,
            }
        )
        plan = self._replace_step(plan, updated_step)
        self._store.save_plan(plan)
        self._record(
            action="offboarding.exit_interview_scheduled",
            actor_id=by,
            subject_type="offboarding_plan",
            subject_id=str(plan.id),
            payload={"step_key": step.key, "scheduled_for": str(scheduled_for)},
        )
        return plan

    def add_handover_note(
        self, plan_id: UUID, *, content: str, authored_by: str
    ) -> OffboardingPlan:
        """Attach a knowledge handover note (agents may draft, humans may too)."""
        plan = self.get_plan(plan_id)
        note = HandoverNote(content=content, authored_by=authored_by)
        plan = plan.model_copy(update={"handover_notes": [*plan.handover_notes, note]})
        self._store.save_plan(plan)
        self._record(
            action="offboarding.handover_note_added",
            actor_id=authored_by,
            subject_type="offboarding_plan",
            subject_id=str(plan.id),
            payload={"note_id": str(note.id), "length": len(content)},
        )
        return plan

    # --- assets -----------------------------------------------------------

    def register_asset(
        self,
        *,
        employee_id: UUID,
        name: str,
        created_by: str,
        plan_id: UUID | None = None,
        asset_code: str | None = None,
        category: str = "",
        assigned_on: date | None = None,
    ) -> OffboardingAsset:
        self._require_human(created_by, "register an asset")
        self._require_employee(employee_id)
        if plan_id is not None:
            self.get_plan(plan_id)
        asset = OffboardingAsset(
            employee_id=employee_id,
            plan_id=plan_id,
            name=name,
            asset_code=asset_code,
            category=category,
            assigned_on=assigned_on,
        )
        self._store.add_asset(asset)
        self._record(
            action="offboarding.asset_registered",
            actor_id=created_by,
            subject_type="offboarding_asset",
            subject_id=str(asset.id),
            payload={"employee_id": str(employee_id), "name": name},
        )
        return asset

    def get_asset(self, asset_id: UUID) -> OffboardingAsset:
        asset = self._store.get_asset(asset_id)
        if asset is None:
            raise OffboardingError(f"unknown asset {asset_id}")
        return asset

    def list_assets(
        self, *, employee_id: UUID | None = None, plan_id: UUID | None = None
    ) -> list[OffboardingAsset]:
        assets = self._store.list_assets()
        if employee_id is not None:
            assets = [asset for asset in assets if asset.employee_id == employee_id]
        if plan_id is not None:
            assets = [asset for asset in assets if asset.plan_id == plan_id]
        return assets

    def mark_asset_returned(
        self,
        asset_id: UUID,
        *,
        by: str,
        note: str | None = None,
        returned_on: date | None = None,
    ) -> OffboardingAsset:
        self._require_human(by, "mark an asset returned")
        asset = self.get_asset(asset_id)
        if asset.status is AssetStatus.RETURNED:
            raise OffboardingError("asset is already returned")
        if asset.status is AssetStatus.WRITTEN_OFF:
            raise OffboardingError("asset is written off; it cannot be marked returned")
        updated = asset.model_copy(
            update={
                "status": AssetStatus.RETURNED,
                "returned_on": returned_on or date.today(),
                "returned_by": by,
                "note": note or asset.note,
                "updated_at": utc_now(),
            }
        )
        self._store.save_asset(updated)
        self._record(
            action="offboarding.asset_returned",
            actor_id=by,
            subject_type="offboarding_asset",
            subject_id=str(updated.id),
            payload={"employee_id": str(updated.employee_id)},
        )
        return updated

    def mark_asset_missing(self, asset_id: UUID, *, by: str, note: str) -> OffboardingAsset:
        self._require_human(by, "mark an asset missing")
        if not note.strip():
            raise OffboardingError("marking an asset missing requires a note")
        asset = self.get_asset(asset_id)
        if asset.status is not AssetStatus.ASSIGNED:
            raise OffboardingError(f"asset is {asset.status.value}; cannot mark missing")
        updated = asset.model_copy(
            update={"status": AssetStatus.MISSING, "note": note, "updated_at": utc_now()}
        )
        self._store.save_asset(updated)
        self._record(
            action="offboarding.asset_missing",
            actor_id=by,
            subject_type="offboarding_asset",
            subject_id=str(updated.id),
            payload={"note": note},
        )
        return updated

    def write_off_asset(self, asset_id: UUID, *, by: str, reason: str) -> OffboardingAsset:
        """Close out an unreturned asset (lost/stolen/waived). Human + reason."""
        self._require_human(by, "write off an asset")
        if not reason.strip():
            raise OffboardingError("writing off an asset requires a reason")
        asset = self.get_asset(asset_id)
        if asset.status not in {AssetStatus.ASSIGNED, AssetStatus.MISSING}:
            raise OffboardingError(f"asset is {asset.status.value}; cannot write off")
        updated = asset.model_copy(
            update={"status": AssetStatus.WRITTEN_OFF, "note": reason, "updated_at": utc_now()}
        )
        self._store.save_asset(updated)
        self._record(
            action="offboarding.asset_written_off",
            actor_id=by,
            subject_type="offboarding_asset",
            subject_id=str(updated.id),
            payload={"reason": reason},
        )
        return updated

    def asset_clearance(self, employee_id: UUID) -> list[OffboardingAsset]:
        """Assets that block exit clearance for this employee."""
        return [
            asset for asset in self.list_assets(employee_id=employee_id) if asset.blocks_clearance
        ]

    # --- final pay ---------------------------------------------------------

    def coordinate_final_pay(self, plan_id: UUID, *, by: str) -> OffboardingPlan:
        """Create and link a FINAL payroll run (prepare/verify only).

        The run itself still needs inputs, computation, anomaly clearance, and
        Finance sign-off; this method only opens the coordination.
        """
        self._require_human(by, "coordinate final pay")
        plan = self.get_plan(plan_id)
        if plan.completed_at is not None:
            raise OffboardingError("plan is already complete")
        if plan.final_pay_run_id is not None:
            raise OffboardingError("final pay is already coordinated for this plan")

        year, month = current_period()
        run = self._payroll.create_run(
            period_year=year, period_month=month, created_by=by, kind=PayrollRunKind.FINAL
        )
        task = self._tasks.create(
            title="[Payroll] Prepare final settlement inputs",
            created_by="system",
            description=(
                f"Final pay run {run.id} opened for offboarding plan {plan.id}. "
                "Enter inputs, compute, and route for Finance sign-off."
            ),
            assignee_role=ApproverRole.FINANCE,
            due_on=plan.last_working_day,
            source=TaskSource.SYSTEM,
            related_subject="payroll_run",
            related_id=str(run.id),
        )
        plan = plan.model_copy(update={"final_pay_run_id": run.id})
        self._store.save_plan(plan)
        self._record(
            action="offboarding.final_pay_coordinated",
            actor_id=by,
            subject_type="offboarding_plan",
            subject_id=str(plan.id),
            payload={
                "payroll_run_id": str(run.id),
                "task_id": str(task.id),
                "period": f"{year}-{month:02d}",
            },
        )
        return plan

    # --- completion ---------------------------------------------------------

    def complete_plan(self, plan_id: UUID, *, by: str) -> OffboardingPlan:
        """Finish the plan: all required steps + asset clearance required.

        Does **not** transition the employee record; HR does that explicitly
        through the employee lifecycle endpoint (which applies its own guards).
        """
        self._require_human(by, "complete an offboarding plan")
        plan = self.get_plan(plan_id)
        if plan.completed_at is not None:
            raise OffboardingError("plan is already complete")

        blockers = [step.key for step in plan.blockers()]
        if blockers:
            raise OffboardingError("required steps incomplete: " + ", ".join(blockers))
        assets = self.asset_clearance(plan.employee_id)
        if assets:
            labels = [
                f"{asset.name}{f' ({asset.asset_code})' if asset.asset_code else ''}"
                f":{asset.status.value}"
                for asset in assets
            ]
            raise OffboardingError("assets not cleared: " + "; ".join(labels))

        plan = plan.model_copy(update={"completed_at": utc_now()})
        self._store.save_plan(plan)
        self._record(
            action="offboarding.plan_completed",
            actor_id=by,
            subject_type="offboarding_plan",
            subject_id=str(plan.id),
            payload={"progress": plan.progress, "steps": len(plan.steps)},
        )
        return plan

    def finalize_employee_exit(self, plan_id: UUID, *, by: str) -> Employee:
        """Complete the plan (if needed), then transition the employee to OFFBOARDED.

        The employee transition keeps its own guards (open approvals block it
        unless a human forces it separately).
        """
        plan = self.get_plan(plan_id)
        if plan.completed_at is None:
            plan = self.complete_plan(plan_id, by=by)
        employee = self._employees.transition(
            plan.employee_id, target=EmployeeStatus.OFFBOARDED, by=by
        )
        self._record(
            action="offboarding.employee_offboarded",
            actor_id=by,
            subject_type="offboarding_plan",
            subject_id=str(plan.id),
            payload={"employee_id": str(employee.id)},
        )
        return employee

    # --- internals ----------------------------------------------------------

    def _require_employee(self, employee_id: UUID) -> Employee:
        try:
            return self._employees.get(employee_id)
        except Exception as exc:
            raise OffboardingError(f"unknown employee {employee_id}") from exc

    def _require_step(self, plan: OffboardingPlan, step_key: str) -> OffboardingStepState:
        for step in plan.steps:
            if step.key == step_key:
                return step
        raise OffboardingError(f"unknown step {step_key!r} in plan {plan.id}")

    @staticmethod
    def _replace_step(plan: OffboardingPlan, updated: OffboardingStepState) -> OffboardingPlan:
        steps = [updated if step.key == updated.key else step for step in plan.steps]
        return plan.model_copy(update={"steps": steps})

    def _require_human(self, actor: str, action: str) -> None:
        if actor.startswith(AGENT_ACTOR_PREFIX):
            raise OffboardingError(f"agents cannot {action}; a named human is required")

    def _record(
        self,
        *,
        action: str,
        actor_id: str,
        subject_type: str,
        subject_id: str,
        payload: dict[str, object],
    ) -> None:
        if actor_id.startswith(AGENT_ACTOR_PREFIX):
            actor_type = ActorType.AGENT
        elif actor_id == "system" or actor_id.startswith("system:"):
            actor_type = ActorType.SYSTEM
        else:
            actor_type = ActorType.HUMAN
        self._audit.append(
            actor=AuditActor(actor_type=actor_type, actor_id=actor_id),
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )


def default_offboarding_template() -> OffboardingTemplate:
    """Starter resignation checklist (operators edit or replace it)."""
    return OffboardingTemplate(
        name="Resignation — starter",
        description=(
            "Starter exit checklist. Operators customise steps and timings in Settings; "
            "notice periods and settlement rules are company/contract-specific."
        ),
        applies_to_reasons=[OffboardingReason.RESIGNATION, OffboardingReason.OTHER],
        steps=[
            OffboardingTemplateStep(
                key="handover",
                title="Write knowledge handover notes",
                kind=OffboardingStepKind.HANDOVER,
                description="Document active work, credentials to transfer, and contacts.",
                due_days_before_last_day=7,
            ),
            OffboardingTemplateStep(
                key="exit_interview",
                title="Conduct exit interview",
                kind=OffboardingStepKind.EXIT_INTERVIEW,
                due_days_before_last_day=2,
                assignee_role=ApproverRole.HR_ADMIN,
            ),
            OffboardingTemplateStep(
                key="return_assets",
                title="Return company assets",
                kind=OffboardingStepKind.ASSET_RETURN,
                description="Laptop, phone, access cards, equipment.",
                due_days_before_last_day=1,
            ),
            OffboardingTemplateStep(
                key="close_accounts",
                title="Close accounts and revoke access",
                kind=OffboardingStepKind.ACCOUNT_CLOSURE,
                description="Email, SSO, tools, shared drives, physical access.",
                due_days_before_last_day=0,
                assignee_role=ApproverRole.HR_ADMIN,
            ),
            OffboardingTemplateStep(
                key="final_pay",
                title="Coordinate final pay (prepare & verify only)",
                kind=OffboardingStepKind.FINAL_PAY,
                description=(
                    "Open a FINAL payroll run; Finance signs off before any external payment."
                ),
                due_days_before_last_day=0,
                assignee_role=ApproverRole.FINANCE,
                requires_human_signoff=True,
            ),
            OffboardingTemplateStep(
                key="confirm_exit",
                title="Confirm exit paperwork and last day",
                kind=OffboardingStepKind.CONFIRMATION,
                due_days_before_last_day=0,
                requires_human_signoff=True,
            ),
        ],
    )


__all__ = [
    "OffboardingError",
    "OffboardingService",
    "default_offboarding_template",
    "template_hash",
]
