"""Dashboard MCP connections: save, delete, test, and admin-only access."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.models import McpProbeResult
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


def body(name: str = "ats") -> dict[str, object]:
    return {
        "name": name,
        "url": "https://mcp.example.com/mcp",
        "auth_env": "ATS_MCP_TOKEN",
        "timeout_seconds": 5,
        "tools": {"get_candidate": "read"},
        "allowed_agents": ["screening_coordinator"],
    }


def test_connections_are_admin_only() -> None:
    with TestClient(create_app(settings())) as client:
        assert client.get("/v1/ops/mcp/servers", headers=EMPLOYEE).status_code == 403
        assert (
            client.put("/v1/ops/mcp/servers/ats", json=body(), headers=EMPLOYEE).status_code == 403
        )
        assert client.delete("/v1/ops/mcp/servers/ats", headers=EMPLOYEE).status_code == 403
        assert client.get("/v1/ops/mcp/servers/ats/test", headers=EMPLOYEE).status_code == 403


def test_save_delete_and_reload() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        reloads: list[int] = []

        async def reload() -> None:
            reloads.append(1)

        app.state.mcp_reload = reload

        saved = client.put("/v1/ops/mcp/servers/ats", json=body(), headers=ADMIN)
        assert saved.status_code == 200
        assert saved.json()["source"] == "dashboard"
        assert saved.json()["tools"] == {"get_candidate": "read"}
        assert reloads == [1]

        listing = client.get("/v1/ops/mcp/servers", headers=ADMIN).json()
        assert [item["name"] for item in listing] == ["ats"]
        assert listing[0]["auth_env"] == "ATS_MCP_TOKEN"
        assert listing[0]["status"] is None

        replaced = client.put("/v1/ops/mcp/servers/ats", json=body(), headers=ADMIN)
        assert replaced.status_code == 200
        assert reloads == [1, 1]

        deleted = client.delete("/v1/ops/mcp/servers/ats", headers=ADMIN)
        assert deleted.status_code == 204
        assert reloads == [1, 1, 1]
        assert client.get("/v1/ops/mcp/servers", headers=ADMIN).json() == []
        assert client.delete("/v1/ops/mcp/servers/ats", headers=ADMIN).status_code == 404

        actions = [entry.action for entry in app.state.audit.entries]
        assert "ops.mcp_server_saved" in actions
        assert "ops.mcp_server_deleted" in actions


def test_the_catalog_is_admin_only_and_says_how_to_enable() -> None:
    with TestClient(create_app(settings())) as client:
        assert client.get("/v1/ops/mcp/catalog", headers=EMPLOYEE).status_code == 403
        body = client.get("/v1/ops/mcp/catalog", headers=ADMIN).json()

    assert [entry["id"] for entry in body] == ["ats", "hris", "slack", "calendar"]
    for entry in body:
        assert entry["data_flow"]
        assert entry["scopes"]
        assert entry["enable_steps"]
        assert "destructive" not in entry["tools"].values()


def test_the_path_name_must_match_the_body() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.put("/v1/ops/mcp/servers/other", json=body(), headers=ADMIN)
        assert response.status_code == 422


def test_credentials_in_the_url_are_refused() -> None:
    payload = body()
    payload["url"] = "https://user:secret@mcp.example.com/mcp"
    with TestClient(create_app(settings())) as client:
        response = client.put("/v1/ops/mcp/servers/ats", json=payload, headers=ADMIN)
        assert response.status_code == 422
        assert "credential" in response.text


def test_the_test_button_uses_the_probe_callback() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        seen: list[str] = []

        async def probe(name: str) -> McpProbeResult:
            seen.append(name)
            if name == "ghost":
                raise KeyError(name)
            return McpProbeResult(name=name, connected=True, tools=["get_candidate"])

        app.state.mcp_probe = probe

        result = client.get("/v1/ops/mcp/servers/ats/test", headers=ADMIN)
        assert result.status_code == 200
        assert result.json()["tools"] == ["get_candidate"]
        assert seen == ["ats"]

        assert client.get("/v1/ops/mcp/servers/ghost/test", headers=ADMIN).status_code == 404
