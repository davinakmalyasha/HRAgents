from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from hr_agents.models import (
    DimensionScore,
    EvaluationFlag,
    JobStatus,
    PolicyDecision,
    Recommendation,
    SchedulingChannel,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    Seniority,
    TechnicalEvaluation,
    TimeSlot,
)
from hr_agents.services import ApplicationStore, AuditChain, SubmissionInput
from hr_agents.services.recruiting import (
    MAX_DOCUMENT_BYTES,
    DocumentTooLargeError,
    EvaluationService,
    JobService,
    RecruitingError,
    RecruitingServices,
    SchedulingService,
    synthesize_feedback,
)

CANDIDATE_ID = uuid4()
APPLICATION_ID = uuid4()

BASE_SLOT = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)


def make_evaluation(
    *,
    s_tech: float = 0.90,
    sigma: float = 0.0,
    candidate_id: UUID = CANDIDATE_ID,
    flags: list[EvaluationFlag] | None = None,
    breakdown: list[DimensionScore] | None = None,
    recommendation: Recommendation = Recommendation.AUTO_SCHEDULE,
) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=s_tech,
        stack_alignment=s_tech,
        systems_literacy=s_tech,
        verifiable_certifications=s_tech,
    )
    return TechnicalEvaluation(
        candidate_id=candidate_id,
        job_id=uuid4(),
        runs=[ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector)],
        mean_vector=vector,
        s_tech=s_tech,
        sigma=sigma,
        breakdown=breakdown
        or [
            DimensionScore(
                dimension=dimension, score=s_tech, weight=0.25, rationale=f"{dimension.value} ok"
            )
            for dimension in ScoreDimension
        ],
        flags=flags or [],
        recommendation=recommendation,
    )


def make_slots(count: int, *, offset_hours: int = 0) -> list[TimeSlot]:
    return [
        TimeSlot(
            start_utc=BASE_SLOT + timedelta(hours=offset_hours + i),
            end_utc=BASE_SLOT + timedelta(hours=offset_hours + i + 1),
        )
        for i in range(count)
    ]


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def services(audit: AuditChain) -> RecruitingServices:
    return RecruitingServices(audit=audit, applications=ApplicationStore())


@pytest.fixture
def jobs(audit: AuditChain) -> JobService:
    return JobService(audit=audit)


@pytest.fixture
def evaluations(audit: AuditChain) -> EvaluationService:
    return EvaluationService(audit=audit)


@pytest.fixture
def scheduling(evaluations: EvaluationService, audit: AuditChain) -> SchedulingService:
    return SchedulingService(evaluations=evaluations, audit=audit)


# --- documents ------------------------------------------------------------------


def test_upload_hashes_and_stores_document(services: RecruitingServices) -> None:
    content = b"Budi Santoso - backend engineer"
    document = services.documents.upload(
        filename="cv.txt", kind="cv", content=content, uploaded_by="hr-admin"
    )

    import hashlib

    assert document.sha256 == hashlib.sha256(content).hexdigest()
    assert document.size_bytes == len(content)
    assert services.documents.get(document.id).content == content


def test_upload_rejects_unknown_kind(services: RecruitingServices) -> None:
    with pytest.raises(RecruitingError, match="unsupported document kind"):
        services.documents.upload(filename="x", kind="photo", content=b"x", uploaded_by="hr")


def test_upload_rejects_empty_and_oversize(services: RecruitingServices) -> None:
    with pytest.raises(RecruitingError, match="empty"):
        services.documents.upload(filename="x", kind="cv", content=b"", uploaded_by="hr")
    with pytest.raises(DocumentTooLargeError, match="limit"):
        services.documents.upload(
            filename="big.pdf",
            kind="cv",
            content=b"x" * (MAX_DOCUMENT_BYTES + 1),
            uploaded_by="hr",
        )


def test_document_upload_is_audited(services: RecruitingServices, audit: AuditChain) -> None:
    services.documents.upload(filename="cv.txt", kind="cv", content=b"abc", uploaded_by="hr-admin")
    actions = [entry.action for entry in audit.entries]
    assert actions == ["document.uploaded"]


# --- jobs -------------------------------------------------------------------------


def test_job_create_defaults(jobs: JobService) -> None:
    job = jobs.create(title="Backend Engineer", created_by="hr-admin")
    assert job.status is JobStatus.DRAFT
    assert job.seniority is Seniority.MID
    assert jobs.get(job.id).title == "Backend Engineer"


