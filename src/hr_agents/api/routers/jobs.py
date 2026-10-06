"""Job specification endpoints — CRUD plus a guarded status lifecycle."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from hr_agents.api.deps import ActorDep, require_permission
from hr_agents.api.problem import conflict, not_found
from hr_agents.api.recruitment_schemas import (
    JobCreate,
    JobStatusChange,
    JobUpdate,
    JobView,
)
from hr_agents.models import JobStatus
from hr_agents.rbac import Permission
from hr_agents.services.recruiting import JobService, RecruitingError

router = APIRouter(
    prefix="/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)


def get_jobs(request: Request) -> JobService:
    return request.app.state.recruiting.jobs


JobsDep = Annotated[JobService, Depends(get_jobs)]


@router.get("", response_model=list[JobView], summary="List job specifications")
def list_jobs(jobs: JobsDep, job_status: JobStatus | None = None) -> list[JobView]:
    return [JobView.from_model(job) for job in jobs.list_all(status=job_status)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=JobView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)
def create_job(payload: JobCreate, jobs: JobsDep, actor: ActorDep) -> JobView:
    try:
        job = jobs.create(actor=actor, **payload.model_dump())
    except (RecruitingError, ValueError) as exc:
        raise conflict(exc) from exc
    return JobView.from_model(job)


@router.get("/{job_id}", response_model=JobView)
def get_job(job_id: UUID, jobs: JobsDep) -> JobView:
    try:
        return JobView.from_model(jobs.get(job_id))
    except RecruitingError as exc:
        raise not_found(str(exc)) from exc


@router.patch(
    "/{job_id}",
    response_model=JobView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)
def update_job(job_id: UUID, payload: JobUpdate, jobs: JobsDep, actor: ActorDep) -> JobView:
    try:
        job = jobs.update(job_id, actor=actor, **payload.model_dump())
    except (RecruitingError, ValueError) as exc:
        raise conflict(exc) from exc
    return JobView.from_model(job)


@router.post(
    "/{job_id}/status",
    response_model=JobView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)
def change_job_status(
    job_id: UUID, payload: JobStatusChange, jobs: JobsDep, actor: ActorDep
) -> JobView:
    try:
        job = jobs.transition(job_id, target=payload.status, actor=actor)
    except RecruitingError as exc:
        raise conflict(exc) from exc
    return JobView.from_model(job)
