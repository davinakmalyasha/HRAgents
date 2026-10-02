"""Authentication: resolve the principal once per request.

Before this, every ``require_permission(...)`` call site built its own closure
and re-resolved the API key inside it. A request that was guarded at router
level *and* endpoint level therefore scanned the configured keys twice, and the
one place that wanted to bucket rate limits per person (``client_key`` reading
``request.state.actor_id``) had nothing to read, because a dependency runs after
all middleware.

The middleware below resolves once, before routing, and parks the result on
``request.state``. It deliberately never raises: ``/healthz``, ``/readyz``,
``/metrics``, the dashboard's static assets, and the SPA itself must answer
without credentials. Authorization stays with ``require_permission``.

Two distinct failures are preserved, because conflating them is how a client ends
up debugging the wrong thing:

- **401** — credentials were presented and refused (recorded in
  ``request.state.auth_error``).
- **403** — the principal authenticated fine but its role lacks a permission.

The key comparison stays constant-time, and a fresh key is marked
``api_key=True`` so the audit trail can distinguish a managed identity from a
self-host install that has not configured principals at all.
"""

from __future__ import annotations

import secrets as secrets_module
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from hr_agents.config import Settings, get_settings
from hr_agents.identity import ActorRef
from hr_agents.rbac import Permission, Principal, RoleId, has_permission

API_KEY_HEADER = "X-API-Key"
LOCAL_OPERATOR_ACTOR = "local-dev"


def lookup_principal(api_key: str | None, settings: Settings) -> Principal | None:
    """Resolve a principal without raising.

    Returns ``None`` when credentials were required and refused. An
    unconfigured install is not an error: it is a single local operator, and
    ``docs/deployment.md`` says plainly that this state is for localhost only.
    """
    if settings.api_principals:
        if api_key is None:
            return None
        for entry in settings.api_principals:
            if secrets_module.compare_digest(entry.key.get_secret_value(), api_key):
                return Principal(
                    actor_id=entry.actor_id, role=entry.role, employee_id=entry.employee_id
                )
        return None

    if not settings.api_keys:
        return Principal(
            actor_id=settings.actor_name or LOCAL_OPERATOR_ACTOR,
            role=RoleId.HR_ADMIN,
            api_key=False,
        )
    if api_key is None:
        return None
    for key in settings.api_keys:
        if secrets_module.compare_digest(key, api_key):
            # An unbound key carries no identity of its own: the operator shared
            # one secret, so there is no person to name. Flagged so the audit
            # trail can say that instead of implying a managed identity.
            return Principal(
                actor_id=settings.actor_name or "api-key",
                role=RoleId.HR_ADMIN,
                api_key=True,
            )
    return None


def auth_is_configured(settings: Settings) -> bool:
    return bool(settings.api_principals or settings.api_keys)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Authenticate once per request, before routing. Never rejects."""

    def __init__(self, app: ASGIApp, settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        settings = self._settings or get_settings()
        principal = lookup_principal(request.headers.get(API_KEY_HEADER), settings)
        request.state.principal = principal
        if principal is not None:
            request.state.actor_id = principal.actor_id
        else:
            request.state.auth_error = "invalid or missing API key"
        return await call_next(request)


def current_principal(request: Request) -> Principal:
    """The resolved principal, or 401 when credentials were required and refused."""
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is not None:
        return principal
    detail: str = getattr(request.state, "auth_error", "authentication required")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def current_actor(request: Request) -> ActorRef:
    """The authenticated actor as an :class:`ActorRef`.

    This is what routers hand to services instead of a body-supplied name, which
    is how the "any caller may attribute a decision to any named person" hole
    gets closed.
    """
    return ActorRef.from_principal(current_principal(request))


def require_permission(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    """Build a dependency enforcing one permission on the authenticated role.

    Purely an authorizer now: the key was already checked by the middleware, and
    a role that lacks the permission is a 403, not a 401.
    """

    async def dependency(request: Request) -> Principal:
        principal = current_principal(request)
        if not has_permission(principal, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"role {principal.role.value} lacks permission {permission.value}"),
            )
        return principal

    return dependency


def require_actor(permission: Permission) -> Callable[..., Awaitable[ActorRef]]:
    """Authorize and return the actor in one dependency, for write endpoints."""

    async def dependency(request: Request) -> ActorRef:
        check = require_permission(permission)
        await check(request)
        return current_actor(request)

    return dependency
