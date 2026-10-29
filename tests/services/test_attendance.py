"""Attendance import: fingerprint CSV into payroll inputs, fail-closed."""

import calendar
from dataclasses import replace
from datetime import date, timedelta

import pytest

from hr_agents.identity import ActorProvenance, ActorRef, ActorType
from hr_agents.models import (
    AccrualMethod,
    ApproverRole,
    Employee,
    LeaveType,
    LeaveTypePolicy,
    PayrollInput,
    RequestStatus,
    business_today,
)
from hr_agents.models.money import money as m
from hr_agents.rbac import RoleId
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    EmployeeService,
    EmployeeStore,
    LeaveService,
    PayrollError,
    PayrollService,
    RateTableService,
    RateTableStore,
)
from hr_agents.services.attendance import parse_attendance_csv, summarize_attendance
from hr_agents.services.audit import AuditChain
from hr_agents.services.payroll import _working_days_in_month

TODAY = business_today()
YEAR, MONTH = TODAY.year, TODAY.month


def hr_admin(actor_id: str = "Rina") -> ActorRef:
    return ActorRef(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.HR_ADMIN.value,
    )


def manager(actor_id: str = "Budi") -> ActorRef:
    return ActorRef(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.MANAGER.value,
    )


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def employees(audit: AuditChain) -> EmployeeService:
    return EmployeeService(EmployeeStore(), audit=audit)


@pytest.fixture
def approvals(audit: AuditChain) -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=audit)


@pytest.fixture
def leave(employees: EmployeeService, approvals: ApprovalEngine, audit: AuditChain) -> LeaveService:
    return LeaveService(employees=employees, approvals=approvals, audit=audit)


@pytest.fixture
def payroll(
    employees: EmployeeService,
    approvals: ApprovalEngine,
    audit: AuditChain,
    leave: LeaveService,
) -> PayrollService:
    return PayrollService(
        employees=employees,
        rate_tables=RateTableService(RateTableStore(), audit=audit),
        approvals=approvals,
        audit=audit,
        leave=leave,
    )


def make_employee(employees: EmployeeService, number: str, name: str = "Sari") -> Employee:
    return employees.create(
        full_name=f"{name} {number}",
        actor=hr_admin(),
        hire_date=TODAY - timedelta(days=400),
        job_title="Staff",
        employee_number=number,
    )


def workdays(year: int, month: int, count: int) -> list[date]:
    days: list[date] = []
    last = calendar.monthrange(year, month)[1]
    for day in range(1, last + 1):
        candidate = date(year, month, day)
        if candidate.weekday() < 5:
            days.append(candidate)
        if len(days) == count:
            return days
    raise AssertionError("month has fewer working days than the test needs")


def csv_text(rows: list[tuple[str, date, str, str]]) -> str:
    lines = ["employee_number,date,clock_in,clock_out"]
    lines.extend(f"{num},{day.isoformat()},{ci},{co}" for num, day, ci, co in rows)
    return "\n".join(lines) + "\n"


def test_parse_overtime_math() -> None:
    day = workdays(YEAR, MONTH, 1)[0]
    days, errors = parse_attendance_csv(
        csv_text([("EMP-1", day, "08:00", "17:30")]),
        period_year=YEAR,
        period_month=MONTH,
    )
    assert errors == []
    assert days[0].worked_hours == 9.5
    assert days[0].overtime_hours == 1.5


def test_parse_exact_eight_hours_no_overtime() -> None:
    day = workdays(YEAR, MONTH, 1)[0]
    days, errors = parse_attendance_csv(
        csv_text([("EMP-1", day, "09:00", "17:00")]),
        period_year=YEAR,
        period_month=MONTH,
    )
    assert errors == []
    assert days[0].overtime_hours == 0.0


def test_parse_empty_file_refused() -> None:
    _, errors = parse_attendance_csv("", period_year=YEAR, period_month=MONTH)
    assert [error.code for error in errors] == ["empty_file"]


