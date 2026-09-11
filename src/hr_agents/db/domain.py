"""Postgres-backed compliance, growth, and offboarding stores.

Thin adapters over the generic mapping helpers; retention policies additionally
upsert by entity (one active policy per entity, matching the service contract).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import compliance_tables as ct
from hr_agents.db import growth_tables as gt
from hr_agents.db import offboarding_tables as ot
from hr_agents.db.mapping import add_model, get_model, list_models, model_from_row, save_model
from hr_agents.db.session import sync_session_scope
from hr_agents.models import (
    BreachIncident,
    ConsentGrant,
    ErasureRequest,
    Goal,
    OffboardingAsset,
    OffboardingPlan,
    OffboardingTemplate,
    RecordEntity,
    RetentionPolicy,
    RetentionRecord,
    ReviewAssignment,
    ReviewCycle,
    ReviewSummary,
)
from hr_agents.services.people_store import (
    ComplianceStore,
    GrowthStore,
    OffboardingStore,
)


class DbComplianceStore(ComplianceStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    # consent
    def add_consent(self, consent: ConsentGrant) -> None:
        add_model(self._session_factory, consent, ct.ConsentRecordTable)

    def save_consent(self, consent: ConsentGrant) -> None:
        save_model(self._session_factory, consent, ct.ConsentRecordTable)

    def get_consent(self, consent_id: UUID) -> ConsentGrant | None:
        return get_model(self._session_factory, ConsentGrant, ct.ConsentRecordTable, consent_id)

    def list_consents(self) -> list[ConsentGrant]:
        consents = list_models(self._session_factory, ConsentGrant, ct.ConsentRecordTable)
        return sorted(consents, key=lambda item: item.granted_at)

    # retention policies (one active policy per entity)
    def save_policy(self, policy: RetentionPolicy) -> None:
        with sync_session_scope(self._session_factory) as session:
            existing = session.execute(
                select(ct.RetentionPolicyTable).where(
                    ct.RetentionPolicyTable.entity == policy.entity.value
                )
            ).scalar_one_or_none()
            if existing is not None and existing.id != policy.id:
                session.delete(existing)
                session.flush()
        stored = get_model(
            self._session_factory, RetentionPolicy, ct.RetentionPolicyTable, policy.id
        )
        if stored is None:
            add_model(self._session_factory, policy, ct.RetentionPolicyTable)
        else:
            save_model(self._session_factory, policy, ct.RetentionPolicyTable)

    def get_policy(self, entity: RecordEntity) -> RetentionPolicy | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(ct.RetentionPolicyTable).where(
                    ct.RetentionPolicyTable.entity == entity.value
                )
            ).scalar_one_or_none()
            return None if row is None else model_from_row(RetentionPolicy, row)

    def list_policies(self) -> list[RetentionPolicy]:
        policies = list_models(self._session_factory, RetentionPolicy, ct.RetentionPolicyTable)
        return sorted(policies, key=lambda item: item.entity.value)

    # retention records
    def add_record(self, record: RetentionRecord) -> None:
        add_model(self._session_factory, record, ct.RetentionRecordTable)

    def save_record(self, record: RetentionRecord) -> None:
        save_model(self._session_factory, record, ct.RetentionRecordTable)

    def get_record(self, record_id: UUID) -> RetentionRecord | None:
        return get_model(self._session_factory, RetentionRecord, ct.RetentionRecordTable, record_id)

    def list_records(self) -> list[RetentionRecord]:
        records = list_models(self._session_factory, RetentionRecord, ct.RetentionRecordTable)
        return sorted(records, key=lambda item: item.anchor_at)

    # erasure requests
    def add_erasure(self, request: ErasureRequest) -> None:
        add_model(self._session_factory, request, ct.ErasureRequestTable)

    def save_erasure(self, request: ErasureRequest) -> None:
        save_model(self._session_factory, request, ct.ErasureRequestTable)

    def get_erasure(self, request_id: UUID) -> ErasureRequest | None:
        return get_model(self._session_factory, ErasureRequest, ct.ErasureRequestTable, request_id)

    def list_erasures(self) -> list[ErasureRequest]:
        requests = list_models(self._session_factory, ErasureRequest, ct.ErasureRequestTable)
        return sorted(requests, key=lambda item: item.received_at)

    # breach incidents
    def add_incident(self, incident: BreachIncident) -> None:
        add_model(self._session_factory, incident, ct.BreachIncidentTable)

    def save_incident(self, incident: BreachIncident) -> None:
        save_model(self._session_factory, incident, ct.BreachIncidentTable)

    def get_incident(self, incident_id: UUID) -> BreachIncident | None:
        return get_model(self._session_factory, BreachIncident, ct.BreachIncidentTable, incident_id)

    def list_incidents(self) -> list[BreachIncident]:
        incidents = list_models(self._session_factory, BreachIncident, ct.BreachIncidentTable)
        return sorted(incidents, key=lambda item: item.discovered_at)


class DbGrowthStore(GrowthStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add_cycle(self, cycle: ReviewCycle) -> None:
        add_model(self._session_factory, cycle, gt.ReviewCycleRecord)

    def save_cycle(self, cycle: ReviewCycle) -> None:
        save_model(self._session_factory, cycle, gt.ReviewCycleRecord)

    def get_cycle(self, cycle_id: UUID) -> ReviewCycle | None:
        return get_model(self._session_factory, ReviewCycle, gt.ReviewCycleRecord, cycle_id)

    def list_cycles(self) -> list[ReviewCycle]:
        cycles = list_models(self._session_factory, ReviewCycle, gt.ReviewCycleRecord)
        return sorted(cycles, key=lambda item: item.created_at)

    def add_assignment(self, assignment: ReviewAssignment) -> None:
        add_model(self._session_factory, assignment, gt.ReviewAssignmentRecord)

    def save_assignment(self, assignment: ReviewAssignment) -> None:
        save_model(self._session_factory, assignment, gt.ReviewAssignmentRecord)

    def get_assignment(self, assignment_id: UUID) -> ReviewAssignment | None:
        return get_model(
            self._session_factory, ReviewAssignment, gt.ReviewAssignmentRecord, assignment_id
        )

    def list_assignments(self) -> list[ReviewAssignment]:
        assignments = list_models(
            self._session_factory, ReviewAssignment, gt.ReviewAssignmentRecord
        )
        return sorted(assignments, key=lambda item: item.created_at)

    def add_summary(self, summary: ReviewSummary) -> None:
        add_model(self._session_factory, summary, gt.ReviewSummaryRecord)

    def save_summary(self, summary: ReviewSummary) -> None:
        save_model(self._session_factory, summary, gt.ReviewSummaryRecord)

    def get_summary(self, summary_id: UUID) -> ReviewSummary | None:
        return get_model(self._session_factory, ReviewSummary, gt.ReviewSummaryRecord, summary_id)

    def list_summaries(self) -> list[ReviewSummary]:
        summaries = list_models(self._session_factory, ReviewSummary, gt.ReviewSummaryRecord)
        return sorted(summaries, key=lambda item: item.created_at)

    def add_goal(self, goal: Goal) -> None:
        add_model(self._session_factory, goal, gt.GoalRecord)

    def save_goal(self, goal: Goal) -> None:
        save_model(self._session_factory, goal, gt.GoalRecord)

    def get_goal(self, goal_id: UUID) -> Goal | None:
        return get_model(self._session_factory, Goal, gt.GoalRecord, goal_id)

    def list_goals(self) -> list[Goal]:
        goals = list_models(self._session_factory, Goal, gt.GoalRecord)
        return sorted(goals, key=lambda item: item.created_at)


class DbOffboardingStore(OffboardingStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add_template(self, template: OffboardingTemplate) -> None:
        add_model(self._session_factory, template, ot.OffboardingTemplateRecord)

    def get_template(self, template_id: UUID) -> OffboardingTemplate | None:
        return get_model(
            self._session_factory, OffboardingTemplate, ot.OffboardingTemplateRecord, template_id
        )

    def list_templates(self) -> list[OffboardingTemplate]:
        templates = list_models(
            self._session_factory, OffboardingTemplate, ot.OffboardingTemplateRecord
        )
        return sorted(templates, key=lambda item: item.name.lower())

    def add_plan(self, plan: OffboardingPlan) -> None:
        add_model(self._session_factory, plan, ot.OffboardingPlanRecord)

    def save_plan(self, plan: OffboardingPlan) -> None:
        save_model(self._session_factory, plan, ot.OffboardingPlanRecord)

    def get_plan(self, plan_id: UUID) -> OffboardingPlan | None:
        return get_model(self._session_factory, OffboardingPlan, ot.OffboardingPlanRecord, plan_id)

    def list_plans(self) -> list[OffboardingPlan]:
        plans = list_models(self._session_factory, OffboardingPlan, ot.OffboardingPlanRecord)
        return sorted(plans, key=lambda item: item.started_at)

    def add_asset(self, asset: OffboardingAsset) -> None:
        add_model(self._session_factory, asset, ot.OffboardingAssetRecord)

    def save_asset(self, asset: OffboardingAsset) -> None:
        save_model(self._session_factory, asset, ot.OffboardingAssetRecord)

    def get_asset(self, asset_id: UUID) -> OffboardingAsset | None:
        return get_model(
            self._session_factory, OffboardingAsset, ot.OffboardingAssetRecord, asset_id
        )

    def list_assets(self) -> list[OffboardingAsset]:
        assets = list_models(self._session_factory, OffboardingAsset, ot.OffboardingAssetRecord)
        return sorted(assets, key=lambda item: item.created_at)
