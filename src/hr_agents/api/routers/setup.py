"""First-run setup: what the install still needs, and the starter action.

The mutating half is one deliberate button: creating the starter checklists and
empty rate-table shells. Identity, providers and the timezone are file
configuration written by ``scripts/setup.py`` before the server starts; a web
route cannot change them at runtime, so this surface reports them instead of
pretending to own them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from hr_agents.api.deps import ActorDep, require_permission
from hr_agents.api.setup_schemas import SetupCounts, SetupStatusView, StarterSeedView
from hr_agents.config import Settings
from hr_agents.rbac import Permission
from hr_agents.starters import seed_starters

router = APIRouter(
    prefix="/v1/setup",
    tags=["setup"],
    dependencies=[Depends(require_permission(Permission.ADMIN_MANAGE))],
)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("", response_model=SetupStatusView)
def setup_status(request: Request) -> SetupStatusView:
    settings = _settings(request)
    people = request.app.state.people
    recruiting = request.app.state.recruiting
    _, employee_total = people.employees.page_employees(limit=1, offset=0)
    tables = people.rate_tables.list_all()
    return SetupStatusView(
        app_name=settings.app_name,
        operator_name=settings.actor_name,
        timezone=settings.timezone,
        store_backend=str(settings.store_backend),
        llm_model=settings.llm_model,
        auth_configured=bool(settings.api_keys or settings.api_principals),
        counts=SetupCounts(
            employees=employee_total,
            jobs=len(recruiting.jobs.list_all()),
            onboarding_templates=len(people.onboarding.list_templates(active_only=False)),
            offboarding_templates=len(people.offboarding.list_templates(active_only=False)),
            rate_tables=len(tables),
            unverified_rate_tables=len(people.rate_tables.unverified()),
        ),
    )


@router.post("/starters", response_model=StarterSeedView)
def seed_starter_content(request: Request, actor: ActorDep) -> StarterSeedView:
    """Create the missing starter checklists and empty rate-table shells."""
    report = seed_starters(request.app.state.people, actor=actor)
    request.app.state.audit.append(
        actor=actor.audit_actor(),
        action="setup.starters_seeded",
        subject_type="setup",
        subject_id="starters",
        payload={
            "created": len(report.created),
            "skipped": len(report.skipped),
            "items": report.created,
        },
    )
    return StarterSeedView(created=report.created, skipped=report.skipped)
