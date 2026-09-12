"""FastAPI application entrypoint."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from hr_agents import __version__
from hr_agents.agents.policy_assistant import PolicyAssistant
from hr_agents.agents.runtime import AgentRuntime
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
    workspaces,
)
from hr_agents.api.routers import chat as chat_router
from hr_agents.api.routers import leave as leave_router
from hr_agents.api.routers import onboarding as onboarding_router
from hr_agents.api.routers import payroll as payroll_router
from hr_agents.api.routers import people as people_router
from hr_agents.config import Settings, get_settings
from hr_agents.db import create_sync_engine, create_sync_session_factory
from hr_agents.db.application import DbApplicationStore
from hr_agents.db.audit import DbAuditChain
from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.logging import configure_logging, get_logger
from hr_agents.services import ApplicationStore, AuditChain, JobQueue
from hr_agents.services.chat import ChatService
from hr_agents.services.front_door import FrontDoor
from hr_agents.services.people import PeopleServices
from hr_agents.services.recruiting import RecruitingServices
from hr_agents.services.workspace_requests import HandoffService
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import (
    ToolRegistry,
    make_canonicalize_skill_tool,
    make_search_knowledge_tool,
)
from hr_agents.workspaces import default_registry

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


async def _build_chat(app: FastAPI) -> None:
    """Build the Ask HR service; degrade quietly when the knowledge base is absent."""
    audit = getattr(app.state, "audit", None)
    skills_root = _REPO_ROOT / "skills"
    if audit is None or not skills_root.is_dir():
        app.state.chat = None
        app.state.handoffs = None
        return
    try:
        skills = SkillRegistry(load_library(skills_root))
        retriever = await KnowledgeRetriever.build(skills.knowledge())
        registry = default_registry()
        namespaces = sorted(
            {namespace for item in registry.list_all() for namespace in item.knowledge_namespaces}
        )
        tools = ToolRegistry(audit=audit)
        tools.register(make_search_knowledge_tool(retriever, namespaces=namespaces))
        tools.register(make_canonicalize_skill_tool())
        assistant = PolicyAssistant(AgentRuntime.from_env(), skills=skills)
        app.state.chat = ChatService(
            front_door=FrontDoor(registry),
            responder=assistant,
            audit=audit,
            tools=tools,
        )
        app.state.handoffs = HandoffService(registry=registry, audit=audit)
        logger.info("chat_ready", workspaces=len(registry.list_all()))
    except Exception as exc:
        logger.warning("chat_unavailable", error=type(exc).__name__)
        app.state.chat = None
        app.state.handoffs = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: configure logging, build chat, dispose the DB engine."""
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "application_startup",
        app=settings.app_name,
        environment=settings.environment,
        version=__version__,
        store_backend=settings.store_backend,
    )
    await _build_chat(app)
    yield
    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        engine.dispose()
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


def _web_dist_path() -> Path | None:
    """The built dashboard directory, or ``None`` when the app was not built."""
    configured = os.environ.get("HRAGENTS_WEB_DIST")
    candidate = Path(configured) if configured else _REPO_ROOT / "web" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


def _mount_web_app(app: FastAPI) -> None:
    """Serve ``web/dist`` at ``/app`` with SPA fallback; no-op without a build."""
    dist = _web_dist_path()
    if dist is None:
        return
    dist_root = dist.resolve()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/app/assets", StaticFiles(directory=assets), name="web-assets")
    index = dist / "index.html"

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{path:path}", include_in_schema=False)
    def spa(path: str = "") -> FileResponse:
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(dist_root):
                return FileResponse(candidate)
        return FileResponse(index)


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

    # Persistence: in-memory by default (zero-config dev, tests); Postgres-backed
    # stores when HRAGENTS_STORE_BACKEND=postgres (ADR 0005).
    audit: AuditChain
    store: ApplicationStore
    if settings.store_backend == "postgres":
        engine = create_sync_engine(settings)
        session_factory = create_sync_session_factory(engine)
        audit = DbAuditChain(session_factory)
        store = DbApplicationStore(session_factory)
        app.state.db_engine = engine
    else:
        session_factory = None
        audit = AuditChain()
        store = ApplicationStore()

    app.state.store = store
    app.state.audit = audit
    app.state.job_queue = JobQueue()
    app.state.recruiting = RecruitingServices(
        audit=audit, applications=store, session_factory=session_factory
    )
    people_services = PeopleServices(audit=audit, session_factory=session_factory)
    app.state.people = people_services
    app.state.onboarding = people_services.onboarding
    app.state.leave = people_services.leave
    app.state.compliance = people_services.compliance
    app.state.growth = people_services.growth
    app.state.offboarding = people_services.offboarding

    app.add_exception_handler(HTTPException, _problem_response)  # type: ignore[arg-type]
    app.include_router(workspaces.router)
    app.include_router(chat_router.router)
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

    _mount_web_app(app)
    return app


app = create_app()
