from datetime import date, timedelta
from uuid import uuid4

import pytest

from hr_agents.models import (
    AccrualMethod,
    ApprovalStatus,
    ApproverRole,
    Employee,
    LeaveType,
    LeaveTypePolicy,
    RequestStatus,
)
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    EmployeeService,
    EmployeeStore,
    LeaveError,
    LeaveService,
)
from hr_agents.services.audit import AuditChain

TODAY = date.today()
# Dynamic working-week anchor: the first Monday at least 30 days out.
WORK_START = TODAY + timedelta(days=((7 - TODAY.weekday()) % 7 or 7) + 28)
WORK_YEAR = WORK_START.year


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def approvals(audit: AuditChain) -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=audit)


@pytest.fixture
def employee_service(audit: AuditChain, approvals: ApprovalEngine) -> EmployeeService:
    return EmployeeService(EmployeeStore(), audit=audit, approvals=approvals)


@pytest.fixture
def service(
    employee_service: EmployeeService, approvals: ApprovalEngine, audit: AuditChain
) -> LeaveService:
    return LeaveService(employees=employee_service, approvals=approvals, audit=audit)


def make_employee(employee_service: EmployeeService, *, days_employed: int = 400) -> Employee:
    return employee_service.create(
        full_name="Sari Dewi",
        created_by="hr-admin",
        hire_date=TODAY - timedelta(days=days_employed),
        job_title="Finance Staff",
    )


def annual_policy(**overrides: object) -> LeaveTypePolicy:
    defaults: dict[str, object] = {
        "leave_type": LeaveType.ANNUAL,
        "name": "Cuti Tahunan",
        "accrual_method": AccrualMethod.LUMP_SUM_ANNUAL,
        "days_per_year": 12.0,
        "min_service_months": 12,
        "carryover_allowed": True,
        "carryover_max_days": 6.0,
    }
    defaults.update(overrides)
    return LeaveTypePolicy(**defaults)  # type: ignore[arg-type]


def per_event_sick_policy() -> LeaveTypePolicy:
    return LeaveTypePolicy(
        leave_type=LeaveType.SICK,
        name="Cuti Sakit",
        accrual_method=AccrualMethod.PER_EVENT_CAP,
        max_days_per_request=14.0,
        requires_document=True,
    )


# --- policies ----------------------------------------------------------------


def test_set_and_get_policy(service: LeaveService) -> None:
    policy = service.set_policy(annual_policy(), by="hr-admin")
    assert service.get_policy(LeaveType.ANNUAL).name == policy.name


def test_missing_policy_raises(service: LeaveService) -> None:
    with pytest.raises(LeaveError, match="no policy configured"):
        service.get_policy(LeaveType.MATERNITY)


def test_flat_monthly_requires_month_rate() -> None:
    with pytest.raises(ValueError, match="days_per_month"):
        LeaveTypePolicy(
            leave_type=LeaveType.ANNUAL, name="X", accrual_method=AccrualMethod.FLAT_MONTHLY
        )


def test_carryover_requires_cap() -> None:
    with pytest.raises(ValueError, match="carryover_max_days"):
        LeaveTypePolicy(
            leave_type=LeaveType.ANNUAL,
            name="X",
            carryover_allowed=True,
        )


# --- working-day math --------------------------------------------------------


def test_working_days_excludes_weekends(service: LeaveService) -> None:
    # Monday 2025-01-06 to Friday 2025-01-10 = 5 working days
    assert service.working_days(date(2025, 1, 6), date(2025, 1, 10)) == 5.0
    # Monday to next Monday = 6 working days
    assert service.working_days(date(2025, 1, 6), date(2025, 1, 13)) == 6.0


def test_holidays_excluded(service: LeaveService) -> None:
    service.set_holidays([date(2025, 1, 8)], by="hr-admin")
    assert service.working_days(date(2025, 1, 6), date(2025, 1, 10)) == 4.0


# --- balances ----------------------------------------------------------------


def test_lump_sum_entitlement_after_service(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service, days_employed=400)

    balance = service.balance(employee.id, LeaveType.ANNUAL)
    assert balance.entitled == 12.0
    assert balance.available == 12.0


def test_entitlement_denied_before_min_service(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service, days_employed=100)

    balance = service.balance(employee.id, LeaveType.ANNUAL)
    assert balance.entitled == 0.0


def test_flat_monthly_accrual(service: LeaveService, employee_service: EmployeeService) -> None:
    service.set_policy(
        annual_policy(
            accrual_method=AccrualMethod.FLAT_MONTHLY,
            days_per_month=1.0,
            days_per_year=None,
            min_service_months=0,
            carryover_allowed=False,
            carryover_max_days=None,
        ),
        by="hr",
    )
    employee = make_employee(employee_service, days_employed=100)
    balance = service.balance(employee.id, LeaveType.ANNUAL)
    # 1 day per worked month this year, capped at 12; always a whole multiple.
    assert 0.0 < balance.entitled <= 12.0
    assert balance.entitled == float(int(balance.entitled))


def test_per_event_cap_has_no_accrual(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(per_event_sick_policy(), by="hr")
    employee = make_employee(employee_service, days_employed=400)
    balance = service.balance(employee.id, LeaveType.SICK)
    assert balance.entitled == 0.0


def test_adjustment_changes_available(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service, days_employed=400)

    balance = service.adjust_balance(
        employee.id, LeaveType.ANNUAL, days=3.0, by="hr-admin", reason="approved carry adjustment"
    )
    assert balance.adjustment == 3.0
    assert balance.available == 15.0

    negative = service.adjust_balance(
        employee.id, LeaveType.ANNUAL, days=-10.0, by="hr-admin", reason="correction"
    )
    assert negative.available == 5.0


# --- requests ----------------------------------------------------------------


def test_request_routes_to_approval(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)

    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        requested_by="sari@example.com",
        reason="family event",
    )

    assert request.status is RequestStatus.PENDING
    assert request.days == 5.0
    assert request.approval_id is not None

    queue = approvals.pending_for(ApproverRole.MANAGER)
    assert any(item.id == request.approval_id for item in queue)


