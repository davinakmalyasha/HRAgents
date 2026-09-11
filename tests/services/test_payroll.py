from datetime import date
from uuid import uuid4

import pytest

from hr_agents.models import (
    AnomalySeverity,
    ApproverRole,
    Employee,
    PayrollRun,
    PayrollRunKind,
    PayrollRunStatus,
    RateEntry,
    RateTableKind,
)
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    EmployeeService,
    EmployeeStore,
    PayrollError,
    PayrollService,
    RateTableService,
    RateTableStore,
)
from hr_agents.services.audit import AuditChain

TODAY = date.today()
PERIOD_YEAR = TODAY.year
PERIOD_MONTH = 6


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def employees(audit: AuditChain) -> EmployeeService:
    return EmployeeService(EmployeeStore(), audit=audit)


@pytest.fixture
def rate_tables(audit: AuditChain) -> RateTableService:
    return RateTableService(RateTableStore(), audit=audit)


@pytest.fixture
def approvals(audit: AuditChain) -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=audit)


@pytest.fixture
def service(
    employees: EmployeeService,
    rate_tables: RateTableService,
    approvals: ApprovalEngine,
    audit: AuditChain,
) -> PayrollService:
    return PayrollService(
        employees=employees, rate_tables=rate_tables, approvals=approvals, audit=audit
    )


def seed_verified_tables(rate_tables: RateTableService) -> None:
    """Illustrative values for tests only — production values are HR-entered."""
    specs = [
        (RateTableKind.BPJS_KESEHATAN, 4.0, 1.0, 12_000_000.0),
        (RateTableKind.BPJS_KETENAGAKERJAAN_JHT, 3.7, 2.0, None),
        (RateTableKind.BPJS_KETENAGAKERJAAN_JP, 2.0, 1.0, 10_000_000.0),
        (RateTableKind.BPJS_JKK, 0.24, None, None),
        (RateTableKind.BPJS_JKM, 0.3, None, None),
    ]
    for kind, employer, employee, cap in specs:
        table = rate_tables.create(
            kind=kind, name=kind.value, created_by="hr-admin", jurisdiction="ID"
        )
        rate_tables.set_entries(
            table.id,
            entries=[
                RateEntry(
                    label="standard",
                    employer_share_percent=employer,
                    employee_share_percent=employee,
                    wage_cap=cap,
                )
            ],
            updated_by="hr-admin",
        )
        rate_tables.verify(
            table.id, verified_by="hr-admin", source_note="test fixture (illustrative)"
        )

    overtime = rate_tables.create(
        kind=RateTableKind.OVERTIME_PREMIUM, name="Overtime", created_by="hr-admin"
    )
    rate_tables.set_entries(
        overtime.id,
        entries=[RateEntry(label="first hour", multiplier=1.5)],
        updated_by="hr-admin",
    )
    rate_tables.verify(overtime.id, verified_by="hr-admin", source_note="test fixture")

    pph = rate_tables.create(kind=RateTableKind.PPH21_TER, name="TER", created_by="hr-admin")
    rate_tables.set_entries(
        pph.id,
        entries=[
            RateEntry(
                label="low", lower_bound=0, upper_bound=10_000_000, employee_share_percent=2.0
            ),
            RateEntry(
                label="mid",
                lower_bound=10_000_000.1,
                upper_bound=30_000_000,
                employee_share_percent=5.0,
            ),
        ],
        updated_by="hr-admin",
    )
    rate_tables.verify(pph.id, verified_by="hr-admin", source_note="test fixture")


def make_employee(employees: EmployeeService, name: str = "Sari Dewi") -> Employee:
    return employees.create(
        full_name=name,
        created_by="hr-admin",
        hire_date=TODAY,
        job_title="Finance Staff",
    )


def make_run(
    service: PayrollService,
    *,
    period_month: int = PERIOD_MONTH,
    kind: PayrollRunKind = PayrollRunKind.MONTHLY,
) -> PayrollRun:
    return service.create_run(
        period_year=PERIOD_YEAR,
        period_month=period_month,
        created_by="hr-admin",
        kind=kind,
    )


# --- run lifecycle -----------------------------------------------------------


def test_create_run_and_edit(service: PayrollService) -> None:
    run = make_run(service)
    assert run.status is PayrollRunStatus.DRAFT
    assert service.list_runs() == [run]


