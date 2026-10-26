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
    allow_writes: bool | None = None,
) -> Any:
    """Build the MCP server. ``client`` is injectable for contract tests."""
    key = api_key if api_key is not None else os.environ.get("HRAGENTS_API_KEY", "")
    if not key.strip():
        raise McpServerError("HRAGENTS_API_KEY is required; create a role-bound key in the install")
    url = (base_url or os.environ.get("HRAGENTS_API_URL", DEFAULT_URL)).rstrip("/")
    http = client or httpx.AsyncClient(base_url=f"{url}/", timeout=30.0)
    http.headers["X-API-Key"] = key
    writes = (
        allow_writes
        if allow_writes is not None
        else os.environ.get("HRAGENTS_MCP_WRITES", "").lower() in {"1", "true", "yes"}
    )

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

    async def call(
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await http.request(method, path, params=params, json=payload)
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
        return await call("GET", "v1/queue", params={"job_id": job_id, "limit": limit})

    @server.tool(description="Status and timeline for one application.")
    async def application_status(application_id: str) -> dict[str, Any]:
        return await call("GET", f"v1/applications/{application_id}")

    @server.tool(
        description=(
            "The deterministic evaluation for an application: score vector, "
            "evidence, rubric family/digest, flags and the routing recommendation."
        )
    )
    async def evaluation_summary(application_id: str) -> dict[str, Any]:
        return await call("GET", f"v1/evaluations/applications/{application_id}/evaluation")

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
        return await call("GET", "v1/approvals", params=params)

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
        return await call("GET", f"v1/leave/balances/{employee_id}", params=params)

    if writes:

        @server.tool(
            description=(
                "Ingest one application from an external ATS (recruiting:write). "
                "Consent is never inferred: the caller supplies the consent object "
                "it captured. The pipeline evaluates asynchronously."
            )
        )
        async def create_application(
            job_id: str,
            candidate: dict[str, Any],
            consent: dict[str, Any],
            source_channel: str = "mcp",
            documents: list[dict[str, Any]] | None = None,
            questionnaire: dict[str, Any] | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "job_id": job_id,
                "source_channel": source_channel,
                "consent": consent,
                "candidate": candidate,
            }
            if documents:
                payload["documents"] = documents
            if questionnaire:
                payload["questionnaire"] = questionnaire
            if metadata:
                payload["metadata"] = metadata
            return await call("POST", "v1/applications", payload=payload)

        @server.tool(
            description=(
                "Open an onboarding plan from a template (people:write). Steps are "
                "linked to real documents; completing quits is still a human action."
            )
        )
        async def start_onboarding_plan(
            employee_id: str, template_id: str | None = None
        ) -> dict[str, Any]:
            payload: dict[str, Any] = {"employee_id": employee_id}
            if template_id:
                payload["template_id"] = template_id
            return await call("POST", "v1/onboarding/plans", payload=payload)

        @server.tool(
            description=(
                "File a leave request (self_service, or people:write). It becomes an "
                "approval in the human queue; this tool cannot decide it."
            )
        )
        async def open_leave_request(
            employee_id: str,
            leave_type: str,
            start_date: str,
            end_date: str,
            reason: str | None = None,
        ) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "employee_id": employee_id,
                "leave_type": leave_type,
                "start_date": start_date,
                "end_date": end_date,
            }
            if reason:
                payload["reason"] = reason
            return await call("POST", "v1/leave/requests", payload=payload)

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
