"""Export deterministic parity fixtures from the Python reference implementation.

The Python product is the oracle until Gate 5. This script runs offline (no
network, no database) and writes fixtures that the Rust core must reproduce
exactly. It is never shipped in the installer.

Usage:
    uv run python scripts/parity_export.py [output-dir]
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from hr_agents.models.audit import ActorProvenance, ActorType, AuditActor, AuditEntry
from hr_agents.models.compensation import RateEntry, RateTable, RateTableKind
from hr_agents.models.evaluation import ScoreVector, ScoringRun, aggregate_runs
from hr_agents.models.money import add, money, percent_of, sub
from hr_agents.services.payroll import PayrollService

OPERATOR_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_AT = datetime(2026, 11, 1, 9, 0, 0, 123000, tzinfo=UTC)


def money_cases() -> list[dict[str, object]]:
    cases = [
        ("zero", "0"),
        ("half_up_positive", "0.125"),
        ("half_up_negative", "-0.125"),
        ("two_places", "1234567.89"),
        ("large", "9876543210.55"),
    ]
    return [{"name": name, "input": value, "sen": int(money(value) * 100)} for name, value in cases]


def money_operations() -> list[dict[str, object]]:
    amount = money("1000000")
    return [
        {
            "name": "percent_2_5",
            "amount": "1000000",
            "percent": "2.5",
            "sen": int(percent_of(amount, "2.5") * 100),
        },
        {
            "name": "add",
            "left": "10.10",
            "right": "20.20",
            "sen": int(add("10.10", "20.20") * 100),
        },
        {
            "name": "sub",
            "left": "10.10",
            "right": "20.20",
            "sen": int(sub("10.10", "20.20") * 100),
        },
    ]


def audit_cases() -> list[dict[str, object]]:
    actor = AuditActor(
        actor_type=ActorType.HUMAN,
        actor_id=str(OPERATOR_ID),
        display_name="Rina",
        provenance=ActorProvenance.AUTHENTICATED,
        role="hr_operator",
    )
    payload = {
        "employee_no": "E-001",
        "name": "Ayu Lestari",
        "dependents": 1,
        "amount_sen": 1152000000,
        "tags": ["payroll", "verified"],
    }
    first = AuditEntry.compute_hash(
        prev_hash=None,
        actor=actor,
        action="employee.created",
        subject_type="employee",
        subject_id="22222222-2222-4222-8222-222222222222",
        payload=payload,
        created_at=CREATED_AT,
    )
    second = AuditEntry.compute_hash(
        prev_hash=first,
        actor=actor,
        action="payroll.approved",
        subject_type="payroll_run",
        subject_id="33333333-3333-4333-8333-333333333333",
        payload={"period": "2026-11-01", "net_sen": 1152000000},
        created_at=CREATED_AT,
    )
    return [
        {
            "name": "employee_created",
            "actor": {
                "actor_type": "human",
                "actor_id": str(OPERATOR_ID),
                "display_name": "Rina",
                "provenance": "authenticated",
                "role": "hr_operator",
            },
            "action": "employee.created",
            "subject_type": "employee",
            "subject_id": "22222222-2222-4222-8222-222222222222",
            "payload": payload,
            "created_at": "2026-11-01T09:00:00.123000+00:00",
            "prev_hash": None,
            "entry_hash": first,
        },
        {
            "name": "payroll_approved",
            "actor": {
                "actor_type": "human",
                "actor_id": str(OPERATOR_ID),
                "display_name": "Rina",
                "provenance": "authenticated",
                "role": "hr_operator",
            },
            "action": "payroll.approved",
            "subject_type": "payroll_run",
            "subject_id": "33333333-3333-4333-8333-333333333333",
            "payload": {"period": "2026-11-01", "net_sen": 1152000000},
            "created_at": "2026-11-01T09:00:00.123000+00:00",
            "prev_hash": first,
            "entry_hash": second,
        },
    ]


def pph21_cases() -> list[dict[str, object]]:
    table = RateTable(
        kind=RateTableKind.PPH21_TER,
        name="TER parity fixture",
        entries=[
            RateEntry(
                label="0-10m",
                lower_bound=money("0"),
                upper_bound=money("10000000"),
                employee_share_percent=0.5,
            ),
            RateEntry(
                label="10m-100m",
                lower_bound=money("10000000"),
                upper_bound=money("100000000"),
                employee_share_percent=1.0,
            ),
            RateEntry(
                label="100m-1b",
                lower_bound=money("100000000"),
                upper_bound=money("1000000000"),
                employee_share_percent=2.0,
            ),
        ],
    )
    cases = [
        ("20m_no_ptkp", "20000000", "0"),
        ("below_ptkp", "20000000", "58500000"),
        ("200m_with_ptkp", "200000000", "54000000"),
        ("exact_bracket_top", "100000000", "0"),
    ]
    return [
        {
            "name": name,
            "gross": gross,
            "exemption": exemption,
            "sen": int(PayrollService._compute_pph21(table, money(gross), money(exemption)) * 100),
        }
        for name, gross, exemption in cases
    ]


def scoring_cases() -> dict[str, object]:
    runs = [
        ScoringRun(
            run_index=index,
            extraction_id=uuid4(),
            vector=ScoreVector(
                technical_depth=technical,
                stack_alignment=stack,
                systems_literacy=systems,
                verifiable_certifications=certs,
            ),
        )
        for index, (technical, stack, systems, certs) in enumerate(
            [
                (0.8, 0.7, 0.6, 0.5),
                (0.9, 0.6, 0.7, 0.4),
                (0.7, 0.8, 0.5, 0.6),
            ]
        )
    ]
    mean, _, s_tech, sigma = aggregate_runs(runs)
    return {
        "weights_bp": {
            "technical_depth": 4000,
            "stack_alignment": 3000,
            "systems_literacy": 2000,
            "verifiable_certifications": 1000,
        },
        "runs": [
            {
                "technical_depth": round(run.vector.technical_depth * 10000),
                "stack_alignment": round(run.vector.stack_alignment * 10000),
                "systems_literacy": round(run.vector.systems_literacy * 10000),
                "verifiable_certifications": round(run.vector.verifiable_certifications * 10000),
            }
            for run in runs
        ],
        "dimension_scores_bp": {
            "technical_depth": round(mean.technical_depth * 10000),
            "stack_alignment": round(mean.stack_alignment * 10000),
            "systems_literacy": round(mean.systems_literacy * 10000),
            "verifiable_certifications": round(mean.verifiable_certifications * 10000),
        },
        "overall_bp": round(s_tech * 10000),
        "sigma_bp": round(sigma * 10000),
    }


def _parity_verified_table(kind, entries):
    """Verified table for parity export (illustrative values, operator-owned in prod)."""
    from hr_agents.models.common import utc_now
    from hr_agents.models.compensation import RateTable

    table = RateTable(kind=kind, name=kind.value, entries=entries)
    return table.model_copy(
        update={
            "verified": True,
            "verified_by": "parity",
            "verified_at": utc_now(),
            "source_note": "parity fixture (illustrative)",
        }
    )


def _parity_base_tables(*, jp_cap=None):
    """Shared oracle tables: BPJS shares, overtime 173/1.5/2.0, PTKP, TER, minimum."""
    from hr_agents.models.compensation import RateEntry, RateTableKind
    from hr_agents.models.money import money as m

    tables = {}
    tables[RateTableKind.BPJS_KESEHATAN] = _parity_verified_table(
        RateTableKind.BPJS_KESEHATAN,
        [
            RateEntry(
                label="standard",
                employee_share_percent=1.0,
                employer_share_percent=4.0,
            )
        ],
    )
    tables[RateTableKind.BPJS_KETENAGAKERJAAN_JHT] = _parity_verified_table(
        RateTableKind.BPJS_KETENAGAKERJAAN_JHT,
        [
            RateEntry(
                key="normal",
                label="normal",
                employee_share_percent=2.0,
                employer_share_percent=3.7,
            )
        ],
    )
    tables[RateTableKind.BPJS_KETENAGAKERJAAN_JP] = _parity_verified_table(
        RateTableKind.BPJS_KETENAGAKERJAAN_JP,
        [
            RateEntry(
                label="standard",
                employee_share_percent=1.0,
                employer_share_percent=2.0,
                wage_cap=m(jp_cap) if jp_cap is not None else None,
            )
        ],
    )
    tables[RateTableKind.BPJS_JKK] = _parity_verified_table(
        RateTableKind.BPJS_JKK,
        [RateEntry(key="class_1", label="class I", employer_share_percent=0.24)],
    )
    tables[RateTableKind.BPJS_JKM] = _parity_verified_table(
        RateTableKind.BPJS_JKM,
        [RateEntry(label="standard", employer_share_percent=0.3)],
    )
    tables[RateTableKind.OVERTIME_PREMIUM] = _parity_verified_table(
        RateTableKind.OVERTIME_PREMIUM,
        [
            RateEntry(key="monthly_hours", label="Monthly hours", hours_per_month=173.0),
            RateEntry(key="first_hour", label="First hour each day", multiplier=1.5),
            RateEntry(key="subsequent_hour", label="Subsequent hours", multiplier=2.0),
        ],
    )
    tables[RateTableKind.PPH21_PTKP] = _parity_verified_table(
        RateTableKind.PPH21_PTKP,
        [
            RateEntry(key="personal", label="Self", flat_amount=m("54000000")),
            RateEntry(key="dependent", label="Per dependent", flat_amount=m("4500000")),
        ],
    )
    tables[RateTableKind.PPH21_TER] = _parity_verified_table(
        RateTableKind.PPH21_TER,
        [
            RateEntry(
                label="0-10m",
                lower_bound=m("0"),
                upper_bound=m("10000000"),
                employee_share_percent=0.5,
            ),
            RateEntry(
                label="10m-100m",
                lower_bound=m("10000000"),
                upper_bound=m("100000000"),
                employee_share_percent=1.0,
            ),
        ],
    )
    tables[RateTableKind.MINIMUM_WAGE] = _parity_verified_table(
        RateTableKind.MINIMUM_WAGE,
        [RateEntry(label="Regional minimum", flat_amount=m("2500000"))],
    )
    return tables


def _parity_thr_tables():
    from hr_agents.models.compensation import RateEntry, RateTableKind
    from hr_agents.models.money import money as m  # noqa: F401 (kept for symmetry)

    tables = _parity_base_tables()
    tables[RateTableKind.THR_FORMULA] = _parity_verified_table(
        RateTableKind.THR_FORMULA,
        [
            RateEntry(key="under_1y", label="Under 1 year", multiplier=1.0),
            RateEntry(key="1y", label="1 to under 2 years", multiplier=2.0),
            RateEntry(key="2y", label="2 to under 3 years", multiplier=3.0),
            RateEntry(key="8y_plus", label="8 years and over", multiplier=10.0),
        ],
    )
    return tables


def bpjs_cases() -> list[dict[str, object]]:
    """BPJS shares on a 12M wage, plus a JP-capped variant (oracle: _share)."""
    import datetime
    from uuid import uuid4

    from hr_agents.models import Employee
    from hr_agents.models.money import money as m
    from hr_agents.models.payroll import PayrollInput
    from hr_agents.services.payroll import PayrollService, _share

    wage = m("12000000")
    # Direct _share oracle values (unit level, sen integers).
    unit = [
        ("kes", 1.0, 4.0, None, False),
        ("kes", 1.0, 4.0, None, True),
        ("jht", 2.0, 3.7, None, False),
        ("jht", 2.0, 3.7, None, True),
        ("jp", 1.0, 2.0, None, False),
        ("jp", 1.0, 2.0, None, True),
        ("jkk", None, 0.24, None, True),
        ("jkm", None, 0.3, None, True),
        ("jp_capped", 1.0, 2.0, "10000000", False),
        ("jp_capped", 1.0, 2.0, "10000000", True),
    ]
    from hr_agents.models.compensation import RateEntry

    shares = []
    for name, emp, erg, cap, employer in unit:
        entry = RateEntry(
            label=name,
            employee_share_percent=emp,
            employer_share_percent=erg,
            wage_cap=m(cap) if cap is not None else None,
        )
        amount = _share(entry, employer=employer, wage=wage)
        shares.append(
            {
                "name": f"{name}_{'employer' if employer else 'employee'}",
                "wage": "12000000",
                "employee_share_percent": emp,
                "employer_share_percent": erg,
                "wage_cap": cap,
                "employer": employer,
                "sen": int(amount * 100),
            }
        )

    # End-to-end line level via _compute_line (BPJS section of the oracle).
    svc = object.__new__(PayrollService)
    lines = []
    for case_name, jp_cap in [("uncapped_12m", None), ("capped_jp_10m", "10000000")]:
        tables = _parity_base_tables(jp_cap=jp_cap)
        employee = Employee(
            full_name="Parity",
            job_title="Staff",
            jkk_risk_level=1,
            dependents=0,
            hire_date=datetime.date(2024, 1, 15),
        )
        payroll_input = PayrollInput(
            employee_id=uuid4(),
            base_salary=wage,
            fixed_allowances=m("0"),
        )
        line, _ = svc._compute_line(payroll_input, employee, tables, working_days=22)
        lines.append(
            {
                "name": case_name,
                "base_salary": "12000000",
                "fixed_allowances": "0",
                "working_days": 22,
                "absence_days": 0,
                "overtime_hours": 0,
                "jp_wage_cap": jp_cap,
                "kes_employee_sen": int(line.bpjs_kesehatan_employee * 100),
                "kes_employer_sen": int(line.bpjs_kesehatan_employer * 100),
                "jht_employee_sen": int(line.bpjs_jht_employee * 100),
                "jht_employer_sen": int(line.bpjs_jht_employer * 100),
                "jp_employee_sen": int(line.bpjs_jp_employee * 100),
                "jp_employer_sen": int(line.bpjs_jp_employer * 100),
                "jkk_employer_sen": int(line.bpjs_jkk_employer * 100),
                "jkm_employer_sen": int(line.bpjs_jkm_employer * 100),
                "gross_sen": int(line.gross * 100),
                "net_sen": int(line.net * 100),
                "employer_cost_sen": int(line.employer_cost * 100),
            }
        )
    return [{"shares": shares, "lines": lines}]


def overtime_cases() -> list[dict[str, object]]:
    """Overtime on an exact-hourly wage (8.65M / 173 = 50k/h). Oracle: _overtime_rules."""
    import datetime
    from uuid import uuid4

    from hr_agents.models import Employee
    from hr_agents.models.money import money as m
    from hr_agents.models.payroll import PayrollInput
    from hr_agents.services.payroll import PayrollService, _overtime_rules

    tables = _parity_base_tables()
    from hr_agents.models.compensation import RateTableKind as _Kind

    rules = _overtime_rules(tables[_Kind.OVERTIME_PREMIUM])
    assert rules is not None
    monthly_hours, first_mult, rest_mult = (str(rules[0]), str(rules[1]), str(rules[2]))

    svc = object.__new__(PayrollService)
    employee = Employee(
        full_name="Parity",
        job_title="Staff",
        jkk_risk_level=1,
        dependents=0,
        hire_date=datetime.date(2024, 1, 15),
    )
    cases = []
    for hours in [0, 1, 5, 25]:
        payroll_input = PayrollInput(
            employee_id=uuid4(),
            base_salary=m("8650000"),
            fixed_allowances=m("0"),
            overtime_hours=float(hours),
        )
        line, _ = svc._compute_line(payroll_input, employee, tables, working_days=22)
        cases.append(
            {
                "name": f"ot_{hours}h",
                "base_salary": "8650000",
                "fixed_allowances": "0",
                "working_days": 22,
                "absence_days": 0,
                "overtime_hours": hours,
                "overtime_minutes": hours * 60,
                "monthly_hours": monthly_hours,
                "first_multiplier": first_mult,
                "rest_multiplier": rest_mult,
                "overtime_pay_sen": int(line.overtime_pay * 100),
                "gross_sen": int(line.gross * 100),
                "net_sen": int(line.net * 100),
            }
        )
    return cases


def thr_cases() -> list[dict[str, object]]:
    """THR ladder under_1y/1y/2y/8y_plus on a 12M wage. Oracle: _thr_months_entitlement."""
    import datetime
    from uuid import uuid4

    from hr_agents.models import Employee
    from hr_agents.models.money import money as m
    from hr_agents.models.payroll import PayrollInput
    from hr_agents.services.payroll import PayrollService, _thr_months_entitlement

    tables = _parity_thr_tables()
    from hr_agents.models.compensation import RateTableKind as _Kind

    svc = object.__new__(PayrollService)
    employee = Employee(
        full_name="Parity",
        job_title="Staff",
        jkk_risk_level=1,
        dependents=0,
        hire_date=datetime.date(2024, 1, 15),
    )
    cases = []
    for service_months in [6, 12, 30, 100]:
        entitlement = _thr_months_entitlement(service_months, tables[_Kind.THR_FORMULA])
        assert entitlement is not None
        payroll_input = PayrollInput(
            employee_id=uuid4(),
            base_salary=m("12000000"),
            fixed_allowances=m("0"),
            service_months=service_months,
        )
        line, _ = svc._compute_thr(payroll_input, employee, tables, working_days=22)
        cases.append(
            {
                "name": f"thr_{service_months}m",
                "base_salary": "12000000",
                "fixed_allowances": "0",
                "working_days": 22,
                "absence_days": 0,
                "service_months": service_months,
                "entitlement_months": str(entitlement),
                "thr_months": line.thr_months,
                "thr_pay_sen": int(line.base_salary * 100),
                "gross_sen": int(line.gross * 100),
                "net_sen": int(line.net * 100),
            }
        )
    return cases


def absence_cases() -> list[dict[str, object]]:
    """Proration on 10M base + 2M fixed over 22 working days. Oracle: _compute_line."""
    import datetime
    from uuid import uuid4

    from hr_agents.models import Employee
    from hr_agents.models.money import money as m
    from hr_agents.models.payroll import PayrollInput
    from hr_agents.services.payroll import PayrollService

    tables = _parity_base_tables()
    svc = object.__new__(PayrollService)
    employee = Employee(
        full_name="Parity",
        job_title="Staff",
        jkk_risk_level=1,
        dependents=0,
        hire_date=datetime.date(2024, 1, 15),
    )
    cases = []
    for absence in [0, 2, 11, 22]:
        payroll_input = PayrollInput(
            employee_id=uuid4(),
            base_salary=m("10000000"),
            fixed_allowances=m("2000000"),
            absence_days=float(absence),
        )
        line, _ = svc._compute_line(payroll_input, employee, tables, working_days=22)
        cases.append(
            {
                "name": f"absence_{absence}",
                "base_salary": "10000000",
                "fixed_allowances": "2000000",
                "working_days": 22,
                "absence_days": absence,
                "base_paid_sen": int(line.base_salary * 100),
                "allowances_sen": int(line.allowances * 100),
                "gross_sen": int(line.gross * 100),
                "net_sen": int(line.net * 100),
            }
        )
    return cases


def _line_payload(line) -> dict[str, object]:
    """Every PayrollLine component, in sen, for a full-line parity assertion."""
    return {
        "base_salary_sen": int(line.base_salary * 100),
        "allowances_sen": int(line.allowances * 100),
        "overtime_pay_sen": int(line.overtime_pay * 100),
        "bonus_sen": int(line.bonus * 100),
        "gross_sen": int(line.gross * 100),
        "kes_employee_sen": int(line.bpjs_kesehatan_employee * 100),
        "kes_employer_sen": int(line.bpjs_kesehatan_employer * 100),
        "jht_employee_sen": int(line.bpjs_jht_employee * 100),
        "jht_employer_sen": int(line.bpjs_jht_employer * 100),
        "jp_employee_sen": int(line.bpjs_jp_employee * 100),
        "jp_employer_sen": int(line.bpjs_jp_employer * 100),
        "jkk_employer_sen": int(line.bpjs_jkk_employer * 100),
        "jkm_employer_sen": int(line.bpjs_jkm_employer * 100),
        "pph21_sen": int(line.pph21 * 100),
        "other_deductions_sen": int(line.other_deductions * 100),
        "total_deductions_sen": int(line.total_deductions * 100),
        "net_sen": int(line.net * 100),
        "employer_cost_sen": int(line.employer_cost * 100),
        "thr_months": line.thr_months,
        "notes": list(line.notes),
    }


def _parity_employee(*, dependents: int, jkk_risk_level: int, hire_date):
    from hr_agents.models import Employee

    return Employee(
        full_name="Parity",
        job_title="Staff",
        jkk_risk_level=jkk_risk_level,
        dependents=dependents,
        hire_date=hire_date,
    )


def monthly_full_cases() -> list[dict[str, object]]:
    """Monthly lines covering every component, absence, overtime, bonus, loans, JP cap."""
    import datetime
    from uuid import uuid4

    from hr_agents.models.money import money as m
    from hr_agents.models.payroll import PayrollInput
    from hr_agents.services.payroll import PayrollService

    svc = object.__new__(PayrollService)
    cases = [
        {
            "name": "plain_10m_2m",
            "base": "10000000",
            "fixed": "2000000",
            "variable": "0",
            "absence": 0,
            "overtime_hours": 0.0,
            "bonus": "0",
            "other": "0",
            "loan": "0",
            "dependents": 1,
            "jkk": 1,
            "jp_cap": None,
        },
        {
            "name": "mixed_allowances_bonus_loan_absence_overtime",
            "base": "10000000",
            "fixed": "1000000",
            "variable": "500000",
            "absence": 2,
            "overtime_hours": 3.0,
            "bonus": "1500000",
            "other": "100000",
            "loan": "50000",
            "dependents": 2,
            "jkk": 1,
            "jp_cap": "10000000",
        },
        {
            "name": "half_month_absence",
            "base": "12000000",
            "fixed": "0",
            "variable": "0",
            "absence": 11,
            "overtime_hours": 0.0,
            "bonus": "0",
            "other": "0",
            "loan": "0",
            "dependents": 0,
            "jkk": 1,
            "jp_cap": None,
        },
        {
            "name": "overtime_25h",
            "base": "8650000",
            "fixed": "0",
            "variable": "0",
            "absence": 0,
            "overtime_hours": 25.0,
            "bonus": "0",
            "other": "0",
            "loan": "0",
            "dependents": 0,
            "jkk": 1,
            "jp_cap": None,
        },
        {
            "name": "high_gross_with_ptkp",
            "base": "80000000",
            "fixed": "5000000",
            "variable": "0",
            "absence": 0,
            "overtime_hours": 0.0,
            "bonus": "10000000",
            "other": "0",
            "loan": "0",
            "dependents": 1,
            "jkk": 1,
            "jp_cap": "10000000",
        },
        {
            "name": "below_minimum_wage",
            "base": "1000000",
            "fixed": "0",
            "variable": "0",
            "absence": 0,
            "overtime_hours": 0.0,
            "bonus": "0",
            "other": "0",
            "loan": "0",
            "dependents": 0,
            "jkk": 1,
            "jp_cap": None,
        },
    ]
    out = []
    for case in cases:
        tables = _parity_base_tables(jp_cap=case["jp_cap"])
        employee = _parity_employee(
            dependents=case["dependents"],
            jkk_risk_level=case["jkk"],
            hire_date=datetime.date(2024, 1, 15),
        )
        payroll_input = PayrollInput(
            employee_id=uuid4(),
            base_salary=m(case["base"]),
            fixed_allowances=m(case["fixed"]),
            variable_allowances=m(case["variable"]),
            absence_days=float(case["absence"]),
            overtime_hours=case["overtime_hours"],
            bonus=m(case["bonus"]),
            other_deductions=m(case["other"]),
            loan_deduction=m(case["loan"]),
        )
        line, _ = svc._compute_line(payroll_input, employee, tables, working_days=22)
        out.append(
            {
                "name": case["name"],
                "base_salary": case["base"],
                "fixed_allowances": case["fixed"],
                "variable_allowances": case["variable"],
                "working_days": 22,
                "absence_days": case["absence"],
                "overtime_minutes": int(case["overtime_hours"] * 60),
                "bonus": case["bonus"],
                "other_deductions": case["other"],
                "loan_deduction": case["loan"],
                "dependents": case["dependents"],
                "jkk_risk_class": case["jkk"],
                "jp_wage_cap": case["jp_cap"],
                **_line_payload(line),
            }
        )
    return out


def thr_full_cases() -> list[dict[str, object]]:
    """THR/proration with absences, deductions, loans, and notes."""
    import datetime
    from uuid import uuid4

    from hr_agents.models.money import money as m
    from hr_agents.models.payroll import PayrollInput
    from hr_agents.services.payroll import PayrollService

    svc = object.__new__(PayrollService)
    tables = _parity_thr_tables()
    employee = _parity_employee(
        dependents=0, jkk_risk_level=1, hire_date=datetime.date(2024, 1, 15)
    )
    cases = [
        ("thr_6m_full", 6, 0, "0", "0", None),
        ("thr_12m_full", 12, 0, "0", "0", None),
        ("thr_30m_half_absent", 30, 11, "0", "0", None),
        ("thr_100m_with_deductions", 100, 2, "100000", "50000", "service award"),
    ]
    out = []
    for name, service_months, absence, other, loan, note in cases:
        payroll_input = PayrollInput(
            employee_id=uuid4(),
            base_salary=m("12000000"),
            fixed_allowances=m("0"),
            absence_days=float(absence),
            service_months=service_months,
            other_deductions=m(other),
            loan_deduction=m(loan),
            note=note,
        )
        line, _ = svc._compute_thr(payroll_input, employee, tables, working_days=22)
        out.append(
            {
                "name": name,
                "base_salary": "12000000",
                "fixed_allowances": "0",
                "working_days": 22,
                "absence_days": absence,
                "service_months": service_months,
                "other_deductions": other,
                "loan_deduction": loan,
                "note": note,
                **_line_payload(line),
            }
        )
    return out


def final_cases() -> list[dict[str, object]]:
    """Python's FINAL line (monthly rules) plus Rust-only severance/leave inputs."""
    import datetime
    from uuid import uuid4

    from hr_agents.models.money import money as m
    from hr_agents.models.payroll import PayrollInput
    from hr_agents.services.payroll import PayrollService

    svc = object.__new__(PayrollService)
    cases = [
        {
            "name": "final_without_additions",
            "base": "10000000",
            "fixed": "2000000",
            "absence": 0,
            "service_months": 6,
            "severance": "0",
            "leave_days_x2": 0,
            "leave_per_day": "0",
        },
        {
            "name": "final_severance_and_leave",
            "base": "10000000",
            "fixed": "2000000",
            "absence": 0,
            "service_months": 30,
            "severance": "5000000",
            "leave_days_x2": 10,
            "leave_per_day": "500000",
        },
        {
            "name": "final_absence_severance_leave",
            "base": "10000000",
            "fixed": "1000000",
            "absence": 2,
            "service_months": 60,
            "severance": "7500000",
            "leave_days_x2": 6,
            "leave_per_day": "400000",
        },
    ]
    out = []
    for case in cases:
        tables = _parity_base_tables()
        employee = _parity_employee(
            dependents=1, jkk_risk_level=1, hire_date=datetime.date(2024, 1, 15)
        )
        payroll_input = PayrollInput(
            employee_id=uuid4(),
            base_salary=m(case["base"]),
            fixed_allowances=m(case["fixed"]),
            absence_days=float(case["absence"]),
        )
        line, _ = svc._compute_line(payroll_input, employee, tables, working_days=22)
        out.append(
            {
                "name": case["name"],
                "base_salary": case["base"],
                "fixed_allowances": case["fixed"],
                "working_days": 22,
                "absence_days": case["absence"],
                "service_months": case["service_months"],
                "severance_pay": case["severance"],
                "unused_leave_days_x2": case["leave_days_x2"],
                "leave_payout_per_day": case["leave_per_day"],
                "dependents": 1,
                "jkk_risk_class": 1,
                "python_line": _line_payload(line),
            }
        )
    return out


