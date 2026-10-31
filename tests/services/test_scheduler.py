"""Scheduled job runner: every engine on an explicit clock, nothing else.


Failure-first behavior is pinned first — unknown names are refused, a
failing job never stops the run, destructive work only runs on request —
then per-engine tests pin the counts, the reports, and the rerun safety.
"""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from tests.actors import finance, hr_admin, manager

from hr_agents.identity import ActorProvenance, ActorRef, ActorType
from hr_agents.messaging.store import ReplyStore
from hr_agents.models import (
    AccrualMethod,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    BreachImpact,
    CandidateReply,
    ContractType,
    DimensionScore,
    DocumentKind,
    Employee,
    LeaveType,
    LeaveTypePolicy,
    OfferStatus,
    OfferTerms,
    ProposalStatus,
    PurgeAction,
    Recommendation,
    RecordEntity,
    RequestStatus,
    ReviewCycleKind,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    SubjectKind,
    TechnicalEvaluation,
    TimeSlot,
    Urgency,
    business_today,
)
from hr_agents.providers.queue import MemoryQueueBackend, QueueBackend
from hr_agents.rbac import RoleId
from hr_agents.services import ApplicationStore, AuditChain, SubmissionInput
from hr_agents.services.people import PeopleServices
from hr_agents.services.recruiting import RecruitingError, RecruitingServices
from hr_agents.services.scheduler import (
    JOB_NAMES,
    Scheduler,
    SchedulerReport,
    format_report,
)

TODAY = business_today()
NOW = datetime.combine(TODAY, time(9, 0), tzinfo=UTC)
FAR = NOW + timedelta(days=30)


@pytest.fixture
def replies() -> ReplyStore:
    return ReplyStore()


def owner(employee: Employee) -> ActorRef:
    """The principal bound to the employee, as the self-service routes require."""
    return ActorRef(
        actor_id="sari",
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.EMPLOYEE.value,
        employee_id=employee.id,
    )


def make_scheduler(
    audit: AuditChain | None = None,
    replies: ReplyStore | None = None,
    queue: QueueBackend | None = None,
    calendar: object | None = None,
) -> tuple[Scheduler, PeopleServices, RecruitingServices, ApplicationStore]:
    people = PeopleServices() if audit is None else PeopleServices(audit=audit)
    applications = ApplicationStore()
    recruiting = RecruitingServices(
        audit=people.audit, applications=applications, approvals=people.approvals
    )
    scheduler = Scheduler(
        people=people,
        recruiting=recruiting,
        replies=replies,
        # Always inject: a None queue makes the reaper resolve the developer's
        # configured backend, which turns a test run into an environment probe.
        queue=queue if queue is not None else MemoryQueueBackend(),
        queue_reaper_grace_seconds=0,
        calendar=calendar,
    )
    return scheduler, people, recruiting, applications


def test_approval_reconcile_applies_a_decision_the_subject_missed() -> None:
    """A crash between the approval and the leave sync leaves two screens disagreeing.

    The job replays the decision the approval *already* records; it does not make
    one. Once it runs, the request matches the inbox.
    """
    scheduler, people, _recruiting, _applications = make_scheduler()
    employee = people.employees.create(
        full_name="Sari Dewi",
        actor=hr_admin(),
        hire_date=TODAY - timedelta(days=400),
        job_title="Finance Staff",
    )
    people.leave.set_policy(
        LeaveTypePolicy(
            leave_type=LeaveType.ANNUAL,
            name="Cuti Tahunan",
            accrual_method=AccrualMethod.LUMP_SUM_ANNUAL,
            days_per_year=12.0,
            min_service_months=0,
            approver_role=ApproverRole.MANAGER,
        ),
        actor=hr_admin(),
    )
    request = people.leave.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=TODAY + timedelta(days=30),
        end_date=TODAY + timedelta(days=31),
        actor=owner(employee),
    )
    assert request.approval_id is not None
    people.approvals.decide(request.approval_id, actor=manager(), approve=True)
    assert people.leave.get_request(request.id).status is RequestStatus.PENDING

    report = scheduler.run(["approval-reconcile"], now=NOW)

    assert report.jobs[0].ok is True
    assert report.jobs[0].changed == 1
    assert people.leave.get_request(request.id).status is RequestStatus.APPROVED


