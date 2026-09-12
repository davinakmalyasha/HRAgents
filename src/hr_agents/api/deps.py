"""Shared FastAPI dependencies: state accessors, principals, and permissions."""

from __future__ import annotations

import secrets as secrets_module
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from hr_agents.config import Settings, get_settings
from hr_agents.rbac import Permission, Principal, RoleId, has_permission
from hr_agents.services import ApplicationStore, AuditChain, JobQueue


def get_store(request: Request) -> ApplicationStore:
    return request.app.state.store


def get_audit(request: Request) -> AuditChain:
    return request.app.state.audit


def get_queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


def resolve_principal(api_key: str | None, settings: Settings) -> Principal:
    """Resolve the request principal from configured keys.

    Role-bound ``api_principals`` win when configured; plain ``api_keys`` are
    treated as ``hr_admin``. No configuration disables auth (local dev only).
    """
    if settings.api_principals:
        if api_key is not None:
            for entry in settings.api_principals:
                if secrets_module.compare_digest(entry.key.get_secret_value(), api_key):
                    return Principal(actor_id=entry.actor_id, role=entry.role)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )

    configured = settings.api_keys
    if not configured:
        return Principal(actor_id="local-dev", role=RoleId.HR_ADMIN)
    if api_key is not None:
        for key in configured:
            if secrets_module.compare_digest(key, api_key):
                return Principal(actor_id="api-key", role=RoleId.HR_ADMIN)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing API key",
    )


async def get_principal(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    """Authenticate the request and return its principal."""
    return resolve_principal(x_api_key, get_settings())


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    """Backwards-compatible authentication dependency returning the principal."""
    return resolve_principal(x_api_key, get_settings())


def require_permission(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    """Build a dependency enforcing one permission on the authenticated role."""

    async def dependency(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> Principal:
        principal = resolve_principal(x_api_key, get_settings())
        if not has_permission(principal, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {principal.role.value} lacks permission {permission.value}",
            )
        return principal

    return dependency
