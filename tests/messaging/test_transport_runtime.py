"""Transport resolution from configuration.

The sandbox is the default: no transport is active, nothing can be dispatched,
and inbound polling stays off. Turning it off hands the bridge the provider the
operator selected, with the legacy ``HRAGENTS_SMTP_*`` settings as the
zero-configuration path for the default SMTP provider.
"""

from __future__ import annotations

import json

import pytest

from hr_agents.config import Settings
from hr_agents.messaging.imap import ImapEmailReceiver
from hr_agents.messaging.runtime import (
    DisabledEmailSender,
    build_email_receiver,
    build_email_sender,
    resolve_telegram_sender,
)
from hr_agents.messaging.smtp import SmtpEmailSender


def test_sandbox_leaves_no_transport_active() -> None:
    settings = Settings(messaging_sandbox=True)

    sender = build_email_sender(settings=settings)

    assert isinstance(sender, DisabledEmailSender)
    assert build_email_receiver(settings=settings) is None


def test_telegram_sender_is_selected_by_the_provider_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HRAGENTS_PROVIDER_TELEGRAM", "telegram.bot")
    monkeypatch.setenv("HRAGENTS_PROVIDER_TELEGRAM_CONFIG", json.dumps({"bot_token": "123:ABC"}))

    sender = resolve_telegram_sender()

    from hr_agents.messaging.telegram import TelegramSender

    assert isinstance(sender, TelegramSender)
    assert sender.provider_id == "telegram.bot"


def test_telegram_has_no_transport_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HRAGENTS_PROVIDER_TELEGRAM", raising=False)

    assert resolve_telegram_sender() is None


def test_gmail_sender_is_selected_by_the_provider_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting email.gmail in configuration hands the outbox the live sender."""
    monkeypatch.setenv("HRAGENTS_PROVIDER_EMAIL_SEND", "email.gmail")
    monkeypatch.setenv(
        "HRAGENTS_PROVIDER_EMAIL_SEND_CONFIG",
        json.dumps(
            {
                "client_id": "client-1",
                "client_secret": "secret-1",
                "refresh_token": "refresh-1",
                "from_address": "talent@example.com",
            }
        ),
    )
    settings = Settings(messaging_sandbox=False)

    sender = build_email_sender(settings=settings)

    from hr_agents.integrations.gmail import GmailSender

    assert isinstance(sender, GmailSender)
    assert sender.provider_id == "email.gmail"


def test_smtp_sender_is_built_from_provider_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HRAGENTS_PROVIDER_EMAIL_SEND", "email.smtp")
    monkeypatch.setenv(
        "HRAGENTS_PROVIDER_EMAIL_SEND_CONFIG",
        json.dumps(
            {
                "host": "smtp.example.com",
                "port": 2525,
                "username": "hr@example.com",
                "password": "secret",
                "use_starttls": False,
                "from_address": "talent@example.com",
            }
        ),
    )
    settings = Settings(messaging_sandbox=False)

    sender = build_email_sender(settings=settings)

    assert isinstance(sender, SmtpEmailSender)
    assert sender.provider_id == "email.smtp"
    assert sender.from_address == "talent@example.com"


def test_legacy_smtp_settings_seed_the_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HRAGENTS_PROVIDER_EMAIL_SEND", raising=False)
    monkeypatch.delenv("HRAGENTS_PROVIDER_EMAIL_SEND_CONFIG", raising=False)
    settings = Settings(
        messaging_sandbox=False,
        smtp_host="mailpit",
        smtp_port=1025,
        smtp_from="dev@example.com",
    )

    sender = build_email_sender(settings=settings)

    assert isinstance(sender, SmtpEmailSender)
    assert sender.from_address == "dev@example.com"


def test_imap_receiver_is_built_when_sandbox_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HRAGENTS_PROVIDER_EMAIL_RECEIVE", "email.imap_poll")
    monkeypatch.setenv(
        "HRAGENTS_PROVIDER_EMAIL_RECEIVE_CONFIG",
        json.dumps({"host": "imap.example.com", "mailbox": "Candidates"}),
    )
    settings = Settings(messaging_sandbox=False)

    receiver = build_email_receiver(settings=settings)

    assert isinstance(receiver, ImapEmailReceiver)
    assert receiver.provider_id == "email.imap_poll"
