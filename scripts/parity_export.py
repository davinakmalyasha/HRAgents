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


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "parity/fixtures")
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "money.json": money_cases(),
        "money_operations.json": money_operations(),
        "audit_hashes.json": audit_cases(),
        "payroll_pph21.json": pph21_cases(),
        "scoring_aggregate.json": scoring_cases(),
    }
    for name, payload in files.items():
        path = output / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
