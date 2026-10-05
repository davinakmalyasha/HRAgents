"""Leave adapter tests on in-memory SQLite.

Two of these are regression tests for silent loss rather than visible loss. A
missing leave request is obvious -- the employee sees an empty list. A missing
balance adjustment and a missing holiday calendar are not: the balance reads
correct-ish and the working-day count is simply wrong, and nothing reports it.

Every read goes through a fresh adapter instance so a fallback to the in-process
dicts would fail here rather than in production.
"""

from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.leave import DbLeaveService
from hr_agents.db.people import DbEmployeeStore
from hr_agents.identity import ActorRef
from hr_agents.models import (
    AccrualMethod,
    ApproverRole,
    Employee,
    LeaveRequest,
    LeaveType,
    LeaveTypePolicy,
)
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.people_store import ApprovalStore

TODAY = date.today()
ACTOR = ActorRef.legacy("hr-admin")
YEAR = TODAY.year


def _service(factory: sessionmaker[Session]) -> DbLeaveService:
    audit = AuditChain()
    approvals = ApprovalEngine(ApprovalStore(), audit=audit)
    # The employee must be a real row: leave_requests.employee_id is a foreign
    # key, and SQLite does not enforce foreign keys unless asked to -- so an
    # in-memory employee passed locally and failed on Postgres in CI.
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


def _request(employee: Employee, *, days: float = 3.0) -> LeaveRequest:
    return LeaveRequest(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=TODAY + timedelta(days=30),
        end_date=TODAY + timedelta(days=30 + int(days) - 1),
        days=days,
        reason="Family event",
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
    from hr_agents.models import RequestStatus

    service = _service(factory)
    employee = _employee(service)
    record = _request(employee)
    service._save_request(record)
    service._save_request(
        record.model_copy(update={"status": RequestStatus.APPROVED, "approval_id": uuid4()})
    )

    loaded = _service(factory)._load_request(record.id)
    assert loaded is not None
    assert loaded.status is RequestStatus.APPROVED
    assert loaded.approval_id is not None


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
