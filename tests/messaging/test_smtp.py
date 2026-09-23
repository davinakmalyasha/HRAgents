"""SMTP transport behavior with a fake client (no network, ever).

Negative tests first: nothing is recorded as sent when the server refuses a
recipient or the connection fails.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

import pytest

from hr_agents.messaging.base import OutboundEmail, TransportError
from hr_agents.messaging.smtp import SMTP_PROVIDER_ID, SmtpEmailSender
from hr_agents.providers.email import SmtpSenderConfig


class FakeSmtpClient:
    """Captures the message the transport hands to the server."""

    def __init__(self, *, refused: dict[str, tuple[int, bytes]] | None = None) -> None:
        self.sent: list[EmailMessage] = []
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.quit_called = False
        self.refused = refused or {}
        self.send_error: Exception | None = None

    def ehlo(self) -> str:
        return "250-mail.example.com"

    def starttls(self, *, context: Any = None) -> str:
        self.started_tls = True
        return "220 ready"

    def login(self, user: str, password: str) -> str:
        self.logged_in = (user, password)
        return "235 ok"

    def send_message(self, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(message)
        return self.refused

    def quit(self) -> str:
        self.quit_called = True
        return "221 bye"


def make_sender(client: FakeSmtpClient, **config: Any) -> SmtpEmailSender:
    return SmtpEmailSender(
        SmtpSenderConfig(**config),
        client_factory=lambda _config: client,
    )


def test_send_reports_acceptance_and_message_id() -> None:
    client = FakeSmtpClient()
    sender = make_sender(client, from_address="hr@example.com", use_starttls=True)

    result = sender.send(OutboundEmail(to="budi@example.com", subject="Your offer", body="Hi Budi"))

    assert result.provider == SMTP_PROVIDER_ID
    assert result.accepted is True
    assert result.message_id is not None
    assert sender.provider_id == SMTP_PROVIDER_ID
    assert len(client.sent) == 1
    assert client.sent[0]["To"] == "budi@example.com"
    assert client.sent[0]["Subject"] == "Your offer"
    assert client.started_tls is True
    assert client.quit_called is True


def test_send_authenticates_only_with_credentials() -> None:
    client = FakeSmtpClient()
    sender = make_sender(client, username="hr@example.com", password="secret")

    sender.send(OutboundEmail(to="budi@example.com", body="Hello"))

    assert client.logged_in == ("hr@example.com", "secret")


def test_refused_recipient_is_not_accepted() -> None:
    client = FakeSmtpClient(refused={"budi@example.com": (550, b"unknown mailbox")})
    sender = make_sender(client)

    result = sender.send(OutboundEmail(to="budi@example.com", body="Hello"))

    assert result.accepted is False
    assert "budi@example.com" in result.detail


def test_smtp_failure_becomes_a_transport_error() -> None:
    client = FakeSmtpClient()
    client.send_error = smtplib.SMTPResponseException(421, b"service unavailable")
    sender = make_sender(client)

    with pytest.raises(TransportError, match="smtp send to"):
        sender.send(OutboundEmail(to="budi@example.com", body="Hello"))


def test_connection_refused_becomes_a_transport_error() -> None:
    def factory(_config: SmtpSenderConfig) -> FakeSmtpClient:
        raise ConnectionRefusedError("mail server is down")

    sender = SmtpEmailSender(SmtpSenderConfig(), client_factory=factory)

    with pytest.raises(TransportError):
        sender.send(OutboundEmail(to="budi@example.com", body="Hello"))


def test_reply_headers_are_carried_for_threading() -> None:
    client = FakeSmtpClient()
    sender = make_sender(client)

    sender.send(
        OutboundEmail(
            to="budi@example.com",
            subject="Re: Your application",
            body="Thanks for the update.",
            in_reply_to="<first@example.com>",
            references=["<first@example.com>"],
        )
    )

    message = client.sent[0]
    assert message["In-Reply-To"] == "<first@example.com>"
    assert message["References"] == "<first@example.com>"


def test_secret_password_is_never_echoed_in_errors() -> None:
    client = FakeSmtpClient()
    client.send_error = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    sender = make_sender(client, username="hr@example.com", password="sup3rs3cret")

    with pytest.raises(TransportError) as excinfo:
        sender.send(OutboundEmail(to="budi@example.com", body="Hello"))

    assert "sup3rs3cret" not in str(excinfo.value)
