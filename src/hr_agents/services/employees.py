"""Employee lifecycle service — guarded state transitions and record keeping.

Deterministic: no LLM. Every transition is validated against the lifecycle
graph and audited. Offboarding is blocked while open approvals reference the
employee unless a human explicitly forces the transition (which is itself
audited).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from hr_agents.models import (
    ActorType,
    AuditActor,
    DocumentKind,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    OrgUnit,
    VerificationStatus,
    utc_now,
)
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import EmployeeStore


class EmployeeError(RuntimeError):
    """Raised for invalid employee operations."""


class EmployeeService:
    """Employee CRUD, lifecycle transitions, and document vault operations."""

    def __init__(
        self,
        store: EmployeeStore,
        *,
        audit: AuditChain | None = None,
        approvals: ApprovalEngine | None = None,
    ) -> None:
        self._store = store
        self._audit = audit or AuditChain()
        self._approvals = approvals

    # --- creation & updates ---------------------------------------------

    def create(
        self,
        *,
        full_name: str,
        created_by: str,
        email: str | None = None,
        phone: str | None = None,
        job_title: str | None = None,
        org_unit_id: UUID | None = None,
        manager_id: UUID | None = None,
        work_location: str | None = None,
        hire_date: date | None = None,
        probation_end_date: date | None = None,
        employee_number: str | None = None,
    ) -> Employee:
        if hire_date is None:
            raise EmployeeError("hire_date is required to create an employee")

        status = EmployeeStatus.ONBOARDING
        if probation_end_date is not None and probation_end_date >= date.today():
            status = EmployeeStatus.PROBATION
        elif probation_end_date is None and hire_date <= date.today():
            status = EmployeeStatus.ACTIVE

        employee = Employee(
            full_name=full_name,
            email=email,
            phone=phone,
            job_title=job_title,
            org_unit_id=org_unit_id,
            manager_id=manager_id,
            work_location=work_location,
            hire_date=hire_date,
            probation_end_date=probation_end_date,
            employee_number=employee_number,
            status=status,
        )
        self._store.add_employee(employee)
        self._record(employee, action="employee.created", actor_id=created_by)
        return employee

    def update_contact(
        self,
        employee_id: UUID,
        *,
        updated_by: str,
        email: str | None = None,
        phone: str | None = None,
        work_location: str | None = None,
    ) -> Employee:
        employee = self._require(employee_id)
        updated = employee.model_copy(
            update={
                "email": email if email is not None else employee.email,
                "phone": phone if phone is not None else employee.phone,
                "work_location": work_location
                if work_location is not None
                else employee.work_location,
                "updated_at": utc_now(),
            }
        )
        self._store.save_employee(updated)
        self._record(updated, action="employee.contact_updated", actor_id=updated_by)
        return updated

    # --- lifecycle ------------------------------------------------------

    def transition(
        self,
        employee_id: UUID,
        *,
        target: EmployeeStatus,
        by: str,
        force: bool = False,
        reason: str | None = None,
    ) -> Employee:
        employee = self._require(employee_id)
        if target is employee.status:
            return employee
        if not employee.can_transition_to(target):
            raise EmployeeError(f"illegal transition {employee.status.value} -> {target.value}")

        if target is EmployeeStatus.OFFBOARDED and not force:
            blockers = self._offboarding_blockers(employee_id)
            if blockers:
                raise EmployeeError(
                    "offboarding blocked by open items: "
                    + "; ".join(blockers)
                    + " (pass force=True with a reason to override)"
                )
        if target is EmployeeStatus.OFFBOARDED and force and not reason:
            raise EmployeeError("forced offboarding requires a reason")

        updates: dict[str, object] = {"status": target, "updated_at": utc_now()}
        if target is EmployeeStatus.OFFBOARDED:
            updates["offboarded_on"] = date.today()
        updated = employee.model_copy(update=updates)
        self._store.save_employee(updated)
        self._record(
            updated,
            action=f"employee.transition.{target.value}",
            actor_id=by,
            extra={"forced": force, "reason": reason},
        )
        return updated

    # --- documents ------------------------------------------------------

    def add_document(
        self,
        employee_id: UUID,
        *,
        kind: DocumentKind,
        storage_key: str,
        sha256: str,
        uploaded_by: str,
        filename: str | None = None,
        issued_on: date | None = None,
        expires_on: date | None = None,
    ) -> EmployeeDocument:
        employee = self._require(employee_id)
        document = EmployeeDocument(
            employee_id=employee.id,
            kind=kind,
            storage_key=storage_key,
            filename=filename,
            sha256=sha256,
            issued_on=issued_on,
            expires_on=expires_on,
            status=VerificationStatus.CLAIMED,
        )
        self._store.add_document(document)
        self._record(
            employee,
            action="employee.document_added",
            actor_id=uploaded_by,
            extra={"kind": kind.value, "document_id": str(document.id)},
        )
        return document

    def mark_document_verified(
        self,
        document_id: UUID,
        *,
        verified_by: str,
        verified: bool,
    ) -> EmployeeDocument:
        document = self.get_document(document_id)
        if document is None:
            raise EmployeeError(f"unknown document {document_id}")
        updated = document.model_copy(
            update={
                "status": VerificationStatus.VERIFIED if verified else VerificationStatus.FAILED
            }
        )
        self._store.add_document(updated)
        employee = self._require(updated.employee_id)
        self._record(
            employee,
            action="employee.document_verified" if verified else "employee.document_failed",
            actor_id=verified_by,
            extra={"document_id": str(updated.id), "kind": updated.kind.value},
        )
        return updated

    def get_document(self, document_id: UUID) -> EmployeeDocument | None:
        """Find a document across all employees (vault lookup)."""
        for document in self._all_documents():
            if document.id == document_id:
                return document
        return None

    def expiring_documents(self, *, within_days: int = 60) -> list[EmployeeDocument]:
        today = date.today()
        result: list[EmployeeDocument] = []
        for document in self._all_documents():
            if document.expires_on is None:
                continue
            days = (document.expires_on - today).days
            if 0 <= days <= within_days:
                result.append(document)
        return sorted(result, key=lambda doc: doc.expires_on or today)

    # --- org units ------------------------------------------------------

    def create_org_unit(
        self,
        *,
        name: str,
        created_by: str,
        parent_id: UUID | None = None,
        cost_center: str | None = None,
    ) -> OrgUnit:
        if parent_id is not None and self._store.get_org_unit(parent_id) is None:
            raise EmployeeError(f"unknown parent org unit {parent_id}")
        unit = OrgUnit(name=name, parent_id=parent_id, cost_center=cost_center)
        self._store.add_org_unit(unit)
        self._record_org(unit, action="org_unit.created", actor_id=created_by)
        return unit

    # --- queries --------------------------------------------------------

    def get(self, employee_id: UUID) -> Employee:
        return self._require(employee_id)

    def list_employees(self, *, status: EmployeeStatus | None = None) -> list[Employee]:
        employees = self._store.list_employees()
        if status is not None:
            employees = [item for item in employees if item.status is status]
        return employees

    def on_probation(self) -> list[Employee]:
        return self.list_employees(status=EmployeeStatus.PROBATION)

    # --- internals ------------------------------------------------------

    def _require(self, employee_id: UUID) -> Employee:
        employee = self._store.get_employee(employee_id)
        if employee is None:
            raise EmployeeError(f"unknown employee {employee_id}")
        return employee

    def _all_documents(self) -> list[EmployeeDocument]:
        documents: list[EmployeeDocument] = []
        for employee in self._store.list_employees():
            documents.extend(self._store.list_documents(employee.id))
        return documents

    def _offboarding_blockers(self, employee_id: UUID) -> list[str]:
        blockers: list[str] = []
        if self._approvals is not None:
            for request in self._approvals._store.list_all():
                if request.subject_id == str(employee_id) and request.active:
                    blockers.append(f"open approval {request.title!r}")
        return blockers

    def _record(
        self,
        employee: Employee,
        *,
        action: str,
        actor_id: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "full_name": employee.full_name,
            "status": employee.status.value,
        }
        if extra:
            payload.update(extra)
        self._audit.append(
            actor=AuditActor(
                actor_type=ActorType.SYSTEM if actor_id == "system" else ActorType.HUMAN,
                actor_id=actor_id,
            ),
            action=action,
            subject_type="employee",
            subject_id=str(employee.id),
            payload=payload,
        )

    def _record_org(self, unit: OrgUnit, *, action: str, actor_id: str) -> None:
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=actor_id),
            action=action,
            subject_type="org_unit",
            subject_id=str(unit.id),
            payload={
                "name": unit.name,
                "parent_id": str(unit.parent_id) if unit.parent_id else None,
            },
        )
