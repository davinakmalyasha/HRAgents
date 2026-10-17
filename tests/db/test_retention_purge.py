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
from tests.services.test_payroll import seed_verified_tables

from hr_agents.db.application import DbApplicationStore
from hr_agents.db.people import DbEmployeeStore
from hr_agents.db.tables import Candidate
from hr_agents.identity import ActorRef
from hr_agents.models import (
    DocumentKind,
    Employee,
    EmployeeDocument,
    PayrollInput,
    PayrollRun,
    PayrollRunStatus,
    PurgeAction,
    RecordEntity,
    RetentionRecord,
    SubjectKind,
    business_today,
)
from hr_agents.models.money import money as m
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    ComplianceService,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.ingestion import (
    ApplicationRecord,
    ApplicationStore,
    SubmissionInput,
)
from hr_agents.services.payroll import payroll_purge_handler
from hr_agents.services.people import PeopleServices
from hr_agents.services.people_store import ComplianceStore, EmployeeStore
from hr_agents.services.recruiting import (
    RecruitingServices,
    register_recruitment_purge_handlers,
)
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


# --- recruitment: the candidate is the person ----------------------------------


def recruit(
    factory: sessionmaker[Session], *, candidate_name: str = "Budi Santoso"
) -> tuple[DbApplicationStore, ApplicationRecord]:
    """One submission through the real store, so candidate and application rows exist."""
    applications = DbApplicationStore(factory)
    services = RecruitingServices(
        audit=AuditChain(), applications=applications, session_factory=factory
    )
    job = services.jobs.create(title="Backend Engineer", actor=HUMAN)
    record, created = applications.submit(
        SubmissionInput(
            job_id=job.id,
            source_channel="api",
            consent_granted=True,
            candidate_name=candidate_name,
            candidate_emails=["budi@example.com"],
        )
    )
    assert created is True
    return applications, record


def compliance_over(applications: ApplicationStore) -> ComplianceService:
    audit = AuditChain()
    compliance = ComplianceService(
        ComplianceStore(), approvals=ApprovalEngine(ApprovalStore(), audit=audit), audit=audit
    )
    register_recruitment_purge_handlers(compliance, applications)
    return compliance


def test_candidate_anonymize_blanks_the_row_and_keeps_it(
    factory: sessionmaker[Session],
) -> None:
    """The funnel cascades off the candidate row, so erasure blanks, never deletes."""
    applications, record = recruit(factory)
    compliance = compliance_over(applications)
    compliance.track_record(
        entity=RecordEntity.CANDIDATE,
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=str(record.candidate_id),
        actor=HUMAN,
        label="Budi Santoso",
    )
    set_policy(compliance, RecordEntity.CANDIDATE, months=1)
    (tracked,) = compliance.list_records()
    backdate(compliance, tracked, days=60)

    report = compliance.execute_purge(actor=SWEEP)

    with factory() as session:
        row = session.get(Candidate, record.candidate_id)
        assert row is not None
        assert row.full_name == "[erased]"
        assert row.primary_email is None
        assert row.location is None
        assert row.profile == {}
        assert row.deleted_at is None, "anonymize is not a deletion"
    (outcome,) = report.purged
    assert "blanked candidate name" in outcome.detail


def test_candidate_delete_is_carried_out_as_a_soft_delete(factory: sessionmaker[Session]) -> None:
    """A hard delete would cascade into applications and evaluations, so the
    handler marks the row deleted instead and records the substitution."""
    applications, record = recruit(factory)
    compliance = compliance_over(applications)
    compliance.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="candidate records",
        retention_months=1,
        expiry_action=PurgeAction.DELETE,
        actor=HUMAN,
    )
    compliance.track_record(
        entity=RecordEntity.CANDIDATE,
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=str(record.candidate_id),
        actor=HUMAN,
    )
    (tracked,) = compliance.list_records()
    backdate(compliance, tracked, days=60)

    report = compliance.execute_purge(actor=SWEEP)

    with factory() as session:
        row = session.get(Candidate, record.candidate_id)
        assert row is not None
        assert row.deleted_at is not None
        assert row.full_name == "[erased]"
    (outcome,) = report.purged
    assert "marked the row deleted" in outcome.detail


def test_application_rows_report_that_they_name_nobody(factory: sessionmaker[Session]) -> None:
    """The application entity gets a handler so a sweep never logs a missing one.

    Its rows hold job, status, scores and timeline -- records about a process.
    The handler says so and marks the ledger row satisfied rather than deleting
    the funnel entry and its evaluations along with it.
    """
    applications, record = recruit(factory)
    compliance = compliance_over(applications)
    compliance.track_record(
        entity=RecordEntity.APPLICATION,
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=str(record.candidate_id),
        actor=HUMAN,
    )
    set_policy(compliance, RecordEntity.APPLICATION, months=1)
    (tracked,) = compliance.list_records()
    backdate(compliance, tracked, days=60)

    report = compliance.execute_purge(actor=SWEEP)

    assert applications.get(record.id) is not None, "the funnel entry must survive"
    (outcome,) = report.purged
    assert "name nobody" in outcome.detail


def test_memory_backend_says_it_stores_no_candidate() -> None:
    """The in-memory store keeps no candidate row, so the honest answer is that
    there is nothing on this backend to erase -- not a pretend mutation."""
    compliance = compliance_over(ApplicationStore())
    compliance.track_record(
        entity=RecordEntity.CANDIDATE,
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=str(uuid4()),
        actor=HUMAN,
    )
    set_policy(compliance, RecordEntity.CANDIDATE, months=1)
    (tracked,) = compliance.list_records()
    backdate(compliance, tracked, days=60)

    report = compliance.execute_purge(actor=SWEEP)

    (outcome,) = report.purged
    assert "not stored on this backend" in outcome.detail


