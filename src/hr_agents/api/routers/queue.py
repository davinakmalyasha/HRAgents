"""Priority-ranked queue endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from hr_agents.api.deps import get_store, require_api_key
from hr_agents.api.schemas import QueueEntry, QueueResponse
from hr_agents.services import ApplicationStore

router = APIRouter(prefix="/v1/queue", tags=["queue"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=QueueResponse, summary="Priority-ranked candidates for a job")
def get_queue(
    store: Annotated[ApplicationStore, Depends(get_store)],
    job_id: Annotated[UUID, Query()],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> QueueResponse:
    now = datetime.now(UTC)
    entries: list[QueueEntry] = []
    for record in store.list_for_job(job_id)[:limit]:
        hours = (now - record.received_at).total_seconds() / 3600.0
        entries.append(
            QueueEntry(
                application_id=record.id,
                candidate_id=record.candidate_id,
                status=record.status.value,
                priority_score=record.priority_score,
                s_tech=record.s_tech,
                hours_waiting=round(hours, 4),
            )
        )
    return QueueResponse(items=entries)
