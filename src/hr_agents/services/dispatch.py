"""Evaluation dispatch: turn an accepted application into queued work.

One owner for "what gets evaluated, and from which text". The submission routers
and the worker both go through here so the message payload can never drift from
what :class:`~hr_agents.services.evaluation_job.EvaluationJobHandler` expects.
"""

from __future__ import annotations

from uuid import UUID

from hr_agents.providers.queue import QueueBackend
from hr_agents.services.documents import extract_text
from hr_agents.services.evaluation_job import EVALUATION_TOPIC, evaluation_payload
from hr_agents.services.ingestion import ApplicationRecord, SubmissionInput
from hr_agents.services.recruiting import DocumentService, RecruitingError, StoredDocument

# Preference order when a submission references several documents: the CV is the
# primary narrative, a portfolio or LinkedIn export is supplementary.
_SOURCE_KIND_PRIORITY = ("cv", "portfolio", "linkedin_export", "other", "questionnaire")


class DispatchSkipped(Exception):
    """The application cannot be evaluated — no extractable source text."""


class EvaluationDispatcher:
    """Publishes accepted applications onto the evaluation queue."""

    def __init__(self, *, queue: QueueBackend, documents: DocumentService) -> None:
        self._queue = queue
        self._documents = documents

    def resolve_source_text(self, document_ids: list[UUID]) -> tuple[str, StoredDocument | None]:
        """Concatenate the extractable text of the submission's documents.

        Returns the text and the primary document, or raises
        :class:`DispatchSkipped` when nothing can be read. PII redaction happens
        inside the agent's injection guard path, not here, so the message carries
        exactly what was submitted.
        """
        ordered: list[StoredDocument] = []
        for document_id in document_ids:
            try:
                ordered.append(self._documents.get(document_id))
            except RecruitingError:
                continue

        if not ordered:
            raise DispatchSkipped("submission referenced no readable document")

        def rank(document: StoredDocument) -> tuple[int, str]:
            try:
                return (_SOURCE_KIND_PRIORITY.index(document.kind), document.filename or "")
            except ValueError:
                return (len(_SOURCE_KIND_PRIORITY), document.filename or "")

        ordered.sort(key=rank)
        parts = [extract_text(document.content, document.filename or "") for document in ordered]
        text = "\n\n".join(part for part in parts if part).strip()
        if not text:
            raise DispatchSkipped("referenced documents produced no extractable text")
        return text, ordered[0]

    async def dispatch(self, record: ApplicationRecord, submission: SubmissionInput) -> str:
        """Publish one application for evaluation; returns the queue message id."""
        resume_text, _primary = self.resolve_source_text(list(submission.document_ids))
        payload = evaluation_payload(
            application_id=record.id,
            job_id=record.job_id,
            resume_text=resume_text,
            candidate_name=submission.candidate_name,
        )
        return await self._queue.publish(EVALUATION_TOPIC, payload)


class UndispatchedDispatcher:
    """Stand-in used when no queue backend is reachable.

    Submissions are still accepted and stored — the application store is the
    system of record and dropping work because a broker is down would be worse.
    Every dispatch is refused with the outage reason, which the submission route
    writes to the audit chain, and :func:`hr_agents.main.readiness_report`
    surfaces the same outage. The application stays ``queued`` and is visible in
    the ``hragents_applications_stuck_queued`` metric.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def resolve_source_text(self, document_ids: list[UUID]) -> tuple[str, StoredDocument | None]:
        raise DispatchSkipped(self._reason)

    async def dispatch(self, record: ApplicationRecord, submission: SubmissionInput) -> str:
        raise DispatchSkipped(self._reason)
