"""The compliance calendar: derived deadlines plus operator-entered dates.

Two sources, one list, and a rule that shapes both: the product never invents
a date. Deadlines it can compute exactly -- probation ends, contract expiries,
document expiries -- come from records it already keeps; anything statutory is
an operator entry that must name its source (``source_note``), because a
hardcoded filing window would be wrong exactly where a person is legally
exposed.

Contract expiries are upcoming-only, deliberately: a contract that already
lapsed has moved into its expiry task and terminal status, and listing it here
as well would double-report the same work. Probation ends and document
expiries do appear overdue, because that is the state a human must act on.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from hr_agents.errors import DomainCode, DomainError
from hr_agents.identity import ActorRef
from hr_agents.models import (
    CalendarDeadline,
    CalendarDeadlineKind,
    CalendarEntryCategory,
    ComplianceCalendarEntry,
    Employee,
    business_today,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.contracts import ContractService
from hr_agents.services.employees import EmployeeError, EmployeeService
from hr_agents.services.people_store import ComplianceStore


class CalendarError(DomainError, RuntimeError):
    """Raised for invalid calendar operations."""


class CalendarService:
    """Deadlines the system already knows, plus the dates only HR can enter."""

    def __init__(
        self,
        store: ComplianceStore,
        *,
        employees: EmployeeService,
        contracts: ContractService,
        audit: AuditChain | None = None,
    ) -> None:
        self._store = store
        self._employees = employees
        self._contracts = contracts
        self._audit = audit or AuditChain()

    # --- queries ---------------------------------------------------------

    def deadlines(self, *, start: date, end: date) -> list[CalendarDeadline]:
        """Computed deadlines whose due date falls inside ``[start, end]``."""
        if end < start:
            raise CalendarError("end must not be before start")
        items: list[CalendarDeadline] = []

        for employee in self._employees.on_probation():
            due = employee.probation_end_date
            if due is not None and start <= due <= end:
                items.append(
                    CalendarDeadline(
                        kind=CalendarDeadlineKind.PROBATION_END,
                        due_on=due,
                        subject_id=str(employee.id),
                        subject_name=employee.full_name,
                        detail=employee.job_title or "",
                    )
                )

        window = (end - business_today()).days
        if window >= 0:
            for contract in self._contracts.expiring(within_days=window):
                due = contract.end_date
                if due is not None and start <= due <= end:
                    subject = self._try_employee(contract.employee_id)
                    items.append(
                        CalendarDeadline(
                            kind=CalendarDeadlineKind.CONTRACT_EXPIRY,
                            due_on=due,
                            subject_id=str(contract.employee_id),
                            subject_name=subject.full_name if subject else "",
                            detail=contract.contract_type.value,
                        )
                    )

        for document in self._employees.document_vault():
            due = document.expires_on
            if due is not None and start <= due <= end:
                subject = self._try_employee(document.employee_id)
                items.append(
                    CalendarDeadline(
                        kind=CalendarDeadlineKind.DOCUMENT_EXPIRY,
                        due_on=due,
                        subject_id=str(document.employee_id),
                        subject_name=subject.full_name if subject else "",
                        detail=document.kind.value,
                    )
                )

        return sorted(
            items, key=lambda item: (item.due_on, item.kind.value, item.subject_id, item.detail)
        )

    def entries(self, *, start: date, end: date) -> list[ComplianceCalendarEntry]:
        """Operator-entered dates inside ``[start, end]``."""
        return [
            entry for entry in self._store.list_calendar_entries() if start <= entry.due_on <= end
        ]

    # --- commands --------------------------------------------------------

    def add_entry(
        self,
        *,
        title: str,
        due_on: date,
        category: CalendarEntryCategory,
        source_note: str,
        actor: ActorRef,
        notes: str | None = None,
        jurisdiction: str = "ID",
    ) -> ComplianceCalendarEntry:
        """Record one operator date. Humans and system jobs only, never agents."""
        actor.require_human_or_system("adding a compliance calendar date", CalendarError)
        entry = ComplianceCalendarEntry(
            title=title,
            due_on=due_on,
            category=category,
            jurisdiction=jurisdiction,
            source_note=source_note,
            notes=notes,
            created_by=actor.actor_id,
        )
        self._store.add_calendar_entry(entry)
        self._record(
            action="compliance.calendar_entry_added",
            entry=entry,
            actor=actor,
            payload={
                "category": entry.category.value,
                "due_on": entry.due_on.isoformat(),
                "source_note": entry.source_note,
            },
        )
        return entry

    def remove_entry(
        self, *, entry_id: UUID, actor: ActorRef, reason: str
    ) -> ComplianceCalendarEntry:
        """Delete one operator date. A reason is required and audited."""
        actor.require_human_or_system("removing a compliance calendar date", CalendarError)
        if not reason.strip():
            raise CalendarError("removing a calendar date requires a reason")
        entry = self._store.get_calendar_entry(entry_id)
        if entry is None:
            raise CalendarError(
                f"unknown calendar entry {entry_id}",
                code=DomainCode.UNKNOWN_RECORD,
                status=404,
            )
        self._store.delete_calendar_entry(entry_id)
        self._record(
            action="compliance.calendar_entry_removed",
            entry=entry,
            actor=actor,
            payload={
                "category": entry.category.value,
                "due_on": entry.due_on.isoformat(),
                "reason": reason.strip(),
            },
        )
        return entry

    # --- internals -------------------------------------------------------

    def _try_employee(self, employee_id: UUID) -> Employee | None:
        try:
            return self._employees.get(employee_id)
        except EmployeeError:
            return None

    def _record(
        self,
        *,
        action: str,
        entry: ComplianceCalendarEntry,
        actor: ActorRef,
        payload: dict[str, object],
    ) -> None:
        self._audit.append(
            actor=actor.audit_actor(),
            action=action,
            subject_type="compliance_calendar_entry",
            subject_id=str(entry.id),
            payload={"title": entry.title, **payload},
        )
