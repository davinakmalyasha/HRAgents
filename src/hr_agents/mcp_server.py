"""`hragents-mcp`: a read-only MCP server over the HRAgents API.

External MCP clients (Claude Desktop, IDE agents) can ask an HRAgents install
what is in a queue, what happened to one application, how it was evaluated,
what awaits a human, and what leave somebody has left. Nothing here writes:
the write half is approval-gated and stays inside the product.

Authorization is not re-implemented. Every call goes through the API with the
operator's key, so the API's permissions, tenant scoping and audit chain apply
exactly as they do to any other client. The server is a thin adapter, and the
key lives in the environment rather than in an argument list.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:8000"


class McpServerError(RuntimeError):
    """Configuration or transport problem that stops the server from starting."""


def build_server(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> Any:
    """Build the MCP server. ``client`` is injectable for contract tests."""
    key = api_key if api_key is not None else os.environ.get("HRAGENTS_API_KEY", "")
    if not key.strip():
        raise McpServerError("HRAGENTS_API_KEY is required; create a role-bound key in the install")
    url = (base_url or os.environ.get("HRAGENTS_API_URL", DEFAULT_URL)).rstrip("/")
    http = client or httpx.AsyncClient(base_url=f"{url}/", timeout=30.0)
    http.headers["X-API-Key"] = key

    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        "hragents",
        instructions=(
            "Read-only access to an HRAgents install: queues, application status, "
            "deterministic evaluations, pending approvals and leave balances. "
            "Nothing here decides or writes; consequential actions belong to a "
            "named human in the dashboard."
        ),
    )

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await http.get(path, params=params)
        except httpx.HTTPError as exc:
            return {"error": f"the API could not be reached ({type(exc).__name__})"}
        if response.is_success:
            body = response.json()
            return body if isinstance(body, dict) else {"data": body}
        detail: Any = None
        try:
            problem = response.json()
            if isinstance(problem, dict):
                detail = problem.get("detail")
        except ValueError:
            detail = None
        return {
            "error": "the API refused this request",
            "status": response.status_code,
            "detail": detail if isinstance(detail, str) else None,
        }

    @server.tool(
        description=(
            "Priority-ranked applications for one job. The API's recruiting:read "
            "permission is required."
        )
    )
    async def queue(job_id: str, limit: int = 50) -> dict[str, Any]:
        return await get("v1/queue", {"job_id": job_id, "limit": limit})

    @server.tool(description="Status and timeline for one application.")
    async def application_status(application_id: str) -> dict[str, Any]:
        return await get(f"v1/applications/{application_id}")

    @server.tool(
        description=(
            "The deterministic evaluation for an application: score vector, "
            "evidence, rubric family/digest, flags and the routing recommendation."
        )
    )
    async def evaluation_summary(application_id: str) -> dict[str, Any]:
        return await get(f"v1/evaluations/applications/{application_id}/evaluation")

    @server.tool(
        description=(
            "Approvals waiting for a human, optionally filtered to an approver "
            "role (manager, finance, hr_admin, …)."
        )
    )
    async def pending_approvals(role: str | None = None, limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"status": "pending", "limit": limit}
        if role:
            params["role"] = role
        return await get("v1/approvals", params)

    @server.tool(
        description=(
            "Leave balances for one employee. The API applies its own self-service "
            "and role rules; a key without access receives a refusal, not data."
        )
    )
    async def leave_balances(employee_id: str, year: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if year is not None:
            params["year"] = year
        return await get(f"v1/leave/balances/{employee_id}", params)

    return server


def main() -> int:
    try:
        server = build_server()
    except McpServerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
