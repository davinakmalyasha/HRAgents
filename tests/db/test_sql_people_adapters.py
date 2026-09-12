"""People store adapter tests on in-memory SQLite."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.people import (
    DbApprovalStore,
    DbContractStore,
    DbEmployeeStore,
    DbRateTableStore,
    DbTaskStore,
)
from hr_agents.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    Contract,
    ContractStatus,
    ContractType,
    DocumentKind,
    EmergencyContact,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    OrgUnit,
    RateEntry,
    RateTable,
    RateTableKind,
    TaskItem,
    TaskStatus,
)


def _add_employee(store: DbEmployeeStore, name: str = "Sari Dewi") -> Employee:
    employee = Employee(full_name=name, email="sari@example.com", status=EmployeeStatus.ACTIVE)
    store.add_employee(employee)
    return employee


def test_employee_store_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbEmployeeStore(factory)
    unit = OrgUnit(name="Engineering", cost_center="ENG")
    store.add_org_unit(unit)
    employee = Employee(
        full_name="Sari Dewi",
        email="sari@example.com",
        job_title="Finance Staff",
        org_unit_id=unit.id,
        status=EmployeeStatus.ACTIVE,
        hire_date=date(2026, 1, 5),
        emergency_contact=EmergencyContact(name="Budi", phone="0812"),
    )
    store.add_employee(employee)

    fresh = DbEmployeeStore(factory)
    loaded = fresh.get_employee(employee.id)
    assert loaded is not None
    assert loaded.full_name == "Sari Dewi"
    assert loaded.hire_date == date(2026, 1, 5)
    assert loaded.emergency_contact is not None
    assert loaded.emergency_contact.name == "Budi"
    assert loaded.emergency_contact.phone == "0812"
    loaded.status = EmployeeStatus.NOTICE_PERIOD
    fresh.save_employee(loaded)

    updated = DbEmployeeStore(factory).get_employee(employee.id)
    assert updated is not None
    assert updated.status is EmployeeStatus.NOTICE_PERIOD

    assert [unit.name for unit in fresh.list_org_units()] == ["Engineering"]
    assert [item.full_name for item in fresh.list_employees()] == ["Sari Dewi"]

    document = EmployeeDocument(
        employee_id=employee.id,
        kind=DocumentKind.KTP,
        storage_key="docs/ktp.pdf",
        sha256="a" * 64,
    )
    fresh.add_document(document)
    assert [doc.id for doc in fresh.list_documents(employee.id)] == [document.id]
    assert fresh.list_documents(uuid4()) == []


def test_contract_store_round_trip(factory: sessionmaker[Session]) -> None:
    employees = DbEmployeeStore(factory)
    employee = _add_employee(employees)

    store = DbContractStore(factory)
    contract = Contract(
        employee_id=employee.id,
        contract_type=ContractType.PKWT,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        compensation_due=True,
    )
    store.add(contract)

    loaded = DbContractStore(factory).get(contract.id)
    assert loaded is not None
    assert loaded.contract_type is ContractType.PKWT
    assert loaded.compensation_due is True

    loaded.status = ContractStatus.ACTIVE
    loaded.notes = "Signed at HQ"
    DbContractStore(factory).save(loaded)
    persisted = DbContractStore(factory).list_for_employee(employee.id)
    assert [item.id for item in persisted] == [contract.id]
    assert persisted[0].status is ContractStatus.ACTIVE
    assert persisted[0].notes == "Signed at HQ"


def test_approval_store_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbApprovalStore(factory)
    request = ApprovalRequest(
        subject=ApprovalSubject.LEAVE_REQUEST,
        subject_id="leave-1",
        title="Approve annual leave",
        summary="3 days in October",
        requested_by="hr-admin",
        assignee_role=ApproverRole.MANAGER,
    )
    store.add(request)

    loaded = DbApprovalStore(factory).get(request.id)
    assert loaded is not None
    assert loaded.status is ApprovalStatus.PENDING
    assert loaded.payload == {}

    loaded.status = ApprovalStatus.APPROVED
    loaded.decided_by = "manager-1"
    loaded.decided_at = datetime.now(UTC)
    loaded.decision_reason = "Approved"
    DbApprovalStore(factory).save(loaded)
    persisted = DbApprovalStore(factory).list_all()
    assert [item.id for item in persisted] == [request.id]
    assert persisted[0].decided_by == "manager-1"
    assert persisted[0].status is ApprovalStatus.APPROVED


def test_task_store_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbTaskStore(factory)
    task = TaskItem(
        title="Collect KTP",
        description="Onboarding",
        assignee_role=ApproverRole.HR_ADMIN,
    )
    store.add(task)

    loaded = DbTaskStore(factory).get(task.id)
    assert loaded is not None
    assert loaded.status is TaskStatus.OPEN

    loaded.status = TaskStatus.DONE
    loaded.completed_by = "hr-admin"
    DbTaskStore(factory).save(loaded)
    persisted = DbTaskStore(factory).list_all()
    assert persisted[0].status is TaskStatus.DONE
    assert persisted[0].completed_by == "hr-admin"


def test_rate_table_store_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbRateTableStore(factory)
    table = RateTable(
        kind=RateTableKind.OVERTIME_PREMIUM,
        name="Overtime premium 2026",
        entries=[RateEntry(label="First hour", multiplier=1.5)],
    )
    store.add(table)

    loaded = DbRateTableStore(factory).get(table.id)
    assert loaded is not None
    assert loaded.verified is False
    assert loaded.entries[0].label == "First hour"
    assert loaded.entries[0].multiplier == 1.5

    loaded.verified = True
    loaded.verified_by = "hr-admin"
    DbRateTableStore(factory).save(loaded)
    persisted = DbRateTableStore(factory).list_all()
    assert persisted[0].verified is True
    assert persisted[0].verified_by == "hr-admin"
