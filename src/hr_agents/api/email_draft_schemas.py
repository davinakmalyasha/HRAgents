"""Email application draft schemas — consent-pending CVs from the hiring mailbox."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from hr_agents.messaging.drafts import EmailApplicationDraft
from hr_agents.models import StrictModel, UtcDateTime


class EmailDraftView(StrictModel):
    id: UUID
    sender: str
    sender_name: str
    subject: str
    body: str
    attachment_names: list[str]
    refused_attachments: list[str]
    document_ids: list[UUID]
    suggested_job_id: UUID | None
    status: str
    application_id: UUID | None
    decided_by: str | None
    discard_reason: str | None
    received_at: UtcDateTime

    @classmethod
    def from_draft(cls, draft: EmailApplicationDraft) -> EmailDraftView:
        return cls(
            id=draft.id,
            sender=draft.sender,
            sender_name=draft.sender_name,
            subject=draft.subject,
            body=draft.body,
            attachment_names=list(draft.attachment_names),
            refused_attachments=list(draft.refused_attachments),
            document_ids=list(draft.document_ids),
            suggested_job_id=draft.suggested_job_id,
            status=draft.status.value,
            application_id=draft.application_id,
            decided_by=draft.decided_by,
            discard_reason=draft.discard_reason,
            received_at=draft.received_at,
        )


class DraftConfirm(StrictModel):
    """Confirm a draft into an application. Consent is caller-supplied, never inferred."""

    job_id: UUID
    consent_granted: bool
    candidate_name: str | None = Field(default=None, max_length=200)


class DraftDiscard(StrictModel):
    reason: str = Field(min_length=1, max_length=1000)
