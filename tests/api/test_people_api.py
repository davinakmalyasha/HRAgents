"""Integration tests for the people API surface (employees, contracts, approvals, tasks)."""

from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from hr_agents.main import create_app

TODAY = date.today()


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(client: TestClient, **overrides: object) -> dict:
    payload: dict = {
        "full_name": "Sari Dewi",
        "hire_date": (TODAY - timedelta(days=200)).isoformat(),
        "created_by": "hr-admin",
        "job_title": "Finance Staff",
    }
    payload.update(overrides)
    response = client.post("/v1/employees", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_get_employee() -> None:
    with make_client() as client:
        created = create_employee(client)
        fetched = client.get(f"/v1/employees/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["full_name"] == "Sari Dewi"
    assert fetched.json()["status"] == "active"


def test_list_employees_filtered_by_status() -> None:
    with make_client() as client:
        create_employee(client, full_name="Active One")
        create_employee(
            client,
            full_name="Future One",
            hire_date=(TODAY + timedelta(days=14)).isoformat(),
        )
        response = client.get("/v1/employees", params={"status": "onboarding"})

    assert response.status_code == 200
    names = [item["full_name"] for item in response.json()]
    assert names == ["Future One"]


def test_employee_lifecycle_transition() -> None:
    with make_client() as client:
        employee = create_employee(client)
        response = client.post(
            f"/v1/employees/{employee['id']}/transition",
            json={"target": "notice_period", "by": "hr-admin"},
        )
        invalid = client.post(
            f"/v1/employees/{employee['id']}/transition",
            json={"target": "probation", "by": "hr-admin"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "notice_period"
    assert invalid.status_code == 409


def test_add_document_and_list_contracts() -> None:
    with make_client() as client:
        employee = create_employee(client)
        document = client.post(
            f"/v1/employees/{employee['id']}/documents",
            json={
                "kind": "ktp",
                "storage_key": f"employees/{employee['id']}/ktp.pdf",
                "sha256": "a" * 64,
                "uploaded_by": "hr-admin",
            },
        )
        contracts = client.get(f"/v1/employees/{employee['id']}/contracts")

    assert document.status_code == 201
    assert document.json()["kind"] == "ktp"
    assert contracts.status_code == 200
    assert contracts.json() == []


def test_contract_lifecycle_via_api() -> None:
    with make_client() as client:
        employee = create_employee(client)
        created = client.post(
            "/v1/contracts",
            json={
                "employee_id": employee["id"],
                "contract_type": "pkwt",
                "start_date": (TODAY - timedelta(days=330)).isoformat(),
                "end_date": (TODAY + timedelta(days=30)).isoformat(),
                "created_by": "hr-admin",
            },
        )
        assert created.status_code == 201, created.text
        contract_id = created.json()["id"]

        activated = client.post(f"/v1/contracts/{contract_id}/activate", json={"by": "hr-admin"})
        expiring = client.get("/v1/contracts", params={"expiring_within_days": 60})

    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert expiring.status_code == 200
    assert any(item["id"] == contract_id for item in expiring.json())


def test_pkwt_without_end_date_rejected() -> None:
    with make_client() as client:
        employee = create_employee(client)
        response = client.post(
            "/v1/contracts",
            json={
                "employee_id": employee["id"],
                "contract_type": "pkwt",
                "start_date": TODAY.isoformat(),
                "created_by": "hr-admin",
            },
        )
    assert response.status_code == 409  # model validation surfaced as conflict


def test_approval_flow_via_api() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/approvals",
            json={
                "subject": "leave_request",
                "subject_id": "leave-1",
                "title": "Annual leave 3 days",
                "assignee_role": "manager",
                "requested_by": "sari@example.com",
                "urgency": "high",
            },
        )
        assert created.status_code == 201, created.text
        approval_id = created.json()["id"]

        queue_response = client.get("/v1/approvals", params={"role": "manager"})
        decided = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"decided_by": "manager-budi", "approve": True, "reason": "ok"},
        )

    assert queue_response.status_code == 200
    assert any(item["id"] == approval_id for item in queue_response.json())
    assert decided.status_code == 200
    assert decided.json()["action"] == "approved"
    assert decided.json()["request"]["status"] == "approved"


def test_agent_cannot_decide_via_api() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/approvals",
            json={
                "subject": "candidate_rejection",
                "subject_id": "cand-1",
                "title": "Rejection sign-off",
                "assignee_role": "engineering_lead",
                "requested_by": "policy_engine",
                "requested_by_agent": True,
            },
        )
        approval_id = created.json()["id"]
        response = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"decided_by": "agent:policy_assistant", "approve": True},
        )

    assert response.status_code == 409
    assert "named human" in response.json()["title"]


def test_tasks_flow_via_api() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/tasks",
            json={
                "title": "Chase missing NPWP",
                "created_by": "hr-admin",
                "assignee_role": "hr_admin",
                "due_on": (TODAY - timedelta(days=1)).isoformat(),
                "priority": "high",
            },
        )
        assert created.status_code == 201
        task_id = created.json()["id"]

        overdue = client.get("/v1/tasks", params={"overdue_only": True})
        completed = client.post(f"/v1/tasks/{task_id}/complete", json={"by": "hr-admin"})
        after = client.get("/v1/tasks")

    assert any(item["id"] == task_id for item in overdue.json())
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    assert all(item["id"] != task_id for item in after.json())


def test_rate_table_unverified_gate_via_api() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/rate-tables",
            json={"kind": "bpjs_kesehatan", "name": "BPJS Kesehatan", "created_by": "hr"},
        )
        unverified = client.get("/v1/rate-tables/unverified")

    assert created.status_code == 201
    assert created.json()["verified"] is False
    assert created.json()["usable"] is False
    assert any(item["id"] == created.json()["id"] for item in unverified.json())


def test_unknown_employee_returns_404() -> None:
    with make_client() as client:
        response = client.get(f"/v1/employees/{uuid4()}")
    assert response.status_code == 404
