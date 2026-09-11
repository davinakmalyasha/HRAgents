"""Contract service — PKWT/PKWTT lifecycle, expiry math, and reminders.

Deterministic: no LLM, no hardcoded statutory money values. Structural rules
(PKWT needs an end date, probation only for PKWTT) are enforced by the model;
the service adds status maintenance, expiry windows, and task creation through
the injected task engine.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from hr_agents.models import (
    ActorType,
    ApproverRole,
    AuditActor,
    Contract,
    ContractStatus,
    ContractType,
    TaskItem,
    TaskPriority,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import ContractStore
from hr_agents.services.tasks import TaskEngine

DEFAULT_WARNING_DAYS = 60
COMPLETION_FLAG_DAYS = 30


class ContractError(RuntimeError):
    """Raised for invalid contract operations."""


class ContractService:
    """Create contracts, maintain expiry status, and raise reminders."""

    def __init__(
        self,
        store: ContractStore,
        *,
        audit: AuditChain | None = None,
        tasks: TaskEngine | None = None,
        warning_days: int = DEFAULT_WARNING_DAYS,
    ) -> None:
        self._store = store
        self._audit = audit or AuditChain()
        self._tasks = tasks
        self._warning_days = warning_days

    # --- creation -------------------------------------------------------

    def create(
        self,
        *,
        employee_id: UUID,
        contract_type: ContractType,
        start_date: date,
        created_by: str,
        end_date: date | None = None,
        probation_end_date: date | None = None,
        notes: str | None = None,
    ) -> Contract:
        contract = Contract(
            employee_id=employee_id,
            contract_type=contract_type,
            start_date=start_date,
            end_date=end_date,
            probation_end_date=probation_end_date,
            notes=notes,
            status=ContractStatus.DRAFT,
        )
        self._store.add(contract)
        self._record(contract, action="contract.created", actor_id=created_by)
        return contract

    def activate(self, contract_id: UUID, *, by: str, signed_on: date | None = None) -> Contract:
        contract = self._require(contract_id)
        if contract.status is not ContractStatus.DRAFT:
            raise ContractError(
                f"contract {contract_id} is {contract.status.value}; cannot activate"
            )
        updated = contract.model_copy(
            update={
                "status": ContractStatus.ACTIVE,
                "signed_on": signed_on or date.today(),
                "updated_at": utc_now(),
            }
        )
        self._store.save(updated)
        self._record(updated, action="contract.activated", actor_id=by)
        return updated

    # --- status maintenance ---------------------------------------------

    def refresh_status(self, contract_id: UUID, *, as_of: date | None = None) -> Contract:
        """Recompute status from dates. Idempotent; safe to run on a schedule."""
        contract = self._require(contract_id)
        today = as_of or date.today()

        if contract.status in {
            ContractStatus.TERMINATED,
            ContractStatus.COMPLETED,
        }:
            return contract

        updates: dict[str, object] = {}
        days = contract.days_until_expiry(as_of=today)

        if days is not None and days < 0 and contract.status is not ContractStatus.EXPIRED:
            updates["status"] = ContractStatus.EXPIRED
        elif (
            days is not None
            and 0 <= days <= self._warning_days
            and contract.status is ContractStatus.ACTIVE
        ):
            updates["status"] = ContractStatus.EXPIRING
        elif (
            days is not None
            and days > self._warning_days
            and contract.status is ContractStatus.EXPIRING
        ):
            updates["status"] = ContractStatus.ACTIVE

        # PKWT completion compensation flag (structure only; amount computed in payroll)
        if contract.contract_type is ContractType.PKWT and days is not None:
            should_flag = 0 <= days <= COMPLETION_FLAG_DAYS
            if should_flag != contract.compensation_due:
                updates["compensation_due"] = should_flag

        if not updates:
            return contract
        updates["updated_at"] = utc_now()
        updated = contract.model_copy(update=updates)
        self._store.save(updated)
        self._record(updated, action=f"contract.status.{updated.status.value}", actor_id="system")
        return updated

    def refresh_all(self, *, as_of: date | None = None) -> list[Contract]:
        return [
            self.refresh_status(contract.id, as_of=as_of) for contract in self._store.list_all()
        ]

    def terminate(self, contract_id: UUID, *, by: str, reason: str) -> Contract:
        contract = self._require(contract_id)
        updated = contract.model_copy(
            update={
                "status": ContractStatus.TERMINATED,
                "notes": ((contract.notes or "") + f"\nTerminated: {reason}").strip(),
                "updated_at": utc_now(),
            }
        )
        self._store.save(updated)
        self._record(updated, action="contract.terminated", actor_id=by)
        return updated

    # --- reminders ------------------------------------------------------

    def expiring(self, *, within_days: int | None = None) -> list[Contract]:
        window = self._warning_days if within_days is None else within_days
        today = date.today()
        result: list[Contract] = []
        for contract in self._store.list_all():
            days = contract.days_until_expiry(as_of=today)
            if days is not None and 0 <= days <= window:
                result.append(contract)
        return sorted(result, key=lambda item: item.days_until_expiry(as_of=today) or 0)

    def create_expiry_tasks(self, *, as_of: date | None = None) -> list[TaskItem]:
        """Create reminder tasks for expiring contracts (idempotent per contract)."""
        if self._tasks is None:
            raise ContractError("task engine is not configured")
        today = as_of or date.today()
        created: list[TaskItem] = []

        existing_pairs = {
            (task.related_subject, task.related_id) for task in self._tasks.open_tasks()
        }
        for contract in self.expiring(within_days=self._warning_days):
            key = ("contract", str(contract.id))
            if key in existing_pairs:
                continue
            days = contract.days_until_expiry(as_of=today)
            due = today + timedelta(days=7)
            task = self._tasks.create_agent_task(
                title=(
                    f"Contract expiring in {days} days — {contract.contract_type.value.upper()}"
                ),
                agent_name="contract_monitor",
                description=(
                    "Review renewal, completion compensation, and required "
                    "paperwork. This contract expires on "
                    f"{contract.end_date.isoformat() if contract.end_date else 'unknown'}."
                ),
                assignee_role=ApproverRole.HR_ADMIN,
                due_on=due,
                priority=TaskPriority.HIGH if (days or 0) <= 14 else TaskPriority.NORMAL,
                related_subject="contract",
                related_id=str(contract.id),
            )
            created.append(task)
        return created

    # --- queries --------------------------------------------------------

    def get(self, contract_id: UUID) -> Contract:
        return self._require(contract_id)

    def for_employee(self, employee_id: UUID) -> list[Contract]:
        return self._store.list_for_employee(employee_id)

    def active_for_employee(self, employee_id: UUID) -> Contract | None:
        active = [
            contract
            for contract in self._store.list_for_employee(employee_id)
            if contract.status in {ContractStatus.ACTIVE, ContractStatus.EXPIRING}
        ]
        return active[-1] if active else None

    # --- internals ------------------------------------------------------

    def _require(self, contract_id: UUID) -> Contract:
        contract = self._store.get(contract_id)
        if contract is None:
            raise ContractError(f"unknown contract {contract_id}")
        return contract

    def _record(self, contract: Contract, *, action: str, actor_id: str) -> None:
        self._audit.append(
            actor=AuditActor(
                actor_type=ActorType.SYSTEM if actor_id == "system" else ActorType.HUMAN,
                actor_id=actor_id,
            ),
            action=action,
            subject_type="contract",
            subject_id=str(contract.id),
            payload={
                "employee_id": str(contract.employee_id),
                "contract_type": contract.contract_type.value,
                "status": contract.status.value,
                "end_date": contract.end_date.isoformat() if contract.end_date else None,
                "compensation_due": contract.compensation_due,
            },
        )
