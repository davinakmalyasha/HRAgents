"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from hr_agents import __version__
from hr_agents.api.routers import (
    applications,
    compliance,
    documents,
    evaluations,
    feedback,
    growth,
    jobs,
    offboarding,
    queue,
    scheduling,
)
from hr_agents.api.routers import leave as leave_router
from hr_agents.api.routers import onboarding as onboarding_router
from hr_agents.api.routers import payroll as payroll_router
from hr_agents.api.routers import people as people_router
from hr_agents.config import Settings, get_settings
from hr_agents.logging import configure_logging, get_logger
from hr_agents.services import ApplicationStore, AuditChain, JobQueue
from hr_agents.services.people import PeopleServices
from hr_agents.services.recruiting import RecruitingServices

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: configure logging and announce startup."""
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "application_startup",
        app=settings.app_name,
        environment=settings.environment,
        version=__version__,
    )
    yield
    logger.info("application_shutdown", app=settings.app_name)


def _problem_response(request: Request, exc: HTTPException) -> JSONResponse:
    """RFC 7807 problem+json error representation."""
    return JSONResponse(
        status_code=exc.status_code,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": str(exc.detail),
            "status": exc.status_code,
            "instance": request.url.path,
        },
        headers=exc.headers,
    )


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        description=(
            "Deterministic, auditable multi-agent candidate evaluation engine. "
            "LLM agents extract evidence; scoring is deterministic; humans gate "
            "every consequential negative decision."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    # Process-local state; replaced with Postgres/Redis-backed adapters in the
    # integrations phase through the same interfaces.
    audit = AuditChain()
    store = ApplicationStore()
    people_services = PeopleServices()
    app.state.store = store
    app.state.audit = audit
    app.state.job_queue = JobQueue()
    app.state.recruiting = RecruitingServices(audit=audit, applications=store)
    app.state.people = people_services
    app.state.onboarding = people_services.onboarding
    app.state.leave = people_services.leave
    app.state.compliance = people_services.compliance
    app.state.growth = people_services.growth
    app.state.offboarding = people_services.offboarding

    app.add_exception_handler(HTTPException, _problem_response)  # type: ignore[arg-type]
    app.include_router(applications.router)
    app.include_router(queue.router)
    app.include_router(documents.router)
    app.include_router(jobs.router)
    app.include_router(evaluations.router)
    app.include_router(feedback.router)
    app.include_router(scheduling.router)
    app.include_router(people_router.employees_router)
    app.include_router(people_router.contracts_router)
    app.include_router(people_router.approvals_router)
    app.include_router(people_router.tasks_router)
    app.include_router(people_router.rate_tables_router)
    app.include_router(onboarding_router.router)
    app.include_router(leave_router.router)
    app.include_router(payroll_router.router)
    app.include_router(compliance.router)
    app.include_router(growth.router)
    app.include_router(offboarding.router)

    @app.get("/healthz", tags=["system"], summary="Liveness probe")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "environment": settings.environment,
        }

    return app


app = create_app()
