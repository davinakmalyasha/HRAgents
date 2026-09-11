"""Integration tests for the payroll API surface."""

from datetime import date, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from hr_agents.main import create_app

TODAY = date.today()
YEAR = TODAY.year


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(client: TestClient) -> dict:
    response = client.post(
        "/v1/employees",
        json={
            "full_name": "Sari Dewi",
            "hire_date": (TODAY - timedelta(days=400)).isoformat(),
            "created_by": "hr-admin",
            "job_title": "Finance Staff",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def seed_tables(client: TestClient) -> None:
    """Create + verify the rate tables payroll requires (illustrative values)."""
    specs = [
        ("bpjs_kesehatan", 4.0, 1.0, 12_000_000.0),
        ("bpjs_ketenagakerjaan_jht", 3.7, 2.0, None),
        ("bpjs_ketenagakerjaan_jp", 2.0, 1.0, 10_000_000.0),
        ("bpjs_jkk", 0.24, None, None),
        ("bpjs_jkm", 0.3, None, None),
    ]
    for kind, employer, employee, cap in specs:
        created = client.post(
            "/v1/rate-tables",
            json={"kind": kind, "name": kind, "created_by": "hr-admin"},
        )
        assert created.status_code == 201, created.text
        table_id = UUID(created.json()["id"])
        # Note: entries/verify endpoints are service-level; use the app state directly.
        app_state = client.app.state.people.rate_tables  # type: ignore[attr-defined]
        from hr_agents.models import RateEntry

        app_state.set_entries(
            table_id,
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
        app_state.verify(
            table_id,
            verified_by="hr-admin",
            source_note="test fixture",
        )

    overtime = client.post(
        "/v1/rate-tables",
        json={"kind": "overtime_premium", "name": "OT", "created_by": "hr-admin"},
    ).json()["id"]
    app_state = client.app.state.people.rate_tables  # type: ignore[attr-defined]
    from hr_agents.models import RateEntry

    app_state.set_entries(
        UUID(overtime), entries=[RateEntry(label="first", multiplier=1.5)], updated_by="hr"
    )
    app_state.verify(UUID(overtime), verified_by="hr", source_note="fixture")

    pph = client.post(
        "/v1/rate-tables",
        json={"kind": "pph21_ter", "name": "TER", "created_by": "hr-admin"},
    ).json()["id"]
    app_state.set_entries(
        UUID(pph),
        entries=[
            RateEntry(
                label="low", lower_bound=0, upper_bound=15_000_000, employee_share_percent=2.0
            )
        ],
        updated_by="hr",
    )
    app_state.verify(UUID(pph), verified_by="hr", source_note="fixture")


def test_payroll_full_flow_without_tables_blocks() -> None:
    with make_client() as client:
        employee = create_employee(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6, "created_by": "hr-admin"},
        ).json()
        inputs = client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "by": "hr-admin",
                "inputs": [{"employee_id": employee["id"], "base_salary": 5_000_000}],
            },
        )
        assert inputs.status_code == 200
        computed = client.post(f"/v1/payroll/runs/{run['id']}/compute", json={"by": "hr-admin"})

    assert computed.status_code == 200
    body = computed.json()
    assert body["blocking_count"] > 0
    assert any(a["severity"] == "error" for a in body["anomalies"])


def test_signoff_blocked_when_anomalies_present() -> None:
    with make_client() as client:
        employee = create_employee(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6, "created_by": "hr-admin"},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "by": "hr-admin",
                "inputs": [{"employee_id": employee["id"], "base_salary": 5_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={"by": "hr-admin"})
        submitted = client.post(f"/v1/payroll/runs/{run['id']}/submit", json={"by": "hr-admin"})

    assert submitted.status_code == 409
    assert "blocking anomalies" in submitted.json()["title"]


def test_payroll_full_flow_with_tables() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)

        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6, "created_by": "hr-admin"},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "by": "hr-admin",
                "inputs": [
                    {
                        "employee_id": employee["id"],
                        "base_salary": 9_000_000,
                        "fixed_allowances": 1_000_000,
                        "overtime_hours": 2,
                    }
                ],
            },
        )
        computed = client.post(
            f"/v1/payroll/runs/{run['id']}/compute", json={"by": "hr-admin"}
        ).json()

        assert computed["blocking_count"] == 0
        line = computed["lines"][0]
        assert line["employee_name"] == "Sari Dewi"
        assert line["net"] < line["gross"]

        submitted = client.post(
            f"/v1/payroll/runs/{run['id']}/submit", json={"by": "hr-admin"}
        ).json()
        approval_id = submitted["approval_id"]
        assert approval_id

        decided = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"decided_by": "finance-lead", "approve": True},
        )
        assert decided.status_code == 200

        synced = client.post(f"/v1/payroll/approvals/{approval_id}/sync")
        assert synced.status_code == 200
        assert synced.json()["status"] == "approved"
        assert synced.json()["signed_off_by"] == "finance-lead"

        packet = client.get(f"/v1/payroll/runs/{run['id']}/packet.xlsx")
        assert packet.status_code == 200
        assert packet.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert "no payments executed" in packet.headers["x-hragents-notice"]

        exported = client.post(f"/v1/payroll/runs/{run['id']}/export", json={"by": "finance-lead"})
        assert exported.json()["status"] == "exported"


def test_agent_cannot_decide_payroll() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6, "created_by": "hr-admin"},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "by": "hr-admin",
                "inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={"by": "hr-admin"})
        submitted = client.post(
            f"/v1/payroll/runs/{run['id']}/submit", json={"by": "hr-admin"}
        ).json()

        response = client.post(
            f"/v1/approvals/{submitted['approval_id']}/decide",
            json={"decided_by": "agent:payroll_bot", "approve": True},
        )

    assert response.status_code == 409
    assert "named human" in response.json()["title"]


def test_edit_after_submission_rejected() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6, "created_by": "hr-admin"},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "by": "hr-admin",
                "inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={"by": "hr-admin"})
        client.post(f"/v1/payroll/runs/{run['id']}/submit", json={"by": "hr-admin"})

        response = client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "by": "hr-admin",
                "inputs": [{"employee_id": employee["id"], "base_salary": 1_000_000}],
            },
        )

    assert response.status_code == 409
    assert "no longer be edited" in response.json()["title"]
