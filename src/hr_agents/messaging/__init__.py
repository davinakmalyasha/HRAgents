"""Messaging bridges — transport ports, adapters, and the outbox/reply services.

The candidate outbox is the source of truth for consequential messages; this
package carries them over whatever email transport an operator configured
(SMTP by default, IMAP polling for replies) and records the evidence. Nothing
here approves, composes, or decides anything.
"""

from hr_agents.messaging.application_ingest import (
    ApplicationIngestor,
    ApplicationIngestReport,
    normalize_subject,
    suggest_job,
)
from hr_agents.messaging.base import (
    EmailReceiver,
    EmailSender,
    InboundAttachment,
    InboundEmail,
    OutboundEmail,
    SendResult,
    TransportError,
)
from hr_agents.messaging.contacts import CandidateDirectory, InMemoryCandidateDirectory
from hr_agents.messaging.drafts import (
    EmailApplicationDraft,
    EmailDraftStatus,
    EmailDraftStore,
    draft_dedup_key,
)
from hr_agents.messaging.imap import IMAP_PROVIDER_ID, ImapEmailReceiver
from hr_agents.messaging.inbound import IngestReport, ReplyIngestor
from hr_agents.messaging.outbox import DispatchPreview, DispatchReport, OutboxDispatcher
from hr_agents.messaging.runtime import (
    DisabledEmailSender,
    MessagingConfigError,
    MessagingServices,
    build_email_receiver,
    build_email_sender,
)
from hr_agents.messaging.smtp import SMTP_PROVIDER_ID, SmtpEmailSender
from hr_agents.messaging.store import ReplyStore, reply_dedup_key

__all__ = [
    "IMAP_PROVIDER_ID",
    "SMTP_PROVIDER_ID",
    "ApplicationIngestReport",
    "ApplicationIngestor",
    "CandidateDirectory",
    "DisabledEmailSender",
    "DispatchPreview",
    "DispatchReport",
    "EmailApplicationDraft",
    "EmailDraftStatus",
    "EmailDraftStore",
    "EmailReceiver",
    "EmailSender",
    "ImapEmailReceiver",
    "InMemoryCandidateDirectory",
    "InboundAttachment",
    "InboundEmail",
    "IngestReport",
    "MessagingConfigError",
    "MessagingServices",
    "OutboundEmail",
    "OutboxDispatcher",
    "ReplyIngestor",
    "ReplyStore",
    "SendResult",
    "SmtpEmailSender",
    "TransportError",
    "build_email_receiver",
    "build_email_sender",
    "draft_dedup_key",
    "normalize_subject",
    "reply_dedup_key",
    "suggest_job",
]
