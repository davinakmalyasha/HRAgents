"""Payroll adapter tests on in-memory SQLite.

The regression these exist for is not "a run disappears" -- it is that a recomputed
run produces *different* numbers. ``compute()`` resolves the rate tables in force for
the period being paid, so re-running a March 2025 payroll after a newer decree was
loaded yields different figures from identical inputs and records the newer tables
as the provenance. ``test_computed_figures_survive_a_restart_unchanged`` pins the
first computation.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.payroll import DbPayrollService
from hr_agents.db.people import DbEmployeeStore
from hr_agents.identity import ActorRef
from hr_agents.models import Employee, PayrollRunKind, PayrollRunStatus, RateEntry, RateTableKind
from hr_agents.models.money import money
from hr_agents.models.payroll import PayrollInput
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.payroll import PayrollError
from hr_agents.services.people_store import ApprovalStore, RateTableStore
from hr_agents.services.rate_tables import RateTableService

TODAY = date.today()
ACTOR = ActorRef.legacy("hr-admin")
YEAR = TODAY.year
MONTH = 6


def _parts(
    factory: sessionmaker[Session],
) -> tuple[DbPayrollService, EmployeeService, RateTableService]:
    audit = AuditChain()
    approvals = ApprovalEngine(ApprovalStore(), audit=audit)
    # payroll_lines.employee_id is a foreign key, so the employee has to be a real
    # row rather than an in-memory one: SQLite does not enforce FKs unless asked.
    employees = EmployeeService(DbEmployeeStore(factory), audit=audit, approvals=approvals)
    rates = RateTableService(RateTableStore(), audit=audit)
    return (
        DbPayrollService(
            factory, employees=employees, rate_tables=rates, approvals=approvals, audit=audit
        ),
        employees,
        rates,
    )


def _seed(rates: RateTableService) -> None:
    """Illustrative rates for tests only; production values are HR-entered."""
    for kind, employer, employee, cap in [
        (RateTableKind.BPJS_KESEHATAN, 4.0, 1.0, 12_000_000.0),
        (RateTableKind.BPJS_KETENAGAKERJAAN_JHT, 3.7, 2.0, None),
        (RateTableKind.BPJS_KETENAGAKERJAAN_JP, 2.0, 1.0, 10_000_000.0),
        (RateTableKind.BPJS_JKK, 0.24, None, None),
        (RateTableKind.BPJS_JKM, 0.3, None, None),
    ]:
        table = rates.create(kind=kind, name=kind.value, actor=ACTOR)
        rates.set_entries(
            table.id,
            entries=[
                RateEntry(
                    label="standard",
                    employer_share_percent=employer,
                    employee_share_percent=employee,
                    wage_cap=money(cap) if cap is not None else None,
                )
            ],
            actor=ACTOR,
        )
        rates.verify(table.id, actor=ACTOR, source_note="test fixture")

    overtime = rates.create(kind=RateTableKind.OVERTIME_PREMIUM, name="OT", actor=ACTOR)
    rates.set_entries(
        overtime.id,
        entries=[
            RateEntry(key="monthly_hours", label="Monthly hours", hours_per_month=173.0),
            RateEntry(key="first_hour", label="First hour", multiplier=1.5),
            RateEntry(key="subsequent_hour", label="Subsequent", multiplier=2.0),
        ],
        actor=ACTOR,
    )
    rates.verify(overtime.id, actor=ACTOR, source_note="test fixture")

    ptkp = rates.create(kind=RateTableKind.PPH21_PTKP, name="PTKP", actor=ACTOR)
    rates.set_entries(
        ptkp.id,
        entries=[RateEntry(key="personal", label="Self", flat_amount=money(54_000_000))],
        actor=ACTOR,
    )
    rates.verify(ptkp.id, actor=ACTOR, source_note="test fixture")

    minimum = rates.create(kind=RateTableKind.MINIMUM_WAGE, name="Minimum", actor=ACTOR)
    rates.set_entries(
        minimum.id,
        entries=[RateEntry(label="Regional", flat_amount=money(2_500_000))],
        actor=ACTOR,
    )
    rates.verify(minimum.id, actor=ACTOR, source_note="test fixture")

    ter = rates.create(kind=RateTableKind.PPH21_TER, name="TER", actor=ACTOR)
    rates.set_entries(
        ter.id,
        entries=[
            RateEntry(
                label="low",
                lower_bound=money(0),
                upper_bound=money(30_000_000),
                employee_share_percent=5.0,
            )
        ],
        actor=ACTOR,
    )
    rates.verify(ter.id, actor=ACTOR, source_note="test fixture")


def _employee(employees: EmployeeService, name: str = "Sari Dewi") -> Employee:
    return employees.create(full_name=name, actor=ACTOR, hire_date=TODAY, job_title="Finance Staff")


def test_run_round_trip(factory: sessionmaker[Session]) -> None:
    service, _, _ = _parts(factory)
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)

    loaded = _parts(factory)[0].get_run(run.id)
    assert loaded.id == run.id
    assert loaded.status is PayrollRunStatus.DRAFT
    assert loaded.kind is PayrollRunKind.MONTHLY
    assert loaded.created_at.tzinfo is not None

    with pytest.raises(PayrollError, match="unknown payroll run"):
        _parts(factory)[0].get_run(uuid4())


def test_inputs_round_trip(factory: sessionmaker[Session]) -> None:
    service, employees, _ = _parts(factory)
    employee = _employee(employees)
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=money("10000.55"),
                overtime_hours=3.0,
                absence_days=2.0,
                service_months=18,
            )
        ],
        actor=ACTOR,
    )

    fresh = _parts(factory)[0].get_run(run.id)
    assert len(fresh.inputs) == 1
    stored = fresh.inputs[0]
    assert stored.base_salary == money("10000.55")
    # Prorating inputs are the values a back-run has to reproduce exactly.
    assert stored.absence_days == 2.0
    assert stored.service_months == 18
    assert stored.overtime_hours == 3.0


def test_computed_figures_survive_a_restart_unchanged(
    factory: sessionmaker[Session],
) -> None:
    """The regression: a lost run cannot be faithfully recomputed.

    `compute()` resolves the rate tables in force for the period. Recomputing after
    a newer decree is loaded gives different money and records the newer tables as
    the provenance, so the first computation is the only correct one.
    """
    service, employees, rates = _parts(factory)
    _seed(rates)
    employee = _employee(employees)
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=money("10000000.01"),
                fixed_allowances=money("1000000.05"),
                overtime_hours=4.0,
            )
        ],
        actor=ACTOR,
    )
    computed = service.compute(run.id, actor=ACTOR)
    original = computed.lines[0]

    fresh = _parts(factory)[0].get_run(run.id)
    assert fresh.status is PayrollRunStatus.READY_FOR_REVIEW
    assert len(fresh.lines) == 1
    restored = fresh.lines[0]
    for field in (
        "base_salary",
        "allowances",
        "overtime_pay",
        "gross",
        "total_deductions",
        "net",
        "employer_cost",
        "pph21",
    ):
        assert getattr(restored, field) == getattr(original, field), field
    # Provenance survives, which is what makes the figures reconstructable.
    assert fresh.rate_table_ids == computed.rate_table_ids
    assert fresh.totals == computed.totals


def test_money_survives_as_exact_two_place_decimals(
    factory: sessionmaker[Session],
) -> None:
    """A float round trip through a double would turn .01 into .010000000000000002.

    The whole reason `models.money` exists is that this is a payslip an employee
    reconciles against a bank transfer, so the stored value must compare equal to
    the computed one with no tolerance.
    """
    from sqlalchemy import select

    from hr_agents.db.payroll_tables import PayrollLineRecord
    from hr_agents.db.session import sync_session_scope

    service, employees, rates = _parts(factory)
    _seed(rates)
    employee = _employee(employees)
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=money("1234567.89"))],
        actor=ACTOR,
    )
    computed = service.compute(run.id, actor=ACTOR)

    session_factory = _parts(factory)[0]._session_factory
    with sync_session_scope(session_factory) as session:
        row = session.execute(select(PayrollLineRecord)).scalars().one()
        assert isinstance(row.base_salary, Decimal)
        assert row.base_salary == Decimal("1234567.89")
    assert computed.lines[0].base_salary == Decimal("1234567.89")


def test_recomputing_replaces_lines_rather_than_merging(
    factory: sessionmaker[Session],
) -> None:
    """A merge would leave a removed employee's line on the payslip."""
    service, employees, rates = _parts(factory)
    _seed(rates)
    first = _employee(employees, "Sari Dewi")
    second = _employee(employees, "Budi")
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)
    inputs = [PayrollInput(employee_id=first.id, base_salary=money("5000000"))]
    service.set_inputs(run.id, inputs=inputs, actor=ACTOR)
    assert len(service.compute(run.id, actor=ACTOR).lines) == 1

    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=first.id, base_salary=money("5000000")),
            PayrollInput(employee_id=second.id, base_salary=money("5000000")),
        ],
        actor=ACTOR,
    )
    service.compute(run.id, actor=ACTOR)
    fresh = _parts(factory)[0].get_run(run.id)
    assert len(fresh.lines) == 2
    assert {line.employee_id for line in fresh.lines} == {first.id, second.id}


