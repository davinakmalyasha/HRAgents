from datetime import date, timedelta
from uuid import uuid4

import pytest

from hr_agents.identity import ActorProvenance, ActorRef, ActorType
from hr_agents.models import (
    AccrualMethod,
    ApprovalStatus,
    ApproverRole,
    Employee,
    LeaveRequest,
    LeaveType,
    LeaveTypePolicy,
    RequestStatus,
)
from hr_agents.rbac import RoleId
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
        actor=people_admin(),
        hire_date=TODAY - timedelta(days=days_employed),
        job_title="Finance Staff",
    )


def people_admin(actor_id: str = "Rina") -> ActorRef:
    """An authenticated principal holding ``people:write``.

    Administering policies, adjusting balances and acting on somebody else's
    leave all key on the permission table, so an actor has to carry a role the
    auth layer could actually have produced.
    """
    return ActorRef(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.HR_ADMIN.value,
    )


def owner_of(employee: Employee) -> ActorRef:
    """The principal bound to ``employee``, as a deployment would configure it.

    Filing leave takes an ``employee_id`` and now checks the caller may act for
    it. That check reads ``ActorRef.employee_id``, which only ``from_principal``
    sets, from a binding the operator configured. A bare string cannot own
    anything, so "Sari" requesting her own leave has to be modelled as a bound
    principal or not at all.
    """
    return ActorRef(
        actor_id="sari",
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.EMPLOYEE.value,
        employee_id=employee.id,
    )


