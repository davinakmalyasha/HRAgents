"""Integration tests for the payroll API surface."""

from datetime import date, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from hr_agents.identity import ActorRef
from hr_agents.main import create_app
from hr_agents.models.money import money as m

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
            json={"kind": kind, "name": kind},
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
                    wage_cap=m(cap) if cap is not None else None,
                )
            ],
            actor=ActorRef.legacy("hr-admin"),
        )
        app_state.verify(
            table_id,
            actor=ActorRef.legacy("hr-admin"),
            source_note="test fixture",
        )

    overtime = client.post(
        "/v1/rate-tables",
        json={"kind": "overtime_premium", "name": "OT"},
    ).json()["id"]
    app_state = client.app.state.people.rate_tables  # type: ignore[attr-defined]
    from hr_agents.models import RateEntry

    app_state.set_entries(
        UUID(overtime),
        entries=[RateEntry(label="first", multiplier=1.5)],
        actor=ActorRef.legacy("hr"),
    )
    app_state.verify(UUID(overtime), actor=ActorRef.legacy("hr"), source_note="fixture")

    pph = client.post(
        "/v1/rate-tables",
        json={"kind": "pph21_ter", "name": "TER"},
    ).json()["id"]
    app_state.set_entries(
        UUID(pph),
        entries=[
            RateEntry(
                label="low", lower_bound=m(0), upper_bound=m(15_000_000), employee_share_percent=2.0
            )
        ],
        actor=ActorRef.legacy("hr"),
    )
    app_state.verify(UUID(pph), actor=ActorRef.legacy("hr"), source_note="fixture")


def test_payroll_full_flow_without_tables_blocks() -> None:
    with make_client() as client:
        employee = create_employee(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        inputs = client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 5_000_000}],
            },
        )
        assert inputs.status_code == 200
        computed = client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})

    assert computed.status_code == 200
    body = computed.json()
    assert body["blocking_count"] > 0
    assert any(a["severity"] == "error" for a in body["anomalies"])


def test_signoff_blocked_when_anomalies_present() -> None:
    with make_client() as client:
        employee = create_employee(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 5_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})
        submitted = client.post(f"/v1/payroll/runs/{run['id']}/submit", json={})

    assert submitted.status_code == 409
    assert "blocking anomalies" in submitted.json()["title"]


def test_payroll_full_flow_with_tables() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)

        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
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
        computed = client.post(f"/v1/payroll/runs/{run['id']}/compute", json={}).json()

        assert computed["blocking_count"] == 0
        line = computed["lines"][0]
        assert line["employee_name"] == "Sari Dewi"
        assert line["net"] < line["gross"]

        submitted = client.post(f"/v1/payroll/runs/{run['id']}/submit", json={}).json()
        approval_id = submitted["approval_id"]
        assert approval_id

        decided = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"approve": True},
        )
        assert decided.status_code == 200

        synced = client.post(f"/v1/payroll/approvals/{approval_id}/sync", json={})
        assert synced.status_code == 200
        assert synced.json()["status"] == "approved"
        assert synced.json()["signed_off_by"] == "local-dev"

        packet = client.get(f"/v1/payroll/runs/{run['id']}/packet.xlsx")
        assert packet.status_code == 200
        assert packet.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert "no payments executed" in packet.headers["x-hragents-notice"]

        exported = client.post(f"/v1/payroll/runs/{run['id']}/export", json={})
        assert exported.json()["status"] == "exported"


def test_approval_decision_refuses_a_caller_supplied_actor() -> None:
    """A decision cannot be attributed by naming someone in the body.

    The old assertion was a 409 with "named human" in it, which is what the
    service returned when a body said ``decided_by="agent:payroll_bot"``. No
    request can name an actor now, so the attempt is refused at the boundary --
    the stronger property. The gate itself lives in ``ApprovalEngine.decide`` and
    is covered in ``tests/test_named_human_gates.py``, where an agent actor can
    actually be constructed.
    """
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})
        submitted = client.post(f"/v1/payroll/runs/{run['id']}/submit", json={}).json()

        refused = client.post(
            f"/v1/approvals/{submitted['approval_id']}/decide",
            json={"approve": True, "decided_by": "agent:payroll_bot"},
        )
        approved = client.post(
            f"/v1/approvals/{submitted['approval_id']}/decide",
            json={"approve": True},
        )
        synced = client.post(f"/v1/payroll/approvals/{submitted['approval_id']}/sync", json={})

    assert refused.status_code == 422
    assert any(error["loc"][-1] == "decided_by" for error in refused.json()["detail"])
    assert approved.status_code == 200
    assert approved.json()["action"] == "approved"
    # and the run names the key's holder as the approver, not a typed-in name
    assert synced.json()["signed_off_by"] == "local-dev"


def test_edit_after_submission_rejected() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})
        client.post(f"/v1/payroll/runs/{run['id']}/submit", json={})

        response = client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 1_000_000}],
            },
        )

    assert response.status_code == 409
    assert "no longer be edited" in response.json()["title"]