def test_line_removal_on_recompute(factory: sessionmaker[Session]) -> None:
    """Dropping an employee from the inputs must remove their line, not orphan it."""
    service, employees, rates = _parts(factory)
    _seed(rates)
    first = _employee(employees, "Sari Dewi")
    second = _employee(employees, "Budi")
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=first.id, base_salary=money("5000000")),
            PayrollInput(employee_id=second.id, base_salary=money("5000000")),
        ],
        actor=ACTOR,
    )
    assert len(service.compute(run.id, actor=ACTOR).lines) == 2

    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=first.id, base_salary=money("5000000"))],
        actor=ACTOR,
    )
    service.compute(run.id, actor=ACTOR)
    fresh = _parts(factory)[0].get_run(run.id)
    assert [line.employee_id for line in fresh.lines] == [first.id]


def test_anomalies_and_status_survive_a_restart(factory: sessionmaker[Session]) -> None:
    """Blocking anomalies are what stop sign-off; losing them unblocks payroll."""
    service, employees, rates = _parts(factory)
    _seed(rates)
    employee = _employee(employees)
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=money("5000000"),
                other_deductions=money("9000000"),
            )
        ],
        actor=ACTOR,
    )
    computed = service.compute(run.id, actor=ACTOR)
    assert computed.blocking_anomalies

    fresh = _parts(factory)[0].get_run(run.id)
    assert {a.code for a in fresh.anomalies} == {"negative_net"}
    assert fresh.blocking_anomalies