def test_a_decision_commits_its_outbox_row_with_the_approval() -> None:
    """The durable half: the decision and the work it implies are one write."""
    scheduler, people, _recruiting, _applications = make_scheduler()
    employee = people.employees.create(
        full_name="Sari Dewi",
        actor=hr_admin(),
        hire_date=TODAY - timedelta(days=400),
        job_title="Finance Staff",
    )
    people.leave.set_policy(
        LeaveTypePolicy(
            leave_type=LeaveType.ANNUAL,
            name="Cuti Tahunan",
            accrual_method=AccrualMethod.LUMP_SUM_ANNUAL,
            days_per_year=12.0,
            min_service_months=0,
            approver_role=ApproverRole.MANAGER,
        ),
        actor=hr_admin(),
    )
    request = people.leave.request(
        employee_id=employee.id,
        leave_type=LeaveType.ANNUAL,
        start_date=TODAY + timedelta(days=30),
        end_date=TODAY + timedelta(days=31),
        actor=owner(employee),
    )
    assert request.approval_id is not None

    people.approvals.decide(request.approval_id, actor=manager(), approve=True)

    pending = people.approvals.pending_syncs
    assert len(pending) == 1
    assert pending[0].approval_id == request.approval_id
    assert pending[0].subject is ApprovalSubject.LEAVE_REQUEST
    assert pending[0].decision is ApprovalStatus.APPROVED

    scheduler.run(["approval-reconcile"], now=NOW)

    assert people.approvals.pending_syncs == []
    assert people.leave.get_request(request.id).status is RequestStatus.APPROVED


def test_a_failed_sync_is_retried_and_then_settles(monkeypatch: pytest.MonkeyPatch) -> None:
    """A store failure is not a lost decision: the row survives with its error."""
    scheduler, people, _recruiting, _applications = make_scheduler()
    approval = people.approvals.create(
        subject=ApprovalSubject.LEAVE_REQUEST,
        subject_id=str(uuid4()),
        title="A request nobody can sync yet",
        summary="",
        assignee_role=ApproverRole.HR_ADMIN,
        actor=hr_admin(),
    )
    people.approvals.decide(approval.id, actor=hr_admin(), approve=True, reason="ok")

    def failing(_approval_id: UUID, *, actor: ActorRef) -> object:
        raise OSError("the leave store is unavailable")

    monkeypatch.setattr(people.leave, "apply_decision", failing)
    first = scheduler.run(["approval-reconcile"], now=NOW)
    monkeypatch.undo()

    assert first.jobs[0].changed == 0
    pending = people.approvals.pending_syncs
    assert len(pending) == 1
    assert pending[0].attempts == 1
    assert "unavailable" in (pending[0].last_error or "")

    scheduler.run(["approval-reconcile"], now=NOW)

    # The leave request does not exist, so the real applier refuses with a domain
    # error — the outbox treats that as settled rather than retrying forever.
    assert people.approvals.pending_syncs == []


def test_a_sync_that_keeps_failing_is_closed_as_gave_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler, people, _recruiting, _applications = make_scheduler()
    approval = people.approvals.create(
        subject=ApprovalSubject.PAYROLL_RUN,
        subject_id=str(uuid4()),
        title="A payroll run with a broken store",
        summary="",
        assignee_role=ApproverRole.FINANCE,
        actor=hr_admin(),
    )
    people.approvals.decide(approval.id, actor=finance(), approve=True, reason="ok")

    def failing(_approval_id: UUID, *, actor: ActorRef) -> object:
        raise OSError("the payroll store is unavailable")

    monkeypatch.setattr(people.payroll, "apply_decision", failing)
    for _ in range(5):
        scheduler.run(["approval-reconcile"], now=NOW)

    assert people.approvals.pending_syncs == []
    all_rows = people.approvals.all_syncs()
    assert all_rows[0].outcome == "gave_up"
    assert all_rows[0].attempts == 5


