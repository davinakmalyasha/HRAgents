"""FastAPI application entrypoint."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from hr_agents import __version__
from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agentset import AgentSet, KnowledgeUnavailableError, build_agent_set
from hr_agents.api.hardening import install_hardening, readiness_report
from hr_agents.api.metrics import PROMETHEUS_CONTENT_TYPE
from hr_agents.api.metrics import render as render_metrics
from hr_agents.api.problem import (
    ERROR_RESPONSES,
    PROBLEM_MEDIA_TYPE,
    ProblemCode,
    ProblemDetail,
    problem_uri,
)
from hr_agents.api.routers import (
    applications,
    communications,
    compliance,
    documents,
    evaluations,
    feedback,
    growth,
    jobs,
    offboarding,
    offers,
    queue,
    scheduling,
    session,
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
from hr_agents.db.messaging import candidate_directory, reply_store
from hr_agents.db.workspace import DbConversationStore, DbWorkspaceRequestStore
from hr_agents.logging import configure_logging, get_logger
from hr_agents.messaging import MessagingServices, build_email_receiver, build_email_sender
from hr_agents.models import ApproverRole
from hr_agents.queue import QueueUnavailableError, resolve_queue_backend
from hr_agents.rbac import validate_approver_coverage
from hr_agents.services import ApplicationStore, AuditChain
from hr_agents.services.chat import ChatService, ConversationStore
from hr_agents.services.dispatch import EvaluationDispatcher, UndispatchedDispatcher
from hr_agents.services.front_door import FrontDoor
from hr_agents.services.people import PeopleServices
from hr_agents.services.recruiting import RecruitingServices
from hr_agents.services.workspace_requests import HandoffService, WorkspaceRequestStore
from hr_agents.workspaces import default_registry

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


async def _build_agents(app: FastAPI) -> AgentSet | None:
    """Build every agent from the skills library, or explain why we cannot."""
    audit = getattr(app.state, "audit", None)
    if audit is None:
        return None
    try:
        agent_set = await build_agent_set(
            audit=audit,
            runtime=AgentRuntime.from_env(),
            skills_root=get_settings().skills_root,
        )
    except KnowledgeUnavailableError as exc:
        # Loud, because a missing skills root means every agent silently runs
        # without its runbooks. In a container this is a truncated image.
        logger.error("skills_unavailable", error=str(exc))
        app.state.skills_error = str(exc)
        return None
    logger.info(
        "agents_ready",
        agents=list(agent_set.agent_names),
        namespaces=len(agent_set.namespaces),
        skills=len(agent_set.skills),
    )
    return agent_set


async def _build_chat(app: FastAPI, agents: AgentSet | None) -> None:
    """Build the Ask HR service from the already-built agent set."""
    if agents is None:
        app.state.chat = None
        app.state.handoffs = None
        return
    try:
        registry = default_registry()
        session_factory: sessionmaker[Session] | None = getattr(app.state, "session_factory", None)
        if session_factory is None:
            conversations: ConversationStore = ConversationStore()
            requests: WorkspaceRequestStore = WorkspaceRequestStore()
        else:
            conversations = DbConversationStore(session_factory)
            requests = DbWorkspaceRequestStore(session_factory)
        app.state.chat = ChatService(
            front_door=FrontDoor(registry),
            responder=agents.policy,
            audit=app.state.audit,
            tools=agents.tools,
            conversations=conversations,
        )
        app.state.handoffs = HandoffService(
            registry=registry, audit=app.state.audit, store=requests
        )
        logger.info("chat_ready", workspaces=len(registry.list_all()))
    except Exception as exc:
        logger.warning("chat_unavailable", error=type(exc).__name__, detail=str(exc))
        app.state.chat = None
        app.state.handoffs = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: configure logging, build agents + queue, dispose the DB."""
    settings: Settings = getattr(app.state, "settings", None) or get_settings()
    configure_logging(settings.log_level)
    validate_approver_coverage(ApproverRole)
    logger.info(
        "application_startup",
        app=settings.app_name,
        environment=settings.environment,
        version=__version__,
        store_backend=settings.store_backend,
        scoring_runs=settings.scoring_runs,
    )
    agents = await _build_agents(app)
    app.state.agents = agents
    await _build_chat(app, agents)

    try:
        app.state.queue = await resolve_queue_backend()
        app.state.dispatcher = EvaluationDispatcher(
            queue=app.state.queue, documents=app.state.recruiting.documents
        )
        logger.info("queue_ready", backend=type(app.state.queue).__name__)
    except QueueUnavailableError as exc:
        # Submissions still persist, but nothing will evaluate them. Readiness
        # reports the outage rather than a green "ok".
        logger.error("queue_unavailable", error=str(exc))
        app.state.queue = None
        app.state.dispatcher = UndispatchedDispatcher(str(exc))

    yield
    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        engine.dispose()
    logger.info("application_shutdown", app=settings.app_name)