def test_parse_bad_header_refused() -> None:
    _, errors = parse_attendance_csv(
        "name,date,in,out\nEMP-1,2026-01-05,08:00,17:00\n",
        period_year=YEAR,
        period_month=MONTH,
    )
    assert [error.code for error in errors] == ["bad_header"]


def test_parse_bad_time_names_row() -> None:
    day = workdays(YEAR, MONTH, 1)[0]
    _, errors = parse_attendance_csv(
        csv_text([("EMP-1", day, "eight", "17:00")]),
        period_year=YEAR,
        period_month=MONTH,
    )
    assert len(errors) == 1
    assert errors[0].code == "bad_time"
    assert errors[0].row == 2


def test_parse_clock_out_before_in_refused() -> None:
    day = workdays(YEAR, MONTH, 1)[0]
    _, errors = parse_attendance_csv(
        csv_text([("EMP-1", day, "17:00", "08:00")]),
        period_year=YEAR,
        period_month=MONTH,
    )
    assert [error.code for error in errors] == ["invalid_hours"]


def test_parse_duplicate_day_refused() -> None:
    day = workdays(YEAR, MONTH, 1)[0]
    _, errors = parse_attendance_csv(
        csv_text([("EMP-1", day, "08:00", "12:00"), ("EMP-1", day, "13:00", "17:00")]),
        period_year=YEAR,
        period_month=MONTH,
    )
    assert [error.code for error in errors] == ["duplicate_day"]


def test_parse_outside_period_refused() -> None:
    other_month = MONTH % 12 + 1
    other_year = YEAR + (1 if other_month == 1 else 0)
    other_day = workdays(other_year, other_month, 1)[0]
    _, errors = parse_attendance_csv(
        csv_text([("EMP-1", other_day, "08:00", "17:00")]),
        period_year=YEAR,
        period_month=MONTH,
    )
    assert [error.code for error in errors] == ["outside_period"]


def test_summarize_absence_math() -> None:
    present = workdays(YEAR, MONTH, 3)
    days, _ = parse_attendance_csv(
        csv_text([("EMP-1", day, "08:00", "17:00") for day in present]),
        period_year=YEAR,
        period_month=MONTH,
    )
    (row,) = summarize_attendance(days, working_days=_working_days_in_month(YEAR, MONTH))
    assert row.days_present == 3
    assert row.absence_days == _working_days_in_month(YEAR, MONTH) - 3


def test_preview_unknown_employee_flagged(
    payroll: PayrollService, employees: EmployeeService
) -> None:
    make_employee(employees, "EMP-1")
    day = workdays(YEAR, MONTH, 1)[0]
    preview = payroll.preview_attendance(
        csv_text([("NOBODY", day, "08:00", "17:00")]),
        period_year=YEAR,
        period_month=MONTH,
    )
    assert preview.rows == []
    assert [error.code for error in preview.errors] == ["unknown_employee"]


def test_preview_approved_leave_excuses_absence(
    payroll: PayrollService,
    employees: EmployeeService,
    leave: LeaveService,
    approvals: ApprovalEngine,
) -> None:
    employee = make_employee(employees, "EMP-1")
    leave.set_policy(
        LeaveTypePolicy(
            leave_type=LeaveType.ANNUAL,
            name="Cuti Tahunan",
            accrual_method=AccrualMethod.LUMP_SUM_ANNUAL,
            days_per_year=12.0,
            min_service_months=0,
            approver_role=ApproverRole.MANAGER,
        ),
        actor=hr_admin(),
    )
    present = workdays(YEAR, MONTH, 3)
    leave_day = workdays(YEAR, MONTH, 4)[3]
    owner = replace(hr_admin("sari"), role=RoleId.EMPLOYEE.value, employee_id=employee.id)
    request = leave.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=leave_day,
        end_date=leave_day,
        actor=owner,
    )
    assert request.approval_id is not None
    approvals.decide(request.approval_id, actor=manager(), approve=True)
    synced = leave.apply_decision(request.approval_id, actor=hr_admin())
    assert synced.status is RequestStatus.APPROVED

    preview = payroll.preview_attendance(
        csv_text([("EMP-1", day, "08:00", "17:00") for day in present]),
        period_year=YEAR,
        period_month=MONTH,
    )
    assert preview.errors == []
    (row,) = preview.rows
    assert row.days_present == 3
    assert row.on_leave_days == 1
    assert row.absence_days == _working_days_in_month(YEAR, MONTH) - 4