def test_approval_reconcile_ignores_subjects_without_a_sync_path() -> None:
    scheduler, people, _recruiting, _applications = make_scheduler()
    approval = people.approvals.create(
        subject=ApprovalSubject.DATA_CHANGE,
        subject_id=str(uuid4()),
        title="Change a payroll field",
        summary="Not a subject with a sync method.",
        assignee_role=ApproverRole.HR_ADMIN,
        actor=hr_admin(),
    )
    people.approvals.decide(approval.id, actor=hr_admin(), approve=True, reason="ok")

    report = scheduler.run(["approval-reconcile"], now=NOW)

    assert report.jobs[0].ok is True
    assert report.jobs[0].changed == 0
    assert people.approvals.pending_syncs == []


def test_an_offer_approval_is_replayed_onto_the_offer() -> None:
    """The offer stayed pending after its approval was decided; the outbox closes it."""
    scheduler, people, recruiting, applications = make_scheduler()
    record, _ = applications.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    recruiting.evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(record.candidate_id),
        candidate_name="Sari Dewi",
        job_title="Backend Engineer",
    )
    offer = recruiting.offers.create(
        record.id,
        OfferTerms(
            position_title="Backend Engineer",
            start_date=TODAY + timedelta(days=30),
            salary_amount=10_000_000,
        ),
        actor=hr_admin(),
    )
    offer = recruiting.offers.submit(offer.id, actor=hr_admin())
    approval = people.approvals.find_by_subject(ApprovalSubject.OFFER, str(offer.id))
    assert approval is not None

    people.approvals.decide(approval.id, actor=hr_admin(), approve=True, reason="terms agreed")
    assert recruiting.offers.get(offer.id).status is OfferStatus.PENDING_APPROVAL

    report = scheduler.run(["approval-reconcile"], now=NOW)

    assert report.jobs[0].changed == 1
    assert recruiting.offers.get(offer.id).status is OfferStatus.APPROVED
    assert people.approvals.pending_syncs == []


def test_a_single_slot_scheduling_approval_is_confirmed() -> None:
    scheduler, people, recruiting, applications = make_scheduler()
    record, _ = applications.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    recruiting.evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(record.candidate_id, s_tech=0.65),
        candidate_name="Sari Dewi",
        job_title="Backend Engineer",
    )
    interviewer = uuid4()
    start = NOW + timedelta(days=3)
    recruiting.scheduling.set_availability(
        interviewer,
        slots=[TimeSlot(start_utc=start, end_utc=start + timedelta(hours=1))],
        actor=hr_admin(),
    )
    proposal = recruiting.scheduling.propose(
        candidate_id=record.candidate_id, job_id=record.job_id, interviewer_ids=[interviewer]
    )
    approval = people.approvals.find_by_subject(ApprovalSubject.SCHEDULING, str(proposal.id))
    assert approval is not None
    people.approvals.decide(approval.id, actor=hr_admin(), approve=True, reason="panel is free")

    scheduler.run(["approval-reconcile"], now=NOW)

    assert recruiting.scheduling.get(proposal.id).status is ProposalStatus.CONFIRMED


