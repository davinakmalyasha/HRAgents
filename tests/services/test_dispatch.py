"""Evaluation dispatch: what gets queued, and what is honestly not.


The dispatcher owns the message payload the worker expects. These tests pin the
source-text resolution, the document ordering, the skip path, and the
undispatchable stand-in used when no queue is reachable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.providers.queue import MemoryQueueBackend
from hr_agents.services.dispatch import (
    DispatchSkipped,
    EvaluationDispatcher,
    UndispatchedDispatcher,
)
from hr_agents.services.evaluation_job import EVALUATION_TOPIC
from hr_agents.services.ingestion import ApplicationRecord, ApplicationStore, SubmissionInput
from hr_agents.services.recruiting import DocumentService

NOW = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def documents() -> DocumentService:
    return DocumentService()


@pytest.fixture
def queue() -> MemoryQueueBackend:
    return MemoryQueueBackend()


@pytest.fixture
def submission() -> SubmissionInput:
    return SubmissionInput(
        job_id=uuid4(),
        source_channel="api",
        consent_granted=True,
        candidate_name="Budi Santoso",
    )


def upload(documents: DocumentService, *, body: bytes, kind: str, filename: str) -> UUID:
    return documents.upload(
        content=body,
        kind=kind,
        filename=filename,
        actor=ActorRef.legacy("hr-admin"),
    ).id


def make_record(submission: SubmissionInput) -> tuple[ApplicationRecord, bool]:
    store = ApplicationStore()
    return store.submit(submission)


# --- source text resolution ---------------------------------------------------


def test_resolves_text_from_a_single_document(
    documents: DocumentService, queue: MemoryQueueBackend
) -> None:
    document_id = upload(
        documents, body=b"Backend engineer. Eight years of Python.", kind="cv", filename="cv.txt"
    )
    dispatcher = EvaluationDispatcher(queue=queue, documents=documents)

    text, primary = dispatcher.resolve_source_text([document_id])

    assert "Backend engineer" in text
    assert primary is not None
    assert primary.id == document_id


def test_cv_wins_over_a_questionnaire(
    documents: DocumentService, queue: MemoryQueueBackend
) -> None:
    """Document order is a policy, not submission order."""
    questionnaire_id = upload(
        documents, body=b"Why do you want this job?", kind="questionnaire", filename="q.txt"
    )
    cv_id = upload(documents, body=b"Actual CV content", kind="cv", filename="cv.txt")
    dispatcher = EvaluationDispatcher(queue=queue, documents=documents)

    text, primary = dispatcher.resolve_source_text([questionnaire_id, cv_id])

    assert primary is not None
    assert primary.id == cv_id
    # Both bodies are carried; the primary is what anchors the ordering.
    assert "Actual CV content" in text
    assert "Why do you want this job?" in text


def test_unknown_document_ids_are_ignored(
    documents: DocumentService, queue: MemoryQueueBackend
) -> None:
    known = upload(documents, body=b"real content", kind="cv", filename="cv.txt")
    dispatcher = EvaluationDispatcher(queue=queue, documents=documents)

    text, _primary = dispatcher.resolve_source_text([uuid4(), known])

    assert "real content" in text


def test_missing_documents_skip_rather_than_guess(
    documents: DocumentService, queue: MemoryQueueBackend
) -> None:
    dispatcher = EvaluationDispatcher(queue=queue, documents=documents)

    with pytest.raises(DispatchSkipped, match="no readable document"):
        dispatcher.resolve_source_text([])


def test_empty_document_body_skips(documents: DocumentService, queue: MemoryQueueBackend) -> None:
    blank = upload(documents, body=b"   \n  ", kind="cv", filename="cv.txt")
    dispatcher = EvaluationDispatcher(queue=queue, documents=documents)

    with pytest.raises(DispatchSkipped, match="no extractable text"):
        dispatcher.resolve_source_text([blank])


# --- publishing ---------------------------------------------------------------


def test_dispatch_publishes_the_payload_the_handler_expects(
    documents: DocumentService, queue: MemoryQueueBackend
) -> None:
    document_id = upload(documents, body=b"Resume body", kind="cv", filename="cv.txt")
    submission = SubmissionInput(
        job_id=uuid4(),
        source_channel="api",
        consent_granted=True,
        candidate_name="Budi Santoso",
        document_ids=[document_id],
    )
    store = ApplicationStore()
    record, _created = store.submit(submission)
    dispatcher = EvaluationDispatcher(queue=queue, documents=documents)

    message_id = asyncio.run(dispatcher.dispatch(record, submission))

    assert message_id
    messages = asyncio.run(queue.claim(EVALUATION_TOPIC))
    assert len(messages) == 1
    payload = messages[0].payload
    assert payload["application_id"] == str(record.id)
    assert payload["job_id"] == str(submission.job_id)
    assert payload["resume_text"] == "Resume body"
    assert payload["candidate_name"] == "Budi Santoso"


def test_dispatch_skips_when_there_is_nothing_to_extract(
    documents: DocumentService, queue: MemoryQueueBackend
) -> None:
    submission = SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    record, _created = make_record(submission)
    dispatcher = EvaluationDispatcher(queue=queue, documents=documents)

    with pytest.raises(DispatchSkipped):
        asyncio.run(dispatcher.dispatch(record, submission))

    assert asyncio.run(queue.stats(EVALUATION_TOPIC)).pending == 0


# --- the undispatchable stand-in ---------------------------------------------


def test_undispatched_dispatcher_refuses_with_the_outage_reason() -> None:
    dispatcher = UndispatchedDispatcher("redis unreachable at redis://redis:6379/0")
    record, _created = make_record(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )

    with pytest.raises(DispatchSkipped, match="redis unreachable"):
        asyncio.run(
            dispatcher.dispatch(
                record, SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
            )
        )
