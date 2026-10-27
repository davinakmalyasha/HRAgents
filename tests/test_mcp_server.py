"""The packaged MCP server: permission-gated tools, no decisions, no key leak."""

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


async def test_the_server_exposes_no_write_tools_by_default() -> None:
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


async def test_writes_are_opt_in_and_never_include_decisions() -> None:
    from mcp.client.client import Client

    server = build_server(
        api_key="secret-key", client=api(lambda request: httpx.Response(200)), allow_writes=True
    )
    async with Client(server) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools.tools}
    assert {
        "create_application",
        "start_onboarding_plan",
        "open_leave_request",
    } <= names
    assert not {"approve", "reject", "decide", "move_stage", "override"} & names


async def test_a_write_posts_json_and_returns_the_api_answer() -> None:
    from mcp.client.client import Client

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert json.loads(request.content) == {
            "employee_id": "emp-1",
            "leave_type": "annual",
            "start_date": "2026-11-02",
            "end_date": "2026-11-03",
            "reason": "family",
        }
        return httpx.Response(201, json={"id": "req-1", "status": "pending_manager"})

    server = build_server(api_key="secret-key", client=api(handler), allow_writes=True)
    async with Client(server) as client:
        result = await client.call_tool(
            "open_leave_request",
            {
                "employee_id": "emp-1",
                "leave_type": "annual",
                "start_date": "2026-11-02",
                "end_date": "2026-11-03",
                "reason": "family",
            },
        )

    request = seen[0]
    assert request.method == "POST"
    assert str(request.url).endswith("/v1/leave/requests")
    assert request.headers["x-api-key"] == "secret-key"
    payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert payload["status"] == "pending_manager"


async def test_intake_never_invents_consent() -> None:
    from mcp.client.client import Client

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"application_id": "app-9", "status": "queued"})

    server = build_server(api_key="secret-key", client=api(handler), allow_writes=True)
    consent = {"granted": True, "policy_version": "2.1"}
    async with Client(server) as client:
        await client.call_tool(
            "create_application",
            {
                "job_id": "job-1",
                "candidate": {"full_name": "Ana", "emails": ["ana@example.com"]},
                "consent": consent,
            },
        )

    body = json.loads(seen[0].content)
    assert body["consent"] == consent
    assert body["source_channel"] == "mcp"
    assert "documents" not in body


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


async def test_a_tool_allowlist_narrows_the_surface() -> None:
    from mcp.client.client import Client

    server = build_server(
        api_key="secret-key",
        client=api(lambda request: httpx.Response(200)),
        tools=["queue", "leave_balances"],
    )
    async with Client(server) as client:
        tools = await client.list_tools()

    assert sorted(tool.name for tool in tools.tools) == ["leave_balances", "queue"]


async def test_the_allowlist_can_come_from_the_environment(monkeypatch: Any) -> None:
    from mcp.client.client import Client

    monkeypatch.setenv("HRAGENTS_MCP_TOOLS", "application_status")
    server = build_server(api_key="secret-key", client=api(lambda request: httpx.Response(200)))
    async with Client(server) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == ["application_status"]


def test_an_unknown_tool_name_stops_startup() -> None:
    with pytest.raises(McpServerError, match="unknown MCP tool\(s\): escalate"):
        build_server(
            api_key="secret-key",
            client=api(lambda request: httpx.Response(200)),
            tools=["queue", "escalate"],
        )


def test_a_write_tool_outside_write_mode_stops_startup() -> None:
    with pytest.raises(McpServerError, match="HRAGENTS_MCP_WRITES=1"):
        build_server(
            api_key="secret-key",
            client=api(lambda request: httpx.Response(200)),
            tools=["queue", "create_application"],
            allow_writes=False,
        )


async def test_read_tools_declare_read_only_annotations() -> None:
    from mcp.client.client import Client

    server = build_server(api_key="secret-key", client=api(lambda request: httpx.Response(200)))
    async with Client(server) as client:
        tools = await client.list_tools()

    for tool in tools.tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


async def test_write_tools_are_explicitly_not_read_only_and_not_destructive() -> None:
    from mcp.client.client import Client

    server = build_server(
        api_key="secret-key",
        client=api(lambda request: httpx.Response(200)),
        allow_writes=True,
    )
    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    for name in ("create_application", "start_onboarding_plan", "open_leave_request"):
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is False
    assert tools["queue"].annotations is not None
    assert tools["queue"].annotations.read_only_hint is True


def test_the_instructions_match_the_mode() -> None:
    read_only = build_server(api_key="secret-key", client=api(lambda request: httpx.Response(200)))
    writable = build_server(
        api_key="secret-key",
        client=api(lambda request: httpx.Response(200)),
        allow_writes=True,
    )

    assert read_only.instructions.startswith("Read-only access")
    assert writable.instructions.startswith("Read and write access")
    assert "nothing here decides" in read_only.instructions.lower()
    assert "nothing here decides" in writable.instructions.lower()