def test_a_multi_slot_approval_waits_for_a_human_to_choose() -> None:
    """The approval cannot invent which of several offered times was agreed."""
    scheduler, people, recruiting, applications = make_scheduler()
    record, _ = applications.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    recruiting.evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(record.candidate_id, s_tech=0.65),
        candidate_name="Sari Dewi",
        job_title="Backend Engineer",
    )
    interviewer = uuid4()
    start = NOW + timedelta(days=4)
    recruiting.scheduling.set_availability(
        interviewer,
        slots=[
            TimeSlot(start_utc=start, end_utc=start + timedelta(hours=1)),
            TimeSlot(start_utc=start + timedelta(hours=2), end_utc=start + timedelta(hours=3)),
        ],
        actor=hr_admin(),
    )
    proposal = recruiting.scheduling.propose(
        candidate_id=record.candidate_id, job_id=record.job_id, interviewer_ids=[interviewer]
    )
    approval = people.approvals.find_by_subject(ApprovalSubject.SCHEDULING, str(proposal.id))
    assert approval is not None
    people.approvals.decide(approval.id, actor=hr_admin(), approve=True, reason="panel is free")

    scheduler.run(["approval-reconcile"], now=NOW)

    assert recruiting.scheduling.get(proposal.id).status is ProposalStatus.PENDING_APPROVAL
    assert people.approvals.pending_syncs == []
    assert people.approvals.all_syncs()[0].outcome == "needs_human"


class FakeCalendar:
    """A free/busy adapter that answers from a fixed list and records its calls."""

    def __init__(self, busy: list[TimeSlot], *, fail_on: set[str] | None = None) -> None:
        self.busy_slots = busy
        self.fail_on = fail_on or set()
        self.calls: list[tuple[datetime, datetime, str]] = []

    def busy(
        self, *, start: datetime, end: datetime, calendar_id: str | None = None
    ) -> list[TimeSlot]:
        assert calendar_id is not None
        self.calls.append((start, end, calendar_id))
        if calendar_id in self.fail_on:
            raise RuntimeError("the calendar did not answer")
        return list(self.busy_slots)


def jakarta(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=ZoneInfo("Asia/Jakarta")).astimezone(UTC)


def next_weekday(weekday: int) -> date:
    """The next ``weekday`` strictly after today, inside the 14-day window."""
    ahead = (weekday - TODAY.weekday()) % 7 or 7
    return TODAY + timedelta(days=ahead)


def test_calendar_sync_refreshes_a_mapped_interviewer_from_free_busy() -> None:
    interviewer = uuid4()
    monday = next_weekday(0)
    busy = TimeSlot(start_utc=jakarta(monday, 10), end_utc=jakarta(monday, 11))
    calendar = FakeCalendar([busy])
    scheduler, _people, recruiting, _applications = make_scheduler(calendar=calendar)
    recruiting.scheduling.set_calendar_id(
        interviewer, calendar_id="panel@example.com", actor=hr_admin()
    )

    report = scheduler.run(["calendar-sync"], now=NOW)

    assert report.jobs[0].changed == 1
    assert "refreshed 1 interviewer calendar(s), 0 failed of 1 mapped" in report.jobs[0].detail
    assert calendar.calls == [(NOW, NOW + timedelta(days=14), "panel@example.com")]
    slots = recruiting.scheduling.get_availability(interviewer)
    assert TimeSlot(start_utc=jakarta(monday, 9), end_utc=jakarta(monday, 10)) in slots
    assert TimeSlot(start_utc=jakarta(monday, 11), end_utc=jakarta(monday, 17)) in slots
    assert not any(
        slot.start_utc < busy.end_utc and busy.start_utc < slot.end_utc for slot in slots
    )


def test_calendar_sync_does_nothing_without_a_mapping() -> None:
    calendar = FakeCalendar([])
    scheduler, _people, _recruiting, _applications = make_scheduler(calendar=calendar)

    report = scheduler.run(["calendar-sync"], now=NOW)

    assert report.jobs[0].changed == 0
    assert "no interviewer has a calendar mapped" in report.jobs[0].detail
    assert calendar.calls == []


def test_a_failing_calendar_leaves_other_interviewers_refreshed() -> None:
    broken, working = uuid4(), uuid4()
    calendar = FakeCalendar([], fail_on={"broken@example.com"})
    scheduler, _people, recruiting, _applications = make_scheduler(calendar=calendar)
    recruiting.scheduling.set_calendar_id(
        broken, calendar_id="broken@example.com", actor=hr_admin()
    )
    recruiting.scheduling.set_calendar_id(
        working, calendar_id="working@example.com", actor=hr_admin()
    )

    report = scheduler.run(["calendar-sync"], now=NOW)

    assert report.jobs[0].changed == 1
    assert "1 failed of 2 mapped" in report.jobs[0].detail
    assert len(recruiting.scheduling.get_availability(working)) > 0
    assert recruiting.scheduling.get_availability(broken) == []


