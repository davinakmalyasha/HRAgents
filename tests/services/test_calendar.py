"""Service-level rules of the compliance calendar.

The API tests cover the merged view; these pin the pieces the view is built
from -- which sources can appear in a window, the upcoming-only contract rule,
and the human gate on operator dates.
"""

from datetime import date, timedelta

import pytest

from hr_agents.errors import DomainCode
from hr_agents.identity import ActorRef
from hr_agents.models import (
    CalendarEntryCategory,
    ContractType,
    DocumentKind,
    Employee,
    EmployeeStatus,
    business_today,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.calendar import CalendarError, CalendarService
from hr_agents.services.contracts import ContractService
from hr_agents.services.employees import EmployeeService
from hr_agents.services.people_store import ComplianceStore, ContractStore, EmployeeStore

HUMAN = ActorRef.legacy("hr-admin")
TODAY = business_today()


def make_services() -> tuple[CalendarService, EmployeeService, ContractService]:
    audit = AuditChain()
    employees = EmployeeService(EmployeeStore(), audit=audit)
    contracts = ContractService(ContractStore(), audit=audit)
    calendar = CalendarService(
        ComplianceStore(), employees=employees, contracts=contracts, audit=audit
    )
    return calendar, employees, contracts


def make_employee(employees: EmployeeService, *, probation_end: date | None = None) -> Employee:
    return employees.create(
        full_name="Sari Dewi",
        actor=HUMAN,
        hire_date=TODAY - timedelta(days=300),
        probation_end_date=probation_end,
    )


def test_probation_ends_appear_in_the_window() -> None:
    calendar, employees, _ = make_services()
    make_employee(employees, probation_end=TODAY + timedelta(days=10))
    make_employee(employees, probation_end=TODAY + timedelta(days=200))

    items = calendar.deadlines(start=TODAY - timedelta(days=30), end=TODAY + timedelta(days=30))

    assert [item.kind.value for item in items] == ["probation_end"]
    assert items[0].due_on == TODAY + timedelta(days=10)
    assert items[0].subject_name == "Sari Dewi"


def test_a_finished_probation_is_not_relisted() -> None:
    """The state machine owns it: whoever ends probation moves the employee on,
    and the calendar must not keep nagging about a step that is already done."""
    calendar, employees, _ = make_services()
    employee = make_employee(employees, probation_end=TODAY - timedelta(days=3))
    assert employee.status is not EmployeeStatus.PROBATION

    items = calendar.deadlines(start=TODAY - timedelta(days=30), end=TODAY + timedelta(days=30))

    assert [item.kind.value for item in items] == []


def test_document_expiries_including_overdue_appear() -> None:
    """A lapsed document is exactly the state a human must fix, so it stays on
    the calendar until somebody does."""
    calendar, employees, _ = make_services()
    employee = make_employee(employees)
    employees.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="vault/ktp.pdf",
        sha256="a" * 64,
        actor=HUMAN,
        expires_on=TODAY - timedelta(days=2),
    )

    items = calendar.deadlines(start=TODAY - timedelta(days=30), end=TODAY + timedelta(days=30))

    assert [item.kind.value for item in items] == ["document_expiry"]
    assert items[0].due_on == TODAY - timedelta(days=2)
    assert items[0].detail == "ktp"


def test_contract_expiries_are_upcoming_only() -> None:
    """A lapsed contract already has its expiry task; the calendar must not
    double-report it. An expiring-soon contract inside the window appears."""
    calendar, employees, contracts = make_services()
    employee = make_employee(employees)
    soon = contracts.create(
        employee_id=employee.id,
        contract_type=ContractType.PKWT,
        start_date=TODAY - timedelta(days=300),
        end_date=TODAY + timedelta(days=20),
        actor=HUMAN,
    )
    soon = contracts.activate(soon.id, actor=HUMAN)
    assert soon.status is not None

    lapsed = contracts.create(
        employee_id=employee.id,
        contract_type=ContractType.PKWT,
        start_date=TODAY - timedelta(days=700),
        end_date=TODAY - timedelta(days=5),
        actor=HUMAN,
    )
    contracts.activate(lapsed.id, actor=HUMAN)

    far = contracts.create(
        employee_id=employee.id,
        contract_type=ContractType.PKWT,
        start_date=TODAY - timedelta(days=100),
        end_date=TODAY + timedelta(days=200),
        actor=HUMAN,
    )
    contracts.activate(far.id, actor=HUMAN)

    items = calendar.deadlines(start=TODAY - timedelta(days=30), end=TODAY + timedelta(days=30))

    assert [item.kind.value for item in items] == ["contract_expiry"]
    assert items[0].due_on == TODAY + timedelta(days=20)
    assert items[0].detail == "pkwt"


def test_inverted_window_is_refused() -> None:
    calendar, _, _ = make_services()
    with pytest.raises(CalendarError, match="end must not be before start"):
        calendar.deadlines(start=TODAY, end=TODAY - timedelta(days=1))


def test_agents_cannot_enter_or_remove_operator_dates() -> None:
    """Dates that carry legal weight are a human act; the agent boundary holds
    here exactly as it does on the rest of the compliance pack."""
    calendar, _, _ = make_services()
    agent = ActorRef.agent("policy_assistant")

    with pytest.raises(CalendarError):
        calendar.add_entry(
            title="THR payout window",
            due_on=TODAY,
            category=CalendarEntryCategory.THR,
            source_note="not the agent's call",
            actor=agent,
        )

    entry = calendar.add_entry(
        title="THR payout window",
        due_on=TODAY,
        category=CalendarEntryCategory.THR,
        source_note="HR policy 2026",
        actor=HUMAN,
    )
    with pytest.raises(CalendarError):
        calendar.remove_entry(entry_id=entry.id, actor=agent, reason="cleanup")


def test_removing_requires_a_reason_and_a_known_entry() -> None:
    from uuid import uuid4

    calendar, _, _ = make_services()
    entry = calendar.add_entry(
        title="BPJS filing",
        due_on=TODAY + timedelta(days=10),
        category=CalendarEntryCategory.BPJS,
        source_note="BPJS portal deadline",
        actor=HUMAN,
    )

    with pytest.raises(CalendarError, match="requires a reason"):
        calendar.remove_entry(entry_id=entry.id, actor=HUMAN, reason="  ")

    with pytest.raises(CalendarError) as unknown:
        calendar.remove_entry(entry_id=uuid4(), actor=HUMAN, reason="cleanup")
    assert unknown.value.code is DomainCode.UNKNOWN_RECORD
    assert calendar.entries(start=TODAY, end=TODAY + timedelta(days=30))[0].id == entry.id
