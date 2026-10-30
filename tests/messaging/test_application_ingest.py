"""Email application ingestion — drafts before consent, never guesses."""

from uuid import uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.messaging.application_ingest import (
    ApplicationIngestor,
    normalize_subject,
    suggest_job,
)
from hr_agents.messaging.base import InboundAttachment, InboundEmail
from hr_agents.messaging.contacts import InMemoryCandidateDirectory
from hr_agents.messaging.drafts import EmailDraftStatus, EmailDraftStore
from hr_agents.models import (
    DimensionScore,
    JobStatus,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
)
from hr_agents.services import AuditChain
from hr_agents.services.recruiting import (
    CommunicationService,
    DocumentService,
    EvaluationService,
    JobService,
)
from hr_agents.services.scanning import ScanOutcome, ScanResult

CANDIDATE_EMAIL = "budi@example.com"
APPLICANT = "rani@example.com"


def make_attachment(
    filename: str = "cv.pdf", content: bytes = b"%PDF-1.4 fake cv body"
) -> InboundAttachment:
    return InboundAttachment(
        filename=filename,
        content_type="application/pdf",
        size_bytes=len(content),
        content=content,
    )


def make_message(**overrides: object) -> InboundEmail:
    payload: dict[str, object] = {
        "provider": "email.imap_poll",
        "from_address": APPLICANT,
        "from_name": "Rani",
        "to_address": "hiring@example.com",
        "subject": "Lamaran Backend Engineer",
        "body": "Please consider my application.",
        "message_id": "<app-1@example.com>",
        "attachments": [],
        "skipped_attachments": [],
    }
    payload.update(overrides)
    return InboundEmail(**payload)  # type: ignore[arg-type]


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def evaluations(audit: AuditChain) -> EvaluationService:
    return EvaluationService(audit=audit)


@pytest.fixture
def communications(evaluations: EvaluationService, audit: AuditChain) -> CommunicationService:
    return CommunicationService(evaluations=evaluations, audit=audit)


@pytest.fixture
def ingestor(communications: CommunicationService, audit: AuditChain) -> ApplicationIngestor:
    return ApplicationIngestor(
        drafts=EmailDraftStore(),
        documents=DocumentService(audit=audit),
        jobs=JobService(audit=audit),
        communications=communications,
        audit=audit,
    )


def register_candidate(evaluations: EvaluationService, candidate_id) -> None:  # type: ignore[no-untyped-def]
    vector = ScoreVector(
        technical_depth=0.90,
        stack_alignment=0.90,
        systems_literacy=0.90,
        verifiable_certifications=0.90,
    )
    evaluations.register(
        application_id=uuid4(),
        evaluation=TechnicalEvaluation(
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
                DimensionScore(dimension=dimension, score=0.90, weight=0.25, rationale="e")
                for dimension in ScoreDimension
            ],
            flags=[],
            recommendation=Recommendation.HUMAN_REVIEW,
        ),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )


def test_reply_thread_is_left_to_the_reply_bridge(
    ingestor: ApplicationIngestor,
    evaluations: EvaluationService,
    communications: CommunicationService,
) -> None:
    candidate_id = uuid4()
    register_candidate(evaluations, candidate_id)
    queued = communications.queue_offer(
        candidate_id,
        actor=ActorRef.legacy("hr-admin"),
        body="Offer body",
        to_email=CANDIDATE_EMAIL,
    )
    communications.record_dispatch(
        queued.id,
        provider="email.smtp",
        recipient=CANDIDATE_EMAIL,
        message_id="<outbound-9@example.com>",
    )

    report = ingestor.ingest(
        [make_message(in_reply_to="<outbound-9@example.com>", attachments=[make_attachment()])]
    )

    assert (report.drafted, report.skipped_is_reply) == (0, 1)


def test_mail_without_attachments_is_not_an_application(
    ingestor: ApplicationIngestor,
) -> None:
    report = ingestor.ingest([make_message()])

    assert (report.drafted, report.skipped_no_attachments) == (0, 1)


def test_application_becomes_a_consent_pending_draft(
    ingestor: ApplicationIngestor, audit: AuditChain
) -> None:
    report = ingestor.ingest([make_message(attachments=[make_attachment()])])

    assert report.drafted == 1
    (outcome,) = report.outcomes
    assert outcome.drafted and outcome.draft_id is not None
    draft = ingestor._drafts.get(outcome.draft_id)
    assert draft is not None
    assert draft.status is EmailDraftStatus.PENDING
    assert draft.sender == APPLICANT
    assert draft.document_ids and len(draft.document_ids) == 1
    assert draft.attachment_names == ["cv.pdf"]
    assert draft.suggested_job_id is None
    assert any(entry.action == "application.draft_received" for entry in audit.entries)


