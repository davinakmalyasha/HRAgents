"""Scheduled job runner: every engine on an explicit clock, nothing else.


Failure-first behavior is pinned first — unknown names are refused, a
failing job never stops the run, destructive work only runs on request —
then per-engine tests pin the counts, the reports, and the rerun safety.
"""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.messaging.store import ReplyStore
from hr_agents.models import (
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    BreachImpact,
    CandidateReply,
    ContractType,
    DimensionScore,
    DocumentKind,
    OfferTerms,
    PurgeAction,
    Recommendation,
    RecordEntity,
    ReviewCycleKind,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    SubjectKind,
    TechnicalEvaluation,
    Urgency,
)
from hr_agents.services import ApplicationStore, AuditChain, SubmissionInput
from hr_agents.services.people import PeopleServices
from hr_agents.services.recruiting import RecruitingServices
from hr_agents.services.scheduler import (
    JOB_NAMES,
    Scheduler,
    SchedulerReport,
    format_report,
)

TODAY = date.today()
NOW = datetime.combine(TODAY, time(9, 0), tzinfo=UTC)
FAR = NOW + timedelta(days=30)


@pytest.fixture
def replies() -> ReplyStore:
    return ReplyStore()


def make_scheduler(
    audit: AuditChain | None = None,
    replies: ReplyStore | None = None,
) -> tuple[Scheduler, PeopleServices, RecruitingServices, ApplicationStore]:
    people = PeopleServices() if audit is None else PeopleServices(audit=audit)
    applications = ApplicationStore()
    recruiting = RecruitingServices(
        audit=people.audit, applications=applications, approvals=people.approvals
    )
    scheduler = Scheduler(people=people, recruiting=recruiting, replies=replies)
    return scheduler, people, recruiting, applications


def make_evaluation(candidate_id: UUID) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=0.90,
        stack_alignment=0.90,
        systems_literacy=0.90,
        verifiable_certifications=0.90,
    )
    return TechnicalEvaluation(
        candidate_id=candidate_id,
        job_id=uuid4(),
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
        mean_vector=vector,
        s_tech=0.90,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=0.9, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[],
        recommendation=Recommendation.AUTO_SCHEDULE,
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
        requested_by="sari@example.com",
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
        updated_by="hr-admin",
        expiry_action=PurgeAction.DELETE,
    )
    record = people.compliance.track_record(
        entity=entity,
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        created_by="screening-pipeline",
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
        discovered_by="it-ops",
        created_by="hr-admin",
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
        created_by="hr-admin",
        kind=ReviewCycleKind.MID_YEAR,
        submission_due_on=NOW.date() + timedelta(days=1),
    )
    people.growth.add_assignment(
        cycle.id, employee_id=uuid4(), reviewer_id="lead-1", created_by="hr-admin"
    )
    people.growth.activate_cycle(cycle.id, by="hr-admin")


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
        by="hr-admin",
    )
    recruiting.offers.submit(stale.id, by="hr-admin")

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
