"""Operator endpoints: the dead-letter queue.

A dead-lettered evaluation message is a submission the API accepted and the
pipeline could not process. Reading the list is how an operator finds out; the
requeue is a named human act with a reason, because "try again" without a cause
is how the same message dies twice.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from hr_agents.api.deps import ActorDep, PaginationDep, require_permission
from hr_agents.api.ops_schemas import (
    DeadLetterRequeue,
    DeadLetterRequeueResult,
    DeadLetterView,
)
from hr_agents.api.problem import domain_problem, not_found, unavailable
from hr_agents.api.schemas import Page
from hr_agents.models import UsageSummary, utc_now
from hr_agents.providers.queue import QueueBackend
from hr_agents.rbac import Permission
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
