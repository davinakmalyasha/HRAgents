"""Integration tests for the first-run setup surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId


def make_client() -> TestClient:
    return TestClient(create_app())


def test_a_fresh_install_reports_an_empty_checklist() -> None:
    with make_client() as client:
        response = client.get("/v1/setup")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["app_name"] == "HRAgents"
        assert body["timezone"] == "Asia/Jakarta"
        assert body["store_backend"] == "memory"
        assert body["llm_model"] == "test"
        assert body["auth_configured"] is False
        assert body["counts"] == {
            "employees": 0,
            "jobs": 0,
            "onboarding_templates": 0,
            "offboarding_templates": 0,
            "rate_tables": 0,
            "unverified_rate_tables": 0,
        }


def test_seeding_starters_is_idempotent_and_updates_the_counts() -> None:
    with make_client() as client:
        first = client.post("/v1/setup/starters")
        assert first.status_code == 200, first.text
        created = first.json()["created"]
        assert "onboarding_template:New hire starter" in created
        assert "offboarding_template:Resignation checklist" in created
        assert len([item for item in created if item.startswith("rate_table:")]) == 9

        counts = client.get("/v1/setup").json()["counts"]
        assert counts["onboarding_templates"] == 1
        assert counts["offboarding_templates"] == 1
        assert counts["rate_tables"] == 9
        assert counts["unverified_rate_tables"] == 9

        second = client.post("/v1/setup/starters").json()
        assert second["created"] == []
        assert second["skipped"] == created

        actions = [entry.action for entry in client.app.state.audit.entries]  # type: ignore[attr-defined]
        assert "setup.starters_seeded" in actions


def test_setup_requires_admin_management() -> None:
    settings = Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("rec-key"), role=RoleId.RECRUITER, actor_id="rec-1")
        ],
    )
    with TestClient(create_app(settings)) as client:
        denied = client.get("/v1/setup", headers={"X-API-Key": "rec-key"})
        assert denied.status_code == 403
        assert denied.json()["code"] == "permission_denied"
