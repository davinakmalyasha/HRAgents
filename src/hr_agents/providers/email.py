"""Email capability providers: sending and receiving.

Sending: SMTP (default — works with any mailbox) or Resend (API).
Receiving: IMAP polling (default — needs no public URL) or a Resend webhook.

All providers are config-only; the messaging bridges (Phase 7) consume the
resolved adapter through one interface, so companies choose what to connect.
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
    from_address: str = "hragents@example.com"


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


class ResendReceiverConfig(ProviderConfig):
    """Receive through a Resend webhook (requires a public HTTPS endpoint)."""

    webhook_secret: SecretStr
    signing_header: str = "svix-signature"


# --- builders (adapters arrive in Phase 7; specs lock the config surface) ---


def _build_smtp(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, SmtpSenderConfig)
    return {
        "transport": "smtp",
        "host": config.host,
        "port": config.port,
        "use_starttls": config.use_starttls,
        "from_address": config.from_address,
    }


def _build_resend(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, ResendSenderConfig)
    return {"transport": "resend", "from_address": config.from_address}


def _build_imap(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, ImapReceiverConfig)
    return {
        "transport": "imap_poll",
        "host": config.host,
        "port": config.port,
        "mailbox": config.mailbox,
        "poll_seconds": config.poll_seconds,
    }


def _build_resend_webhook(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, ResendReceiverConfig)
    return {"transport": "resend_webhook", "signing_header": config.signing_header}


# --- health checks -----------------------------------------------------------


def _health_smtp(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, SmtpSenderConfig)
    if config.host == "localhost" and config.port != 1025:
        return ProviderHealth.ok("configured for local SMTP (Mailpit on 1025 in dev)")
    return ProviderHealth.ok(f"configured for {config.host}:{config.port}")


def _health_resend(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, ResendSenderConfig)
    if not config.api_key.get_secret_value():
        return ProviderHealth.misconfigured("api_key is required")
    return ProviderHealth.ok("configuration valid (live probe in Phase 7)")


def _health_imap(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, ImapReceiverConfig)
    if config.username and config.password is None:
        return ProviderHealth.misconfigured("username set but password missing")
    return ProviderHealth.ok(f"configured to poll {config.host}/{config.mailbox}")


def _health_resend_webhook(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, ResendReceiverConfig)
    if not config.webhook_secret.get_secret_value():
        return ProviderHealth.misconfigured("webhook_secret is required")
    return ProviderHealth.ok("configuration valid (webhook verification in Phase 7)")


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
            id="email.imap_poll",
            capability=Capability.EMAIL_RECEIVE,
            display_name="IMAP polling",
            description="Read replies from any mailbox. No public URL required.",
            config_model=ImapReceiverConfig,
            build=_build_imap,
            health_check=_health_imap,
            secret_fields=["password"],
        ),
        ProviderSpec(
            id="email.resend_webhook",
            capability=Capability.EMAIL_RECEIVE,
            display_name="Resend inbound webhook",
            description="Real-time inbound email via signed webhooks (public URL required).",
            docs_url="https://resend.com/docs/dashboard/receiving/introduction",
            config_model=ResendReceiverConfig,
            build=_build_resend_webhook,
            health_check=_health_resend_webhook,
            requires_network=True,
            secret_fields=["webhook_secret"],
        ),
    ]
