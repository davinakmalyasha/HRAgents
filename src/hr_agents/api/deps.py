"""Shared FastAPI dependencies: state accessors and authentication."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from hr_agents.config import get_settings
from hr_agents.services import ApplicationStore, AuditChain, JobQueue


def get_store(request: Request) -> ApplicationStore:
    return request.app.state.store


def get_audit(request: Request) -> AuditChain:
    return request.app.state.audit


def get_queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Enforce API-key auth when keys are configured.

    Empty key configuration disables authentication (local development only);
    production deployments must set HRAGENTS_API_KEYS.
    """
    configured = get_settings().api_keys
    if not configured:
        return
    if x_api_key is None or x_api_key not in configured:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )
