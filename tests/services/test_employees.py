from datetime import date, timedelta
from uuid import uuid4

import pytest

from hr_agents.models import (
    ApprovalSubject,
    ApproverRole,
    DocumentKind,
    Employee,
    EmployeeStatus,
    VerificationStatus,
)
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    EmployeeError,
    EmployeeService,
    EmployeeStore,
)
from hr_agents.services.audit import AuditChain

TODAY = date.today()


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def approvals(audit: AuditChain) -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=audit)


@pytest.fixture
def service(audit: AuditChain, approvals: ApprovalEngine) -> EmployeeService:
    return EmployeeService(EmployeeStore(), audit=audit, approvals=approvals)


def create_employee(
    service: EmployeeService,
    *,
    full_name: str = "Sari Dewi",
    hire_date: date | None = None,
    probation_end_date: date | None = None,
    job_title: str = "Finance Staff",
) -> Employee:
    return service.create(
        full_name=full_name,
        created_by="hr-admin",
        hire_date=hire_date if hire_date is not None else TODAY - timedelta(days=200),
        probation_end_date=probation_end_date,
        job_title=job_title,
    )


# --- creation ---------------------------------------------------------------


def test_create_requires_hire_date(service: EmployeeService) -> None:
    with pytest.raises(EmployeeError, match="hire_date"):
        service.create(full_name="X", created_by="hr")


def test_create_sets_active_for_past_hire(service: EmployeeService) -> None:
    employee = create_employee(service)
    assert employee.status is EmployeeStatus.ACTIVE


def test_create_sets_onboarding_for_future_hire(service: EmployeeService) -> None:
    employee = create_employee(service, hire_date=TODAY + timedelta(days=14))
    assert employee.status is EmployeeStatus.ONBOARDING


def test_create_with_future_probation_end_sets_probation(service: EmployeeService) -> None:
    employee = create_employee(service, probation_end_date=TODAY + timedelta(days=60))
    assert employee.status is EmployeeStatus.PROBATION


def test_create_audits(service: EmployeeService, audit: AuditChain) -> None:
    create_employee(service)
    assert audit.verify() == -1
    assert audit.entries[-1].action == "employee.created"


# --- lifecycle transitions ---------------------------------------------------


def test_legal_transition_active_to_notice(service: EmployeeService) -> None:
    employee = create_employee(service)
    updated = service.transition(employee.id, target=EmployeeStatus.NOTICE_PERIOD, by="hr-admin")
    assert updated.status is EmployeeStatus.NOTICE_PERIOD


def test_illegal_transition_rejected(service: EmployeeService) -> None:
    employee = create_employee(service)
    with pytest.raises(EmployeeError, match="illegal transition"):
        service.transition(employee.id, target=EmployeeStatus.PROBATION, by="hr-admin")


def test_offboarding_sets_date(service: EmployeeService) -> None:
    employee = create_employee(service)
    offboarded = service.transition(employee.id, target=EmployeeStatus.OFFBOARDED, by="hr-admin")
    assert offboarded.offboarded_on == TODAY


def test_offboarding_blocked_by_open_approval(
    service: EmployeeService, approvals: ApprovalEngine
) -> None:
    employee = create_employee(service)
    approvals.create(
        subject=ApprovalSubject.DATA_CHANGE,
        subject_id=str(employee.id),
        title="Update bank account",
        assignee_role=ApproverRole.HR_ADMIN,
        requested_by="hr-staff",
    )
    with pytest.raises(EmployeeError, match="blocked by open items"):
        service.transition(employee.id, target=EmployeeStatus.OFFBOARDED, by="hr-admin")


def test_forced_offboarding_requires_reason(
    service: EmployeeService, approvals: ApprovalEngine
) -> None:
    employee = create_employee(service)
    approvals.create(
        subject=ApprovalSubject.DATA_CHANGE,
        subject_id=str(employee.id),
        title="Open item",
        assignee_role=ApproverRole.HR_ADMIN,
        requested_by="hr-staff",
    )
    with pytest.raises(EmployeeError, match="requires a reason"):
        service.transition(employee.id, target=EmployeeStatus.OFFBOARDED, by="hr-admin", force=True)


def test_forced_offboarding_with_reason_succeeds(
    service: EmployeeService, approvals: ApprovalEngine, audit: AuditChain
) -> None:
    employee = create_employee(service)
    approvals.create(
        subject=ApprovalSubject.DATA_CHANGE,
        subject_id=str(employee.id),
        title="Open item",
        assignee_role=ApproverRole.HR_ADMIN,
        requested_by="hr-staff",
    )
    offboarded = service.transition(
        employee.id,
        target=EmployeeStatus.OFFBOARDED,
        by="hr-admin",
        force=True,
        reason="employee resigned; approval superseded",
    )
    assert offboarded.status is EmployeeStatus.OFFBOARDED
    forced_entries = [
        entry for entry in audit.entries if entry.action == "employee.transition.offboarded"
    ]
    assert forced_entries and forced_entries[-1].payload["forced"] is True


# --- documents ---------------------------------------------------------------


def test_add_document_records_and_lists(service: EmployeeService) -> None:
    employee = create_employee(service)
    document = service.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="employees/ktp-1.pdf",
        sha256="a" * 64,
        uploaded_by="hr-admin",
        expires_on=TODAY + timedelta(days=30),
    )
    assert document.status is VerificationStatus.CLAIMED
    assert service._store.list_documents(employee.id)


def test_expiring_documents_window(service: EmployeeService) -> None:
    employee = create_employee(service)
    service.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="k1",
        sha256="a" * 64,
        uploaded_by="hr",
        expires_on=TODAY + timedelta(days=20),
    )
    service.add_document(
        employee.id,
        kind=DocumentKind.NPWP,
        storage_key="k2",
        sha256="b" * 64,
        uploaded_by="hr",
        expires_on=TODAY + timedelta(days=200),
    )
    expiring = service.expiring_documents(within_days=30)
    assert [doc.kind for doc in expiring] == [DocumentKind.KTP]


def test_mark_document_verified(service: EmployeeService) -> None:
    employee = create_employee(service)
    document = service.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="k1",
        sha256="a" * 64,
        uploaded_by="hr",
    )
    verified = service.mark_document_verified(document.id, verified_by="hr-admin", verified=True)
    assert verified.status is VerificationStatus.VERIFIED

    failed = service.mark_document_verified(document.id, verified_by="hr-admin", verified=False)
    assert failed.status is VerificationStatus.FAILED


# --- org units & queries -----------------------------------------------------


def test_org_unit_hierarchy(service: EmployeeService) -> None:
    parent = service.create_org_unit(name="Operations", created_by="hr")
    child = service.create_org_unit(name="Finance", created_by="hr", parent_id=parent.id)
    assert child.parent_id == parent.id


def test_org_unit_unknown_parent_rejected(service: EmployeeService) -> None:
    with pytest.raises(EmployeeError, match="unknown parent"):
        service.create_org_unit(name="X", created_by="hr", parent_id=uuid4())


def test_on_probation_filter(service: EmployeeService) -> None:
    create_employee(service, full_name="Active Person")
    create_employee(
        service,
        full_name="Probation Person",
        probation_end_date=TODAY + timedelta(days=30),
    )
    assert [emp.full_name for emp in service.on_probation()] == ["Probation Person"]


def test_unknown_employee_raises(service: EmployeeService) -> None:
    with pytest.raises(EmployeeError, match="unknown employee"):
        service.get(uuid4())