def test_mapping_a_calendar_requires_a_value() -> None:
    _scheduler, _people, recruiting, _applications = make_scheduler()
    interviewer = uuid4()

    with pytest.raises(RecruitingError, match="calendar id is required"):
        recruiting.scheduling.set_calendar_id(interviewer, calendar_id="  ", actor=hr_admin())

    assert recruiting.scheduling.list_calendar_mappings() == []


def make_evaluation(candidate_id: UUID, *, s_tech: float = 0.90) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=s_tech,
        stack_alignment=s_tech,
        systems_literacy=s_tech,
        verifiable_certifications=s_tech,
    )
    return TechnicalEvaluation(
        candidate_id=candidate_id,
        job_id=uuid4(),
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
        mean_vector=vector,
        s_tech=s_tech,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=s_tech, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[],
        recommendation=(
            Recommendation.AUTO_SCHEDULE if s_tech >= 0.75 else Recommendation.HUMAN_REVIEW
        ),
    )


# --- runner behavior ---------------------------------------------------------------


def test_unknown_job_names_are_refused() -> None:
    scheduler, _, _, _ = make_scheduler()

    with pytest.raises(ValueError, match="unknown scheduled job"):
        scheduler.run(["midnight-snack"])

    with pytest.raises(ValueError, match="unknown scheduled job"):
        scheduler.run(["approvals", "midnight-snack"])


def test_run_reports_every_job_and_is_idempotent() -> None:
    scheduler, _, _, _ = make_scheduler()

    first = scheduler.run(now=NOW)
    second = scheduler.run(now=NOW)

    assert [job.name for job in first.jobs] == list(JOB_NAMES)
    assert all(job.ok for job in first.jobs)
    assert all(job.changed == 0 for job in first.jobs)
    assert [job.name for job in second.jobs] == list(JOB_NAMES)
    assert all(job.changed == 0 for job in second.jobs)
    assert first.dry_run is True

    text = format_report(first)
    for name in JOB_NAMES:
        assert name in text
    assert "dry run" in text


def test_run_selected_jobs_only() -> None:
    scheduler, _, _, _ = make_scheduler()

    report = scheduler.run(["growth", "offer-expiry"], now=NOW)

    assert [job.name for job in report.jobs] == ["growth", "offer-expiry"]


def test_failing_job_does_not_stop_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler, people, _, _ = make_scheduler()

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("queue backend exploded")

    monkeypatch.setattr(people.approvals, "escalate_overdue", boom)

    report = scheduler.run(now=NOW)

    by_name = {job.name: job for job in report.jobs}
    assert by_name["approvals"].ok is False
    assert "queue backend exploded" in (by_name["approvals"].error or "")
    assert by_name["growth"].ok is True
    assert isinstance(report, SchedulerReport)


# --- approvals -----------------------------------------------------------------------


def test_approvals_escalate_then_expire_across_runs() -> None:
    scheduler, people, _, _ = make_scheduler()
    request = people.approvals.create(
        subject=ApprovalSubject.LEAVE_REQUEST,
        subject_id="leave-1",
        title="Annual leave 3 days",
        assignee_role=ApproverRole.MANAGER,
        actor=ActorRef.legacy("sari@example.com"),
        urgency=Urgency.NORMAL,
        max_escalations=1,
    )

    first = scheduler.run(["approvals"], now=FAR)
    assert first.jobs[0].ok is True
    assert first.jobs[0].changed == 2
    assert "escalated 1" in first.jobs[0].detail
    assert "expired 1" in first.jobs[0].detail

    final = people.approvals._store.get(request.id)
    assert final is not None
    assert final.status is ApprovalStatus.EXPIRED

    second = scheduler.run(["approvals"], now=FAR)
    assert second.jobs[0].changed == 0


