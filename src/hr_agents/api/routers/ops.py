"""Operator endpoints: the dead-letter queue.

A dead-lettered evaluation message is a submission the API accepted and the
pipeline could not process. Reading the list is how an operator finds out; the
requeue is a named human act with a reason, because "try again" without a cause
is how the same message dies twice.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from hr_agents.api.deps import ActorDep, PaginationDep, get_audit, require_permission
from hr_agents.api.ops_schemas import (
    DeadLetterRequeue,
    DeadLetterRequeueResult,
    DeadLetterView,
    McpServerView,
)
from hr_agents.api.problem import domain_problem, not_found, unavailable
from hr_agents.api.schemas import Page
from hr_agents.models import (
    McpProbeResult,
    McpServerCatalogEntry,
    McpServerConfig,
    McpServerStatus,
    ScoreDistributionReport,
    UsageSummary,
    utc_now,
)
from hr_agents.providers.queue import QueueBackend
from hr_agents.rbac import Permission
from hr_agents.services.audit import AuditChain
from hr_agents.services.audit_events import record_audit
from hr_agents.services.distribution import ScoreDistributionService
from hr_agents.services.mcp_catalog import catalog
from hr_agents.services.mcp_config import McpConfigError
from hr_agents.services.queue_ops import QueueOpsError
from hr_agents.services.queue_ops import requeue_dead_letter as requeue_dead_letter_service

router = APIRouter(
    prefix="/v1/ops",
    tags=["ops"],
    dependencies=[Depends(require_permission(Permission.ADMIN_MANAGE))],
)


def get_queue(request: Request) -> QueueBackend | None:
    return getattr(request.app.state, "queue", None)


QueueDep = Annotated[QueueBackend | None, Depends(get_queue)]
AuditDep = Annotated[AuditChain, Depends(get_audit)]


@router.get("/mcp", response_model=list[McpServerStatus])
def mcp_status(request: Request) -> list[McpServerStatus]:
    """Which external MCP servers are connected, and which tools they expose."""
    manager = getattr(request.app.state, "mcp", None)
    return manager.statuses() if manager is not None else []


def _mcp_view(request: Request, config: McpServerConfig) -> McpServerView:
    manager = getattr(request.app.state, "mcp", None)
    statuses = {item.name: item for item in manager.statuses()} if manager is not None else {}
    service = request.app.state.mcp_configs
    return McpServerView(
        name=config.name,
        url=config.url,
        source=service.source(config.name),
        auth_env=config.auth_env,
        timeout_seconds=config.timeout_seconds,
        allowed_agents=config.allowed_agents,
        tools=config.tools,
        status=statuses.get(config.name),
    )


async def _reload_mcp(request: Request) -> None:
    reload = getattr(request.app.state, "mcp_reload", None)
    if reload is not None:
        await reload()


@router.get("/mcp/catalog", response_model=list[McpServerCatalogEntry])
def mcp_catalog() -> list[McpServerCatalogEntry]:
    """Connector templates: capabilities, data flow and enablement, never endpoints."""
    return catalog()


@router.get("/mcp/servers", response_model=list[McpServerView])
def list_mcp_servers(request: Request) -> list[McpServerView]:
    """Environmental and dashboard connections, merged, with live statuses."""
    service = request.app.state.mcp_configs
    return [_mcp_view(request, config) for config in service.merged()]


@router.put("/mcp/servers/{name}", response_model=McpServerView)
async def save_mcp_server(
    name: str,
    payload: McpServerConfig,
    request: Request,
    actor: ActorDep,
    audit: AuditDep,
) -> McpServerView:
    """Add or replace a dashboard connection. Environment names are locked."""
    if payload.name != name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="the body name must match the path",
        )
    service = request.app.state.mcp_configs
    try:
        service.save(payload, actor=actor)
    except McpConfigError as exc:
        raise domain_problem(exc) from exc
    record_audit(
        audit,
        actor=actor,
        action="ops.mcp_server_saved",
        subject_type="mcp_server",
        subject_id=name,
        payload={
            "url": payload.url,
            "tools": sorted(payload.tools),
            "allowed_agents": payload.allowed_agents,
        },
    )
    await _reload_mcp(request)
    return _mcp_view(request, payload)


@router.delete("/mcp/servers/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    name: str,
    request: Request,
    actor: ActorDep,
    audit: AuditDep,
) -> Response:
    """Remove a dashboard connection. Environment connections cannot be deleted."""
    service = request.app.state.mcp_configs
    try:
        service.delete(name)
    except McpConfigError as exc:
        raise domain_problem(exc) from exc
    except KeyError as exc:
        raise not_found(f"unknown MCP server {name}") from exc
    record_audit(
        audit,
        actor=actor,
        action="ops.mcp_server_deleted",
        subject_type="mcp_server",
        subject_id=name,
    )
    await _reload_mcp(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mcp/servers/{name}/test", response_model=McpProbeResult)
async def test_mcp_server(name: str, request: Request) -> McpProbeResult:
    """Connect, list tools and disconnect without registering anything."""
    probe = getattr(request.app.state, "mcp_probe", None)
    if probe is None:
        raise unavailable("MCP testing is not available")
    try:
        return await probe(name)
    except KeyError as exc:
        raise not_found(f"unknown MCP server {name}") from exc


@router.get("/fairness", response_model=ScoreDistributionReport)
def fairness_report(
    request: Request,
    days: int = Query(default=90, ge=1, le=365, description="Window in days."),
) -> ScoreDistributionReport:
    """Per-job score distributions over evaluations the pipeline registered.

    Deliberately not a demographic metric: protected attributes are neither
    collected nor scored, so this monitors drift, routing and flags by job.
    """
    recruiting = getattr(request.app.state, "recruiting", None)
    if recruiting is None:
        raise unavailable("score distribution is not available")
    return ScoreDistributionService(recruiting.evaluations).report(days=days)


@router.get("/usage", response_model=UsageSummary)
def usage_summary(
    request: Request,
    days: int = Query(default=30, ge=1, le=365, description="Window in days."),
) -> UsageSummary:
    """Tokens consumed by provider and model, for the operator's cost view."""
    service = getattr(request.app.state, "llm_usage", None)
    if service is None:
        raise unavailable("token usage is not available")
    return service.summary(since=utc_now() - timedelta(days=days))


