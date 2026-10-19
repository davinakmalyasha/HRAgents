"""Versioned scoring rubrics: list, draft, verify, activate."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from hr_agents.api.deps import ActorDep, PaginationDep, require_permission
from hr_agents.api.problem import domain_problem
from hr_agents.api.rubric_schemas import (
    RubricFamilyView,
    RubricVerifyRequest,
    RubricVersionView,
)
from hr_agents.api.schemas import Page
from hr_agents.models import JobFamily
from hr_agents.rbac import Permission
from hr_agents.services.dimensions import (
    DimensionTemplate,
    families,
    rubric_digest,
    template_for,
)
from hr_agents.services.rubrics import RubricError, RubricRegistry

router = APIRouter(
    prefix="/v1/rubrics",
    tags=["rubrics"],
    dependencies=[Depends(require_permission(Permission.RECRUITING_READ))],
)


def get_rubrics(request: Request) -> RubricRegistry:
    return request.app.state.recruiting.rubrics


RubricsDep = Annotated[RubricRegistry, Depends(get_rubrics)]


@router.get("", response_model=Page[RubricFamilyView])
def list_rubrics(rubrics: RubricsDep, paging: PaginationDep) -> Page[RubricFamilyView]:
    """Which rubric scores each family, and whether it is code or a stored version."""
    items: list[RubricFamilyView] = []
    for family in families():
        active = rubrics.active_version(family)
        if active is None:
            items.append(
                RubricFamilyView(
                    family=family,
                    source="code",
                    digest=rubric_digest(template_for(family)),
                )
            )
        else:
            items.append(
                RubricFamilyView(
                    family=family,
                    source="registry",
                    revision=active.revision,
                    digest=active.digest,
                    verified_by=active.verified_by,
                    verified_at=active.verified_at,
                )
            )
    return Page.of(
        items[paging.offset : paging.offset + paging.limit],
        total=len(items),
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/{family}/versions", response_model=Page[RubricVersionView])
def list_versions(
    family: JobFamily, rubrics: RubricsDep, paging: PaginationDep
) -> Page[RubricVersionView]:
    versions = rubrics.versions(family)
    return Page.of(
        [RubricVersionView.from_model(item) for item in versions][
            paging.offset : paging.offset + paging.limit
        ],
        total=len(versions),
        limit=paging.limit,
        offset=paging.offset,
    )


@router.post(
    "/{family}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=RubricVersionView,
    dependencies=[Depends(require_permission(Permission.RECRUITING_WRITE))],
    summary="Draft a new rubric version (unverified; nothing scores with it yet)",
)
def create_version(
    family: JobFamily,
    payload: DimensionTemplate,
    rubrics: RubricsDep,
    actor: ActorDep,
) -> RubricVersionView:
    try:
        record = rubrics.create_version(family=family, template=payload, actor=actor)
    except RubricError as exc:
        raise domain_problem(exc) from exc
    return RubricVersionView.from_model(record)


@router.post(
    "/versions/{version_id}/verify",
    response_model=RubricVersionView,
    dependencies=[Depends(require_permission(Permission.RUBRICS_VERIFY))],
    summary="Certify a version with a named human and a source note",
)
def verify_version(
    version_id: UUID,
    payload: RubricVerifyRequest,
    rubrics: RubricsDep,
    actor: ActorDep,
) -> RubricVersionView:
    try:
        record = rubrics.verify(version_id, actor=actor, source_note=payload.source_note)
    except RubricError as exc:
        raise domain_problem(exc) from exc
    return RubricVersionView.from_model(record)


@router.post(
    "/versions/{version_id}/activate",
    response_model=RubricVersionView,
    dependencies=[Depends(require_permission(Permission.RUBRICS_VERIFY))],
    summary="Score new evaluations with this verified version",
)
def activate_version(version_id: UUID, rubrics: RubricsDep, actor: ActorDep) -> RubricVersionView:
    try:
        record = rubrics.activate(version_id, actor=actor)
    except RubricError as exc:
        raise domain_problem(exc) from exc
    return RubricVersionView.from_model(record)
