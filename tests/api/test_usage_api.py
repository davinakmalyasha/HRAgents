"""The usage endpoint: admin-only, zeros are honest, totals reflect the ledger."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.models import LlmPricing, LlmUsage
from hr_agents.rbac import RoleId
from hr_agents.services import SubmissionInput

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


def test_application_and_candidate_rollups_include_the_cost_snapshot() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        record, _ = app.state.store.submit(
            SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
        )
        app.state.llm_usage.record(
            usage=LlmUsage(
                provider_id="llm.demo",
                model="model-a",
                input_tokens=1_000_000,
                output_tokens=0,
                requests=1,
            ),
            application_id=str(record.id),
            pricing=LlmPricing(input_cost_per_million=2.0),
        )

        application = client.get(f"/v1/ops/usage/applications/{record.id}", headers=ADMIN)
        candidate = client.get(f"/v1/ops/usage/candidates/{record.candidate_id}", headers=ADMIN)
        forbidden = client.get(f"/v1/ops/usage/candidates/{record.candidate_id}", headers=EMPLOYEE)

    assert application.status_code == 200, application.text
    assert application.json()["cost_usd"] == 2.0
    assert application.json()["totals"]["total_tokens"] == 1_000_000
    assert candidate.status_code == 200, candidate.text
    assert candidate.json()["application_ids"] == [str(record.id)]
    assert candidate.json()["cost_usd"] == 2.0
    assert forbidden.status_code == 403


def test_an_unknown_application_rollup_is_zero_not_an_error() -> None:
    with TestClient(create_app(settings())) as client:
        body = client.get(f"/v1/ops/usage/applications/{uuid4()}", headers=ADMIN)

    assert body.status_code == 200
    assert body.json()["entries"] == 0
    assert body.json()["cost_usd"] is None