def payroll_1000_cases() -> dict[str, object]:
    """Deterministic 1,000-line run, compared line-by-line and in aggregate."""
    import datetime

    from hr_agents.models.money import money as m
    from hr_agents.models.payroll import PayrollInput
    from hr_agents.services.payroll import PayrollService

    svc = object.__new__(PayrollService)
    employees = {
        cap: _parity_employee(dependents=0, jkk_risk_level=1, hire_date=datetime.date(2024, 1, 15))
        for cap in (None, "10000000")
    }
    tables = {cap: _parity_base_tables(jp_cap=cap) for cap in (None, "10000000")}
    cases = []
    for index in range(1_000):
        base = 6_000_000 + (index % 20) * 3_750_000
        fixed = 1_000_000 + (index % 5) * 100_000
        variable = 250_000 if index % 4 == 0 else 0
        absence = index % 4
        overtime_hours = (index % 3) * 1.5
        bonus = 500_000 if index % 7 == 0 else 0
        other = 100_000 if index % 5 == 0 else 0
        loan = 50_000 if index % 11 == 0 else 0
        dependents = index % 3
        cap = "10000000" if index % 2 == 0 else None
        employee = employees[cap].model_copy(update={"dependents": dependents})
        payroll_input = PayrollInput(
            employee_id=uuid4(),
            base_salary=m(str(base)),
            fixed_allowances=m(str(fixed)),
            variable_allowances=m(str(variable)),
            absence_days=float(absence),
            overtime_hours=overtime_hours,
            bonus=m(str(bonus)),
            other_deductions=m(str(other)),
            loan_deduction=m(str(loan)),
        )
        line, _ = svc._compute_line(payroll_input, employee, tables[cap], working_days=22)
        cases.append(
            {
                "name": f"line_{index:04}",
                "base_salary": str(base),
                "fixed_allowances": str(fixed),
                "variable_allowances": str(variable),
                "working_days": 22,
                "absence_days": absence,
                "overtime_minutes": int(overtime_hours * 60),
                "bonus": str(bonus),
                "other_deductions": str(other),
                "loan_deduction": str(loan),
                "dependents": dependents,
                "jkk_risk_class": 1,
                "jp_wage_cap": cap,
                **_line_payload(line),
            }
        )

    def total(field: str) -> int:
        return sum(int(case[field]) for case in cases)

    return {
        "employees": len(cases),
        "totals": {
            "gross_sen": total("gross_sen"),
            "net_sen": total("net_sen"),
            "employee_deductions_sen": total("total_deductions_sen"),
            "employer_cost_sen": total("employer_cost_sen"),
            "pph21_sen": total("pph21_sen"),
        },
        "cases": cases,
    }


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "parity/fixtures")
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "money.json": money_cases(),
        "money_operations.json": money_operations(),
        "audit_hashes.json": audit_cases(),
        "payroll_pph21.json": pph21_cases(),
        "scoring_aggregate.json": scoring_cases(),
        "payroll_bpjs.json": bpjs_cases(),
        "payroll_overtime.json": overtime_cases(),
        "payroll_thr.json": thr_cases(),
        "payroll_absence.json": absence_cases(),
        "payroll_monthly_full.json": monthly_full_cases(),
        "payroll_thr_full.json": thr_full_cases(),
        "payroll_final.json": final_cases(),
        "payroll_1000.json": payroll_1000_cases(),
    }
    for name, payload in files.items():
        path = output / name
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
