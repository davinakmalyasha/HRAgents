"""Runtime resolution for the messaging transports.

Everything about *which* transport is active is configuration: the provider
layer resolves ``email_send``/``email_receive`` specs from the environment, and
this module turns the resolved spec into the object the bridge uses. With
``HRAGENTS_MESSAGING_SANDBOX=true`` (the default) no transport is active at all —
queued messages stay queued and inbound polling is disabled, exactly like the
documented degradation matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hr_agents.config import Settings, get_settings
from hr_agents.messaging.base import (
    EmailReceiver,
    EmailSender,
    OutboundEmail,
    SendResult,
    TransportError,
)
from hr_agents.messaging.contacts import CandidateDirectory
from hr_agents.messaging.inbound import ReplyIngestor
from hr_agents.messaging.outbox import OutboxDispatcher
from hr_agents.messaging.store import ReplyStore
from hr_agents.providers.base import Capability
from hr_agents.providers.email import SmtpSenderConfig
from hr_agents.providers.registry import ProviderRegistry
from hr_agents.providers.registry import default_registry as default_provider_registry
from hr_agents.providers.settings import ResolvedProvider, resolve_provider_settings
from hr_agents.services.audit import AuditChain
from hr_agents.services.recruiting import CommunicationService


class MessagingConfigError(RuntimeError):
    """Raised when the messaging provider configuration cannot be used."""


@dataclass
class MessagingServices:
    """Resolved transports plus the stores the bridge writes to."""

    sender: EmailSender
    receiver: EmailReceiver | None
    replies: ReplyStore
    directory: CandidateDirectory
    live: bool

    @property
    def provider_id(self) -> str:
        return self.sender.provider_id

    def dispatcher(self, communications: CommunicationService) -> OutboxDispatcher:
        """The outbox bridge over the resolved transport."""
        return OutboxDispatcher(
            communications=communications,
            sender=self.sender,
            directory=self.directory,
        )

    def ingestor(
        self,
        communications: CommunicationService,
        *,
        audit: AuditChain | None = None,
    ) -> ReplyIngestor:
        """The reply bridge; requires a receiver, so callers check ``receiver`` first."""
        return ReplyIngestor(
            replies=self.replies,
            communications=communications,
            directory=self.directory,
            audit=audit,
        )


class DisabledEmailSender:
    """Stands in when no transport is active; carrying a message is an error.

    The bridge never records a fake dispatch: with the sandbox on, the operator
    gets a preview of what would be sent and the queue stays untouched.
    """

    @property
    def provider_id(self) -> str:
        return "email.disabled"

    def send(self, message: OutboundEmail) -> SendResult:
        raise TransportError(
            "messaging sandbox is enabled; set HRAGENTS_MESSAGING_SANDBOX=false "
            "and configure a provider to dispatch"
        )


def _smtp_defaults(settings: Settings) -> dict[str, Any]:
    """Legacy ``HRAGENTS_SMTP_*`` settings, used when no provider config is given."""
    return {
        "host": settings.smtp_host,
        "port": settings.smtp_port,
        "from_address": settings.smtp_from,
    }


def _resolved(capability: Capability) -> ResolvedProvider | None:
    return resolve_provider_settings().get(capability)


def build_email_sender(
    *,
    settings: Settings | None = None,
    registry: ProviderRegistry | None = None,
) -> EmailSender:
    """Resolve the active ``email_send`` transport (sandbox-safe)."""
    resolved_settings = settings or get_settings()
    if resolved_settings.messaging_sandbox:
        return DisabledEmailSender()
    selected = _resolved(Capability.EMAIL_SEND)
    spec = (registry or default_provider_registry()).resolve(
        Capability.EMAIL_SEND,
        selected.provider_id if selected else None,
    )
    raw = dict(selected.config) if selected and selected.config else {}
    if not raw and issubclass(spec.config_model, SmtpSenderConfig):
        raw = _smtp_defaults(resolved_settings)
    return spec.apply(spec.make_config(raw))


def build_email_receiver(
    *,
    settings: Settings | None = None,
    registry: ProviderRegistry | None = None,
) -> EmailReceiver | None:
    """Resolve the active ``email_receive`` transport, or ``None`` when inactive."""
    resolved_settings = settings or get_settings()
    if resolved_settings.messaging_sandbox:
        return None
    selected = _resolved(Capability.EMAIL_RECEIVE)
    spec = (registry or default_provider_registry()).resolve(
        Capability.EMAIL_RECEIVE,
        selected.provider_id if selected else None,
    )
    built = spec.apply(
        spec.make_config(dict(selected.config) if selected and selected.config else {})
    )
    if not hasattr(built, "poll"):
        return None
    return built