# --- payroll: pseudonymize the money, keep the trail ---------------------------


def _exported_payroll(services: PeopleServices) -> tuple[Employee, PayrollRun]:
    """One employee, one computed-then-exported run, verified tables.

    Export is the tracking moment: the run is approved and frozen, so this is
    the state a purge can meaningfully act on.
    """
    seed_verified_tables(services.rate_tables)
    employee = make_employee(services.employees)
    run = services.payroll.create_run(period_year=TODAY.year, period_month=6, actor=HUMAN)
    services.payroll.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(10_000_000))],
        actor=HUMAN,
    )
    computed = services.payroll.compute(run.id, actor=HUMAN)
    approved = computed.model_copy(update={"status": PayrollRunStatus.APPROVED})
    services.payroll._save_run(approved)
    services.payroll.mark_exported(computed.id, actor=HUMAN)
    return employee, computed


def test_exporting_a_run_tracks_its_lines_for_retention() -> None:
    services = PeopleServices()
    employee, _ = _exported_payroll(services)

    rows = services.compliance.list_records(entity=RecordEntity.PAYROLL)

    assert [row.subject_id for row in rows] == [str(employee.id)]
    assert rows[0].subject_kind is SubjectKind.EMPLOYEE
    assert f"{TODAY.year}-06" in rows[0].label


def test_payroll_purge_pseudonymizes_lines_and_keeps_the_figures() -> None:
    services = PeopleServices()
    _, computed = _exported_payroll(services)
    before = computed.lines[0]

    set_policy(services.compliance, RecordEntity.PAYROLL, months=1)
    (tracked,) = services.compliance.list_records(entity=RecordEntity.PAYROLL)
    backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP)

    (outcome,) = [item for item in report.purged if item.entity is RecordEntity.PAYROLL]
    assert "pseudonymized" in outcome.detail
    after = services.payroll.get_run(computed.id).lines[0]
    assert after.employee_name == "[erased]"
    assert after.employee_id == before.employee_id
    assert after.gross == before.gross
    assert after.net == before.net
    assert after.total_deductions == before.total_deductions
    assert after.pph21 == before.pph21


def test_payroll_delete_is_carried_out_as_pseudonym_and_says_so() -> None:
    """A payroll row is a tax record: deleting it destroys figures a third
    party may need to reconcile. The handler does the safe equivalent and the
    detail names the substitution instead of pretending."""
    services = PeopleServices()
    _, computed = _exported_payroll(services)

    services.compliance.set_policy(
        entity=RecordEntity.PAYROLL,
        name="payroll records",
        retention_months=1,
        expiry_action=PurgeAction.DELETE,
        actor=HUMAN,
    )
    (tracked,) = services.compliance.list_records(entity=RecordEntity.PAYROLL)
    backdate(services.compliance, tracked, days=60)

    report = services.compliance.execute_purge(actor=SWEEP)

    (outcome,) = [item for item in report.purged if item.entity is RecordEntity.PAYROLL]
    assert "rather than deleted" in outcome.detail
    survivor = services.payroll.get_run(computed.id).lines[0]
    assert survivor.employee_name == "[erased]"
    assert survivor.net > 0


def test_a_second_payroll_purge_reports_lines_already_pseudonymized() -> None:
    services = PeopleServices()
    _, computed = _exported_payroll(services)
    set_policy(services.compliance, RecordEntity.PAYROLL, months=1)
    (tracked,) = services.compliance.list_records(entity=RecordEntity.PAYROLL)
    backdate(services.compliance, tracked, days=60)
    services.compliance.execute_purge(actor=SWEEP)

    handler = payroll_purge_handler(services.payroll)
    detail = handler(tracked, PurgeAction.ANONYMIZE)

    assert "already carry the erasure pseudonym" in detail
    assert services.payroll.get_run(computed.id).lines[0].employee_name == "[erased]"


def test_payroll_purge_touches_only_the_named_employee() -> None:
    services = PeopleServices()
    seed_verified_tables(services.rate_tables)
    sari = make_employee(services.employees, full_name="Sari Dewi")
    budi = make_employee(services.employees, full_name="Budi Santoso")
    run = services.payroll.create_run(period_year=TODAY.year, period_month=6, actor=HUMAN)
    services.payroll.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=sari.id, base_salary=m(10_000_000)),
            PayrollInput(employee_id=budi.id, base_salary=m(8_000_000)),
        ],
        actor=HUMAN,
    )
    computed = services.payroll.compute(run.id, actor=HUMAN)

    services.compliance.track_record(
        entity=RecordEntity.PAYROLL,
        subject_kind=SubjectKind.EMPLOYEE,
        subject_id=str(sari.id),
        actor=HUMAN,
    )
    set_policy(services.compliance, RecordEntity.PAYROLL, months=1)
    (tracked,) = services.compliance.list_records(entity=RecordEntity.PAYROLL)
    backdate(services.compliance, tracked, days=60)

    services.compliance.execute_purge(actor=SWEEP)

    names = {line.employee_name for line in services.payroll.get_run(computed.id).lines}
    assert names == {"[erased]", "Budi Santoso"}
    handler = payroll_purge_handler(services.payroll)
    unknown = tracked.model_copy(update={"subject_id": str(uuid4())})
    assert "nothing to remove" in handler(unknown, PurgeAction.ANONYMIZE)
    assert "not an employee id" in handler(
        tracked.model_copy(update={"subject_id": "subject-without-uuid"}),
        PurgeAction.ANONYMIZE,
    )
