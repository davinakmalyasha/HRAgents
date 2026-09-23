"""IMAP polling — the default ``email_receive`` provider (no public URL needed).

The receiver reads unseen mail, normalizes it, and marks what it handled. The
stdlib client is blocking; the CLI drives one poll per run. Tests inject a fake
client through ``client_factory``, so no test touches a network.
"""

from __future__ import annotations

import imaplib
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Protocol, cast

from hr_agents.messaging.base import InboundEmail, TransportError
from hr_agents.models import utc_now
from hr_agents.providers.email import ImapReceiverConfig

IMAP_PROVIDER_ID = "email.imap_poll"

SEEN_FLAG = "\\Seen"


ImapResult = tuple[str, Any]
"""``(status, payload)`` as :mod:`imaplib` returns it, loosely typed."""


class ImapClient(Protocol):
    """The slice of :class:`imaplib.IMAP4` the receiver uses."""

    def login(self, user: str, password: str) -> ImapResult: ...

    def select(self, mailbox: str = "INBOX") -> ImapResult: ...

    def search(self, charset: str | None, *criteria: str) -> ImapResult: ...

    def fetch(self, message_set: str, message_parts: str) -> ImapResult: ...

    def store(self, message_set: str, command: str, flags: str) -> ImapResult: ...

    def logout(self) -> ImapResult: ...


ImapClientFactory = Callable[[ImapReceiverConfig], ImapClient]


def _connect(config: ImapReceiverConfig) -> ImapClient:
    if config.use_ssl:
        return imaplib.IMAP4_SSL(config.host, config.port, timeout=config.timeout_seconds)
    return imaplib.IMAP4(config.host, config.port, timeout=config.timeout_seconds)


def message_numbers(data: list[bytes | bytearray]) -> list[str]:
    """Message numbers from an IMAP search response."""
    found: list[str] = []
    for chunk in data:
        for token in bytes(chunk).split():
            text = token.decode("ascii", errors="ignore").strip()
            if text.isdigit():
                found.append(text)
    return found


def _text_body(message: EmailMessage) -> str | None:
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        return None
    content = part.get_content()
    if not isinstance(content, str):
        return None
    return content.strip() or None


def _received_at(message: EmailMessage) -> datetime:
    raw = message.get("Date")
    if raw:
        try:
            parsed = parsedate_to_datetime(str(raw))
        except TypeError, ValueError:
            parsed = None
        if parsed is not None:
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return utc_now()


def parse_message(raw: bytes, *, provider: str = IMAP_PROVIDER_ID) -> InboundEmail | None:
    """Normalize a raw RFC 5322 message; unusable mail is skipped, never guessed."""
    message = cast(EmailMessage, BytesParser(policy=policy.default).parsebytes(raw))
    sender = parseaddr(str(message.get("From", "")))[1]
    body = _text_body(message)
    if not sender or body is None:
        return None
    references = str(message.get("References", "")).split()
    return InboundEmail(
        provider=provider,
        from_address=sender,
        to_address=parseaddr(str(message.get("To", "")))[1],
        subject=str(message.get("Subject", ""))[:500],
        body=body,
        message_id=str(message.get("Message-ID", "")).strip() or None,
        in_reply_to=str(message.get("In-Reply-To", "")).strip() or None,
        references=references,
        received_at=_received_at(message),
    )


class ImapEmailReceiver:
    """Poll unseen mail from one mailbox and mark what was handled."""

    def __init__(
        self,
        config: ImapReceiverConfig,
        *,
        client_factory: ImapClientFactory | None = None,
    ) -> None:
        self._config = config
        self._factory = client_factory or _connect

    @property
    def provider_id(self) -> str:
        return IMAP_PROVIDER_ID

    def poll(self) -> list[InboundEmail]:
        """Return unseen messages; anything unparseable is marked and skipped."""
        client: ImapClient | None = None
        received: list[InboundEmail] = []
        try:
            client = self._factory(self._config)
            if self._config.username and self._config.password is not None:
                client.login(
                    self._config.username,
                    self._config.password.get_secret_value(),
                )
            self._require_ok(client.select(f'"{self._config.mailbox}"'), "select mailbox")
            status, data = client.search(None, "UNSEEN")
            if status.upper() != "OK":
                raise TransportError(f"imap search failed with status {status!r}")
            for number in message_numbers(data):
                raw = self._fetch(client, number)
                parsed = parse_message(raw) if raw else None
                if parsed is not None:
                    received.append(parsed)
                if self._config.mark_seen:
                    client.store(number, "+FLAGS", SEEN_FLAG)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TransportError(f"imap poll of {self._config.host} failed: {exc}") from exc
        finally:
            if client is not None:
                self._logout(client)
        return received

    def _fetch(self, client: ImapClient, number: str) -> bytes | None:
        status, data = client.fetch(number, "(RFC822)")
        if status.upper() != "OK":
            raise TransportError(f"imap fetch of message {number} failed with status {status!r}")
        for _header, payload in data:
            if payload:
                return bytes(payload)
        return None

    @staticmethod
    def _require_ok(result: ImapResult, action: str) -> None:
        status, _data = result
        if status.upper() != "OK":
            raise TransportError(f"imap {action} failed with status {status!r}")

    def _logout(self, client: ImapClient) -> None:
        with suppress(OSError, imaplib.IMAP4.error):
            client.logout()


def build_imap_receiver(config: ImapReceiverConfig) -> ImapEmailReceiver:
    """Provider builder for ``email.imap_poll``."""
    return ImapEmailReceiver(config)
