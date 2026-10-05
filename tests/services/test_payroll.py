from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from tests.actors import finance as finance_principal

from hr_agents.identity import ActorRef
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
from hr_agents.models.money import ZERO, add, percent_of, sum_money
from hr_agents.models.money import money as m
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
from hr_agents.services.payroll import _working_days_in_month as working_days_in

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
            kind=kind, name=kind.value, actor=ActorRef.legacy("hr-admin"), jurisdiction="ID"
        )
        rate_tables.set_entries(
            table.id,
            entries=[
                RateEntry(
                    label="standard",
                    employer_share_percent=employer,
                    employee_share_percent=employee,
                    wage_cap=m(cap) if cap is not None else None,
                )
            ],
            actor=ActorRef.legacy("hr-admin"),
        )
        rate_tables.verify(
            table.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture (illustrative)"
        )

    overtime = rate_tables.create(
        kind=RateTableKind.OVERTIME_PREMIUM,
        name="Overtime",
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.set_entries(
        overtime.id,
        entries=[
            # Every part of overtime pricing is operator-entered; the service has no
            # defaults for any of them and blocks if a row is missing.
            RateEntry(key="monthly_hours", label="Monthly hours", hours_per_month=173.0),
            RateEntry(key="first_hour", label="First hour each day", multiplier=1.5),
            RateEntry(key="subsequent_hour", label="Subsequent hours", multiplier=2.0),
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(overtime.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture")

    ptkp = rate_tables.create(
        kind=RateTableKind.PPH21_PTKP, name="PTKP", actor=ActorRef.legacy("hr-admin")
    )
    rate_tables.set_entries(
        ptkp.id,
        entries=[
            RateEntry(key="personal", label="Self", flat_amount=m(54_000_000)),
            RateEntry(key="dependent", label="Per dependent", flat_amount=m(6_750_000)),
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(ptkp.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture")

    minimum = rate_tables.create(
        kind=RateTableKind.MINIMUM_WAGE, name="Minimum wage", actor=ActorRef.legacy("hr-admin")
    )
    rate_tables.set_entries(
        minimum.id,
        entries=[RateEntry(label="Regional minimum", flat_amount=m(2_500_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(minimum.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture")

    thr = rate_tables.create(
        kind=RateTableKind.THR_FORMULA, name="THR", actor=ActorRef.legacy("hr-admin")
    )
    rate_tables.set_entries(
        thr.id,
        entries=[
            RateEntry(key="under_1y", label="Under 1 year", multiplier=1.0),
            RateEntry(key="1y", label="1 to under 2 years", multiplier=2.0),
            RateEntry(key="2y", label="2 to under 3 years", multiplier=3.0),
            RateEntry(key="8y_plus", label="8 years and over", multiplier=10.0),
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(thr.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture")

    pph = rate_tables.create(
        kind=RateTableKind.PPH21_TER, name="TER", actor=ActorRef.legacy("hr-admin")
    )
    rate_tables.set_entries(
        pph.id,
        entries=[
            RateEntry(
                label="low", lower_bound=m(0), upper_bound=m(10_000_000), employee_share_percent=2.0
            ),
            RateEntry(
                label="mid",
                lower_bound=m(10_000_000.1),
                upper_bound=m(30_000_000),
                employee_share_percent=5.0,
            ),
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(pph.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture")


def make_employee(employees: EmployeeService, name: str = "Sari Dewi") -> Employee:
    return employees.create(
        full_name=name,
        actor=ActorRef.legacy("hr-admin"),
        hire_date=TODAY,
        job_title="Finance Staff",
    )


def zero_ptkp(rate_tables: RateTableService) -> None:
    """Drop the personal exemption to nil, to isolate bracket arithmetic.

    Re-verifying is required: `set_entries` invalidates verification, and an
    unverified table must not drive payroll.
    """
    table = next(t for t in rate_tables.list_all() if t.kind is RateTableKind.PPH21_PTKP)
    rate_tables.set_entries(
        table.id,
        entries=[
            RateEntry(key="personal", label="Self", flat_amount=ZERO),
            RateEntry(key="dependent", label="Per dependent", flat_amount=m(6_750_000)),
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(table.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture")


def make_run(
    service: PayrollService,
    *,
    period_month: int = PERIOD_MONTH,
    kind: PayrollRunKind = PayrollRunKind.MONTHLY,
) -> PayrollRun:
    return service.create_run(
        period_year=PERIOD_YEAR,
        period_month=period_month,
        actor=ActorRef.legacy("hr-admin"),
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
        service.compute(run.id, actor=ActorRef.legacy("hr-admin"))


def test_compute_blocks_without_verified_tables(
    service: PayrollService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[
            __import__("hr_agents.models", fromlist=["PayrollInput"]).PayrollInput(
                employee_id=employee.id, base_salary=m(5_000_000)
            )
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    # Missing required tables are ERROR anomalies
    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "rate_table_unusable:bpjs_kesehatan" in codes
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
                base_salary=m(10_000_000),
                fixed_allowances=m(1_000_000),
                overtime_hours=3.0,
            )
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    assert computed.status is PayrollRunStatus.READY_FOR_REVIEW
    line = computed.lines[0]
    assert line.employee_name == "Sari Dewi"
    # wage = 11,000,000
    assert line.bpjs_kesehatan_employee == m(110_000)  # 1%
    assert line.bpjs_jht_employee == m(220_000)  # 2%
    assert line.bpjs_jp_employee == m(100_000)  # 1% capped at 10M
    # Overtime is priced per day: UU 13/2003 Pasal 56(2) gives 1.5x for the first
    # hour *of each day* and 2x beyond that, so three overtime hours on three
    # separate days are all first-tier. The previous code applied the 1.5x tier to
    # one hour for the whole month, pricing 3 hours as 1 at 1.5x and 2 at 2.0x.
    hourly = Decimal(11_000_000) / Decimal(173)
    expected_ot = (hourly * Decimal("1.5") * 3).quantize(Decimal("0.01"))
    assert line.overtime_pay == expected_ot
    assert line.gross == m(11_000_000) + expected_ot
    # employer cost present
    assert line.employer_cost > 0
    # No PPh 21: gross is far below the personal exemption in the verified PTKP
    # table. Asserting `== 0` rather than `> 0` is the point -- it is evidence the
    # exemption is being applied, not evidence that the bracket was skipped.
    assert line.pph21 == ZERO


def test_missing_employee_is_not_fatal(
    service: PayrollService, rate_tables: RateTableService
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=uuid4(), base_salary=m(5_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
    assert computed.lines[0].employee_name == ""
    assert computed.lines[0].net > 0


# --- exact money, proration and rate provenance --------------------------------


def test_payslip_totals_are_exact_not_float_rounded(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """Thirty employees at a figure that `float` addition cannot hold.

    0.1 has no exact binary representation, so summing it 30 times drifts. The
    Decimal sum must be exactly `base * 30`, and the run total must equal the sum
    of the lines -- which is the identity an HR department reconciles a bank
    transfer against.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    run = make_run(service)
    salary = m(0.1)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=make_employee(employees, f"Staff {i}").id, base_salary=salary)
            for i in range(30)
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    totals = computed.totals
    assert totals.employees == 30
    assert totals.gross == sum_money([line.gross for line in computed.lines])
    # Every line is exactly 0.10 and the run total is exactly 3.00, which float
    # addition of thirty 0.1s does not guarantee.
    assert all(line.gross == m(0.1) for line in computed.lines)
    assert totals.gross == m(3.0)


def test_absence_days_prorate_pay(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """`absence_days` was collected, validated, exposed and never read.

    An employee absent for half the month was paid in full, with their own absence
    note printed on the payslip. Base pay and fixed allowances must scale with the
    days actually paid.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=m(10_000_000),
                fixed_allowances=m(1_000_000),
                absence_days=8,
            )
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
    line = computed.lines[0]

    working_days = working_days_in(PERIOD_YEAR, PERIOD_MONTH)
    fraction = (working_days - 8) / working_days
    assert line.base_salary == percent_of(m(10_000_000), fraction * 100)
    assert line.allowances == percent_of(m(1_000_000), fraction * 100)
    # The bonus is not attendance-earned, so an absence does not reduce it.
    assert line.bonus == ZERO
    line.check_invariants()


def test_absence_covering_the_whole_period_is_an_error(
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
                base_salary=m(10_000_000),
                absence_days=float(working_days_in(PERIOD_YEAR, PERIOD_MONTH)),
            )
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "absence_exceeds_period" in codes
    assert computed.blocking_anomalies


def test_keyed_jkk_table_without_a_recorded_risk_class_blocks(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """A keyed JKK table must not be silently charged to everyone.

    `Employee` has no risk-class field yet, so a table that distinguishes classes
    has nothing to select with. Charging its first row is what the old code did and
    it under-declares a high-risk role; the run must block instead.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    jkk = next(t for t in rate_tables.list_all() if t.kind is RateTableKind.BPJS_JKK)
    rate_tables.set_entries(
        jkk.id,
        entries=[
            RateEntry(key="class_1", label="low", employer_share_percent=0.24),
            RateEntry(key="class_4", label="high", employer_share_percent=1.74),
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(jkk.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture")

    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(10_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "jkk_risk_class_unrecorded" in codes
    assert computed.lines[0].bpjs_jkk_employer == ZERO
    assert computed.blocking_anomalies


def test_pph21_raises_on_uncovered_gross(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """Gross above the top bracket must not be silently taxed at zero.

    The old loop fell off the end of the bracket table and returned `0.0`, so the
    highest earners -- the ones with the most to lose -- paid nothing. That is the
    worst available failure mode, so the run refuses instead.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(90_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    with pytest.raises(PayrollError, match="TER brackets cover up to"):
        service.compute(run.id, actor=ActorRef.legacy("hr-admin"))


def test_pph21_is_progressive_not_the_whole_gross_at_one_rate(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """TER accumulates slab by slab; it does not apply one bracket to all of gross.

    The flat-bracket version withheld 5% of the entire 20,000,000 gross
    (1,000,000) where progressive accumulation gives 2% of the first 10,000,000 plus
    5% of the remaining 10,000,000 (700,000).
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    zero_ptkp(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(20_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    expected = add(percent_of(m(10_000_000), 2.0), percent_of(m(10_000_000), 5.0))
    assert computed.lines[0].pph21 == expected


def test_pph21_reduces_the_taxable_base_by_ptkp_and_dependents(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """The exemption is subtracted *before* the brackets are walked.

    Working: PTKP + 2 dependents = 54,000,000 + 13,500,000. On a 70,000,000 gross
    the taxable base is 2,500,000, which lands wholly inside the first bracket, so
    2% of 2,500,000 = 50,000 is owed. An unadjusted base of 70,000,000 would blow
    past the fixture's top bracket entirely.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    employees.update_payroll_profile(employee.id, dependents=2, actor=ActorRef.legacy("hr-admin"))
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(70_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    assert computed.lines[0].pph21 == percent_of(m(2_500_000), 2.0)


def test_pph21_blocks_when_no_ptkp_table_is_verified(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """Negative test: withholding with no exemption is not a quiet outcome.

    Over-collecting every month leaves the employee owed the difference at year end,
    which surfaces as an audit finding rather than as a payroll error.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    ptkp = next(t for t in rate_tables.list_all() if t.kind is RateTableKind.PPH21_PTKP)
    # Verified but with no `personal` row, which is what an operator who filled the
    # table in half actually has. (An empty table cannot be verified at all.)
    rate_tables.set_entries(
        ptkp.id,
        entries=[RateEntry(key="dependent", label="Per dependent", flat_amount=m(6_750_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(ptkp.id, actor=ActorRef.legacy("hr-admin"), source_note="half-filled")

    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(20_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "pph21_ptkp_missing" in codes
    assert computed.blocking_anomalies


def test_payslip_flags_that_bpjs_on_thr_is_not_modelled(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """A THR payslip must block sign-off rather than quietly apply monthly rules.

    Which contributions attach to a termination payout is not derivable from the
    monthly tables. The gap is declared as an ERROR so a named human settles it.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service, kind=PayrollRunKind.THR)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(
                employee_id=employee.id,
                base_salary=m(10_000_000),
                service_months=30,
            )
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "thr_bpjs_unmodelled" in codes
    assert computed.blocking_anomalies
    assert computed.lines[0].bpjs_kesehatan_employee == ZERO
    assert computed.lines[0].bpjs_jkk_employer == ZERO


def test_payroll_uses_the_rate_table_in_force_for_the_period(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """Back-running a period must use that period's rates.

    `_resolve_tables` filtered `list_all()` -- which is sorted by *name* -- and took
    the last match, so whichever table name sorted latest won regardless of
    verification or effective dates, and its id was recorded as the provenance.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    back_period = date(PERIOD_YEAR, 1, 1)

    superseding = rate_tables.create(
        kind=RateTableKind.BPJS_KESEHATAN,
        name="BPJS Kesehatan 2027",
        actor=ActorRef.legacy("hr-admin"),
        effective_from=date(PERIOD_YEAR + 1, 1, 1),
    )
    rate_tables.set_entries(
        superseding.id,
        entries=[RateEntry(label="2027", employee_share_percent=2.0, employer_share_percent=5.0)],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(superseding.id, actor=ActorRef.legacy("hr-admin"), source_note="later")

    run = service.create_run(
        period_year=PERIOD_YEAR,
        period_month=back_period.month,
        actor=ActorRef.legacy("hr-admin"),
    )
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(10_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    assert computed.rate_table_ids[RateTableKind.BPJS_KESEHATAN.value] != str(superseding.id)
    # The in-force table is the 1% employee share, not the 2027 table's 2%.
    assert computed.lines[0].bpjs_kesehatan_employee == m(100_000)


def test_thr_pays_months_of_wages_for_length_of_service(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """THR is months of wages from the verified ladder, not a relabelled month.

    30 months of service selects the `2y` row (3 months), so a Rp 10,000,000 wage
    owes Rp 30,000,000. The old code ignored `kind` entirely and paid Rp 10,000,000.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service, kind=PayrollRunKind.THR)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=employee.id, base_salary=m(10_000_000), service_months=30)
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
    line = computed.lines[0]

    assert line.thr_months == 3
    assert line.gross == m(30_000_000)
    assert line.net == m(30_000_000)
    line.check_invariants()


def test_thr_blocks_when_the_service_length_is_not_covered(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """Negative test: an uncovered service length must not quietly pay zero.

    The fixture ladder has no `5y` row, so five years of service cannot be priced.
    Paying a departing employee nothing because a table row is missing is the worst
    available outcome, so the run blocks instead.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service, kind=PayrollRunKind.THR)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=employee.id, base_salary=m(10_000_000), service_months=60)
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "thr_entitlement_missing" in codes
    assert computed.lines[0].gross == ZERO
    assert computed.blocking_anomalies


def test_payroll_below_the_verified_minimum_wage_blocks(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """Negative test: paying under the statutory minimum is a labour-law breach.

    The `minimum_wage` table existed in the enum since the start and nothing read
    it, so an employee could be paid Rp 1,000,000 with no complaint from the system.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(1_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "below_minimum_wage" in codes
    assert computed.blocking_anomalies


def test_payroll_at_or_above_the_minimum_wage_is_clean(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(2_500_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "below_minimum_wage" not in codes


def test_overtime_blocks_when_the_table_lacks_a_required_row(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """Negative test: no fallback to a hardcoded 173/1.5/2.0.

    `AGENTS.md` forbids hardcoded statutory rates. The service used to carry them as
    constants, so a half-configured overtime table produced plausible-looking figures
    nobody could trace to a source. A missing row now blocks.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    overtime = next(t for t in rate_tables.list_all() if t.kind is RateTableKind.OVERTIME_PREMIUM)
    rate_tables.set_entries(
        overtime.id,
        entries=[RateEntry(key="first_hour", label="First hour", multiplier=1.5)],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(overtime.id, actor=ActorRef.legacy("hr-admin"), source_note="partial")

    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[
            PayrollInput(employee_id=employee.id, base_salary=m(10_000_000), overtime_hours=4.0)
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "overtime_rules_missing" in codes
    assert computed.lines[0].overtime_pay == ZERO
    assert computed.blocking_anomalies


def test_jkk_risk_class_selects_the_matching_row(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """A recorded risk class must actually choose the rate.

    Before the keyed lookup, the first row was applied to everyone: a class-IV
    industrial worker was charged the class-I 0.24% instead of 1.74%, which is both
    an under-declaration and a BPJS compliance failure.
    """
    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    jkk = next(t for t in rate_tables.list_all() if t.kind is RateTableKind.BPJS_JKK)
    rate_tables.set_entries(
        jkk.id,
        entries=[
            RateEntry(key="class_1", label="Low", employer_share_percent=0.24),
            RateEntry(key="class_4", label="High", employer_share_percent=1.74),
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    rate_tables.verify(jkk.id, actor=ActorRef.legacy("hr-admin"), source_note="test fixture")

    employee = make_employee(employees)
    employees.update_payroll_profile(
        employee.id, jkk_risk_level=4, actor=ActorRef.legacy("hr-admin")
    )
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(10_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    assert computed.lines[0].bpjs_jkk_employer == percent_of(m(10_000_000), 1.74)
    codes = {anomaly.code for anomaly in computed.anomalies}
    assert "jkk_risk_class_unrecorded" not in codes


def test_line_invariants_reject_an_inconsistent_payslip() -> None:
    """The identity check must actually fail, or it is decoration.

    Negative test: a payslip whose gross does not match its components is what an
    employee's bank reconciliation compares against, so it must be unconstructable.
    """
    from hr_agents.models import PayrollLine

    with pytest.raises(ValueError, match=r"gross .* does not equal"):
        PayrollLine(
            employee_id=uuid4(),
            base_salary=m(1_000),
            allowances=m(500),
            gross=m(999),
            total_deductions=ZERO,
            net=m(999),
            employer_cost=ZERO,
        ).check_invariants()

    with pytest.raises(ValueError, match=r"net .* does not equal"):
        PayrollLine(
            employee_id=uuid4(),
            base_salary=m(1_000),
            gross=m(1_000),
            other_deductions=m(100),
            total_deductions=m(100),
            net=m(950),
            employer_cost=ZERO,
        ).check_invariants()

    with pytest.raises(ValueError, match=r"employer_cost .* does not equal"):
        PayrollLine(
            employee_id=uuid4(),
            base_salary=m(1_000),
            gross=m(1_000),
            total_deductions=ZERO,
            net=m(1_000),
            bpjs_jkk_employer=m(50),
            employer_cost=ZERO,
        ).check_invariants()


def test_xlsx_packet_reports_the_line_employer_cost(
    service: PayrollService, employees: EmployeeService, rate_tables: RateTableService
) -> None:
    """The packet's employer column is the line's own exact total.

    It used to be re-summed in the exporter with `round()`, a second, float,
    independently-drifting computation of a figure the line had already proved.
    """
    import io

    from openpyxl import load_workbook

    from hr_agents.models import PayrollInput

    seed_verified_tables(rate_tables)
    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(10_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    sheet = load_workbook(io.BytesIO(service.build_review_packet_xlsx(run.id))).worksheets[0]
    headers = [cell.value for cell in sheet[1]]
    employer_column = headers.index("Employer BPJS (total)")
    line = computed.lines[0]
    assert sheet.cell(row=2, column=employer_column + 1).value == pytest.approx(
        float(line.employer_cost), abs=0.005
    )


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
                base_salary=m(1_000_000),
                other_deductions=m(5_000_000),
            )
        ],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
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
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(5_000_000), overtime_hours=80)],
        actor=ActorRef.legacy("hr-admin"),
    )
    computed = service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
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
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(10_000_000))],
        actor=ActorRef.legacy("hr"),
    )
    service.compute(first.id, actor=ActorRef.legacy("hr"))

    second = make_run(service, period_month=6)
    service.set_inputs(
        second.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(4_000_000))],
        actor=ActorRef.legacy("hr"),
    )
    computed = service.compute(second.id, actor=ActorRef.legacy("hr"))

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
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(8_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    submitted = service.submit_for_signoff(run.id, actor=ActorRef.legacy("hr-admin"))
    assert submitted.status is PayrollRunStatus.PENDING_SIGNOFF

    queue = approvals.pending_for(ApproverRole.FINANCE)
    assert any(item.id == submitted.approval_id for item in queue)

    approval_id = submitted.approval_id
    assert approval_id is not None
    approvals.decide(approval_id, actor=finance_principal("finance-lead"), approve=True)
    approved = service.apply_decision(approval_id, actor=ActorRef.legacy("hr-admin"))

    assert approved.status is PayrollRunStatus.APPROVED
    assert approved.signed_off_by == "finance-lead"

    exported = service.mark_exported(run.id, actor=finance_principal("finance-lead"))
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
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(8_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
    submitted = service.submit_for_signoff(run.id, actor=ActorRef.legacy("hr-admin"))

    approval_id = submitted.approval_id
    assert approval_id is not None
    with pytest.raises(Exception, match="named human"):
        approvals.decide(approval_id, actor=ActorRef.agent("payroll_bot"), approve=True)


def test_signoff_blocked_by_anomalies(service: PayrollService, employees: EmployeeService) -> None:
    from hr_agents.models import PayrollInput

    employee = make_employee(employees)
    run = make_run(service)
    service.set_inputs(
        run.id,
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(5_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    service.compute(run.id, actor=ActorRef.legacy("hr-admin"))  # missing tables → ERROR anomalies

    with pytest.raises(PayrollError, match="blocking anomalies"):
        service.submit_for_signoff(run.id, actor=ActorRef.legacy("hr-admin"))


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
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(8_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
    submitted = service.submit_for_signoff(run.id, actor=ActorRef.legacy("hr-admin"))
    approval_id = submitted.approval_id
    assert approval_id is not None
    approvals.decide(approval_id, actor=finance_principal("finance"), approve=True)
    service.apply_decision(approval_id, actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(PayrollError, match="no longer be edited"):
        service.set_inputs(
            run.id,
            inputs=[PayrollInput(employee_id=employee.id, base_salary=m(1_000_000))],
            actor=ActorRef.legacy("hr-admin"),
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
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(8_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    service.compute(run.id, actor=ActorRef.legacy("hr-admin"))
    submitted = service.submit_for_signoff(run.id, actor=ActorRef.legacy("hr-admin"))
    approval_id = submitted.approval_id
    assert approval_id is not None
    approvals.decide(
        approval_id, actor=finance_principal("finance"), approve=False, reason="wrong period"
    )
    rejected = service.apply_decision(approval_id, actor=ActorRef.legacy("hr-admin"))
    assert rejected.status is PayrollRunStatus.REJECTED
    assert rejected.signed_off_by is None


def test_cancel_run_requires_reason_and_state(service: PayrollService) -> None:
    run = make_run(service)
    with pytest.raises(PayrollError, match="requires a reason"):
        service.cancel_run(run.id, actor=ActorRef.legacy("hr"), reason="")

    cancelled = service.cancel_run(run.id, actor=ActorRef.legacy("hr"), reason="wrong period")
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
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(9_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

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
        inputs=[PayrollInput(employee_id=employee.id, base_salary=m(5_000_000))],
        actor=ActorRef.legacy("hr-admin"),
    )
    service.compute(run.id, actor=ActorRef.legacy("hr-admin"))

    actions = [entry.action for entry in audit.entries]
    assert "payroll.run_created" in actions
    assert "payroll.inputs_set" in actions
    assert "payroll.computed" in actions
    assert audit.verify() == -1