def test_job_lifecycle_guards(jobs: JobService) -> None:
    job = jobs.create(title="X", created_by="hr-admin")
    opened = jobs.transition(job.id, target=JobStatus.OPEN, by="hr-admin")
    assert opened.status is JobStatus.OPEN

    paused = jobs.transition(job.id, target=JobStatus.PAUSED, by="hr-admin")
    assert paused.status is JobStatus.PAUSED
    with pytest.raises(RecruitingError, match="cannot move job"):
        jobs.transition(job.id, target=JobStatus.DRAFT, by="hr-admin")

    closed = jobs.transition(job.id, target=JobStatus.CLOSED, by="hr-admin")
    assert closed.status is JobStatus.CLOSED
    with pytest.raises(RecruitingError, match="read-only"):
        jobs.update(job.id, by="hr-admin", title="New title")


def test_job_update_merges_fields(jobs: JobService) -> None:
    job = jobs.create(title="X", created_by="hr-admin", must_have_skills=["python"])
    updated = jobs.update(
        job.id, by="hr-admin", title="Y", nice_to_have_skills=["go"], min_years_experience=3
    )
    assert updated.title == "Y"
    assert updated.must_have_skills == ["python"]
    assert updated.nice_to_have_skills == ["go"]
    assert updated.min_years_experience == 3


def test_job_list_filters_by_status(jobs: JobService) -> None:
    first = jobs.create(title="A", created_by="hr")
    jobs.create(title="B", created_by="hr")
    jobs.transition(first.id, target=JobStatus.OPEN, by="hr")
    assert [job.title for job in jobs.list_all(status=JobStatus.OPEN)] == ["A"]


def test_job_unknown_raises(jobs: JobService) -> None:
    with pytest.raises(RecruitingError, match="unknown job"):
        jobs.get(uuid4())


# --- evaluations -------------------------------------------------------------------


def test_register_evaluation_and_lookup(evaluations: EvaluationService) -> None:
    evaluation = make_evaluation()
    record = evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=evaluation,
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )

    assert evaluations.get(evaluation.id).application_id == APPLICATION_ID
    assert evaluations.get_by_application(APPLICATION_ID).candidate_id == CANDIDATE_ID
    assert evaluations.get_by_candidate(CANDIDATE_ID).evaluation.s_tech == 0.90
    assert record.policy.decision is PolicyDecision.AUTO_SCHEDULE


def test_register_is_idempotent_guarded(evaluations: EvaluationService) -> None:
    evaluation = make_evaluation()
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=evaluation,
        candidate_name="Budi",
        job_title="Engineer",
    )
    with pytest.raises(RecruitingError, match="already registered"):
        evaluations.register(
            application_id=APPLICATION_ID,
            evaluation=evaluation,
            candidate_name="Budi",
            job_title="Engineer",
        )


def test_register_syncs_application_record(audit: AuditChain) -> None:
    store = ApplicationStore()
    record, _ = store.submit(
        SubmissionInput(
            job_id=uuid4(), source_channel="api", consent_granted=True, candidate_name="Budi"
        )
    )
    service = EvaluationService(audit=audit, applications=store)
    evaluation = make_evaluation(candidate_id=record.candidate_id)

    service.register(
        application_id=record.id,
        evaluation=evaluation,
        candidate_name="Budi",
        job_title="Backend Engineer",
    )

    assert record.s_tech == 0.90
    assert record.recommendation is Recommendation.AUTO_SCHEDULE
    assert record.status.value == "evaluated"
    assert record.timeline[-1][1] == "application.evaluated.evaluated"


def test_override_is_append_only_with_audit_receipt(evaluations: EvaluationService) -> None:
    evaluation = make_evaluation(s_tech=0.75)
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=evaluation,
        candidate_name="Budi",
        job_title="Engineer",
    )

    first = evaluations.record_override(
        evaluation.id,
        reviewer_id="lead-1",
        reviewer_role="engineering_lead",
        override_decision=PolicyDecision.HITL_SOFT_REJECTION,
        reason_code="confirm_review",
    )
    second = evaluations.record_override(
        evaluation.id,
        reviewer_id="recruiter-2",
        reviewer_role="recruiter_lead",
        override_decision=PolicyDecision.REJECT_AUTO,
        reason_code="below_bar_after_review",
        notes="Discussed with the lead.",
    )

    overrides = evaluations.list_overrides(evaluation.id)
    assert [item.reason_code for item in overrides] == ["confirm_review", "below_bar_after_review"]
    assert second.receipt.prev_hash == first.receipt.entry_hash
    assert second.receipt.verify()