def manager_principal(actor_id: str = "Budi") -> ActorRef:
    """A principal with the manager role, deciding an approval.

    Deciding an approval is checked against ``APPROVER_ROLE_HOLDERS``, not against
    the employee directory, so this actor needs no employee binding and is not
    modelled as the reporting line -- it is whoever holds the manager role.
    Deciding *somebody's* leave is a different check, exercised by the ownership
    tests.
    """
    return ActorRef(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.MANAGER.value,
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
    policy = service.set_policy(annual_policy(), actor=people_admin())
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
    service.set_holidays([date(2025, 1, 8)], actor=people_admin())
    assert service.working_days(date(2025, 1, 6), date(2025, 1, 10)) == 4.0


# --- balances ----------------------------------------------------------------


def test_lump_sum_entitlement_after_service(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service, days_employed=400)

    balance = service.balance(employee.id, LeaveType.ANNUAL)
    assert balance.entitled == 12.0
    assert balance.available == 12.0


def test_entitlement_denied_before_min_service(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
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
        actor=people_admin(),
    )
    employee = make_employee(employee_service, days_employed=100)
    balance = service.balance(employee.id, LeaveType.ANNUAL)
    # 1 day per worked month this year, capped at 12; always a whole multiple.
    assert 0.0 < balance.entitled <= 12.0
    assert balance.entitled == float(int(balance.entitled))


def test_per_event_cap_has_no_accrual(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(per_event_sick_policy(), actor=people_admin())
    employee = make_employee(employee_service, days_employed=400)
    balance = service.balance(employee.id, LeaveType.SICK)
    assert balance.entitled == 0.0


def test_adjustment_changes_available(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service, days_employed=400)

    balance = service.adjust_balance(
        employee.id,
        LeaveType.ANNUAL,
        days=3.0,
        actor=people_admin(),
        reason="approved carry adjustment",
    )
    assert balance.adjustment == 3.0
    assert balance.available == 15.0

    negative = service.adjust_balance(
        employee.id,
        LeaveType.ANNUAL,
        days=-10.0,
        actor=people_admin(),
        reason="correction",
    )
    assert negative.available == 5.0


# --- requests ----------------------------------------------------------------


def test_request_routes_to_approval(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)

    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        actor=owner_of(employee),
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
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        actor=owner_of(employee),
    )
    assert request.approval_id is not None

    approvals.decide(request.approval_id, actor=manager_principal("Budi"), approve=True)
    synced = service.apply_decision(request.approval_id, actor=people_admin())

    assert synced.status is RequestStatus.APPROVED
    balance = service.balance(employee.id, LeaveType.ANNUAL, year=WORK_YEAR)
    assert balance.used == 5.0


def test_approval_reject_syncs_request(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        actor=owner_of(employee),
    )
    assert request.approval_id is not None
    approvals.decide(
        request.approval_id, actor=manager_principal(), approve=False, reason="peak period"
    )
    synced = service.apply_decision(request.approval_id, actor=people_admin())
    assert synced.status is RequestStatus.REJECTED


def test_insufficient_balance_rejected(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(days_per_year=2.0), actor=people_admin())
    employee = make_employee(employee_service)
    with pytest.raises(LeaveError, match="insufficient balance"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.ANNUAL,
            start_date=WORK_START,
            end_date=WORK_START + timedelta(days=4),
            actor=owner_of(employee),
        )


def test_document_required_rejected(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(per_event_sick_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    with pytest.raises(LeaveError, match="supporting document"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.SICK,
            start_date=WORK_START,
            end_date=WORK_START + timedelta(days=1),
            actor=owner_of(employee),
        )


def test_document_provided_passes_sick_policy(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(per_event_sick_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.SICK,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        actor=owner_of(employee),
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
        actor=people_admin(),
    )
    employee = make_employee(employee_service)
    with pytest.raises(LeaveError, match=r"exceeds the 2\.0-day cap"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.SICK,
            start_date=WORK_START,
            end_date=WORK_START + timedelta(days=4),
            actor=owner_of(employee),
        )


def test_overlapping_requests_rejected(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        actor=owner_of(employee),
    )
    with pytest.raises(LeaveError, match="overlaps"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.ANNUAL,
            start_date=WORK_START + timedelta(days=2),
            end_date=WORK_START + timedelta(days=8),
            actor=owner_of(employee),
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
        actor=people_admin(),
    )
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.PERSONAL,
        start_date=WORK_START,
        end_date=WORK_START,
        actor=owner_of(employee),
    )
    assert request.status is RequestStatus.APPROVED
    assert request.approval_id is None


def test_min_service_rejected(service: LeaveService, employee_service: EmployeeService) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service, days_employed=100)
    with pytest.raises(LeaveError, match="requires 12 months"):
        service.request(
            employee_id=employee.id,
            leave_type=LeaveType.ANNUAL,
            start_date=WORK_START,
            end_date=WORK_START + timedelta(days=1),
            actor=owner_of(employee),
        )


def test_cancel_withdraws_approval(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        actor=owner_of(employee),
    )
    cancelled = service.cancel(request.id, actor=owner_of(employee), reason="trip moved")
    assert cancelled.status is RequestStatus.CANCELLED

    assert request.approval_id is not None
    approval = approvals._store.get(request.approval_id)
    assert approval is not None
    assert approval.status is ApprovalStatus.WITHDRAWN


def test_cancel_requires_a_reason(service: LeaveService, employee_service: EmployeeService) -> None:
    """The router was accepting a reason and dropping it.

    The record said "cancelled" with no way to tell a withdrawn trip from a change of
    plan two months later, so a blank reason is refused rather than silently discarded.
    """
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        actor=owner_of(employee),
    )

    for blank in (None, "", "   "):
        with pytest.raises(LeaveError, match="requires a reason"):
            service.cancel(request.id, actor=owner_of(employee), reason=blank)

    assert service.get_request(request.id).status is RequestStatus.PENDING


def test_cancel_records_the_reason_it_was_given(
    service: LeaveService, employee_service: EmployeeService, audit: AuditChain
) -> None:
    """The reason has to survive into the audit trail, not just pass validation."""
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        actor=owner_of(employee),
    )

    service.cancel(request.id, actor=owner_of(employee), reason="  flights rebooked  ")

    entries = [entry for entry in audit.entries if entry.action == "leave.request_cancelled"]
    assert len(entries) == 1
    assert entries[0].payload == {
        "approval_id": str(request.approval_id),
        "reason": "flights rebooked",
    }


def test_cancel_after_decision_rejected(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        actor=owner_of(employee),
    )
    assert request.approval_id is not None
    approvals.decide(request.approval_id, actor=manager_principal(), approve=True)
    service.apply_decision(request.approval_id, actor=people_admin())

    with pytest.raises(LeaveError, match="cannot cancel"):
        service.cancel(request.id, actor=owner_of(employee), reason="trip moved")


# --- queries -----------------------------------------------------------------


def test_calendar_on_leave(
    service: LeaveService, employee_service: EmployeeService, approvals: ApprovalEngine
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    request = service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        actor=owner_of(employee),
    )
    assert request.approval_id is not None
    approvals.decide(request.approval_id, actor=manager_principal(), approve=True)
    service.apply_decision(request.approval_id, actor=people_admin())

    assert [item.id for item in service.on_leave(on_date=WORK_START + timedelta(days=2))] == [
        request.id
    ]
    assert service.on_leave(on_date=WORK_START + timedelta(days=5)) == []


