"""The usage endpoint: admin-only, zeros are honest, totals reflect the ledger."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.models import LlmUsage
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


def test_usage_is_empty_before_any_evaluation() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get("/v1/ops/usage", headers=ADMIN)
        assert response.status_code == 200
        assert response.json()["totals"]["input_tokens"] == 0
        assert response.json()["by_model"] == []


def test_usage_reflects_the_ledger_and_is_admin_only() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        app.state.llm_usage.record(
            usage=LlmUsage(
                provider_id="llm.demo",
                model="model-a",
                input_tokens=120,
                output_tokens=30,
                requests=2,
            ),
            application_id="app-1",
        )

        assert client.get("/v1/ops/usage", headers=EMPLOYEE).status_code == 403
        body = client.get("/v1/ops/usage", headers=ADMIN).json()
        assert body["totals"]["input_tokens"] == 120
        assert body["totals"]["total_tokens"] == 150
        assert body["by_model"][0]["model"] == "model-a"
        assert client.get("/v1/ops/usage?days=0", headers=ADMIN).status_code == 422
