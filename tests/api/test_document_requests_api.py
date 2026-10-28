"""Document requests enter through the approval queue, never as a direct demand."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.models import business_today
from hr_agents.rbac import RoleId

ADMIN = {"X-API-Key": "admin-key"}
EMPLOYEE = {"X-API-Key": "employee-key"}


def settings() -> Settings:
    return Settings(
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("admin-key"), role=RoleId.HR_ADMIN, actor_id="rina"),
            ApiPrincipalSettings(
                key=SecretStr("employee-key"), role=RoleId.EMPLOYEE, actor_id="sari"
            ),
        ]
    )


def make_employee(client: TestClient) -> str:
    response = client.post(
        "/v1/employees",
        json={
            "full_name": "Rudi Hartono",
            "hire_date": (business_today() - timedelta(days=400)).isoformat(),
            "job_title": "Engineering Lead",
        },
        headers=ADMIN,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def request_document(client: TestClient, employee_id: str) -> dict:
    response = client.post(
        f"/v1/employees/{employee_id}/document-requests",
        json={"kind": "ktp", "reason": "Payroll needs the ID for tax reporting."},
        headers=ADMIN,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_an_employee_key_cannot_demand_documents() -> None:
    with TestClient(create_app(settings())) as client:
        employee_id = make_employee(client)
        response = client.post(
            f"/v1/employees/{employee_id}/document-requests",
            json={"kind": "ktp", "reason": "Payroll needs the ID."},
            headers=EMPLOYEE,
        )
        assert response.status_code == 403


def test_the_full_flow_is_request_decide_sync() -> None:
    with TestClient(create_app(settings())) as client:
        employee_id = make_employee(client)
        approval = request_document(client, employee_id)
        assert approval["status"] == "pending"
        assert approval["subject"] == "document_request"
        assert approval["assignee_role"] == "manager"

        decide = client.post(
            f"/v1/approvals/{approval['id']}/decide",
            json={"approve": True, "reason": "legitimate need"},
            headers=ADMIN,
        )
        assert decide.status_code == 200, decide.text

        sync = client.post(
            f"/v1/employees/document-requests/{approval['id']}/sync",
            headers=ADMIN,
        )
        assert sync.status_code == 200, sync.text
        task = sync.json()
        assert task["related_subject"] == "document_request"
        assert task["related_id"] == approval["id"]
        assert "KTP" in task["title"]
        assert task["status"] == "open"

        tasks = client.get("/v1/tasks", headers=ADMIN)
        assert tasks.status_code == 200, tasks.text
        assert any(item["id"] == task["id"] for item in tasks.json()["items"])


def test_sync_before_a_decision_and_after_a_rejection_refuse() -> None:
    with TestClient(create_app(settings())) as client:
        employee_id = make_employee(client)
        approval = request_document(client, employee_id)

        early = client.post(
            f"/v1/employees/document-requests/{approval['id']}/sync",
            headers=ADMIN,
        )
        assert early.status_code == 409

        decide = client.post(
            f"/v1/approvals/{approval['id']}/decide",
            json={"approve": False, "reason": "ask later"},
            headers=ADMIN,
        )
        assert decide.status_code == 200, decide.text

        refused = client.post(
            f"/v1/employees/document-requests/{approval['id']}/sync",
            headers=ADMIN,
        )
        assert refused.status_code == 409


def test_unknown_records_and_missing_reasons_are_shaped() -> None:
    with TestClient(create_app(settings())) as client:
        employee_id = make_employee(client)

        assert (
            client.post(
                "/v1/employees/00000000-0000-0000-0000-000000000000/document-requests",
                json={"kind": "ktp", "reason": "Payroll needs the ID."},
                headers=ADMIN,
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/v1/employees/{employee_id}/document-requests",
                json={"kind": "ktp", "reason": "  "},
                headers=ADMIN,
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/v1/employees/{employee_id}/document-requests",
                json={"kind": "passport", "reason": "Payroll needs the ID."},
                headers=ADMIN,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/employees/document-requests/00000000-0000-0000-0000-000000000000/sync",
                headers=ADMIN,
            ).status_code
            == 404
        )