def test_pending_balance_counted(service: LeaveService, employee_service: EmployeeService) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        actor=owner_of(employee),
    )
    balance = service.balance(employee.id, LeaveType.ANNUAL, year=WORK_YEAR)
    assert balance.pending == 2.0
    assert balance.available == 10.0


def test_unknown_employee_and_request_raise(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    with pytest.raises(LeaveError, match="unknown employee"):
        service.balance(uuid4(), LeaveType.ANNUAL)
    with pytest.raises(LeaveError, match="unknown leave request"):
        service.get_request(uuid4())


def test_audit_chain_covers_leave(
    service: LeaveService, employee_service: EmployeeService, audit: AuditChain
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)
    service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=1),
        actor=owner_of(employee),
    )
    actions = [entry.action for entry in audit.entries]
    assert "leave.policy_set" in actions
    assert "leave.request_submitted" in actions
    assert audit.verify() == -1


# --- ownership ------------------------------------------------------------------
#
# `request` took an `employee_id` on trust, and `cancel` checked nothing at all.
# Both were safe only because the routes reaching them required a permission
# that no ordinary employee held. Granting self-service removes that protection,
# so the check has to live in the service: a permission alone would let any
# employee file leave for anyone by naming their id.


def _request_for(employee: Employee, service: LeaveService, actor: ActorRef) -> LeaveRequest:
    return service.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=WORK_START,
        end_date=WORK_START + timedelta(days=4),
        actor=actor,
        reason="family event",
    )


def test_an_employee_can_file_their_own_leave(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    employee = make_employee(employee_service)

    request = _request_for(employee, service, owner_of(employee))

    assert request.employee_id == employee.id
    assert request.status is RequestStatus.PENDING


def test_an_employee_cannot_file_leave_for_somebody_else(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    sari = make_employee(employee_service)
    budi = make_employee(employee_service)

    with pytest.raises(LeaveError, match="cannot request leave for employee"):
        _request_for(sari, service, owner_of(budi))


def test_a_bare_string_actor_cannot_file_leave_for_anybody(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    """ActorRef.legacy has no employee, so it owns nothing.

    This is the case that matters for the legacy actors the suite used to pass:
    a display name is a claim about who acted, not a binding to a record, and it
    must not reach one.
    """
    service.set_policy(annual_policy(), actor=people_admin())
    sari = make_employee(employee_service)

    with pytest.raises(LeaveError, match="cannot request leave for employee"):
        _request_for(sari, service, ActorRef.legacy("sari@example.com"))


def test_a_people_administrator_can_file_leave_for_somebody_else(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    sari = make_employee(employee_service)

    request = _request_for(sari, service, people_admin())

    assert request.employee_id == sari.id


def test_a_employees_manager_can_file_leave_for_them(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    """The reporting line is consulted, not assumed.

    `Employee.manager_id` is modelled and indexed but was never read for
    authorization. Without consulting it, a manager could not file leave for a
    report, which is most of why an employee would ring HR instead.
    """
    service.set_policy(annual_policy(), actor=people_admin())
    manager = employee_service.create(
        full_name="Budi Santoso",
        actor=people_admin(),
        hire_date=TODAY - timedelta(days=900),
        job_title="Manager",
    )
    report = employee_service.create(
        full_name="Sari Dewi",
        actor=people_admin(),
        hire_date=TODAY - timedelta(days=400),
        manager_id=manager.id,
    )
    manager_actor = ActorRef(
        actor_id="Budi",
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.MANAGER.value,
        employee_id=manager.id,
    )

    request = _request_for(report, service, manager_actor)

    assert request.employee_id == report.id


def test_an_employee_cannot_cancel_somebody_elses_leave(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    sari = make_employee(employee_service)
    budi = make_employee(employee_service)
    request = _request_for(sari, service, owner_of(sari))

    with pytest.raises(LeaveError, match="cannot cancel a leave request"):
        service.cancel(request.id, actor=owner_of(budi), reason="not mine")

    assert service.get_request(request.id).status is RequestStatus.PENDING


def test_an_employee_can_cancel_their_own_leave(
    service: LeaveService, employee_service: EmployeeService
) -> None:
    service.set_policy(annual_policy(), actor=people_admin())
    sari = make_employee(employee_service)
    request = _request_for(sari, service, owner_of(sari))

    cancelled = service.cancel(request.id, actor=owner_of(sari), reason="plan changed")

    assert cancelled.status is RequestStatus.CANCELLED