# --- retention -------------------------------------------------------------------------


def track_expired_candidate(
    people: PeopleServices, *, entity: RecordEntity = RecordEntity.CANDIDATE
) -> UUID:
    people.compliance.set_policy(
        entity=entity,
        name=f"{entity.value} records",
        retention_months=12,
        actor=ActorRef.legacy("hr-admin"),
        expiry_action=PurgeAction.DELETE,
    )
    record = people.compliance.track_record(
        entity=entity,
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        actor=ActorRef.legacy("screening-pipeline"),
        label="Budi Santoso",
        anchor_at=NOW - timedelta(days=400),
    )
    return record.id


def test_retention_dry_run_reports_without_mutating() -> None:
    scheduler, people, _, _ = make_scheduler()
    record_id = track_expired_candidate(people)

    report = scheduler.run(["retention"], now=NOW)

    assert report.dry_run is True
    assert report.jobs[0].ok is True
    assert report.jobs[0].changed == 0
    assert "dry run" in report.jobs[0].detail
    assert not people.compliance.get_record(record_id).purged


def test_retention_purge_applies_on_request() -> None:
    scheduler, people, _, _ = make_scheduler()
    record_id = track_expired_candidate(people, entity=RecordEntity.CONSENT)

    report = scheduler.run(["retention"], now=NOW, purge=True)

    assert report.dry_run is False
    assert report.jobs[0].changed == 1
    assert "purged 1" in report.jobs[0].detail
    assert people.compliance.get_record(record_id).purged
    assert people.audit.verify() == -1


def test_retention_purge_reports_records_it_cannot_remove() -> None:
    """A purge that cannot reach the underlying store must say so, not claim success.

    ``consent`` is the only entity with a registered store handler. A candidate
    record is therefore skipped, counted as unchanged, and named in the detail so
    an operator reading the scheduler log sees the coverage gap.
    """
    scheduler, people, _, _ = make_scheduler()
    record_id = track_expired_candidate(people)

    report = scheduler.run(["retention"], now=NOW, purge=True)

    assert report.jobs[0].ok is True
    assert report.jobs[0].changed == 0
    assert "purged 0" in report.jobs[0].detail
    assert "SKIPPED 1" in report.jobs[0].detail
    assert "candidate" in report.jobs[0].detail
    assert people.compliance.get_record(record_id).purged_at is None


# --- breaches ----------------------------------------------------------------------------


def test_breach_overdue_is_reported_read_only() -> None:
    scheduler, people, _, _ = make_scheduler()
    people.compliance.create_incident(
        title="Laptop with HR export lost",
        description="Device encryption status unknown",
        impact=BreachImpact.HIGH,
        actor=ActorRef.legacy("it-ops"),
        discovered_at=NOW,
    )

    report = scheduler.run(["breaches"], now=NOW + timedelta(hours=25))

    assert report.jobs[0].ok is True
    assert report.jobs[0].changed == 0
    assert "2 overdue" in report.jobs[0].detail
    assert "breaches: ok" in format_report(report)


# --- growth ------------------------------------------------------------------------------


def seed_due_review(people: PeopleServices) -> None:
    cycle = people.growth.create_cycle(
        name="2026 H1 Review",
        period_start=NOW.date() - timedelta(days=180),
        period_end=NOW.date(),
        actor=ActorRef.legacy("hr-admin"),
        kind=ReviewCycleKind.MID_YEAR,
        submission_due_on=NOW.date() + timedelta(days=1),
    )
    # Growth rows reference employees with real foreign keys: the reviewee has
    # to be a row, not an invented id.
    employee = people.employees.create(
        full_name="Sari Dewi",
        actor=ActorRef.legacy("hr-admin"),
        hire_date=NOW.date() - timedelta(days=200),
    )
    people.growth.add_assignment(
        cycle.id,
        employee_id=employee.id,
        reviewer_id="lead-1",
        actor=ActorRef.legacy("hr-admin"),
    )
    people.growth.activate_cycle(cycle.id, actor=ActorRef.legacy("hr-admin"))


