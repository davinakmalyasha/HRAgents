"""The export route: admin only, Postgres only, and audited."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from hr_agents.config import ApiPrincipalSettings, Settings
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


def sqlite_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_the_export_requires_a_durable_backend() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get("/v1/export", headers=ADMIN)
        assert response.status_code == 409
        assert "Postgres" in response.json()["detail"]


def test_an_admin_gets_the_document_and_an_employee_does_not() -> None:
    app = create_app(settings())
    app.state.session_factory = sqlite_factory()
    with TestClient(app) as client:
        forbidden = client.get("/v1/export", headers=EMPLOYEE)
        assert forbidden.status_code == 403

        response = client.get("/v1/export", headers=ADMIN)
        assert response.status_code == 200, response.text
        assert "attachment" in response.headers["content-disposition"]
        body = response.json()
        assert body["manifest"]["exported_by"] == "rina"
        assert "audit_log" in body["data"]

    assert app.state.audit.entries[-1].action == "data.exported"