def test_approval_approve_syncs_request(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        requested_by="sari@example.com",
    )
    assert request.approval_id is not None

    approvals.decide(request.approval_id, decided_by="manager-budi", approve=True)
    synced = service.apply_decision(request.approval_id)

    assert synced.status is RequestStatus.APPROVED
    balance = service.balance(employee.id, LeaveType.ANNUAL, year=WORK_YEAR)
    assert balance.used == 5.0


def test_approval_reject_syncs_request(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        requested_by="sari@example.com",
    )
    assert request.approval_id is not None
    approvals.decide(request.approval_id, decided_by="manager", approve=False, reason="peak period")
    synced = service.apply_decision(request.approval_id)
    assert synced.status is RequestStatus.REJECTED


def test_insufficient_balance_rejected(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(days_per_year=2.0), by="hr")
    employee = make_employee(employee_service)
    with pytest.raises(LeaveError, match="insufficient balance"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.ANNUAL,
            start_date=WORK_START,
            end_date=WORK_START + timedelta(days=4),
            requested_by="sari@example.com",
        )


def test_document_required_rejected(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(per_event_sick_policy(), by="hr")
    employee = make_employee(employee_service)
    with pytest.raises(LeaveError, match="supporting document"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.SICK,
            start_date=WORK_START,
            end_date=WORK_START + timedelta(days=1),
            requested_by="sari@example.com",
        )


def test_document_provided_passes_sick_policy(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(per_event_sick_policy(), by="hr")
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.SICK,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        requested_by="sari@example.com",
        document_id=uuid4(),
    )
    assert request.status is RequestStatus.PENDING


def test_over_max_per_request_rejected(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(
        per_event_sick_policy().model_copy(
            update={"max_days_per_request": 2.0, "requires_document": False}
        ),
        by="hr",
    )
    employee = make_employee(employee_service)
    with pytest.raises(LeaveError, match=r"exceeds the 2\.0-day cap"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.SICK,
            start_date=WORK_START,
            end_date=WORK_START + timedelta(days=4),
            requested_by="sari@example.com",
        )


def test_overlapping_requests_rejected(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)
    service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        requested_by="sari@example.com",
    )
    with pytest.raises(LeaveError, match="overlaps"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.ANNUAL,
            start_date=WORK_START + timedelta(days=2),
            end_date=WORK_START + timedelta(days=8),
            requested_by="sari@example.com",
        )


def test_no_approval_policy_auto_approves(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(
        LeaveTypePolicy(
            leave_type=LeaveType.PERSONAL,
            name="Izin",
            requires_approval=False,
            accrual_method=AccrualMethod.NONE,
        ),
        by="hr",
    )
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.PERSONAL,
        start_date=WORK_START,
        end_date=WORK_START,
        requested_by="sari@example.com",
    )
    assert request.status is RequestStatus.APPROVED
    assert request.approval_id is None


def test_min_service_rejected(service: LeaveService, employee_service: EmployeeService) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service, days_employed=100)
    with pytest.raises(LeaveError, match="requires 12 months"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.ANNUAL,
            start_date=WORK_START,
            end_date=WORK_START + timedelta(days=1),
            requested_by="sari@example.com",
        )


def test_cancel_withdraws_approval(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        requested_by="sari@example.com",
    )
    cancelled = service.cancel(request.id, by="sari@example.com")
    assert cancelled.status is RequestStatus.CANCELLED

    assert request.approval_id is not None
    approval = approvals._store.get(request.approval_id)
    assert approval is not None
    assert approval.status is ApprovalStatus.WITHDRAWN


def test_cancel_after_decision_rejected(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        requested_by="sari@example.com",
    )
    assert request.approval_id is not None
    approvals.decide(request.approval_id, decided_by="manager", approve=True)
    service.apply_decision(request.approval_id)

    with pytest.raises(LeaveError, match="cannot cancel"):
        service.cancel(request.id, by="sari@example.com")


# --- queries -----------------------------------------------------------------


def test_calendar_on_leave(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        requested_by="sari@example.com",
    )
    assert request.approval_id is not None
    approvals.decide(request.approval_id, decided_by="manager", approve=True)
    service.apply_decision(request.approval_id)

    assert [item.id for item in service.on_leave(on_date=WORK_START + timedelta(days=2))] == [
        request.id
    ]
    assert service.on_leave(on_date=WORK_START + timedelta(days=5)) == []


def test_pending_balance_counted(service: LeaveService, employee_service: EmployeeService) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)
    service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        requested_by="sari@example.com",
    )
    balance = service.balance(employee.id, LeaveType.ANNUAL, year=WORK_YEAR)
    assert balance.pending == 2.0
    assert balance.available == 10.0


def test_unknown_employee_and_request_raise(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), by="hr")
    with pytest.raises(LeaveError, match="unknown employee"):
        service.balance(uuid4(), LeaveType.ANNUAL)
    with pytest.raises(LeaveError, match="unknown leave request"):
        service.get_request(uuid4())


def test_audit_chain_covers_leave(
    service: LeaveService, employee_service: EmployeeService, audit: AuditChain
) -> None:
    service.set_policy(annual_policy(), by="hr")
    employee = make_employee(employee_service)
    service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        requested_by="sari@example.com",
    )
    actions = [entry.action for entry in audit.entries]
    assert "leave.policy_set" in actions
    assert "leave.request_submitted" in actions
    assert audit.verify() == -1
