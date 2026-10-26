"""The ops view of MCP servers: connected or not, and which tools are exposed."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.models import McpServerStatus
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


def test_no_servers_is_an_empty_list() -> None:
    with TestClient(create_app(settings())) as client:
        assert client.get("/v1/ops/mcp", headers=ADMIN).json() == []


def test_statuses_are_reported_and_admin_only() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        app.state.mcp = SimpleNamespace(
            statuses=lambda: [
                McpServerStatus(
                    name="ats",
                    url="https://mcp.example.com/mcp",
                    connected=True,
                    detail="connected",
                    tools=["mcp.ats.get_candidate"],
                    tool_count=1,
                ),
                McpServerStatus(
                    name="hris",
                    url="https://hris.example.com/mcp",
                    connected=False,
                    detail="HRIS_MCP_TOKEN is not set",
                ),
            ]
        )

        assert client.get("/v1/ops/mcp", headers=EMPLOYEE).status_code == 403
        body = client.get("/v1/ops/mcp", headers=ADMIN).json()
        assert [item["name"] for item in body] == ["ats", "hris"]
        assert body[0]["tool_count"] == 1
        assert body[1]["connected"] is False
