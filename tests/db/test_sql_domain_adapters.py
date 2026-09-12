"""Compliance, growth, and offboarding adapter tests on in-memory SQLite."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.domain import (
    DbComplianceStore,
    DbGrowthStore,
    DbOffboardingStore,
)
from hr_agents.models import (
    ApproverRole,
    BreachIncident,
    ConsentGrant,
    ErasureRequest,
    Goal,
    OffboardingAsset,
    OffboardingPlan,
    OffboardingReason,
    RecordEntity,
    RetentionPolicy,
    RetentionRecord,
    ReviewAssignment,
    ReviewCycle,
    ReviewSummary,
    SubjectKind,
)
from hr_agents.models.offboarding import (
    AssetStatus,
    OffboardingStepKind,
    OffboardingStepState,
    OffboardingTemplate,
    OffboardingTemplateStep,
)


def test_compliance_store_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbComplianceStore(factory)
    consent = ConsentGrant(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
    )
    store.add_consent(consent)

    loaded = DbComplianceStore(factory).get_consent(consent.id)
    assert loaded is not None
    assert loaded.subject_id == "cand-1"
    loaded.revoked_at = datetime.now(UTC)
    loaded.revoked_reason = "withdrawn"
    DbComplianceStore(factory).save_consent(loaded)
    revoked = DbComplianceStore(factory).get_consent(consent.id)
    assert revoked is not None
    assert revoked.revoked_reason == "withdrawn"

    policy = RetentionPolicy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
    )
    store.save_policy(policy)
    stored = DbComplianceStore(factory).get_policy(RecordEntity.CANDIDATE)
    assert stored is not None
    assert stored.retention_months == 24

    replacement = RetentionPolicy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records v2",
        retention_months=12,
        updated_by="hr-admin",
    )
    DbComplianceStore(factory).save_policy(replacement)
    policies = DbComplianceStore(factory).list_policies()
    assert [item.id for item in policies] == [replacement.id]
    assert policies[0].retention_months == 12

    record = RetentionRecord(
        entity=RecordEntity.CANDIDATE,
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
    )
    store.add_record(record)
    assert [item.id for item in DbComplianceStore(factory).list_records()] == [record.id]

    erasure = ErasureRequest(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        reason="UU PDP request",
        requested_by="hr-admin",
    )
    store.add_erasure(erasure)
    loaded_erasure = DbComplianceStore(factory).get_erasure(erasure.id)
    assert loaded_erasure is not None
    loaded_erasure.reason = "Verified UU PDP request"
    DbComplianceStore(factory).save_erasure(loaded_erasure)
    assert DbComplianceStore(factory).list_erasures()[0].reason == "Verified UU PDP request"

    incident = BreachIncident(
        title="Laptop lost",
        discovered_by="it-ops",
        template_name="default_incident_checklist",
    )
    store.add_incident(incident)
    loaded_incident = DbComplianceStore(factory).get_incident(incident.id)
    assert loaded_incident is not None
    assert loaded_incident.title == "Laptop lost"
    assert [item.id for item in DbComplianceStore(factory).list_incidents()] == [incident.id]


def test_growth_store_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbGrowthStore(factory)
    cycle = ReviewCycle(
        name="2026 H1",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        created_by="hr-admin",
    )
    store.add_cycle(cycle)
    loaded_cycle = DbGrowthStore(factory).get_cycle(cycle.id)
    assert loaded_cycle is not None
    loaded_cycle.description = "First half"
    DbGrowthStore(factory).save_cycle(loaded_cycle)
    assert DbGrowthStore(factory).list_cycles()[0].description == "First half"

    assignment = ReviewAssignment(
        cycle_id=cycle.id,
        employee_id=uuid4(),
        reviewer_id="lead-1",
    )
    store.add_assignment(assignment)
    loaded_assignment = DbGrowthStore(factory).get_assignment(assignment.id)
    assert loaded_assignment is not None
    loaded_assignment.comments = "Strong delivery"
    DbGrowthStore(factory).save_assignment(loaded_assignment)
    assert DbGrowthStore(factory).list_assignments()[0].comments == "Strong delivery"

    summary = ReviewSummary(cycle_id=cycle.id, employee_id=assignment.employee_id)
    store.add_summary(summary)
    loaded_summary = DbGrowthStore(factory).get_summary(summary.id)
    assert loaded_summary is not None
    loaded_summary.agent_draft = "Draft summary"
    DbGrowthStore(factory).save_summary(loaded_summary)
    assert DbGrowthStore(factory).list_summaries()[0].agent_draft == "Draft summary"

    goal = Goal(employee_id=assignment.employee_id, title="Ship v2", created_by="hr-admin")
    store.add_goal(goal)
    loaded_goal = DbGrowthStore(factory).get_goal(goal.id)
    assert loaded_goal is not None
    loaded_goal.progress_percent = 40.0
    DbGrowthStore(factory).save_goal(loaded_goal)
    assert DbGrowthStore(factory).list_goals()[0].progress_percent == 40.0


def test_offboarding_store_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbOffboardingStore(factory)
    template = OffboardingTemplate(
        name="Resignation starter",
        steps=[
            OffboardingTemplateStep(
                key="handover",
                title="Handover",
                kind=OffboardingStepKind.HANDOVER,
            ),
        ],
    )
    store.add_template(template)
    loaded_template = DbOffboardingStore(factory).get_template(template.id)
    assert loaded_template is not None
    assert loaded_template.steps[0].key == "handover"
    assert [item.id for item in DbOffboardingStore(factory).list_templates()] == [template.id]

    employee_id = uuid4()
    step_state = OffboardingStepState(
        key="handover",
        title="Handover",
        kind=OffboardingStepKind.HANDOVER,
        required=True,
        requires_human_signoff=True,
        assignee_role=ApproverRole.HR_ADMIN,
    )
    plan = OffboardingPlan(
        employee_id=employee_id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=date(2026, 10, 1),
        template_id=template.id,
        template_name=template.name,
        template_version_hash="a" * 64,
        steps=[step_state],
    )
    store.add_plan(plan)
    loaded_plan = DbOffboardingStore(factory).get_plan(plan.id)
    assert loaded_plan is not None
    assert loaded_plan.reason is OffboardingReason.RESIGNATION
    assert loaded_plan.steps[0].key == "handover"
    DbOffboardingStore(factory).save_plan(loaded_plan)
    assert [item.id for item in DbOffboardingStore(factory).list_plans()] == [plan.id]

    laptop = OffboardingAsset(employee_id=employee_id, plan_id=plan.id, name="MacBook Pro")
    store.add_asset(laptop)
    loaded_asset = DbOffboardingStore(factory).get_asset(laptop.id)
    assert loaded_asset is not None
    loaded_asset.status = AssetStatus.RETURNED
    DbOffboardingStore(factory).save_asset(loaded_asset)
    assert DbOffboardingStore(factory).list_assets()[0].status is AssetStatus.RETURNED