def test_growth_reminders_create_tasks_once() -> None:
    scheduler, people, _, _ = make_scheduler()
    seed_due_review(people)

    first = scheduler.run(["growth"], now=NOW)
    assert first.jobs[0].changed == 1
    assert "1 review reminder" in first.jobs[0].detail

    second = scheduler.run(["growth"], now=NOW)
    assert second.jobs[0].changed == 0


# --- expiry watchers -----------------------------------------------------------------------


def seed_expiring_employee(people: PeopleServices) -> None:
    employee = people.employees.create(
        full_name="Sari Dewi",
        actor=ActorRef.legacy("hr-admin"),
        hire_date=NOW.date() - timedelta(days=200),
        job_title="Finance Staff",
    )
    people.contracts.create(
        employee_id=employee.id,
        contract_type=ContractType.PKWT,
        start_date=NOW.date() - timedelta(days=365),
        actor=ActorRef.legacy("hr-admin"),
        end_date=NOW.date() + timedelta(days=20),
    )
    people.employees.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="employees/ktp-1.pdf",
        sha256="a" * 64,
        actor=ActorRef.legacy("hr-admin"),
        expires_on=NOW.date() + timedelta(days=20),
    )


def test_contract_and_document_expiry_create_tasks_once() -> None:
    scheduler, people, _, _ = make_scheduler()
    seed_expiring_employee(people)

    contracts = scheduler.run(["contract-expiry"], now=NOW)
    documents = scheduler.run(["document-expiry"], now=NOW)
    assert contracts.jobs[0].changed == 1
    assert "1 contract reminder" in contracts.jobs[0].detail
    assert documents.jobs[0].changed == 1
    assert "1 document reminder" in documents.jobs[0].detail

    again = scheduler.run(["contract-expiry", "document-expiry"], now=NOW)
    assert all(job.changed == 0 for job in again.jobs)


# --- offer expiry ----------------------------------------------------------------------------


def test_offer_expiry_applies_and_leaves_live_offers() -> None:
    scheduler, _, recruiting, applications = make_scheduler()
    record, _ = applications.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    recruiting.evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(record.candidate_id),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    stale = recruiting.offers.create(
        record.id,
        OfferTerms(
            position_title="Backend Engineer",
            employment_type=ContractType.PKWTT,
            start_date=date(2026, 11, 1),
            probation_months=3,
            salary_amount=25_000_000.0,
            salary_currency="IDR",
            expires_at=NOW - timedelta(hours=1),
        ),
        actor=ActorRef.legacy("hr-admin"),
    )
    recruiting.offers.submit(stale.id, actor=ActorRef.legacy("hr-admin"))

    report = scheduler.run(["offer-expiry"], now=NOW)

    assert report.jobs[0].changed == 1
    assert "1 offer(s) expired" in report.jobs[0].detail
    assert recruiting.offers.get(stale.id).status.value == "expired"


# --- audit verification ------------------------------------------------------------------


def test_audit_chain_verification_runs_read_only() -> None:
    scheduler, _, _, _ = make_scheduler()

    report = scheduler.run(["audit-verify"], now=NOW)

    assert report.jobs[0].ok is True
    assert report.jobs[0].changed == 0
    assert "intact" in report.jobs[0].detail


# --- reply SLA (anti-ghosting) -------------------------------------------------------------


def dispatch_offer(
    recruiting: RecruitingServices,
    applications: ApplicationStore,
    *,
    recipient: str = "budi@example.com",
    sent_at: datetime | None = None,
) -> UUID:
    record, _ = applications.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    recruiting.evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(record.candidate_id),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    message = recruiting.communications.queue_offer(
        record.candidate_id,
        actor=ActorRef.legacy("hr-admin"),
        body="Offer body",
        to_email=recipient,
    )
    recruiting.communications.record_dispatch(
        message.id,
        provider="email.smtp",
        recipient=recipient,
        message_id=f"<{message.id}@example.com>",
        sent_at=sent_at or NOW - timedelta(hours=100),
    )
    return message.id


