"""API-level RBAC: role-bound keys gate router access."""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId


def _settings() -> Settings:
    return Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("rec-key"), role=RoleId.RECRUITER, actor_id="rec-1"),
            ApiPrincipalSettings(key=SecretStr("fin-key"), role=RoleId.FINANCE, actor_id="fin-1"),
            ApiPrincipalSettings(key=SecretStr("emp-key"), role=RoleId.EMPLOYEE, actor_id="emp-1"),
        ],
    )


def _payroll_payload() -> dict:
    return {
        "period_year": date.today().year,
        "period_month": 6,
        "created_by": "finance-1",
    }


def test_recruiter_can_read_recruiting_but_not_payroll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hr_agents.api.deps.get_settings", _settings)
    app = create_app()
    with TestClient(app) as client:
        queue = client.get(
            "/v1/queue",
            params={"job_id": str(uuid4())},
            headers={"X-API-Key": "rec-key"},
        )
        assert queue.status_code == 200

        payroll = client.post(
            "/v1/payroll/runs",
            json=_payroll_payload(),
            headers={"X-API-Key": "rec-key"},
        )
        assert payroll.status_code == 403


def test_finance_can_create_payroll_but_not_read_recruiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hr_agents.api.deps.get_settings", _settings)
    app = create_app()
    with TestClient(app) as client:
        run = client.post(
            "/v1/payroll/runs",
            json=_payroll_payload(),
            headers={"X-API-Key": "fin-key"},
        )
        assert run.status_code == 201

        queue = client.get(
            "/v1/queue",
            params={"job_id": str(uuid4())},
            headers={"X-API-Key": "fin-key"},
        )
        assert queue.status_code == 403


def test_manager_can_decide_approvals_but_not_payroll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hr_agents.api.deps.get_settings", _settings)
    app = create_app()
    with TestClient(app) as client:
        payroll = client.post(
            "/v1/payroll/runs",
            json=_payroll_payload(),
            headers={"X-API-Key": "emp-key"},
        )
        assert payroll.status_code == 403

        approvals = client.get("/v1/approvals", headers={"X-API-Key": "emp-key"})
        assert approvals.status_code == 403


def test_missing_or_wrong_key_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hr_agents.api.deps.get_settings", _settings)
    app = create_app()
    with TestClient(app) as client:
        missing = client.get("/v1/queue", params={"job_id": str(uuid4())})
        assert missing.status_code == 401

        wrong = client.get(
            "/v1/queue",
            params={"job_id": str(uuid4())},
            headers={"X-API-Key": "nope"},
        )
        assert wrong.status_code == 401


def test_unconfigured_auth_allows_local_admin() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/queue", params={"job_id": str(uuid4())})
        assert response.status_code == 200