def test_first_attachment_is_the_cv_rest_are_other(
    ingestor: ApplicationIngestor,
) -> None:
    report = ingestor.ingest(
        [
            make_message(
                attachments=[
                    make_attachment("cv.pdf"),
                    make_attachment("portfolio.pdf", content=b"%PDF-1.4 portfolio"),
                ]
            )
        ]
    )

    assert report.drafted == 1
    stored = ingestor._documents.list_all()
    assert sorted(document.kind for document in stored) == ["cv", "other"]


def test_repolling_the_same_mail_does_not_draft_twice(
    ingestor: ApplicationIngestor,
) -> None:
    message = make_message(attachments=[make_attachment()])

    ingestor.ingest([message])
    report = ingestor.ingest([message])

    assert (report.drafted, report.duplicates) == (0, 1)


def test_exact_job_title_is_suggested(ingestor: ApplicationIngestor, audit: AuditChain) -> None:
    job = ingestor._jobs.create(
        title="Backend Engineer",
        actor=ActorRef.legacy("hr-admin"),
        status=JobStatus.OPEN,
    )

    report = ingestor.ingest(
        [make_message(subject="Re: Lamaran Backend Engineer", attachments=[make_attachment()])]
    )

    assert report.drafted == 1
    draft = ingestor._drafts.get(report.outcomes[0].draft_id)  # type: ignore[arg-type]
    assert draft is not None
    assert draft.suggested_job_id == job.id


def test_near_miss_title_stays_unassigned(
    ingestor: ApplicationIngestor,
) -> None:
    ingestor._jobs.create(
        title="Backend Engineer",
        actor=ActorRef.legacy("hr-admin"),
        status=JobStatus.OPEN,
    )

    report = ingestor.ingest(
        [make_message(subject="Backend Enginer", attachments=[make_attachment()])]
    )

    assert report.drafted == 1
    draft = ingestor._drafts.get(report.outcomes[0].draft_id)  # type: ignore[arg-type]
    assert draft is not None
    assert draft.suggested_job_id is None


def test_closed_job_is_never_suggested(
    ingestor: ApplicationIngestor,
) -> None:
    ingestor._jobs.create(
        title="Backend Engineer",
        actor=ActorRef.legacy("hr-admin"),
        status=JobStatus.CLOSED,
    )

    report = ingestor.ingest(
        [make_message(subject="Backend Engineer", attachments=[make_attachment()])]
    )

    assert report.drafted == 1
    draft = ingestor._drafts.get(report.outcomes[0].draft_id)  # type: ignore[arg-type]
    assert draft is not None
    assert draft.suggested_job_id is None


def test_bodyless_mail_with_cv_still_drafts(
    ingestor: ApplicationIngestor,
) -> None:
    report = ingestor.ingest(
        [make_message(body="", attachments=[make_attachment()], message_id="<app-2@x.com>")]
    )

    assert report.drafted == 1


class FixedScanner:
    def __init__(self, outcome: ScanOutcome, detail: str = "") -> None:
        self._result = ScanResult(outcome=outcome, scanner="fixed", detail=detail)

    def scan(self, content: bytes, *, filename: str | None = None) -> ScanResult:
        return self._result


def test_infected_attachment_is_refused_not_stored(
    communications: CommunicationService, audit: AuditChain
) -> None:
    ingestor = ApplicationIngestor(
        drafts=EmailDraftStore(),
        documents=DocumentService(
            audit=audit, scanner=FixedScanner(ScanOutcome.INFECTED, detail="eicar")
        ),
        jobs=JobService(audit=audit),
        communications=communications,
        audit=audit,
    )

    report = ingestor.ingest([make_message(attachments=[make_attachment()])])

    assert report.drafted == 1
    draft = ingestor._drafts.get(report.outcomes[0].draft_id)  # type: ignore[arg-type]
    assert draft is not None
    assert draft.document_ids == []
    assert any("malware" in note for note in draft.refused_attachments)


def test_normalize_subject_strips_prefixes() -> None:
    assert normalize_subject("Re: Fwd: Lamaran Backend Engineer") == "backend engineer"
    assert normalize_subject("Application for Data Analyst") == "data analyst"
    assert normalize_subject("  Posisi: QA Engineer --") == "qa engineer"


def test_suggest_job_requires_exact_equality() -> None:
    job_id = uuid4()
    titles = {"backend engineer": job_id}

    assert suggest_job("Backend Engineer", titles) == job_id
    assert suggest_job("Backend Enginer", titles) is None
    assert suggest_job("Senior Backend Engineer", titles) is None
    assert suggest_job("", titles) is None


def test_directory_match_does_not_stop_a_draft(
    ingestor: ApplicationIngestor,
) -> None:
    ingestor._directory = InMemoryCandidateDirectory()
    ingestor._directory.add(uuid4(), APPLICANT)

    report = ingestor.ingest([make_message(attachments=[make_attachment()])])

    assert report.drafted == 1