def test_unanswered_message_gets_one_follow_up_task(
    replies: ReplyStore,
) -> None:
    scheduler, people, recruiting, applications = make_scheduler(replies=replies)
    dispatch_offer(recruiting, applications)

    report = scheduler.run(["reply-sla"], now=NOW)

    assert report.jobs[0].changed == 1
    tasks = people.tasks.open_tasks()
    assert len(tasks) == 1
    assert tasks[0].assignee_role is ApproverRole.RECRUITER_LEAD
    assert tasks[0].related_subject == "candidate_communication"
    assert "No reply to the offer message" in tasks[0].title


def test_a_reply_clears_the_sla_and_reruns_stay_quiet(
    replies: ReplyStore,
) -> None:
    scheduler, people, recruiting, applications = make_scheduler(replies=replies)
    message_id = dispatch_offer(recruiting, applications)
    communication = recruiting.communications.get(message_id)
    replies.add(
        CandidateReply(
            candidate_id=communication.candidate_id,
            communication_id=message_id,
            sender="budi@example.com",
            subject="Re: Your offer",
            body="Saya tertarik, terima kasih.",
            provider="email.imap_poll",
            provider_message_id="<reply-1@example.com>",
            dedup_key="a" * 64,
            received_at=NOW - timedelta(hours=1),
        )
    )

    first = scheduler.run(["reply-sla"], now=NOW)
    second = scheduler.run(["reply-sla"], now=NOW)

    assert first.jobs[0].changed == 0
    assert second.jobs[0].changed == 0
    assert people.tasks.open_tasks() == []


def test_a_recent_dispatch_is_not_chased_yet(replies: ReplyStore) -> None:
    scheduler, people, recruiting, applications = make_scheduler(replies=replies)
    dispatch_offer(recruiting, applications, sent_at=NOW - timedelta(minutes=5))

    report = scheduler.run(["reply-sla"], now=NOW)

    assert report.jobs[0].changed == 0
    assert people.tasks.open_tasks() == []


def test_sla_task_is_not_duplicated_across_runs(replies: ReplyStore) -> None:
    scheduler, people, recruiting, applications = make_scheduler(replies=replies)
    dispatch_offer(recruiting, applications)

    first = scheduler.run(["reply-sla"], now=NOW)
    second = scheduler.run(["reply-sla"], now=NOW + timedelta(hours=1))

    assert first.jobs[0].changed == 1
    assert second.jobs[0].changed == 0
    assert len(people.tasks.open_tasks()) == 1


def test_sla_job_reports_cleanly_without_a_reply_store() -> None:
    scheduler, _, _, _ = make_scheduler()

    report = scheduler.run(["reply-sla"], now=NOW)

    assert report.jobs[0].ok is True
    assert report.jobs[0].changed == 0
    assert "no reply store" in report.jobs[0].detail


# --- queue reaper -------------------------------------------------------------------------


def test_the_queue_reaper_requeues_a_stale_lease() -> None:
    """A wedged worker never loops back to claim; the scheduler's process
    must put the message back, and the attempt count still rises."""
    import asyncio

    from hr_agents.providers.queue import MemoryQueueBackend

    backend = MemoryQueueBackend()
    scheduler, *_ = make_scheduler(queue=backend)
    topic = "evaluation.evaluate"

    async def stage() -> None:
        await backend.publish(topic, {"application_id": "demo"})
        await backend.claim(topic, lease_seconds=0.01)
        await asyncio.sleep(0.05)

    asyncio.run(stage())

    report = scheduler.run(["queue-reaper"], now=NOW)

    (job,) = report.jobs
    assert job.ok is True
    assert job.changed == 1
    assert "stale lease" in job.detail
    assert asyncio.run(backend.stats(topic)).pending == 1
