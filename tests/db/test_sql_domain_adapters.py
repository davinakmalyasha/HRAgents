"""Compliance, growth, and offboarding adapter tests on in-memory SQLite."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.domain import (
    DbComplianceStore,
    DbGrowthStore,
    DbOffboardingStore,
)
from hr_agents.db.people import DbEmployeeStore
from hr_agents.models import (
    ApproverRole,
    AssignmentStatus,
    BreachIncident,
    CalendarEntryCategory,
    ComplianceCalendarEntry,
    ConsentGrant,
    Employee,
    EmployeeStatus,
    ErasureRequest,
    Goal,
    GoalStatus,
    OffboardingAsset,
    OffboardingPlan,
    OffboardingReason,
    RecordEntity,
    RetentionPolicy,
    RetentionRecord,
    ReviewAssignment,
    ReviewCycle,
    ReviewCycleStatus,
    ReviewSummary,
    SubjectKind,
    business_today,
)
from hr_agents.models.offboarding import (
    AssetStatus,
    OffboardingStepKind,
    OffboardingStepState,
    OffboardingTemplate,
    OffboardingTemplateStep,
)
from hr_agents.services.people_store import ComplianceStore


def _consent(subject_id: str = "cand-purge") -> ConsentGrant:
    return ConsentGrant(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=subject_id,
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
        note="signed the paper form, kept in the filing cabinet",
    )


def test_the_postgres_store_can_delete_a_consent_grant(factory: sessionmaker[Session]) -> None:
    """`delete_consent` must reach the database, not the inherited empty dict.

    `DbComplianceStore` overrides `add_consent`, `save_consent`, `get_consent` and
    `list_consents`, but not `delete_consent`. It therefore inherited the
    in-memory implementation, which pops from `self._consents` -- a dict that
    stays empty on this backend, because `add_consent` writes SQL.

    So under Postgres the method returned `False` for a grant that existed. The
    erasure handler counts the returns, and `_apply_purge` reads a non-empty
    detail string as proof the store was mutated. The chain recorded `DELETED`
    and the consent row survived: a data-protection workflow reporting success
    on data it did not touch, in the one backend the shipped compose stack uses.
    """
    store = DbComplianceStore(factory)
    consent = _consent()
    store.add_consent(consent)

    assert DbComplianceStore(factory).delete_consent(consent.id) is True
    assert DbComplianceStore(factory).get_consent(consent.id) is None
    assert [item.id for item in DbComplianceStore(factory).list_consents()] == []
    # Deleting again is honestly False, not a second "success".
    assert DbComplianceStore(factory).delete_consent(consent.id) is False


def test_the_postgres_store_can_redact_a_consent_grant(factory: sessionmaker[Session]) -> None:
    """Anonymize keeps the grant on record and blanks only the capture evidence.

    Same inheritance bug as the delete above, and worse: `redact_consent`
    returned `None`, the handler counted zero, and the retention record was
    marked purged with the personal data still readable in the note field.
    """
    store = DbComplianceStore(factory)
    consent = _consent("cand-anonymize")
    store.add_consent(consent)

    redacted = DbComplianceStore(factory).redact_consent(consent.id)
    assert redacted is not None
    assert redacted.note == "redacted on erasure"
    assert redacted.captured_by == "redacted"
    assert redacted.capture_method == "redacted"

    stored = DbComplianceStore(factory).get_consent(consent.id)
    assert stored is not None, "anonymize must keep the grant so the ledger still shows it"
    assert stored.note == "redacted on erasure"
    assert stored.subject_id == "cand-anonymize"


def test_the_two_backends_agree_on_whether_a_consent_was_removed(
    factory: sessionmaker[Session],
) -> None:
    """Both stores return the same answers, which is the property that mattered.

    `docs/architecture/data-storage.md` treats the in-memory implementation as the
    definition of the port and the Postgres adapter as an implementation of it.
    These two methods disagreed on exactly one question -- did anything get
    removed -- and the erasure workflow trusted the answer.
    """
    memory = ComplianceStore()
    sql = DbComplianceStore(factory)

    for store in (memory, sql):
        store.add_consent(_consent("cand-parity"))

    assert memory.delete_consent(memory.list_consents()[0].id) is True
    assert sql.delete_consent(sql.list_consents()[0].id) is True
    assert memory.list_consents() == []
    assert sql.list_consents() == []
    assert memory.redact_consent(uuid4()) is None
    assert sql.redact_consent(uuid4()) is None


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

    # Growth rows reference employees (and cycles) with real foreign keys now,
    # so the subject must be a row in the same database.
    employees = DbEmployeeStore(factory)
    subject = Employee(full_name="Sari Dewi", status=EmployeeStatus.ACTIVE)
    employees.add_employee(subject)

    assignment = ReviewAssignment(
        cycle_id=cycle.id,
        employee_id=subject.id,
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


def test_page_growth_lists_filter_and_page_in_sql(factory: sessionmaker[Session]) -> None:
    """Cycles, assignments, summaries and goals page with their route predicates.

    Two cycles, two reviewers, a terminal form and past-due goals: each page
    proves its predicate and its count. The two-deep walks pin the
    ``(created_at, id)`` order that keeps OFFSET from skipping rows.
    """
    store = DbGrowthStore(factory)
    employees = DbEmployeeStore(factory)
    subject = Employee(full_name="Sari Dewi", status=EmployeeStatus.ACTIVE)
    other = Employee(full_name="Budi Santoso", status=EmployeeStatus.ACTIVE)
    employees.add_employee(subject)
    employees.add_employee(other)

    draft = ReviewCycle(
        name="Draft round",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        created_by="hr-admin",
    )
    active = ReviewCycle(
        name="Active round",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 12, 31),
        created_by="hr-admin",
        status=ReviewCycleStatus.ACTIVE,
    )
    store.add_cycle(draft)
    store.add_cycle(active)

    pending = ReviewAssignment(cycle_id=active.id, employee_id=subject.id, reviewer_id="lead-1")
    submitted = ReviewAssignment(
        cycle_id=active.id,
        employee_id=other.id,
        reviewer_id="lead-2",
        status=AssignmentStatus.SUBMITTED,
    )
    draft_form = ReviewAssignment(cycle_id=draft.id, employee_id=subject.id, reviewer_id="lead-1")
    for assignment in (pending, submitted, draft_form):
        store.add_assignment(assignment)

    first_summary = ReviewSummary(cycle_id=active.id, employee_id=subject.id)
    second_summary = ReviewSummary(cycle_id=active.id, employee_id=other.id)
    draft_summary = ReviewSummary(cycle_id=draft.id, employee_id=subject.id)
    for summary in (first_summary, second_summary, draft_summary):
        store.add_summary(summary)

    today = business_today()
    overdue_goal = Goal(
        employee_id=subject.id,
        title="Overdue",
        created_by="hr-admin",
        due_on=today - timedelta(days=3),
        status=GoalStatus.ACTIVE,
    )
    upcoming_goal = Goal(
        employee_id=subject.id,
        title="Upcoming",
        created_by="hr-admin",
        due_on=today + timedelta(days=10),
    )
    completed_goal = Goal(
        employee_id=subject.id,
        title="Completed",
        created_by="hr-admin",
        due_on=today - timedelta(days=5),
        status=GoalStatus.COMPLETED,
    )
    other_goal = Goal(
        employee_id=other.id,
        title="Other's goal",
        created_by="hr-admin",
        due_on=today + timedelta(days=2),
    )
    for goal in (overdue_goal, upcoming_goal, completed_goal, other_goal):
        store.add_goal(goal)

    cycles, cycle_total = store.page_cycles(status=None, limit=10, offset=0)
    assert cycle_total == 2
    expected_cycles = sorted([draft, active], key=lambda cycle: (cycle.created_at, str(cycle.id)))
    assert [cycle.id for cycle in cycles] == [cycle.id for cycle in expected_cycles]
    open_cycles, open_total = store.page_cycles(status=ReviewCycleStatus.ACTIVE, limit=10, offset=0)
    assert open_total == 1
    assert [cycle.id for cycle in open_cycles] == [active.id]

    cycle_forms, cycle_forms_total = store.page_assignments(cycle_id=active.id, limit=10, offset=0)
    assert cycle_forms_total == 2
    expected_forms = sorted([pending, submitted], key=lambda item: (item.created_at, str(item.id)))
    assert [item.id for item in cycle_forms] == [item.id for item in expected_forms]

    mine, mine_total = store.page_assignments(
        reviewer_id="lead-1", open_only=True, limit=10, offset=0
    )
    assert mine_total == 2, "the draft cycle's pending form is still outstanding work"
    expected_mine = sorted([pending, draft_form], key=lambda item: (item.created_at, str(item.id)))
    assert [item.id for item in mine] == [item.id for item in expected_mine]

    terminal, terminal_total = store.page_assignments(
        reviewer_id="lead-2", open_only=True, limit=10, offset=0
    )
    assert terminal_total == 0
    assert terminal == []

    expected_summaries = sorted(
        [first_summary, second_summary], key=lambda item: (item.created_at, str(item.id))
    )
    summaries, summary_total = store.page_summaries(cycle_id=active.id, limit=1, offset=1)
    assert summary_total == 2
    assert [summary.id for summary in summaries] == [expected_summaries[1].id]

    expected_goals = sorted(
        [overdue_goal, upcoming_goal, completed_goal],
        key=lambda goal: (goal.created_at, str(goal.id)),
    )
    goals, goal_total = store.page_goals(employee_id=subject.id, as_of=today, limit=10, offset=0)
    assert goal_total == 3
    assert [goal.id for goal in goals] == [goal.id for goal in expected_goals]
    rest, rest_total = store.page_goals(employee_id=subject.id, as_of=today, limit=1, offset=2)
    assert rest_total == 3
    assert [goal.id for goal in rest] == [expected_goals[2].id]

    past_due, past_due_total = store.page_goals(overdue_only=True, as_of=today, limit=10, offset=0)
    assert past_due_total == 1, "completed goals are not overdue work"
    assert [goal.id for goal in past_due] == [overdue_goal.id]

    completed, completed_total = store.page_goals(
        status=GoalStatus.COMPLETED, as_of=today, limit=10, offset=0
    )
    assert completed_total == 1
    assert [goal.id for goal in completed] == [completed_goal.id]


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

    # offboarding_plans.employee_id is a foreign key, so the employee must be a
    # real row in the same database.
    employees = DbEmployeeStore(factory)
    employee = Employee(full_name="Sari Dewi", status=EmployeeStatus.ACTIVE)
    employees.add_employee(employee)
    employee_id = employee.id
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


def test_calendar_entries_round_trip_and_delete(factory: sessionmaker[Session]) -> None:
    """The operator calendar survives a restart and a removal is a real DELETE.

    A Postgres adapter that inherited the in-memory dict would answer an empty
    calendar after every deploy while the operator's statutory dates sat in the
    table -- the same inheritance failure the consent methods above were caught
    by, in a surface whose whole point is not forgetting a date.
    """
    store = DbComplianceStore(factory)
    entry = ComplianceCalendarEntry(
        title="PPh 21 monthly filing",
        due_on=date(2026, 11, 10),
        category=CalendarEntryCategory.TAX,
        source_note="DJP announcement 2026-01",
        created_by="hr-admin",
    )
    store.add_calendar_entry(entry)

    fresh = DbComplianceStore(factory)
    loaded = fresh.get_calendar_entry(entry.id)
    assert loaded is not None
    assert loaded.title == "PPh 21 monthly filing"
    assert loaded.due_on == date(2026, 11, 10)
    assert loaded.category is CalendarEntryCategory.TAX
    assert loaded.source_note == "DJP announcement 2026-01"
    assert [item.id for item in fresh.list_calendar_entries()] == [entry.id]

    assert fresh.delete_calendar_entry(entry.id) is True
    assert fresh.get_calendar_entry(entry.id) is None
    assert fresh.delete_calendar_entry(entry.id) is False


def test_offboarding_active_plans_page_in_sql(factory: sessionmaker[Session]) -> None:
    """The routed active list: completed filter, ORDER BY and LIMIT in SQL.

    `active_plans` used to materialize every plan the tenant ever ran and drop
    the completed ones in Python; the client only ever pages a slice of it.
    """
    store = DbOffboardingStore(factory)
    employees = DbEmployeeStore(factory)
    employee = Employee(full_name="Sari Dewi", status=EmployeeStatus.ACTIVE)
    employees.add_employee(employee)
    template = OffboardingTemplate(
        name="Resignation starter",
        steps=[
            OffboardingTemplateStep(
                key="handover", title="Handover", kind=OffboardingStepKind.HANDOVER
            ),
        ],
    )
    store.add_template(template)

    def plan(*, completed: bool) -> OffboardingPlan:
        return OffboardingPlan(
            employee_id=employee.id,
            reason=OffboardingReason.RESIGNATION,
            last_working_day=date(2026, 10, 1),
            template_id=template.id,
            template_name=template.name,
            template_version_hash="a" * 64,
            steps=[
                OffboardingStepState(
                    key="handover",
                    title="Handover",
                    kind=OffboardingStepKind.HANDOVER,
                    required=True,
                    requires_human_signoff=True,
                    assignee_role=ApproverRole.HR_ADMIN,
                )
            ],
            completed_at=datetime(2026, 9, 1, tzinfo=UTC) if completed else None,
        )

    finished = plan(completed=True)
    active = plan(completed=False)
    store.add_plan(finished)
    store.add_plan(active)

    fresh = DbOffboardingStore(factory)
    page, total = fresh.page_active_plans(limit=10, offset=0)
    assert total == 1
    assert [item.id for item in page] == [active.id]
    assert finished.id not in {item.id for item in page}
