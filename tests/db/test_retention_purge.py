"""Retention purges that actually remove data, for employees and documents.

Until these tests existed, ``execute_purge`` could only report "skipped" for
every entity except consent: nothing fed the retention ledger except the
operator endpoint, and only consent had a purge handler. These tests build the
full ``PeopleServices`` composition, so the ledger feed, the handlers and the
purge mechanics are exercised together rather than assumed compatible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.people import DbEmployeeStore
from hr_agents.identity import ActorRef
from hr_agents.models import (
    DocumentKind,
    Employee,
    EmployeeDocument,
    PurgeAction,
    RecordEntity,
    RetentionRecord,
    SubjectKind,
    business_today,
)
from hr_agents.services import ComplianceService
from hr_agents.services.employees import EmployeeService
from hr_agents.services.people import PeopleServices
from hr_agents.services.people_store import EmployeeStore
from hr_agents.services.retention import RetentionLedger

HUMAN = ActorRef.legacy("hr-admin")
SWEEP = ActorRef.system("retention-sweep")
TODAY = business_today()


def make_employee(service: EmployeeService, *, full_name: str = "Sari Dewi") -> Employee:
    return service.create(
        full_name=full_name,
        actor=HUMAN,
        email="sari@example.com",
        phone="+62-812-000000",
        job_title="Finance Staff",
        work_location="Jakarta",
        hire_date=TODAY - timedelta(days=200),
        employee_number="EMP-001",
    )


def add_document(service: EmployeeService, employee_id: UUID) -> None:
    service.add_document(
        employee_id,
        kind=DocumentKind.KTP,
        storage_key="vault/ktp-sari.pdf",
        sha256="a" * 64,
        actor=HUMAN,
        filename="KTP-Sari.pdf",
    )


def set_policy(compliance: ComplianceService, entity: RecordEntity, months: int) -> None:
    compliance.set_policy(
        entity=entity,
        name=f"{entity.value} records",
        retention_months=months,
        actor=HUMAN,
    )


def backdate(compliance: ComplianceService, record: RetentionRecord, *, days: int) -> None:
    """Age a tracked record so the sweep treats it as expired. Present, not the product."""
    aged = record.model_copy(update={"anchor_at": datetime.now(UTC) - timedelta(days=days)})
    compliance._store.save_record(aged)


# --- the feed: services report what they create --------------------------------


def test_the_ledger_is_bound_in_production_composition() -> None:
    """The wiring test: without it, the feed calls below are dead code."""
    services = PeopleServices()

    assert services.employees._retention is not None
    assert services.employees._retention.bound


def test_a_bare_service_has_nowhere_to_report_and_does_not_crash() -> None:
    """Unbound is a valid state: unit tests have no compliance engine behind them."""
    ledger = RetentionLedger()
    assert not ledger.bound

    service = EmployeeService(EmployeeStore(), retention=ledger)

    employee = make_employee(service)

    assert ledger.tracked == [(RecordEntity.EMPLOYEE, SubjectKind.EMPLOYEE, str(employee.id))]


def test_creating_an_employee_tracks_it_for_retention() -> None:
    services = PeopleServices()
    employee = make_employee(services.employees)

    rows = services.compliance.list_records(entity=RecordEntity.EMPLOYEE)

    assert [row.subject_id for row in rows] == [str(employee.id)]


def test_adding_a_document_tracks_it_against_its_owner() -> None:
    """Erasure is a request about *somebody*, so the document is tracked under the
    owner's subject id; the document's own id travels in the label for a human
    reading the ledger."""
    services = PeopleServices()
    employee = make_employee(services.employees)
    add_document(services.employees, employee.id)

    rows = services.compliance.list_records(entity=RecordEntity.DOCUMENT)

    assert len(rows) == 1
    assert rows[0].subject_id == str(employee.id)
    assert rows[0].subject_kind is SubjectKind.EMPLOYEE


# --- the purge: expired records actually go ------------------------------------


def test_employee_anonymize_keeps_the_row_but_loses_the_person() -> None:
    services = PeopleServices()
    employee = make_employee(services.employees)
    set_policy(services.compliance, RecordEntity.EMPLOYEE, months=1)
    (tracked,) = services.compliance.list_records(entity=RecordEntity.EMPLOYEE)
    backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP)

    survivors = services.employees._store.get_employee(employee.id)
    assert survivors is not None
    assert survivors.full_name == "[erased]"
    assert survivors.email is None
    assert survivors.phone is None
    assert survivors.job_title is None
    assert survivors.work_location is None
    assert survivors.employee_number is None
    assert survivors.emergency_contact is None
    assert survivors.hire_date == employee.hire_date
    assert survivors.status == employee.status
    employee_outcomes = [o for o in report.purged if o.entity is RecordEntity.EMPLOYEE]
    assert len(employee_outcomes) == 1


def test_employee_delete_is_carried_out_as_anonymize_and_says_so() -> None:
    """Postgres cascades an employee-row deletion into leave, onboarding,
    payroll_lines, documents and contracts. The handler refuses that trade and
    does the closest safe equivalent -- erasing the identity while keeping the
    row the dependents point at -- and the substitution is recorded, not
    silent."""
    services = PeopleServices()
    employee = make_employee(services.employees)
    services.compliance.set_policy(
        entity=RecordEntity.EMPLOYEE,
        name="employee records",
        retention_months=1,
        expiry_action=PurgeAction.DELETE,
        actor=HUMAN,
    )
    (tracked,) = services.compliance.list_records(entity=RecordEntity.EMPLOYEE)
    backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP)

    survivor = services.employees._store.get_employee(employee.id)
    assert survivor is not None
    assert survivor.full_name == "[erased]"
    (outcome,) = report.purged
    assert "anonymized rather than deleted" in outcome.detail


def test_document_purge_deletes_the_file_rows() -> None:
    services = PeopleServices()
    employee = make_employee(services.employees)
    add_document(services.employees, employee.id)
    set_policy(services.compliance, RecordEntity.DOCUMENT, months=1)
    (tracked,) = services.compliance.list_records(entity=RecordEntity.DOCUMENT)
    backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP)

    assert services.employees._store.list_documents(employee.id) == []
    (outcome,) = report.purged
    assert "deleted 1 document" in outcome.detail
    untouched = services.employees._store.get_employee(employee.id)
    assert untouched is not None
    assert untouched.full_name != "[erased]"


def test_anonymize_policy_deletes_documents_too_and_says_why() -> None:
    """A document's filename, hash and content *are* the personal data, so there
    is no non-personal remainder to keep; the detail records that equivalence."""
    services = PeopleServices()
    employee = make_employee(services.employees)
    add_document(services.employees, employee.id)
    set_policy(services.compliance, RecordEntity.DOCUMENT, months=1)
    (tracked,) = services.compliance.list_records(entity=RecordEntity.DOCUMENT)
    backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP)

    assert services.employees._store.list_documents(employee.id) == []
    assert "no non-personal remainder" in report.purged[0].detail


def test_dry_run_mutates_nothing_but_reports_everything() -> None:
    services = PeopleServices()
    employee = make_employee(services.employees)
    add_document(services.employees, employee.id)
    set_policy(services.compliance, RecordEntity.EMPLOYEE, months=1)
    set_policy(services.compliance, RecordEntity.DOCUMENT, months=1)
    for tracked in services.compliance.list_records():
        backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP, dry_run=True)

    assert report.dry_run is True
    assert len(report.purged) == 2
    intact = services.employees._store.get_employee(employee.id)
    assert intact is not None
    assert intact.full_name == "Sari Dewi"
    assert len(services.employees._store.list_documents(employee.id)) == 1


def test_a_garbage_subject_id_does_not_abort_the_sweep() -> None:
    """The ledger accepts any string as a subject id; an operator can track
    one the handler cannot act on. The sweep must report that honestly and
    keep going, not raise."""
    services = PeopleServices()
    employee = make_employee(services.employees)
    set_policy(services.compliance, RecordEntity.EMPLOYEE, months=1)
    services.compliance.track_record(
        entity=RecordEntity.EMPLOYEE,
        subject_kind=SubjectKind.EMPLOYEE,
        subject_id="not-a-person",
        actor=HUMAN,
    )
    for tracked in services.compliance.list_records():
        backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP)

    details = {outcome.subject_id: outcome.detail for outcome in report.purged}
    assert "not an employee id" in details["not-a-person"]
    swept = services.employees._store.get_employee(employee.id)
    assert swept is not None
    assert swept.full_name == "[erased]"


def test_a_vanished_employee_reports_nothing_to_remove() -> None:
    """Emptiness is an outcome, not an error: the ledger row says what happened
    rather than the sweep pretending the record was there."""
    services = PeopleServices()
    set_policy(services.compliance, RecordEntity.EMPLOYEE, months=1)
    services.compliance.track_record(
        entity=RecordEntity.EMPLOYEE,
        subject_kind=SubjectKind.EMPLOYEE,
        subject_id="0" * 32,
        actor=HUMAN,
    )
    (tracked,) = services.compliance.list_records()
    backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP)

    assert "nothing to remove" in report.purged[0].detail


def test_held_records_are_never_touched() -> None:
    services = PeopleServices()
    services.compliance.track_record(
        entity=RecordEntity.DOCUMENT,
        subject_kind=SubjectKind.EMPLOYEE,
        subject_id="legal-matter-7",
        actor=HUMAN,
    )
    record = services.compliance.list_records()[0]
    set_policy(services.compliance, RecordEntity.DOCUMENT, months=1)
    backdate(services.compliance, record, days=60)
    held = services.compliance._store.get_record(record.id)
    assert held is not None
    services.compliance.set_legal_hold(held.id, held=True, actor=HUMAN, reason="litigation")

    report = services.compliance.execute_purge(actor=SWEEP)

    assert report.purged == []
    assert report.held == [record.id]
    reread = services.compliance._store.get_record(record.id)
    assert reread is not None
    assert reread.purged_at is None


# --- the sql adapter keeps the same contract -----------------------------------


def test_sql_adapter_anonymizes_and_deletes(factory: sessionmaker[Session]) -> None:
    store = DbEmployeeStore(factory)
    employee = make_employee(EmployeeService(store))
    add_documents_via(store, employee)

    anonymized = store.anonymize_employee(employee.id)
    assert anonymized is not None
    assert anonymized.full_name == "[erased]"

    documents = store.list_documents(employee.id)
    assert len(documents) == 2
    assert store.delete_document(documents[0].id) is True
    assert store.delete_document(documents[0].id) is False
    assert len(store.list_documents(employee.id)) == 1


def add_documents_via(store: DbEmployeeStore, employee: Employee) -> None:
    for index in range(2):
        store.add_document(
            EmployeeDocument(
                id=uuid4(),
                employee_id=employee.id,
                kind=DocumentKind.KTP,
                storage_key=f"vault/ktp-{index}.pdf",
                sha256="b" * 64,
            )
        )