def test_apply_merges_only_worked_time(payroll: PayrollService, employees: EmployeeService) -> None:
    employee = make_employee(employees, "EMP-1")
    other = make_employee(employees, "EMP-2", name="Ayu")
    run = payroll.create_run(period_year=YEAR, period_month=MONTH, actor=hr_admin())
    payroll.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=employee.id, base_salary=m(10_000_000), overtime_hours=0.0),
            PayrollInput(employee_id=other.id, base_salary=m(8_000_000), overtime_hours=0.0),
        ],
        actor=hr_admin(),
    )
    present = workdays(YEAR, MONTH, 2)
    text = csv_text(
        [
            ("EMP-1", present[0], "08:00", "18:00"),
            ("EMP-1", present[1], "08:00", "17:00"),
            ("EMP-2", present[0], "08:00", "17:00"),
            ("EMP-2", present[1], "08:00", "17:00"),
        ]
    )
    updated = payroll.apply_attendance(run.id, text, actor=hr_admin())
    first = next(item for item in updated.inputs if item.employee_id == employee.id)
    second = next(item for item in updated.inputs if item.employee_id == other.id)
    assert first.overtime_hours == 3.0
    assert second.overtime_hours == 2.0
    assert first.base_salary == m(10_000_000)
    assert second.absence_days == _working_days_in_month(YEAR, MONTH) - 2


def test_apply_refuses_on_any_error_without_mutating(
    payroll: PayrollService, employees: EmployeeService
) -> None:
    employee = make_employee(employees, "EMP-1")
    run = payroll.create_run(period_year=YEAR, period_month=MONTH, actor=hr_admin())
    payroll.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(10_000_000))],
        actor=hr_admin(),
    )
    day = workdays(YEAR, MONTH, 1)[0]
    with pytest.raises(PayrollError, match="error"):
        payroll.apply_attendance(
            run.id,
            csv_text([("GHOST", day, "08:00", "17:00")]),
            actor=hr_admin(),
        )
    assert payroll.get_run(run.id).inputs[0].overtime_hours == 0.0


def test_apply_refuses_when_coverage_is_partial(
    payroll: PayrollService, employees: EmployeeService
) -> None:
    employee = make_employee(employees, "EMP-1")
    other = make_employee(employees, "EMP-2", name="Ayu")
    run = payroll.create_run(period_year=YEAR, period_month=MONTH, actor=hr_admin())
    payroll.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=employee.id, base_salary=m(10_000_000)),
            PayrollInput(employee_id=other.id, base_salary=m(8_000_000)),
        ],
        actor=hr_admin(),
    )
    day = workdays(YEAR, MONTH, 1)[0]
    with pytest.raises(PayrollError, match="does not cover"):
        payroll.apply_attendance(
            run.id,
            csv_text([("EMP-1", day, "08:00", "17:00")]),
            actor=hr_admin(),
        )


def test_apply_refuses_without_inputs(payroll: PayrollService, employees: EmployeeService) -> None:
    make_employee(employees, "EMP-1")
    run = payroll.create_run(period_year=YEAR, period_month=MONTH, actor=hr_admin())
    day = workdays(YEAR, MONTH, 1)[0]
    with pytest.raises(PayrollError, match="set_inputs"):
        payroll.apply_attendance(
            run.id,
            csv_text([("EMP-1", day, "08:00", "17:00")]),
            actor=hr_admin(),
        )
