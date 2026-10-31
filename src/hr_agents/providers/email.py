"""Email capability providers: sending and receiving.

Sending: SMTP (default — works with any mailbox) or Resend (API).
Receiving: IMAP polling (default — needs no public URL) or a Resend webhook.

The SMTP and IMAP specs build live adapters (``hr_agents.messaging``); the
Resend specs stay config-only until their HTTP adapters land. The messaging
bridges consume the resolved adapter through one interface, so companies choose
what to connect.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, SecretStr

from hr_agents.providers.base import (
    Capability,
    ProviderConfig,
    ProviderHealth,
)


class SmtpSenderConfig(ProviderConfig):
    """Send email through any existing mailbox."""

    host: str = "localhost"
    port: int = Field(default=587, ge=1, le=65535)
    username: str | None = None
    password: SecretStr | None = None
    use_starttls: bool = True
    use_ssl: bool = False
    from_address: str = "hragents@example.com"
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)


class ResendSenderConfig(ProviderConfig):
    api_key: SecretStr
    from_address: str = "hragents@example.com"
    base_url: str = "https://api.resend.com"


class ImapReceiverConfig(ProviderConfig):
    """Poll a mailbox for replies — no public webhook endpoint required."""

    host: str = "localhost"
    port: int = Field(default=993, ge=1, le=65535)
    username: str | None = None
    password: SecretStr | None = None
    mailbox: str = "INBOX"
    use_ssl: bool = True
    poll_seconds: int = Field(default=30, ge=5, le=3600)
    mark_seen: bool = True
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)


class ResendReceiverConfig(ProviderConfig):
    """Receive through a Resend webhook (requires a public HTTPS endpoint)."""

    webhook_secret: SecretStr
    signing_header: str = "svix-signature"


class GmailSenderConfig(ProviderConfig):
    """Send through the Gmail API with an OAuth refresh token (``gmail.send``)."""

    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    refresh_token: SecretStr
    from_address: str = "hragents@example.com"
    user_id: str = "me"
    base_url: str = "https://gmail.googleapis.com"
    token_url: str = "https://oauth2.googleapis.com/token"


# --- builders (SMTP/IMAP build live adapters; Resend stays config-only) ---


def _build_smtp(config: ProviderConfig) -> Any:
    from hr_agents.messaging.smtp import build_smtp_sender

    assert isinstance(config, SmtpSenderConfig)
    return build_smtp_sender(config)


def _build_resend(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, ResendSenderConfig)
    return {"transport": "resend", "from_address": config.from_address}


def _build_gmail(config: ProviderConfig) -> Any:
    from hr_agents.integrations.gmail import build_gmail_sender

    assert isinstance(config, GmailSenderConfig)
    return build_gmail_sender(config)


def _build_imap(config: ProviderConfig) -> Any:
    from hr_agents.messaging.imap import build_imap_receiver

    assert isinstance(config, ImapReceiverConfig)
    return build_imap_receiver(config)


def _build_resend_webhook(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, ResendReceiverConfig)
    return {"transport": "resend_webhook", "signing_header": config.signing_header}


# --- health checks -----------------------------------------------------------


def _health_smtp(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, SmtpSenderConfig)
    if config.username and config.password is None:
        return ProviderHealth.misconfigured("username set but password missing")
    if config.host == "localhost" and config.port != 1025:
        return ProviderHealth.ok("configured for local SMTP (Mailpit on 1025 in dev)")
    return ProviderHealth.ok(f"configured for {config.host}:{config.port}")


def _health_resend(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, ResendSenderConfig)
    if not config.api_key.get_secret_value():
        return ProviderHealth.misconfigured("api_key is required")
    return ProviderHealth.degraded(
        "api key is set but the live send adapter is not implemented; "
        "mail stays in the sandbox rather than sending"
    )


def _health_imap(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, ImapReceiverConfig)
    if config.username and config.password is None:
        return ProviderHealth.misconfigured("username set but password missing")
    return ProviderHealth.ok(f"configured to poll {config.host}/{config.mailbox}")


def _health_resend_webhook(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, ResendReceiverConfig)
    if not config.webhook_secret.get_secret_value():
        return ProviderHealth.misconfigured("webhook_secret is required")
    return ProviderHealth.ok(
        "Svix signatures are verified at /v1/webhooks/email/resend; "
        "the provider must be able to reach that public URL"
    )


def _health_gmail(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, GmailSenderConfig)
    if not config.refresh_token.get_secret_value():
        return ProviderHealth.misconfigured("refresh_token is required")
    if not config.from_address.strip():
        return ProviderHealth.misconfigured("from_address is required")
    return ProviderHealth.ok(
        "sends through the Gmail API; the OAuth client needs the gmail.send scope"
    )


def email_specs() -> list[Any]:
    from hr_agents.providers.base import ProviderSpec

    return [
        ProviderSpec(
            id="email.smtp",
            capability=Capability.EMAIL_SEND,
            display_name="SMTP (existing mailbox)",
            description="Send through your current mail provider. Works everywhere.",
            config_model=SmtpSenderConfig,
            build=_build_smtp,
            health_check=_health_smtp,
            requires_network=True,
            secret_fields=["password"],
        ),
        ProviderSpec(
            id="email.resend",
            capability=Capability.EMAIL_SEND,
            display_name="Resend",
            description="Transactional email API with delivery tracking.",
            docs_url="https://resend.com/docs",
            config_model=ResendSenderConfig,
            build=_build_resend,
            health_check=_health_resend,
            requires_network=True,
            secret_fields=["api_key"],
        ),
        ProviderSpec(
            id="email.gmail",
            capability=Capability.EMAIL_SEND,
            display_name="Gmail API",
            description=(
                "Send through a Google Workspace mailbox with an OAuth refresh token "
                "(gmail.send scope); threading headers are preserved."
            ),
            docs_url="https://developers.google.com/gmail/api/guides/sending",
            config_model=GmailSenderConfig,
            build=_build_gmail,
            health_check=_health_gmail,
            requires_network=True,
            secret_fields=["client_secret", "refresh_token"],
        ),
        ProviderSpec(
            id="email.imap_poll",
            capability=Capability.EMAIL_RECEIVE,
            display_name="IMAP polling",
            description="Read replies from any mailbox. No public URL required.",
            config_model=ImapReceiverConfig,
            build=_build_imap,
            health_check=_health_imap,
            requires_network=True,
            secret_fields=["password"],
        ),
        ProviderSpec(
            id="email.resend_webhook",
            capability=Capability.EMAIL_RECEIVE,
            display_name="Resend inbound webhook",
            description=(
                "Real-time inbound email via Svix-signed webhooks, verified at "
                "/v1/webhooks/email/resend (public HTTPS URL required)."
            ),
            docs_url="https://resend.com/docs/dashboard/receiving/introduction",
            config_model=ResendReceiverConfig,
            build=_build_resend_webhook,
            health_check=_health_resend_webhook,
            requires_network=True,
            secret_fields=["webhook_secret"],
        ),
    ]
