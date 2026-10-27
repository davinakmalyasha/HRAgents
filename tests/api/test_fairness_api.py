"""The fairness report is admin-only and states its own limits."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
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


def test_an_empty_installation_reports_zero_evaluations_with_its_limits() -> None:
    with TestClient(create_app(settings())) as client:
        assert client.get("/v1/ops/fairness", headers=EMPLOYEE).status_code == 403

        response = client.get("/v1/ops/fairness", headers=ADMIN)
        assert response.status_code == 200
        body = response.json()
        assert body["evaluations"] == 0
        assert body["jobs"] == []
        assert "Protected attributes are never collected" in body["note"]
        assert body["truncated"] is False


def test_the_window_is_validated() -> None:
    with TestClient(create_app(settings())) as client:
        assert client.get("/v1/ops/fairness", params={"days": 0}, headers=ADMIN).status_code == 422
        assert (
            client.get("/v1/ops/fairness", params={"days": 366}, headers=ADMIN).status_code == 422
        )
