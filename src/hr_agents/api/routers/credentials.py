"""Credential registries: the operator's verified rows.

An extracted certificate is a claim. The registry is where a named human records
what the issuer actually confirmed, with its source; scoring only trusts it once
the registry is verified.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from hr_agents.api.credential_schemas import (
    CredentialEntriesUpdate,
    CredentialRegistryCreate,
    CredentialRegistryView,
    CredentialVerifyRequest,
)
from hr_agents.api.deps import ActorDep, PaginationDep, require_permission
from hr_agents.api.problem import domain_problem
from hr_agents.api.schemas import Page
from hr_agents.models import CredentialEntry
from hr_agents.rbac import Permission
from hr_agents.services.credentials import (
    CredentialRegistryError,
    CredentialRegistryService,
)

router = APIRouter(
    prefix="/v1/credentials",
    tags=["credentials"],
    dependencies=[Depends(require_permission(Permission.ADMIN_MANAGE))],
)


def get_credentials(request: Request) -> CredentialRegistryService:
    return request.app.state.people.credentials


CredentialsDep = Annotated[CredentialRegistryService, Depends(get_credentials)]


@router.get("", response_model=Page[CredentialRegistryView])
def list_registries(
    credentials: CredentialsDep, paging: PaginationDep
) -> Page[CredentialRegistryView]:
    items = [CredentialRegistryView.from_model(item) for item in credentials.list_all()]
    return Page.of(
        items[paging.offset : paging.offset + paging.limit],
        total=len(items),
        limit=paging.limit,
        offset=paging.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CredentialRegistryView,
    summary="Create an empty, unverified registry for one issuer",
)
def create_registry(
    payload: CredentialRegistryCreate, credentials: CredentialsDep, actor: ActorDep
) -> CredentialRegistryView:
    registry = credentials.create(name=payload.name, issuer=payload.issuer, actor=actor)
    return CredentialRegistryView.from_model(registry)


@router.get("/{registry_id}", response_model=CredentialRegistryView)
def get_registry(registry_id: UUID, credentials: CredentialsDep) -> CredentialRegistryView:
    try:
        registry = credentials.require(registry_id)
    except CredentialRegistryError as exc:
        raise domain_problem(exc) from exc
    return CredentialRegistryView.from_model(registry)


@router.put(
    "/{registry_id}/entries",
    response_model=CredentialRegistryView,
    summary="Replace the imported rows (this invalidates verification)",
)
def set_entries(
    registry_id: UUID,
    payload: CredentialEntriesUpdate,
    credentials: CredentialsDep,
    actor: ActorDep,
) -> CredentialRegistryView:
    try:
        registry = credentials.set_entries(
            registry_id,
            entries=[CredentialEntry(**entry.model_dump()) for entry in payload.entries],
            actor=actor,
        )
    except CredentialRegistryError as exc:
        raise domain_problem(exc) from exc
    return CredentialRegistryView.from_model(registry)


@router.post(
    "/{registry_id}/verify",
    response_model=CredentialRegistryView,
    summary="Certify the rows with a named human and a source",
)
def verify_registry(
    registry_id: UUID,
    payload: CredentialVerifyRequest,
    credentials: CredentialsDep,
    actor: ActorDep,
) -> CredentialRegistryView:
    try:
        registry = credentials.verify(registry_id, actor=actor, source_note=payload.source_note)
    except CredentialRegistryError as exc:
        raise domain_problem(exc) from exc
    return CredentialRegistryView.from_model(registry)
