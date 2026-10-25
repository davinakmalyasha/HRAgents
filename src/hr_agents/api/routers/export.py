"""Full-tenant export: the operator's copy of everything the system knows.

This is a read, but a consequential one: it returns every personal record in
the tenant. It is admin-only, audited before the stream starts, and streamed
because a payroll or audit history can be large.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from hr_agents.api.deps import ActorDep, require_permission
from hr_agents.models import utc_now
from hr_agents.rbac import Permission
from hr_agents.services.export import (
    EXPORT_FORMAT,
    export_filename,
    export_tables,
    iter_export,
)

router = APIRouter(
    prefix="/v1/export",
    tags=["export"],
    dependencies=[Depends(require_permission(Permission.ADMIN_MANAGE))],
)


@router.get(
    "",
    summary="Download every tenant row as one JSON document",
    response_class=StreamingResponse,
)
def download_export(request: Request, actor: ActorDep) -> StreamingResponse:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "a full export needs the Postgres backend; the in-memory demo has "
                "no durable record to export"
            ),
        )
    moment = utc_now()
    request.app.state.audit.append(
        actor=actor.audit_actor(),
        action="data.exported",
        subject_type="tenant",
        subject_id="default",
        payload={"format": EXPORT_FORMAT, "tables": len(export_tables())},
    )
    return StreamingResponse(
        iter_export(factory, exported_at=moment, exported_by=actor.actor_id),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{export_filename(moment)}"'},
    )