def test_override_requires_named_human_and_permitted_role(
    evaluations: EvaluationService,
) -> None:
    evaluation = make_evaluation()
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=evaluation,
        candidate_name="Budi",
        job_title="Engineer",
    )

    with pytest.raises(RecruitingError, match="named human"):
        evaluations.record_override(
            evaluation.id,
            reviewer_id="agent:screening_coordinator",
            reviewer_role="engineering_lead",
            override_decision=PolicyDecision.REJECT_AUTO,
            reason_code="x",
        )
    with pytest.raises(RecruitingError, match="cannot override"):
        evaluations.record_override(
            evaluation.id,
            reviewer_id="someone",
            reviewer_role="manager",
            override_decision=PolicyDecision.REJECT_AUTO,
            reason_code="x",
        )
    with pytest.raises(RecruitingError, match="reason code"):
        evaluations.record_override(
            evaluation.id,
            reviewer_id="lead-1",
            reviewer_role="engineering_lead",
            override_decision=PolicyDecision.REJECT_AUTO,
            reason_code="  ",
        )


def test_override_syncs_application_status(audit: AuditChain) -> None:
    store = ApplicationStore()
    record, _ = store.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    service = EvaluationService(audit=audit, applications=store)
    evaluation = make_evaluation(
        candidate_id=record.candidate_id, s_tech=0.60, recommendation=Recommendation.REJECT
    )
    service.register(
        application_id=record.id,
        evaluation=evaluation,
        candidate_name="Budi",
        job_title="Engineer",
    )
    assert record.status.value == "rejected"  # REJECT recommendation maps to rejected

    service.record_override(
        evaluation.id,
        reviewer_id="lead-1",
        reviewer_role="engineering_lead",
        override_decision=PolicyDecision.HITL_MANUAL,
        reason_code="reconsider",
    )
    assert record.status.value == "gated"


# --- feedback -----------------------------------------------------------------------


def test_synthesized_feedback_uses_breakdown(evaluations: EvaluationService) -> None:
    breakdown = [
        DimensionScore(
            dimension=ScoreDimension.TECHNICAL_DEPTH, score=0.9, weight=0.4, rationale="strong"
        ),
        DimensionScore(
            dimension=ScoreDimension.STACK_ALIGNMENT, score=0.4, weight=0.3, rationale="weak"
        ),
        DimensionScore(
            dimension=ScoreDimension.SYSTEMS_LITERACY, score=0.85, weight=0.2, rationale="strong"
        ),
        DimensionScore(
            dimension=ScoreDimension.VERIFIABLE_CERTIFICATIONS,
            score=0.3,
            weight=0.1,
            rationale="none",
        ),
    ]
    evaluation = make_evaluation(s_tech=0.71, breakdown=breakdown)
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=evaluation,
        candidate_name="Budi",
        job_title="Backend Engineer",
    )

    report = evaluations.feedback_for(CANDIDATE_ID)

    assert report.candidate_name == "Budi"
    assert report.job_title == "Backend Engineer"
    assert [item.dimension for item in report.strengths] == [
        ScoreDimension.TECHNICAL_DEPTH,
        ScoreDimension.SYSTEMS_LITERACY,
    ]
    assert [item.dimension for item in report.growth_areas] == [
        ScoreDimension.VERIFIABLE_CERTIFICATIONS,
        ScoreDimension.STACK_ALIGNMENT,
    ]
    assert "0.4" not in report.summary  # no raw scores in prose


def test_feedback_language_id(evaluations: EvaluationService) -> None:
    evaluation = make_evaluation()
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=evaluation,
        candidate_name="Budi",
        job_title="Backend Engineer",
    )
    report = evaluations.feedback_for(CANDIDATE_ID, language="id")
    assert report.language == "id"
    assert "hubungi HR" in report.correction_notice


def test_stored_feedback_takes_precedence(evaluations: EvaluationService) -> None:
    evaluation = make_evaluation()
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=evaluation,
        candidate_name="Budi",
        job_title="Engineer",
    )
    from hr_agents.models import FeedbackReport

    stored = FeedbackReport(
        candidate_name="Budi",
        job_title="Engineer",
        summary="Agent-authored summary.",
        process_note="Written by the feedback agent from the evidence.",
        correction_notice="Contact HR for corrections.",
    )
    evaluations.save_feedback(CANDIDATE_ID, stored, by="agent:feedback_writer")
    assert evaluations.feedback_for(CANDIDATE_ID).summary == "Agent-authored summary."


