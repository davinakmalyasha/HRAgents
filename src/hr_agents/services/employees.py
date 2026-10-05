"""Employee lifecycle service — guarded state transitions and record keeping.

Deterministic: no LLM. Every transition is validated against the lifecycle
graph and audited. Offboarding is blocked while open approvals reference the
employee unless a human explicitly forces the transition (which is itself
audited).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from hr_agents.identity import ActorRef
from hr_agents.models import (
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
        actor: ActorRef,
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
        self._record(employee, action="employee.created", actor=actor)
        return employee

    def update_contact(
        self,
        employee_id: UUID,
        *,
        actor: ActorRef,
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
        self._record(updated, action="employee.contact_updated", actor=actor)
        return updated

    def update_payroll_profile(
        self,
        employee_id: UUID,
        *,
        actor: ActorRef,
        jkk_risk_level: int | None = None,
        dependents: int | None = None,
        clear_jkk_risk: bool = False,
    ) -> Employee:
        """Record the employee's payroll classification.

        Only the *bracket* an employee falls in, never a rate: `jkk_risk_level`
        selects a row of the verified `bpjs_jkk` table, and `dependents` multiplies
        the per-dependent allowance from the verified `pph21_ptkp` table. Rates
        themselves cannot be set here, which is what stops a statutory figure being
        hardcoded on an employee record.

        Clearing the risk class needs `clear_jkk_risk=True` rather than a bare
        `None`, so that updating a dependent count cannot quietly wipe a
        classification an operator entered. A cleared class is itself meaningful:
        payroll treats it as blocking on a keyed JKK table, so clearing stops the
        wrong rate being charged but also stops the run being payable.
        """
        employee = self._require(employee_id)
        updates: dict[str, object] = {"updated_at": utc_now()}
        if clear_jkk_risk:
            updates["jkk_risk_level"] = None
        elif jkk_risk_level is not None:
            updates["jkk_risk_level"] = jkk_risk_level
        if dependents is not None:
            updates["dependents"] = dependents
        updated = employee.model_copy(update=updates)
        self._store.save_employee(updated)
        self._record(updated, action="employee.payroll_profile_updated", actor=actor)
        return updated

    # --- lifecycle ------------------------------------------------------

    def transition(
        self,
        employee_id: UUID,
        *,
        target: EmployeeStatus,
        actor: ActorRef,
        force: bool = False,
        reason: str | None = None,
    ) -> Employee:
        """Move an employee through their lifecycle.

        The most consequential state change in the people domain, and the one an
        agent must never make: every status here changes someone's employment.
        The gate sits here rather than in the router so no caller can route around
        it, and above the idempotent early return below, so a repeat call by a
        system actor is refused rather than quietly succeeding.
        """
        actor.require_human(
            "changing an employee status",
            EmployeeError,
            subject=f"employee {employee_id} -> {target.value}",
        )
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
            actor=actor,
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
        actor: ActorRef,
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
            actor=actor,
            extra={"kind": kind.value, "document_id": str(document.id)},
        )
        return document

    def mark_document_verified(
        self,
        document_id: UUID,
        *,
        actor: ActorRef,
        verified: bool,
    ) -> EmployeeDocument:
        """Judge a document verified or failed — a named human only.

        The gate lives here, not in the router: any other caller (an agent tool, a
        worker, a future service) would otherwise be able to verify a legal
        document without passing it.
        """
        actor.require_human(
            "verifying a document", EmployeeError, subject=f"document {document_id}"
        )
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
            actor=actor,
            extra={"document_id": str(updated.id), "kind": updated.kind.value},
        )
        return updated

    def get_document(self, document_id: UUID) -> EmployeeDocument | None:
        """Find a document across all employees (vault lookup)."""
        for document in self._all_documents():
            if document.id == document_id:
                return document
        return None

    def documents_for(self, employee_id: UUID) -> list[EmployeeDocument]:
        """One employee's vault, soonest expiry first (checklist linking and review).

        The docstring here used to say "oldest first", which matched neither
        store: the database adapter ordered by expiry and the in-memory one by
        insertion. Both now order by expiry, and the docstring says so.
        """
        self._require(employee_id)
        return self._store.list_documents(employee_id)

    def document_vault(
        self,
        *,
        employee_id: UUID | None = None,
        expiring_within_days: int | None = None,
        status: VerificationStatus | None = None,
    ) -> list[EmployeeDocument]:
        """The whole vault with the filters the records workspace needs.

        Soonest expiry first, so an expiry sweep and a human reviewing the vault
        read the same order.
        """
        today = date.today()
        documents = (
            self._store.list_documents(employee_id) if employee_id else self._store.all_documents()
        )
        selected: list[EmployeeDocument] = []
        for document in documents:
            if status is not None and document.status is not status:
                continue
            if expiring_within_days is not None:
                if document.expires_on is None:
                    continue
                days = (document.expires_on - today).days
                if not 0 <= days <= expiring_within_days:
                    continue
            selected.append(document)
        return sorted(
            selected,
            key=lambda doc: (doc.expires_on is None, doc.expires_on or date.min),
        )

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

    def list_org_units(self) -> list[OrgUnit]:
        """Every org unit, name-ordered (the records org chart reads this)."""
        return self._store.list_org_units()

    def create_org_unit(
        self,
        *,
        name: str,
        actor: ActorRef,
        parent_id: UUID | None = None,
        cost_center: str | None = None,
    ) -> OrgUnit:
        if parent_id is not None and self._store.get_org_unit(parent_id) is None:
            raise EmployeeError(f"unknown parent org unit {parent_id}")
        unit = OrgUnit(name=name, parent_id=parent_id, cost_center=cost_center)
        self._store.add_org_unit(unit)
        self._record_org(unit, action="org_unit.created", actor=actor)
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
        """Every document in the vault, in the store's order.

        This looped the employee list and called ``list_documents`` per employee,
        which made an org-wide lookup cost one full-table read per employee --
        501 statements to list documents for 100 employees. The store can answer
        the whole-vault question directly, so ask it directly.
        """
        return self._store.all_documents()

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
        actor: ActorRef | str,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "full_name": employee.full_name,
            "status": employee.status.value,
        }
        if extra:
            payload.update(extra)
        self._audit.append(
            actor=ActorRef.coerce(actor).audit_actor(),
            action=action,
            subject_type="employee",
            subject_id=str(employee.id),
            payload=payload,
        )

    def _record_org(self, unit: OrgUnit, *, action: str, actor: ActorRef | str) -> None:
        self._audit.append(
            actor=ActorRef.coerce(actor).audit_actor(),
            action=action,
            subject_type="org_unit",
            subject_id=str(unit.id),
            payload={
                "name": unit.name,
                "parent_id": str(unit.parent_id) if unit.parent_id else None,
            },
        )
