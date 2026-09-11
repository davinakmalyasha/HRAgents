"""Request/response schemas for the public API (mirrors docs/api/openapi.yaml)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import EmailStr, Field

from hr_agents.models import StrictModel
from hr_agents.services.ingestion import ApplicationRecord, SubmissionInput


class ConsentInput(StrictModel):
    granted: bool
    policy_version: str = "1.0"


class CandidateInput(StrictModel):
    full_name: str = ""
    emails: list[EmailStr] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    links: dict[str, Any] = Field(default_factory=dict)


class DocumentRef(StrictModel):
    document_id: UUID
    kind: str = "other"


class ApplicationSubmission(StrictModel):
    job_id: UUID
    source_channel: str = "api"
    consent: ConsentInput
    candidate: CandidateInput | None = None
    documents: list[DocumentRef] = Field(default_factory=list)
    questionnaire: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_input(self) -> SubmissionInput:
        candidate = self.candidate or CandidateInput()
        return SubmissionInput(
            job_id=self.job_id,
            source_channel=self.source_channel,
            consent_granted=self.consent.granted,
            consent_policy_version=self.consent.policy_version,
            candidate_name=candidate.full_name,
            candidate_emails=[str(email) for email in candidate.emails],
            candidate_links=candidate.links,
            document_ids=[doc.document_id for doc in self.documents],
            questionnaire=self.questionnaire,
            metadata=self.metadata,
        )


class ApplicationAccepted(StrictModel):
    application_id: UUID
    candidate_id: UUID
    status: str
    queued_at: datetime


class BatchSubmissionRequest(StrictModel):
    items: list[ApplicationSubmission] = Field(min_length=1, max_length=500)


class BatchItemResult(StrictModel):
    application_id: UUID | None = None
    status: str
    error: str | None = None


class BatchAccepted(StrictModel):
    accepted: int
    items: list[BatchItemResult] = Field(default_factory=list)


class TimelineEvent(StrictModel):
    at: datetime
    event: str


class ApplicationStatusResponse(StrictModel):
    application_id: UUID
    candidate_id: UUID
    job_id: UUID
    status: str
    received_at: datetime
    s_tech: float | None = None
    sigma: float | None = None
    priority_score: float
    timeline: list[TimelineEvent] = Field(default_factory=list)

    @classmethod
    def from_record(cls, record: ApplicationRecord) -> ApplicationStatusResponse:
        return cls(
            application_id=record.id,
            candidate_id=record.candidate_id,
            job_id=record.job_id,
            status=record.status.value,
            received_at=record.received_at,
            s_tech=record.s_tech,
            sigma=record.sigma,
            priority_score=record.priority_score,
            timeline=[TimelineEvent(at=at, event=event) for at, event in record.timeline],
        )


class QueueEntry(StrictModel):
    application_id: UUID
    candidate_id: UUID
    status: str
    priority_score: float
    s_tech: float | None = None
    hours_waiting: float


class QueueResponse(StrictModel):
    items: list[QueueEntry] = Field(default_factory=list)