def test_synthesize_feedback_handles_empty_band() -> None:
    evaluation = make_evaluation(s_tech=0.2)
    report = synthesize_feedback(
        evaluation, candidate_name="Budi", job_title="Engineer", language="en"
    )
    assert report.strengths == []
    assert len(report.growth_areas) == 2


# --- scheduling ------------------------------------------------------------------------


def test_proposal_requires_evaluation(scheduling: SchedulingService) -> None:
    with pytest.raises(RecruitingError, match="no evaluation"):
        scheduling.propose(candidate_id=uuid4(), job_id=uuid4(), interviewer_ids=[uuid4()])


def test_proposal_requires_availability(
    scheduling: SchedulingService, evaluations: EvaluationService
) -> None:
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=make_evaluation(),
        candidate_name="Budi",
        job_title="Engineer",
    )
    with pytest.raises(RecruitingError, match="no interviewer availability"):
        scheduling.propose(candidate_id=CANDIDATE_ID, job_id=uuid4(), interviewer_ids=[uuid4()])


def test_auto_scheduling_inside_policy_bounds(
    scheduling: SchedulingService, evaluations: EvaluationService
) -> None:
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=make_evaluation(s_tech=0.90, sigma=0.0),
        candidate_name="Budi",
        job_title="Engineer",
    )
    first, second = uuid4(), uuid4()
    scheduling.set_availability(first, slots=make_slots(3), by="hr-admin")
    scheduling.set_availability(second, slots=make_slots(3), by="hr-admin")

    proposal = scheduling.propose(
        candidate_id=CANDIDATE_ID,
        job_id=uuid4(),
        interviewer_ids=[first, second],
        requested_channels=[SchedulingChannel.WHATSAPP],
    )

    assert proposal.payload.auto_scheduled is True
    assert proposal.requires_human_approval is False
    assert proposal.needs_human_reconciliation is False
    assert proposal.payload.channel is SchedulingChannel.WHATSAPP
    assert len(proposal.payload.slots) == 3


def test_calendar_constraint_routes_to_human(
    scheduling: SchedulingService, evaluations: EvaluationService
) -> None:
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=make_evaluation(s_tech=0.90),
        candidate_name="Budi",
        job_title="Engineer",
    )
    first, second = uuid4(), uuid4()
    scheduling.set_availability(first, slots=make_slots(2), by="hr-admin")
    scheduling.set_availability(second, slots=make_slots(2, offset_hours=10), by="hr-admin")

    proposal = scheduling.propose(
        candidate_id=CANDIDATE_ID, job_id=uuid4(), interviewer_ids=[first, second]
    )

    assert proposal.payload.auto_scheduled is False
    assert proposal.requires_human_approval is True
    assert proposal.needs_human_reconciliation is True
    assert proposal.payload.policy.decision is PolicyDecision.HITL_CALENDAR
    assert proposal.payload.slots  # union offered for human reconciliation


def test_flags_block_auto_scheduling(
    scheduling: SchedulingService, evaluations: EvaluationService
) -> None:
    evaluations.register(
        application_id=APPLICATION_ID,
        evaluation=make_evaluation(s_tech=0.95, flags=[EvaluationFlag.INJECTION_SUSPECTED]),
        candidate_name="Budi",
        job_title="Engineer",
    )
    interviewer = uuid4()
    scheduling.set_availability(interviewer, slots=make_slots(3), by="hr-admin")

    proposal = scheduling.propose(
        candidate_id=CANDIDATE_ID, job_id=uuid4(), interviewer_ids=[interviewer]
    )

    assert proposal.payload.policy.decision is PolicyDecision.HITL_ANOMALY
    assert proposal.requires_human_approval is True
    assert proposal.payload.auto_scheduled is False


def test_availability_replacement(
    scheduling: SchedulingService,
) -> None:
    interviewer = uuid4()
    scheduling.set_availability(interviewer, slots=make_slots(3), by="hr-admin")
    scheduling.set_availability(interviewer, slots=make_slots(1), by="hr-admin")
    assert len(scheduling.get_availability(interviewer)) == 1


# --- container -------------------------------------------------------------------------


def test_recruiting_services_share_one_audit_chain() -> None:
    services = RecruitingServices()
    services.documents.upload(filename="c.txt", kind="cv", content=b"x", uploaded_by="hr")
    services.jobs.create(title="X", created_by="hr")
    assert [entry.action for entry in services.audit.entries] == [
        "document.uploaded",
        "job.created",
    ]
