"""SMTP transport — the default ``email_send`` provider (any existing mailbox).

The stdlib client is synchronous and blocking on purpose: the bridge runs from
the operator-driven CLI, and the domain stays synchronous (ADR 0005). Tests
inject a fake client through ``client_factory`` so nothing touches a network.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable
from contextlib import suppress
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Protocol

from hr_agents.messaging.base import OutboundEmail, SendResult, TransportError
from hr_agents.providers.email import SmtpSenderConfig

SMTP_PROVIDER_ID = "email.smtp"


class SmtpClient(Protocol):
    """The slice of :class:`smtplib.SMTP` the transport uses."""

    def ehlo(self) -> object: ...

    def starttls(self, *, context: ssl.SSLContext | None = None) -> object: ...

    def login(self, user: str, password: str) -> object: ...

    def send_message(self, message: EmailMessage) -> dict[str, tuple[int, bytes]]: ...

    def quit(self) -> object: ...


SmtpClientFactory = Callable[[SmtpSenderConfig], SmtpClient]


def _connect(config: SmtpSenderConfig) -> SmtpClient:
    if config.use_ssl:
        return smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout_seconds)
    return smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds)


class SmtpEmailSender:
    """Deliver one plain-text message per call over a configured mailbox."""

    def __init__(
        self,
        config: SmtpSenderConfig,
        *,
        client_factory: SmtpClientFactory | None = None,
    ) -> None:
        self._config = config
        self._factory = client_factory or _connect

    @property
    def provider_id(self) -> str:
        return SMTP_PROVIDER_ID

    @property
    def from_address(self) -> str:
        return self._config.from_address

    def send(self, message: OutboundEmail) -> SendResult:
        """Send one message; refused recipients come back as ``accepted=False``."""
        email = EmailMessage()
        email["From"] = self._config.from_address
        email["To"] = str(message.to)
        email["Subject"] = message.subject
        domain = parseaddr(self._config.from_address)[1].partition("@")[2] or None
        email["Message-ID"] = make_msgid(domain=domain)
        if message.in_reply_to:
            email["In-Reply-To"] = message.in_reply_to
        if message.references:
            email["References"] = " ".join(message.references)
        email.set_content(message.body)

        client: SmtpClient | None = None
        try:
            client = self._factory(self._config)
            client.ehlo()
            if self._config.use_starttls and not self._config.use_ssl:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if self._config.username and self._config.password is not None:
                client.login(
                    self._config.username,
                    self._config.password.get_secret_value(),
                )
            refused = client.send_message(email)
        except (OSError, smtplib.SMTPException) as exc:
            raise TransportError(f"smtp send to {message.to} failed: {exc}") from exc
        finally:
            if client is not None:
                self._quit(client)

        message_id = email["Message-ID"]
        if refused:
            detail = f"recipients refused: {', '.join(sorted(refused))}"
            return SendResult(
                provider=SMTP_PROVIDER_ID,
                accepted=False,
                message_id=message_id,
                detail=detail[:500],
            )
        return SendResult(provider=SMTP_PROVIDER_ID, accepted=True, message_id=message_id)

    def _quit(self, client: SmtpClient) -> None:
        with suppress(OSError, smtplib.SMTPException):
            client.quit()


def build_smtp_sender(config: SmtpSenderConfig) -> SmtpEmailSender:
    """Provider builder for ``email.smtp``."""
    return SmtpEmailSender(config)
