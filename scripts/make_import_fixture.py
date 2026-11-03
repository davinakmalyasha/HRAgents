"""Generate a small, real `hragents-export/1` fixture for the Rust importer.

Builds a throwaway SQLite database with the Python SQLAlchemy metadata, seeds
two org units and three employees (one managed by another), then streams a real
export with `iter_export`. The output is committed as the importer's test
fixture; regenerate with this script, never by hand.

Usage:
    uv run python scripts/make_import_fixture.py [output-path]
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from hr_agents.db import (  # noqa: F401 — register every table on the metadata
    compliance_tables,
    growth_tables,
    leave_tables,
    offboarding_tables,
    offers_tables,
    onboarding_tables,
    payroll_tables,
    people_tables,
    tables,
    workspace_tables,
)
from hr_agents.db.base import Base
from hr_agents.services.export import iter_export

PRODUCT_ID = "11111111-1111-4111-8111-111111111111"
DESIGN_ID = "22222222-2222-4222-8222-222222222222"
TENANT_ID = "00000000-0000-4000-8000-000000000000"


def main() -> int:
    output = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "rust/crates/hragents-ipc/tests/fixtures/import_demo.json"
    )
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    from sqlalchemy import text

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO org_units (id, tenant_id, name, cost_center, created_at)"
                " VALUES (:id, :tenant, :name, :cost, :now)"
            ),
            [
                {
                    "id": PRODUCT_ID,
                    "tenant": TENANT_ID,
                    "name": "Product",
                    "cost": "CC-100",
                    "now": datetime(2025, 1, 10, tzinfo=UTC),
                },
                {
                    "id": DESIGN_ID,
                    "tenant": TENANT_ID,
                    "name": "Design",
                    "cost": None,
                    "now": datetime(2025, 1, 10, tzinfo=UTC),
                },
            ],
        )
        rina, dimas, sari = str(uuid4()), str(uuid4()), str(uuid4())
        connection.execute(
            text(
                "INSERT INTO employees (id, tenant_id, employee_number, full_name, email,"
                " phone, job_title, org_unit_id, manager_id, status, hire_date,"
                " created_at, updated_at)"
                " VALUES (:id, :tenant, :no, :name, :email, :phone, :title,"
                " :org, :manager, :status, :hire, :now, :now)"
            ),
            [
                {
                    "id": rina,
                    "tenant": TENANT_ID,
                    "no": "E-001",
                    "name": "Rina Kartika",
                    "email": "rina@example.test",
                    "phone": None,
                    "title": "HR Manager",
                    "org": PRODUCT_ID,
                    "manager": None,
                    "status": "active",
                    "hire": date(2024, 2, 1),
                    "now": datetime(2025, 1, 10, tzinfo=UTC),
                },
                {
                    "id": dimas,
                    "tenant": TENANT_ID,
                    "no": "E-002",
                    "name": "Dimas Pratama",
                    "email": "dimas@example.test",
                    "phone": "+62 812 0000 0001",
                    "title": "Backend Engineer",
                    "org": PRODUCT_ID,
                    "manager": rina,
                    "status": "probation",
                    "hire": date(2025, 6, 1),
                    "now": datetime(2025, 6, 1, tzinfo=UTC),
                },
                {
                    "id": sari,
                    "tenant": TENANT_ID,
                    "no": "E-003",
                    "name": "Sari Wulandari",
                    "email": None,
                    "phone": None,
                    "title": "Product Designer",
                    "org": DESIGN_ID,
                    "manager": rina,
                    "status": "notice_period",
                    "hire": date(2023, 3, 15),
                    "now": datetime(2025, 1, 10, tzinfo=UTC),
                },
            ],
        )
        import json as _json

        annual_policy, sick_policy = str(uuid4()), str(uuid4())
        connection.execute(
            text(
                "INSERT INTO leave_policies (id, tenant_id, leave_type, policy,"
                " created_at, updated_at)"
                " VALUES (:id, :tenant, :type, :policy, :now, :now)"
            ),
            [
                {
                    "id": annual_policy,
                    "tenant": TENANT_ID,
                    "type": "annual",
                    "policy": _json.dumps(
                        {
                            "leave_type": "annual",
                            "name": "Annual leave",
                            "requires_document": False,
                            "days_per_year": 12.0,
                            "carryover_allowed": True,
                            "carryover_max_days": 6.0,
                        }
                    ),
                    "now": datetime(2025, 1, 10, tzinfo=UTC),
                },
                {
                    "id": sick_policy,
                    "tenant": TENANT_ID,
                    "type": "sick",
                    "policy": _json.dumps(
                        {
                            "leave_type": "sick",
                            "name": "Sick leave",
                            "requires_document": True,
                            "days_per_year": None,
                            "carryover_allowed": False,
                            "carryover_max_days": None,
                        }
                    ),
                    "now": datetime(2025, 1, 10, tzinfo=UTC),
                },
            ],
        )
        connection.execute(
            text(
                "INSERT INTO leave_requests (id, tenant_id, employee_id, leave_type, start_date,"
                " end_date, days, reason, status, created_at, updated_at)"
                " VALUES (:id, :tenant, :employee, :type, :start, :end, :days, :reason,"
                " :status, :now, :now)"
            ),
            [
                {
                    "id": str(uuid4()),
                    "tenant": TENANT_ID,
                    "employee": dimas,
                    "type": "annual",
                    "start": date(2025, 7, 7),
                    "end": date(2025, 7, 8),
                    "days": 2.0,
                    "reason": "Family trip",
                    "status": "approved",
                    "now": datetime(2025, 6, 20, tzinfo=UTC),
                },
                {
                    "id": str(uuid4()),
                    "tenant": TENANT_ID,
                    "employee": sari,
                    "type": "sick",
                    "start": date(2025, 8, 4),
                    "end": date(2025, 8, 4),
                    "days": 1.0,
                    "reason": None,
                    "status": "pending",
                    "now": datetime(2025, 8, 4, tzinfo=UTC),
                },
            ],
        )

        from decimal import Decimal as _D

        run_approved, run_draft = str(uuid4()), str(uuid4())
        connection.execute(
            text(
                "INSERT INTO payroll_runs (id, tenant_id, period_year, period_month, kind,"
                " status, inputs, anomalies, rate_table_ids, signed_off_by, created_at)"
                " VALUES (:id, :tenant, :year, :month, :kind, :status, :inputs,"
                " :anomalies, :tables, :signed, :now)"
            ),
            [
                {
                    "id": run_approved,
                    "tenant": TENANT_ID,
                    "year": 2025,
                    "month": 6,
                    "kind": "monthly",
                    "status": "approved",
                    "inputs": "[]",
                    "anomalies": _json.dumps(
                        [
                            {
                                "code": "overtime_excessive",
                                "severity": "warning",
                                "employee_id": None,
                                "detail": "3 overtime hours need a manager check.",
                            }
                        ]
                    ),
                    "tables": "{}",
                    "signed": "Rina Kartika",
                    "now": datetime(2025, 7, 1, tzinfo=UTC),
                },
                {
                    "id": run_draft,
                    "tenant": TENANT_ID,
                    "year": 2025,
                    "month": 7,
                    "kind": "monthly",
                    "status": "draft",
                    "inputs": "[]",
                    "anomalies": "[]",
                    "tables": "{}",
                    "signed": None,
                    "now": datetime(2025, 7, 20, tzinfo=UTC),
                },
            ],
        )
        line_columns = (
            "id, tenant_id, run_id, employee_id, employee_name, base_salary, allowances,"
            " overtime_pay, bonus, gross, bpjs_kesehatan_employee, bpjs_jht_employee,"
            " bpjs_jp_employee, pph21, other_deductions, total_deductions, net,"
            " bpjs_kesehatan_employer, bpjs_jht_employer, bpjs_jp_employer,"
            " bpjs_jkk_employer, bpjs_jkm_employer, employer_cost, thr_months, notes"
        )
        line_placeholders = (
            ":id, :tenant, :run, :employee, :name, :base, :allow, :ot, :bonus, :gross,"
            " :kes, :jht, :jp, :pph21, :other, :total, :net, :keser, :jhther, :jper,"
            " :jkker, :jkmer, :cost, :thr, :notes"
        )
        connection.execute(
            text(f"INSERT INTO payroll_lines ({line_columns}) VALUES ({line_placeholders})"),
            [
                {
                    "id": str(uuid4()),
                    "tenant": TENANT_ID,
                    "run": run_approved,
                    "employee": dimas,
                    "name": "Dimas Pratama",
                    "base": str(str(_D("10000000"))),
                    "allow": str(_D("2000000")),
                    "ot": str(_D("0")),
                    "bonus": str(_D("0")),
                    "gross": str(_D("12000000")),
                    "kes": str(_D("120000")),
                    "jht": str(_D("240000")),
                    "jp": str(_D("120000")),
                    "pph21": str(_D("0")),
                    "other": str(_D("0")),
                    "total": str(_D("480000")),
                    "net": str(_D("11520000")),
                    "keser": str(_D("480000")),
                    "jhther": str(_D("444000")),
                    "jper": str(_D("240000")),
                    "jkker": str(_D("28800")),
                    "jkmer": str(_D("36000")),
                    "cost": str(_D("1228800")),
                    "thr": 0,
                    "notes": "[]",
                },
                {
                    "id": str(uuid4()),
                    "tenant": TENANT_ID,
                    "run": run_approved,
                    "employee": sari,
                    "name": "Sari Wulandari",
                    "base": str(_D("8000000")),
                    "allow": str(_D("500000")),
                    "ot": str(_D("150000")),
                    "bonus": str(_D("0")),
                    "gross": str(_D("8650000")),
                    "kes": str(_D("85000")),
                    "jht": str(_D("170000")),
                    "jp": str(_D("85000")),
                    "pph21": str(_D("0")),
                    "other": str(_D("50000")),
                    "total": str(_D("390000")),
                    "net": str(_D("8260000")),
                    "keser": str(_D("340000")),
                    "jhther": str(_D("314500")),
                    "jper": str(_D("170000")),
                    "jkker": str(_D("20400")),
                    "jkmer": str(_D("25500")),
                    "cost": str(_D("870400")),
                    "thr": 0,
                    "notes": "[]",
                },
            ],
        )

    chunks = list(
        iter_export(
            factory,
            exported_at=datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC),
            exported_by="fixture-generator",
        )
    )
    document = json.loads("".join(chunks))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    employees = next(
        table
        for table in document["data"].values()
        if isinstance(table, dict) and table.get("count") == 3
    )
    print(f"wrote {output} ({len(employees['rows'])} employees)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