@router.get("/dead-letters", response_model=Page[DeadLetterView])
async def list_dead_letters(queue: QueueDep, paging: PaginationDep) -> Page[DeadLetterView]:
    """Dead-lettered messages, newest first, metadata only."""
    if queue is None:
        raise unavailable("the queue backend is not resolved yet")
    messages = await queue.dead_letters()
    views = [DeadLetterView.from_message(message) for message in messages]
    views.sort(
        key=lambda view: (view.failed_at or view.created_at, view.message_id),
        reverse=True,
    )
    return Page.slice(views, limit=paging.limit, offset=paging.offset)


@router.post(
    "/dead-letters/{message_id}/requeue",
    response_model=DeadLetterRequeueResult,
)
async def requeue_dead_letter(
    message_id: str,
    payload: DeadLetterRequeue,
    queue: QueueDep,
    actor: ActorDep,
    request: Request,
) -> DeadLetterRequeueResult:
    """Return one dead letter to its topic's pending list, reason recorded."""
    if queue is None:
        raise unavailable("the queue backend is not resolved yet")
    try:
        requeued = await requeue_dead_letter_service(
            queue,
            message_id=message_id,
            reason=payload.reason,
            actor=actor,
            audit=request.app.state.audit,
        )
    except QueueOpsError as exc:
        raise domain_problem(exc) from exc
    if not requeued:
        raise not_found(f"no dead letter {message_id}")
    return DeadLetterRequeueResult(requeued=True)