def test_compute_requires_inputs(service: PayrollService) -> None:
    run = make_run(service)
    with pytest.raises(PayrollError, match="no inputs"):
        service.compute(run.id, by="hr-admin")


def test_compute_blocks_without_verified_tables(
    service: PayrollService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[
            __import__("hr_agents.models", fromlist=["PayrollInput"]).PayrollInput(
                employee_id=employee.id, base_salary=5_000_000
            )
        ],
        by="hr-admin",
    )
    computed = service.compute(run.id, by="hr-admin")

    # Missing required tables are ERROR anomalies
    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "rate_table_missing:bpjs_kesehatan" in codes
    assert computed.blocking_anomalies  # sign-off would be blocked


def test_compute_with_verified_tables(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=10_000_000,
                fixed_allowances=1_000_000,
                overtime_hours=3.0,
            )
        ],
        by="hr-admin",
    )
    computed = service.compute(run.id, by="hr-admin")

    assert computed.status is PayrollRunStatus.READY_FOR_REVIEW
    line = computed.lines[0]
    assert line.employee_name == "Sari Dewi"
    # wage = 11,000,000
    assert line.bpjs_kesehatan_employee == pytest.approx(110_000.0)  # 1%
    assert line.bpjs_jht_employee == pytest.approx(220_000.0)  # 2%
    assert line.bpjs_jp_employee == pytest.approx(100_000.0)  # 1% capped at 10M
    # overtime: hourly = 11,000,000/173; 1h * 1.5 + 2h * 2
    hourly = 11_000_000 / 173
    expected_ot = round(hourly * 1.5 + hourly * 2 * 2, 2)
    assert line.overtime_pay == pytest.approx(expected_ot)
    assert line.gross == pytest.approx(11_000_000 + expected_ot)
    # employer cost present
    assert line.employer_cost > 0
    # PPh21 computed from TER (gross ~11.2M → 5% bracket)
    assert line.pph21 > 0


def test_missing_employee_is_not_fatal(
    service: PayrollService, rate_tables: RateTableService
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=uuid4(), base_salary=5_000_000)],
        by="hr-admin",
    )
    computed = service.compute(run.id, by="hr-admin")
    assert computed.lines[0].employee_name == ""
    assert computed.lines[0].net > 0


# --- anomalies ---------------------------------------------------------------


def test_negative_net_blocks(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=1_000_000,
                other_deductions=5_000_000,
            )
        ],
        by="hr-admin",
    )
    computed = service.compute(run.id, by="hr-admin")
    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "negative_net" in codes
    assert any(anomaly.severity is AnomalySeverity.ERROR for anomaly in computed.anomalies)


def test_excessive_overtime_warns(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=5_000_000, overtime_hours=80)],
        by="hr-admin",
    )
    computed = service.compute(run.id, by="hr-admin")
    assert any(anomaly.code == "overtime_excessive" for anomaly in computed.anomalies)


def test_net_deviation_warns(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)

    first = make_run(service, period_month=5)
    service.set_inputs(
        first.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=10_000_000)],
        by="hr",
    )
    service.compute(first.id, by="hr")

    second = make_run(service, period_month=6)
    service.set_inputs(
        second.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=4_000_000)],
        by="hr",
    )
    computed = service.compute(second.id, by="hr")

    assert any(anomaly.code == "net_deviation" for anomaly in computed.anomalies)


# --- sign-off flow -----------------------------------------------------------


def test_signoff_flow_approve_and_export(
    service: PayrollService,
    employees: EmployeeService,
    rate_tables: RateTableService,
    approvals: ApprovalEngine,
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=8_000_000)],
        by="hr-admin",
    )
    service.compute(run.id, by="hr-admin")

    submitted = service.submit_for_signoff(run.id, by="hr-admin")
    assert submitted.status is PayrollRunStatus.PENDING_SIGNOFF

    queue = approvals.pending_for(ApproverRole.FINANCE)
    assert any(item.id == submitted.approval_id for item in queue)

    approval_id = submitted.approval_id
    assert approval_id is not None
    approvals.decide(approval_id, decided_by="finance-lead", approve=True)
    approved = service.apply_decision(approval_id)

    assert approved.status is PayrollRunStatus.APPROVED
    assert approved.signed_off_by == "finance-lead"

    exported = service.mark_exported(run.id, by="finance-lead")
    assert exported.status is PayrollRunStatus.EXPORTED