def _problem_response(request: Request, exc: HTTPException) -> JSONResponse:
    """RFC 7807 problem+json, carrying a stable ``code`` where one is known.

    A bare ``HTTPException`` has no code, so it gets `ProblemCode.INTERNAL`'s sibling
    `about:blank` type and a null ``code`` -- the RFC's default for "we do not describe
    this one yet". `ApiProblem` raise-sites supply a real code.
    """
    code: ProblemCode | None = getattr(exc, "code", None)
    return JSONResponse(
        status_code=exc.status_code,
        media_type=PROBLEM_MEDIA_TYPE,
        content={
            "type": problem_uri(code) if code is not None else "about:blank",
            "title": str(exc.detail),
            "status": exc.status_code,
            "detail": str(exc.detail),
            "instance": request.url.path,
            "code": code.value if code is not None else None,
        },
        headers=exc.headers,
    )


def _validation_problem_response(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422, expressed as a problem document.

    FastAPI's default 422 was the only structured error the API produced, and it was not
    a problem document at all: no ``status``, no ``type``, no ``instance``, and served as
    ``application/json``. ``detail`` stays the *list* of per-field errors -- fourteen API
    tests assert that shape, and it is genuinely the most useful thing in the response --
    so this adds the problem envelope without changing the payload clients already read.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        media_type=PROBLEM_MEDIA_TYPE,
        content={
            "type": problem_uri(ProblemCode.VALIDATION_FAILED),
            "title": "request body failed validation",
            "status": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "detail": exc.errors(),
            "instance": request.url.path,
            "code": ProblemCode.VALIDATION_FAILED.value,
        },
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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory.

    ``settings`` is injectable so the app and its middleware provably share one
    instance. Tests configure a role-bound key set by passing settings here
    rather than monkeypatching a module global, which is how the pre-middleware
    code had to be tested and why the auth lookup could drift between the
    request path and the limiter.
    """
    settings = settings or get_settings()
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
    # Published so the chat/handoff stores, which are built later in the lifespan,
    # can reach the same factory. Without it they had no way to be durable: they
    # held their state in dicts and a restart emptied the Ask HR transcript.
    app.state.session_factory = session_factory

    app.state.store = store
    app.state.audit = audit
    app.state.settings = settings
    # Filled in by the lifespan: agents, queue, dispatcher. Pre-seeded so that
    # requests served before startup completes, and tests that skip the lifespan,
    # see the same degraded shape instead of an AttributeError.
    app.state.agents = None
    app.state.skills_error = None
    app.state.queue = None
    app.state.chat = None
    app.state.handoffs = None
    # People first: its approval engine is shared with recruiting so pending
    # scheduling confirmations surface in the same queues (and the same store).
    people_services = PeopleServices(audit=audit, session_factory=session_factory)
    app.state.recruiting = RecruitingServices(
        audit=audit,
        applications=store,
        session_factory=session_factory,
        approvals=people_services.approvals,
    )
    app.state.people = people_services
    app.state.onboarding = people_services.onboarding
    app.state.leave = people_services.leave
    app.state.compliance = people_services.compliance
    app.state.growth = people_services.growth
    app.state.offboarding = people_services.offboarding
    # Messaging transports are resolved here so the API, the worker CLI, and the
    # scheduler all read the same provider configuration. With the sandbox on
    # (the default) no transport is active: queued messages stay queued.
    app.state.messaging = MessagingServices(
        sender=build_email_sender(settings=settings),
        receiver=build_email_receiver(settings=settings),
        replies=reply_store(session_factory),
        directory=candidate_directory(session_factory),
        live=not settings.messaging_sandbox,
    )
    app.state.dispatcher = UndispatchedDispatcher(
        "queue backend is not resolved yet; the application lifespan must run"
    )

    app.add_exception_handler(HTTPException, _problem_response)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        _validation_problem_response,  # type: ignore[arg-type]
    )
    install_hardening(app, settings)
    app.include_router(workspaces.router, responses=ERROR_RESPONSES)
    app.include_router(chat_router.router, responses=ERROR_RESPONSES)
    app.include_router(applications.router, responses=ERROR_RESPONSES)
    app.include_router(queue.router, responses=ERROR_RESPONSES)
    app.include_router(documents.router, responses=ERROR_RESPONSES)
    app.include_router(jobs.router, responses=ERROR_RESPONSES)
    app.include_router(evaluations.router, responses=ERROR_RESPONSES)
    app.include_router(feedback.router, responses=ERROR_RESPONSES)
    app.include_router(scheduling.router, responses=ERROR_RESPONSES)
    app.include_router(communications.router, responses=ERROR_RESPONSES)
    app.include_router(offers.router, responses=ERROR_RESPONSES)
    app.include_router(people_router.employees_router, responses=ERROR_RESPONSES)
    app.include_router(people_router.org_units_router, responses=ERROR_RESPONSES)
    app.include_router(people_router.documents_router, responses=ERROR_RESPONSES)
    app.include_router(people_router.contracts_router, responses=ERROR_RESPONSES)
    app.include_router(people_router.approvals_router, responses=ERROR_RESPONSES)
    app.include_router(people_router.tasks_router, responses=ERROR_RESPONSES)
    app.include_router(people_router.rate_tables_router, responses=ERROR_RESPONSES)
    app.include_router(onboarding_router.router, responses=ERROR_RESPONSES)
    app.include_router(leave_router.router, responses=ERROR_RESPONSES)
    app.include_router(payroll_router.router, responses=ERROR_RESPONSES)
    app.include_router(compliance.router, responses=ERROR_RESPONSES)
    app.include_router(growth.router, responses=ERROR_RESPONSES)
    app.include_router(offboarding.router, responses=ERROR_RESPONSES)
    app.include_router(session.router, responses=ERROR_RESPONSES)

    @app.get("/healthz", tags=["system"], summary="Liveness probe")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "environment": settings.environment,
        }

    @app.get("/readyz", tags=["system"], summary="Readiness probe (dependencies)")
    async def readyz() -> JSONResponse:
        report = readiness_report(app)
        code = 200 if report["status"] == "ok" else 503
        return JSONResponse(status_code=code, content={**report, "version": __version__})

    @app.get(
        "/metrics",
        tags=["system"],
        summary="Prometheus metrics (text format)",
        include_in_schema=False,
    )
    async def metrics() -> Response:
        return Response(content=render_metrics(app), media_type=PROMETHEUS_CONTENT_TYPE)

    _mount_web_app(app)
    _register_problem_schemas(app)
    return app


def _register_problem_schemas(app: FastAPI) -> None:
    """Put `ProblemDetail` and `ProblemCode` in the document's components.

    `ERROR_RESPONSES` declares each error with an explicit `$ref` rather than FastAPI's
    `model` shorthand, because the shorthand registers the schema under
    `application/json` -- which would contradict the media type the server actually uses
    and leave a client branching on it treating every error as unrecognised.

    The cost of spelling the content out is that FastAPI no longer infers the schemas, so
    they are added here. Doing it in one place keeps `ERROR_RESPONSES` free of
    openapi-typescript-specific plumbing.
    """

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.setdefault(
            ProblemDetail.__name__,
            ProblemDetail.model_json_schema(
                ref_template="#/components/schemas/{model}", mode="validation"
            ),
        )
        components.setdefault(
            ProblemCode.__name__,
            {
                "type": "string",
                "enum": [code.value for code in ProblemCode],
                "description": (
                    "Machine-readable error kinds. Switch on this rather than on the "
                    "prose in `title`, which may be reworded."
                ),
            },
        )
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


app = create_app()
