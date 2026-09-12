"""Job specification endpoints — CRUD plus a guarded status lifecycle."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from hr_agents.api.deps import require_permission
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
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
)


def get_jobs(request: Request) -> JobService:
    return request.app.state.recruiting.jobs


JobsDep = Annotated[JobService, Depends(get_jobs)]


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


@router.get("", response_model=list[JobView], summary="List job specifications")
def list_jobs(jobs: JobsDep, job_status: JobStatus | None = None) -> list[JobView]:
    return [JobView.from_model(job) for job in jobs.list_all(status=job_status)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=JobView)
def create_job(payload: JobCreate, jobs: JobsDep) -> JobView:
    try:
        job = jobs.create(**payload.model_dump())
    except (RecruitingError, ValueError) as exc:
        raise _conflict(exc) from exc
    return JobView.from_model(job)


@router.get("/{job_id}", response_model=JobView)
def get_job(job_id: UUID, jobs: JobsDep) -> JobView:
    try:
        return JobView.from_model(jobs.get(job_id))
    except RecruitingError as exc:
        raise _not_found(str(exc)) from exc


@router.patch("/{job_id}", response_model=JobView)
def update_job(job_id: UUID, payload: JobUpdate, jobs: JobsDep) -> JobView:
    try:
        job = jobs.update(job_id, **payload.model_dump())
    except (RecruitingError, ValueError) as exc:
        raise _conflict(exc) from exc
    return JobView.from_model(job)


@router.post("/{job_id}/status", response_model=JobView)
def change_job_status(job_id: UUID, payload: JobStatusChange, jobs: JobsDep) -> JobView:
    try:
        job = jobs.transition(job_id, target=payload.status, by=payload.by)
    except RecruitingError as exc:
        raise _conflict(exc) from exc
    return JobView.from_model(job)