def test_signed_off_state_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """An approved run that reverts to review would be exportable twice."""
    from tests.actors import finance as finance_principal

    service, employees, rates = _parts(factory)
    _seed(rates)
    finance = finance_principal()
    employee = _employee(employees)
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=money("5000000"))],
        actor=ACTOR,
    )
    service.compute(run.id, actor=ACTOR)
    # HR raises it, finance decides: the engine refuses to let the raiser decide
    # their own request, which is the rule this test also has to respect.
    submitted = service.submit_for_signoff(run.id, actor=ACTOR)
    assert submitted.approval_id is not None
    service._approvals.decide(
        submitted.approval_id, actor=finance, approve=True, reason="figures checked"
    )
    approved = service.apply_decision(submitted.approval_id, actor=finance)
    assert approved.status is PayrollRunStatus.APPROVED

    fresh = _parts(factory)[0].get_run(run.id)
    assert fresh.status is PayrollRunStatus.APPROVED
    assert fresh.signed_off_by == approved.signed_off_by
    assert fresh.signed_off_at == approved.signed_off_at
    assert fresh.approval_id == approved.approval_id


def test_previous_run_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """The net-deviation check needs the prior period, and reads every run to find it."""
    service, employees, rates = _parts(factory)
    _seed(rates)
    employee = _employee(employees)
    earlier = service.create_run(period_year=YEAR, period_month=3, actor=ACTOR)
    service.set_inputs(
        earlier.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=money("5000000"))],
        actor=ACTOR,
    )
    service.compute(earlier.id, actor=ACTOR)

    later = service.create_run(period_year=YEAR, period_month=4, actor=ACTOR)
    service.set_inputs(
        later.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=money("50000000"))],
        actor=ACTOR,
    )
    computed = service.compute(later.id, actor=ACTOR)
    assert "net_deviation" in {a.code for a in computed.anomalies}


def test_list_runs_is_period_ordered_after_a_restart(
    factory: sessionmaker[Session],
) -> None:
    service, _, _ = _parts(factory)
    for month in (MONTH, 3, 9):
        service.create_run(period_year=YEAR, period_month=month, actor=ACTOR)

    fresh = _parts(factory)[0]
    assert [(run.period_year, run.period_month) for run in fresh.list_runs()] == [
        (YEAR, 3),
        (YEAR, MONTH),
        (YEAR, 9),
    ]


def test_thr_months_survive_a_restart(factory: sessionmaker[Session]) -> None:
    """The number an employee checks first is how many months they were credited."""
    from hr_agents.models import RateEntry as Entry

    service, employees, rates = _parts(factory)
    _seed(rates)
    thr = rates.create(kind=RateTableKind.THR_FORMULA, name="THR", actor=ACTOR)
    rates.set_entries(
        thr.id,
        entries=[
            Entry(key="under_1y", label="Under a year", multiplier=1.0),
            Entry(key="2y", label="Two years", multiplier=3.0),
        ],
        actor=ACTOR,
    )
    rates.verify(thr.id, actor=ACTOR, source_note="test fixture")

    employee = _employee(employees)
    run = service.create_run(
        period_year=YEAR, period_month=MONTH, actor=ACTOR, kind=PayrollRunKind.THR
    )
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=money("10000000"),
                service_months=30,
            )
        ],
        actor=ACTOR,
    )
    service.compute(run.id, actor=ACTOR)

    fresh = _parts(factory)[0].get_run(run.id)
    assert fresh.lines[0].thr_months == 3
    assert fresh.lines[0].gross == money("30000000")


def test_notes_survive_a_restart(factory: sessionmaker[Session]) -> None:
    service, employees, rates = _parts(factory)
    _seed(rates)
    employee = _employee(employees)
    run = service.create_run(period_year=YEAR, period_month=MONTH, actor=ACTOR)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=money("5000000"),
                note="Backdated correction",
            )
        ],
        actor=ACTOR,
    )
    service.compute(run.id, actor=ACTOR)
    assert _parts(factory)[0].get_run(run.id).lines[0].notes == ["Backdated correction"]
