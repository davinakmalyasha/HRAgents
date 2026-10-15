"""Shared FastAPI dependencies: state accessors, principals, and permissions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status

from hr_agents.api.auth import (
    current_actor,
    current_principal,
    lookup_principal,
    require_actor,
    require_permission,
)
from hr_agents.config import Settings
from hr_agents.identity import ActorRef
from hr_agents.providers.queue import QueueBackend
from hr_agents.rbac import Principal
from hr_agents.services import ApplicationStore, AuditChain
from hr_agents.services.compliance import ComplianceService
from hr_agents.services.dispatch import EvaluationDispatcher

ActorDep = Annotated[ActorRef, Depends(current_actor)]
"""The authenticated actor for a request.

Authorization stays declarative: the route already declares its permission via
``dependencies=[Depends(require_permission(...))]``, so this only answers *who*.
Splitting the two keeps the gate visible where a reviewer looks for it,
instead of hiding it inside the parameter that happens to carry the name.
"""


@dataclass(frozen=True)
class Pagination:
    """The shared limit/offset pair every paged list endpoint accepts."""

    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum items to return.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Items to skip before the slice.")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(pagination)]
"""Limits live here, not in each route: one ceiling, one default, one doc string.

A paged response always mirrors these values back inside its ``Page`` envelope,
so a client learns the effective page size from the body even when the
request omitted the parameters.
"""


def get_store(request: Request) -> ApplicationStore:
    return request.app.state.store


def get_compliance(request: Request) -> ComplianceService:
    return request.app.state.compliance


def get_audit(request: Request) -> AuditChain:
    return request.app.state.audit


def get_queue_backend(request: Request) -> QueueBackend:
    """The live queue. Absent only when startup could not reach any provider."""
    backend = getattr(request.app.state, "queue", None)
    if backend is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "no queue backend is available, so applications cannot be queued for "
                "evaluation. Check the worker's queue provider configuration."
            ),
        )
    return backend


def get_dispatcher(request: Request) -> EvaluationDispatcher:
    return request.app.state.dispatcher


def resolve_principal(api_key: str | None, settings: Settings) -> Principal:
    """Resolve the request principal from configured keys.

    Role-bound ``api_principals`` win when configured; plain ``api_keys`` are
    treated as ``hr_admin``. No configuration disables auth (local dev only).

    Thin wrapper over :mod:`hr_agents.api.auth`, kept because callers that
    resolve a key directly — CLI tooling, tests — have no ``Request`` to read
    ``request.state`` from.
    """
    principal = lookup_principal(api_key, settings)
    if principal is not None:
        return principal
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing API key",
    )


async def get_principal(request: Request) -> Principal:
    """Authenticate the request and return its principal.

    Reads the principal the middleware already resolved, so the key is not
    scanned a second time for every guarded endpoint.
    """
    return current_principal(request)


async def require_api_key(request: Request) -> Principal:
    """Backwards-compatible authentication dependency returning the principal."""
    return current_principal(request)


__all__ = [
    "ActorDep",
    "Pagination",
    "PaginationDep",
    "current_actor",
    "current_principal",
    "get_audit",
    "get_dispatcher",
    "get_principal",
    "get_queue_backend",
    "get_store",
    "lookup_principal",
    "pagination",
    "require_actor",
    "require_api_key",
    "require_permission",
    "resolve_principal",
]
