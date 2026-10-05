"""Postgres-backed onboarding store.

Implements only the primitives ``OnboardingService`` exposes. Waiver rules, gate
enforcement, document auto-completion and the template version hash all stay in the
service class.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.onboarding_tables import OnboardingPlanRecord, OnboardingTemplateRecord
from hr_agents.db.session import sync_session_scope
from hr_agents.models.onboarding import (
    OnboardingPlan,
    OnboardingStepState,
    OnboardingTemplate,
    TemplateStep,
)
from hr_agents.services.onboarding import OnboardingService


def _aware(moment: datetime) -> datetime:
    """Stamp a naive datetime as UTC; SQLite drops the tzinfo SQLite has no zone."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _optional_aware(moment: datetime | None) -> datetime | None:
    return None if moment is None else _aware(moment)


class DbOnboardingService(OnboardingService):
    """Durable onboarding templates and plans on the ``onboarding_*`` tables."""

    def __init__(self, session_factory: sessionmaker[Session], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._session_factory = session_factory

    # --- templates -------------------------------------------------------

    def _load_template(self, template_id: UUID) -> OnboardingTemplate | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(OnboardingTemplateRecord, template_id)
            return None if row is None else self._to_template(row)

    def _iter_templates(self) -> Iterator[OnboardingTemplate]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(OnboardingTemplateRecord)).scalars().all()
            return iter([self._to_template(row) for row in rows])

    def _save_template(self, template: OnboardingTemplate) -> None:
        with sync_session_scope(self._session_factory) as session:
            existing = session.get(OnboardingTemplateRecord, template.id)
            values = {
                "name": template.name,
                "description": template.description,
                "applies_to_contract_types": list(template.applies_to_contract_types),
                "applies_to_roles": list(template.applies_to_roles),
                "steps": [step.model_dump(mode="json") for step in template.steps],
                "active": template.active,
                "created_at": _aware(template.created_at),
                "updated_at": _aware(template.updated_at),
            }
            if existing is None:
                session.add(OnboardingTemplateRecord(id=template.id, **values))
            else:
                for column, value in values.items():
                    setattr(existing, column, value)

    @staticmethod
    def _to_template(row: OnboardingTemplateRecord) -> OnboardingTemplate:
        return OnboardingTemplate(
            id=row.id,
            name=row.name,
            description=row.description,
            applies_to_contract_types=list(row.applies_to_contract_types),
            applies_to_roles=list(row.applies_to_roles),
            steps=[TemplateStep.model_validate(step) for step in row.steps],
            active=row.active,
            created_at=_aware(row.created_at),
            updated_at=_aware(row.updated_at),
        )

    # --- plans -----------------------------------------------------------

    def _load_plan(self, plan_id: UUID) -> OnboardingPlan | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(OnboardingPlanRecord, plan_id)
            return None if row is None else self._to_plan(row)

    def _iter_plans(self) -> Iterator[OnboardingPlan]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(OnboardingPlanRecord)).scalars().all()
            # Materialised inside the session: a lazy iterator would read through a
            # closed session. `active_plans` filters on the derived `is_complete`,
            # so the whole tenant's plans are read and the filter stays in Python --
            # which is also why `completed_at` is indexed for that read.
            return iter([self._to_plan(row) for row in rows])

    def _save_plan(self, plan: OnboardingPlan) -> None:
        with sync_session_scope(self._session_factory) as session:
            existing = session.get(OnboardingPlanRecord, plan.id)
            values = {
                "employee_id": plan.employee_id,
                "template_id": plan.template_id,
                "template_name": plan.template_name,
                "template_version_hash": plan.template_version_hash,
                "steps": [step.model_dump(mode="json") for step in plan.steps],
                "started_at": _aware(plan.started_at),
                "completed_at": _optional_aware(plan.completed_at),
            }
            if existing is None:
                session.add(OnboardingPlanRecord(id=plan.id, **values))
            else:
                for column, value in values.items():
                    setattr(existing, column, value)

    @staticmethod
    def _to_plan(row: OnboardingPlanRecord) -> OnboardingPlan:
        return OnboardingPlan(
            id=row.id,
            employee_id=row.employee_id,
            template_id=row.template_id,
            template_name=row.template_name,
            template_version_hash=row.template_version_hash,
            steps=[OnboardingStepState.model_validate(step) for step in row.steps],
            started_at=_aware(row.started_at),
            completed_at=_optional_aware(row.completed_at),
        )