def test_signoff_requires_human(
    service: PayrollService,
    employees: EmployeeService,
    rate_tables: RateTableService,
    approvals: ApprovalEngine,
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=8_000_000)],
        by="hr-admin",
    )
    service.compute(run.id, by="hr-admin")
    submitted = service.submit_for_signoff(run.id, by="hr-admin")

    approval_id = submitted.approval_id
    assert approval_id is not None
    with pytest.raises(Exception, match="named human"):
        approvals.decide(approval_id, decided_by="agent:payroll_bot", approve=True)


def test_signoff_blocked_by_anomalies(service: PayrollService, employees: EmployeeService) -> None:
    from hr_agents.models import PayrollInput

    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=5_000_000)],
        by="hr-admin",
    )
    service.compute(run.id, by="hr-admin")  # missing tables → ERROR anomalies

    with pytest.raises(PayrollError, match="blocking anomalies"):
        service.submit_for_signoff(run.id, by="hr-admin")


def test_cannot_edit_after_signoff(
    service: PayrollService,
    employees: EmployeeService,
    rate_tables: RateTableService,
    approvals: ApprovalEngine,
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=8_000_000)],
        by="hr-admin",
    )
    service.compute(run.id, by="hr-admin")
    submitted = service.submit_for_signoff(run.id, by="hr-admin")
    approval_id = submitted.approval_id
    assert approval_id is not None
    approvals.decide(approval_id, decided_by="finance", approve=True)
    service.apply_decision(approval_id)

    with pytest.raises(PayrollError, match="no longer be edited"):
        service.set_inputs(
            run.id,
            inputs=[PayrollInput(employee_id=employee.id, base_salary=1_000_000)],
            by="hr-admin",
        )


def test_rejected_run_returns_to_review_state(
    service: PayrollService,
    employees: EmployeeService,
    rate_tables: RateTableService,
    approvals: ApprovalEngine,
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=8_000_000)],
        by="hr-admin",
    )
    service.compute(run.id, by="hr-admin")
    submitted = service.submit_for_signoff(run.id, by="hr-admin")
    approval_id = submitted.approval_id
    assert approval_id is not None
    approvals.decide(approval_id, decided_by="finance", approve=False, reason="wrong period")
    rejected = service.apply_decision(approval_id)
    assert rejected.status is PayrollRunStatus.REJECTED
    assert rejected.signed_off_by is None


def test_cancel_run_requires_reason_and_state(service: PayrollService) -> None:
    run = make_run(service)
    with pytest.raises(PayrollError, match="requires a reason"):
        service.cancel_run(run.id, by="hr", reason="")

    cancelled = service.cancel_run(run.id, by="hr", reason="wrong period")
    assert cancelled.status is PayrollRunStatus.CANCELLED


# --- THR / kinds -------------------------------------------------------------


def test_thr_run_kind(service: PayrollService) -> None:
    run = make_run(service, kind=PayrollRunKind.THR, period_month=3)
    assert run.kind is PayrollRunKind.THR


# --- export ------------------------------------------------------------------


def test_review_packet_exports_xlsx(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    from io import BytesIO

    from openpyxl import load_workbook

    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=9_000_000)],
        by="hr-admin",
    )
    service.compute(run.id, by="hr-admin")

    content = service.build_review_packet_xlsx(run.id)
    workbook = load_workbook(BytesIO(content))
    sheet = workbook["Payroll 2026-06"]
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][0] == "Employee ID"
    assert rows[1][1] == "Sari Dewi"
    assert any(row[0] == "TOTALS" for row in rows if row[0])

    info = workbook["Run info"]
    notice = [row for row in info.iter_rows(values_only=True) if row[0] == "Notice"]
    assert notice and "does not execute payments" in notice[0][1]


def test_export_requires_lines(service: PayrollService) -> None:
    run = make_run(service)
    with pytest.raises(PayrollError, match="no computed lines"):
        service.build_review_packet_xlsx(run.id)


# --- audit -------------------------------------------------------------------


def test_audit_chain_covers_payroll(
    service: PayrollService,
    employees: EmployeeService,
    rate_tables: RateTableService,
    audit: AuditChain,
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=5_000_000)],
        by="hr-admin",
    )
    service.compute(run.id, by="hr-admin")

    actions = [entry.action for entry in audit.entries]
    assert "payroll.run_created" in actions
    assert "payroll.inputs_set" in actions
    assert "payroll.computed" in actions
    assert audit.verify() == -1
