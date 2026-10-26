"""The packaged MCP server: read-only contract, permissions delegated, no key leak."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hr_agents.mcp_server import McpServerError, build_server


def api(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="http://api.test/",
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )


async def test_the_server_exposes_only_read_tools() -> None:
    from mcp.client.client import Client

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    server = build_server(api_key="secret-key", client=api(handler))
    async with Client(server) as client:
        tools = await client.list_tools()

    assert sorted(tool.name for tool in tools.tools) == [
        "application_status",
        "evaluation_summary",
        "leave_balances",
        "pending_approvals",
        "queue",
    ]
    assert seen == []  # discovery does not call the API


async def test_a_tool_call_goes_through_the_api_with_the_key_and_is_a_get() -> None:
    from mcp.client.client import Client

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"id": "app-1", "status": "applied", "title": "Backend Engineer"},
        )

    server = build_server(api_key="secret-key", client=api(handler))
    async with Client(server) as client:
        result = await client.call_tool("application_status", {"application_id": "app-1"})

    request = seen[0]
    assert request.method == "GET"
    assert str(request.url).endswith("/v1/applications/app-1")
    assert request.headers["x-api-key"] == "secret-key"
    text = result.content[0].text  # type: ignore[union-attr]
    assert json.loads(text)["status"] == "applied"
    assert "secret-key" not in text


async def test_a_refusal_is_reported_with_its_status_not_the_key() -> None:
    from mcp.client.client import Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"code": "permission_denied", "detail": "not available for your role"},
        )

    server = build_server(api_key="secret-key", client=api(handler))
    async with Client(server) as client:
        result = await client.call_tool("pending_approvals", {})

    payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert payload["status"] == 403
    assert payload["detail"] == "not available for your role"
    assert "secret-key" not in json.dumps(payload)


async def test_an_unreachable_api_is_a_tool_error_not_a_crash() -> None:
    from mcp.client.client import Client

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    server = build_server(api_key="secret-key", client=api(handler))
    async with Client(server) as client:
        result = await client.call_tool("queue", {"job_id": "job-1"})

    payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert "could not be reached" in payload["error"]


def test_the_key_is_required_and_never_read_from_the_url() -> None:
    with pytest.raises(McpServerError, match="HRAGENTS_API_KEY"):
        build_server(api_key="", client=api(lambda request: httpx.Response(200)))
