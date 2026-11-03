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
from datetime import date, datetime
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
                    "now": datetime(2025, 1, 10),
                },
                {
                    "id": DESIGN_ID,
                    "tenant": TENANT_ID,
                    "name": "Design",
                    "cost": None,
                    "now": datetime(2025, 1, 10),
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
                    "now": datetime(2025, 1, 10),
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
                    "now": datetime(2025, 6, 1),
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
                    "now": datetime(2025, 1, 10),
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
                    "now": datetime(2025, 1, 10),
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
                    "now": datetime(2025, 1, 10),
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
                    "now": datetime(2025, 6, 20),
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
                    "now": datetime(2025, 8, 4),
                },
            ],
        )

    chunks = list(
        iter_export(
            factory,
            exported_at=datetime(2026, 1, 15, 9, 0, 0),
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
