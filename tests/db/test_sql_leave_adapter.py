"""Leave adapter tests on in-memory SQLite.

Two of these are regression tests for silent loss rather than visible loss. A
missing leave request is obvious -- the employee sees an empty list. A missing
balance adjustment and a missing holiday calendar are not: the balance reads
correct-ish and the working-day count is simply wrong, and nothing reports it.

Every read goes through a fresh adapter instance so a fallback to the in-process
dicts would fail here rather than in production.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.leave import DbLeaveService
from hr_agents.db.people import DbApprovalStore, DbEmployeeStore
from hr_agents.identity import ActorRef
from hr_agents.models import (
    AccrualMethod,
    ApprovalRequest,
    ApprovalSubject,
    ApproverRole,
    DocumentKind,
    Employee,
    LeaveRequest,
    LeaveType,
    LeaveTypePolicy,
    RequestStatus,
    business_today,
)
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService

TODAY = business_today()
ACTOR = ActorRef.legacy("hr-admin")
YEAR = TODAY.year


def _service(factory: sessionmaker[Session]) -> DbLeaveService:
    audit = AuditChain()
    # The approval engine must write through the database too: a leave request
    # persists its approval_id, and `leave_requests.approval_id` is a foreign
    # key the tests enforce (conftest sets `PRAGMA foreign_keys=ON` on SQLite,
    # and CI runs the same suite on Postgres).
    approvals = ApprovalEngine(DbApprovalStore(factory), audit=audit)
    # The employee must be a real row: leave_requests.employee_id is a foreign
    # key, so an in-memory employee passed locally and failed on Postgres in CI.
    employees = EmployeeService(DbEmployeeStore(factory), audit=audit, approvals=approvals)
    return DbLeaveService(factory, employees=employees, approvals=approvals, audit=audit)


def _employee(service: DbLeaveService, name: str = "Sari Dewi") -> Employee:
    return service._employees.create(
        full_name=name, actor=ACTOR, hire_date=TODAY - timedelta(days=365)
    )


def _policy() -> LeaveTypePolicy:
    return LeaveTypePolicy(
        leave_type=LeaveType.ANNUAL,
        name="Annual leave",
        paid=True,
        approver_role=ApproverRole.MANAGER,
        accrual_method=AccrualMethod.FLAT_MONTHLY,
        days_per_month=1.75,
        max_days_per_request=12,
        working_days_only=True,
    )


def _request(
    employee: Employee,
    *,
    days: float = 3.0,
    start_in_days: int = 30,
    status: RequestStatus = RequestStatus.DRAFT,
) -> LeaveRequest:
    return LeaveRequest(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=TODAY + timedelta(days=start_in_days),
        end_date=TODAY + timedelta(days=start_in_days + int(days) - 1),
        days=days,
        reason="Family event",
        status=status,
    )


def test_leave_request_round_trip(factory: sessionmaker[Session]) -> None:
    service = _service(factory)
    employee = _employee(service)
    record = _request(employee)

    service._save_request(record)

    fresh = _service(factory)
    loaded = fresh._load_request(record.id)
    assert loaded is not None
    assert loaded.employee_id == employee.id
    assert loaded.leave_type is LeaveType.ANNUAL
    assert loaded.days == 3.0
    assert loaded.reason == "Family event"
    assert loaded.created_at.tzinfo is not None

    assert fresh._load_request(uuid4()) is None
    assert [item.id for item in fresh._iter_requests()] == [record.id]


def test_leave_request_update_persists(factory: sessionmaker[Session]) -> None:
    """An approved request must not revert to draft when the process restarts."""
    service = _service(factory)
    employee = _employee(service)
    record = _request(employee)
    approval = ApprovalRequest(
        subject=ApprovalSubject.LEAVE_REQUEST,
        subject_id=str(record.id),
        title="Approve annual leave",
        summary="3 days",
        requested_by="hr-admin",
        assignee_role=ApproverRole.MANAGER,
    )
    DbApprovalStore(factory).add(approval)
    service._save_request(record)
    service._save_request(
        record.model_copy(update={"status": RequestStatus.APPROVED, "approval_id": approval.id})
    )

    loaded = _service(factory)._load_request(record.id)
    assert loaded is not None
    assert loaded.status is RequestStatus.APPROVED
    assert loaded.approval_id == approval.id


def test_policy_round_trip(factory: sessionmaker[Session]) -> None:
    """A lost policy fails closed with \"no policy configured\".

    That is the acceptable loss of the four, which is why the other three are tested
    against silent-wrongness instead.
    """
    service = _service(factory)
    policy = _policy()
    service.set_policy(policy, actor=ACTOR)

    fresh = _service(factory)
    loaded = fresh.get_policy(LeaveType.ANNUAL)
    assert loaded.name == "Annual leave"
    assert loaded.accrual_method is AccrualMethod.FLAT_MONTHLY
    assert loaded.days_per_month == 1.75
    assert [item.leave_type for item in fresh.list_policies()] == [LeaveType.ANNUAL]


def test_policy_update_replaces_rather_than_duplicates(factory: sessionmaker[Session]) -> None:
    service = _service(factory)
    service.set_policy(_policy(), actor=ACTOR)
    service.set_policy(
        _policy().model_copy(update={"days_per_month": 2.0, "max_days_per_request": 17}),
        actor=ACTOR,
    )

    fresh = _service(factory)
    assert len(fresh.list_policies()) == 1
    loaded = fresh.get_policy(LeaveType.ANNUAL)
    assert loaded.days_per_month == 2.0
    assert loaded.max_days_per_request == 17


def test_balance_adjustment_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """Regression: a lost adjustment silently overstates the employee's balance.

    The adjustment is a signed correction HR enters. Dropping it leaves the balance
    looking plausible and wrong, with nothing in the UI or the audit trail to say so.
    """
    service = _service(factory)
    # djust_balance requires the policy to exist, so it exercises the persisted
    # policy rather than skipping the gate.
    service.set_policy(_policy(), actor=ACTOR)
    employee = _employee(service)
    service.adjust_balance(employee.id, LeaveType.ANNUAL, days=2.5, year=YEAR, actor=ACTOR)

    fresh = _service(factory)
    assert fresh._load_adjustment(employee.id, LeaveType.ANNUAL, YEAR) == 2.5
    assert fresh._load_adjustment(employee.id, LeaveType.SICK, YEAR) == 0.0


def test_repeat_adjustments_accumulate_onto_one_row(factory: sessionmaker[Session]) -> None:
    """(employee, type, year) is the identity; a second adjustment must add to it."""
    service = _service(factory)
    # djust_balance requires the policy to exist, so it exercises the persisted
    # policy rather than skipping the gate.
    service.set_policy(_policy(), actor=ACTOR)
    employee = _employee(service)
    service.adjust_balance(employee.id, LeaveType.ANNUAL, days=1.0, year=YEAR, actor=ACTOR)
    service.adjust_balance(employee.id, LeaveType.ANNUAL, days=2.5, year=YEAR, actor=ACTOR)

    fresh = _service(factory)
    assert fresh._load_adjustment(employee.id, LeaveType.ANNUAL, YEAR) == 3.5


def test_holiday_calendar_survives_a_restart_and_changes_working_days(
    factory: sessionmaker[Session],
) -> None:
    """Regression: a lost calendar silently counts a public holiday as working.

    Nothing reports it. `working_days` just returns one day too many, the employee's
    balance is over-consumed, and the payroll proration that depends on it is wrong
    too.
    """
    monday = TODAY + timedelta(days=(7 - TODAY.weekday()) % 7 or 7)
    service = _service(factory)
    service.set_holidays([monday], actor=ACTOR)

    fresh = _service(factory)
    assert fresh.is_working_day(monday) is False
    assert fresh.working_days(monday, monday) == 0
    assert fresh.working_days(monday + timedelta(days=7), monday + timedelta(days=7)) == 1


def test_setting_holidays_replaces_the_calendar(factory: sessionmaker[Session]) -> None:
    monday = TODAY + timedelta(days=(7 - TODAY.weekday()) % 7 or 7)
    tuesday = monday + timedelta(days=1)
    service = _service(factory)
    service.set_holidays([monday, tuesday], actor=ACTOR)
    service.set_holidays([monday], actor=ACTOR)

    fresh = _service(factory)
    assert fresh.is_working_day(monday) is False
    assert fresh.is_working_day(tuesday) is True


def test_requests_for_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """The employee-facing list is the regression an operator would actually hit."""
    service = _service(factory)
    employee = _employee(service)
    other = _employee(service, "Budi")
    mine = _request(employee)
    service._save_request(mine)
    service._save_request(_request(other))

    fresh = _service(factory)
    assert [item.id for item in fresh.requests_for(employee.id)] == [mine.id]
    assert [item.employee_id for item in fresh.requests_for(other.id)] == [other.id]
    # `pending_requests` reads across every employee's rows, which is the other
    # cross-row aggregation that had no seam before.
    assert fresh.pending_requests() == []


def test_document_id_must_name_a_vault_document(factory: sessionmaker[Session]) -> None:
    """The supporting document is a real row, and the database holds it so.

    The service checks the id before saving; this test also writes a made-up
    id past the service check and proves the foreign key refuses it, so no
    future caller can reintroduce an orphaned reference.
    """
    service = _service(factory)
    employee = _employee(service)
    document = service._employees.add_document(
        employee.id,
        kind=DocumentKind.OTHER,
        storage_key="vault/sick-note.pdf",
        sha256="a" * 64,
        actor=ACTOR,
    )

    record = _request(employee).model_copy(update={"document_id": document.id})
    service._save_request(record)
    loaded = _service(factory)._load_request(record.id)
    assert loaded is not None
    assert loaded.document_id == document.id

    dangling = _request(employee).model_copy(update={"document_id": uuid4()})
    with pytest.raises(IntegrityError):
        service._save_request(dangling)


def test_page_on_leave_filters_the_day_in_sql(factory: sessionmaker[Session]) -> None:
    """The calendar reads the day's approved requests, not every request ever filed.

    Overlap is inclusive on both ends (``start_date <= day <= end_date``) and
    only approved requests count; the id tiebreak keeps same-day paging stable.
    """
    service = _service(factory)
    employee = _employee(service)
    early = _request(employee, start_in_days=0, days=3, status=RequestStatus.APPROVED)
    late = _request(employee, start_in_days=1, days=2, status=RequestStatus.APPROVED)
    outside = _request(employee, start_in_days=10, days=1, status=RequestStatus.APPROVED)
    pending = _request(employee, start_in_days=0, days=3, status=RequestStatus.PENDING)
    for request in (early, late, outside, pending):
        service._save_request(request)

    target = TODAY + timedelta(days=1)
    page, total = service.page_on_leave(on_date=target, limit=10, offset=0)
    assert total == 2, "pending and non-overlapping requests are not the calendar"
    assert [item.id for item in page] == [early.id, late.id]

    second, second_total = service.page_on_leave(on_date=target, limit=1, offset=1)
    assert second_total == 2
    assert [item.id for item in second] == [late.id]

    today_page, today_total = service.page_on_leave(on_date=None, limit=10, offset=0)
    assert today_total == 1, "no on_date means the business day"
    assert [item.id for item in today_page] == [early.id]


def test_page_requests_pushes_predicate_order_and_limit_into_sql(
    factory: sessionmaker[Session],
) -> None:
    """The paged read keeps the two filters apart and counts in the same call.

    `page_requests(employee_id=None)` is the pending sweep; an id is that
    employee's whole history. Both order by ``(start_date, id)`` in the
    database, so OFFSET cannot shuffle rows whose dates collide.
    """
    service = _service(factory)
    employee = _employee(service)
    other = _employee(service, "Budi")
    for start_in_days in (3, 1, 2):
        service._save_request(
            _request(employee, start_in_days=start_in_days, status=RequestStatus.PENDING)
        )
    service._save_request(_request(other, start_in_days=5, status=RequestStatus.PENDING))
    draft = _request(employee, start_in_days=0)
    service._save_request(draft)

    fresh = _service(factory)
    pending_page, pending_total = fresh.page_requests(employee_id=None, limit=2, offset=1)
    assert pending_total == 4
    assert [item.start_date for item in pending_page] == [
        TODAY + timedelta(days=2),
        TODAY + timedelta(days=3),
    ]

    mine, mine_total = fresh.page_requests(employee_id=employee.id, limit=10, offset=0)
    assert mine_total == 4, "the employee filter ignores status; the draft is theirs too"
    assert [item.employee_id for item in mine] == [employee.id] * 4
    assert [item.start_date for item in mine] == [
        TODAY + timedelta(days=0),
        TODAY + timedelta(days=1),
        TODAY + timedelta(days=2),
        TODAY + timedelta(days=3),
    ]
