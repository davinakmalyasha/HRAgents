"""IMAP polling behavior with a fake client (no network, ever).

Negative tests first: mail that matches no candidate is never attributed, and a
failed poll raises a transport error instead of pretending the inbox is empty.
"""

from __future__ import annotations

from typing import Any

import pytest

from hr_agents.messaging.base import TransportError
from hr_agents.messaging.imap import (
    IMAP_PROVIDER_ID,
    ImapEmailReceiver,
    message_numbers,
    parse_message,
)
from hr_agents.providers.email import ImapReceiverConfig

RAW_REPLY = b"""From: Budi Santoso <budi@example.com>
To: hr@example.com
Subject: Re: Your application for Backend Engineer
Message-ID: <reply-1@example.com>
In-Reply-To: <outbound-1@example.com>
References: <outbound-1@example.com>
Date: Tue, 22 Sep 2026 09:15:00 +0700
Content-Type: text/plain; charset="utf-8"

Terima kasih, saya tertarik untuk lanjut.
"""


class FakeImapClient:
    """Minimal IMAP double: unseen search, RFC822 fetch, flag store."""

    def __init__(self, messages: dict[str, bytes] | None = None) -> None:
        self.messages = messages or {}
        self.logged_in: tuple[str, str] | None = None
        self.selected: str | None = None
        self.searched: tuple[str, ...] = ()
        self.stored: list[tuple[str, str, str]] = []
        self.logged_out = False
        self.search_status = "OK"
        self.select_status = "OK"
        self.fetch_status = "OK"

    def login(self, user: str, password: str) -> tuple[str, Any]:
        self.logged_in = (user, password)
        return "OK", [b"LOGIN completed"]

    def select(self, mailbox: str = "INBOX") -> tuple[str, Any]:
        self.selected = mailbox
        return self.select_status, [b"1 EXISTS"]

    def search(self, charset: str | None, *criteria: str) -> tuple[str, list[bytes]]:
        self.searched = criteria
        if self.search_status != "OK":
            return self.search_status, []
        return "OK", [" ".join(self.messages).encode("ascii")]

    def fetch(self, message_set: str, message_parts: str) -> tuple[str, list[Any]]:
        if self.fetch_status != "OK":
            return self.fetch_status, []
        return "OK", [(b"1 (RFC822)", self.messages[message_set])]

    def store(self, message_set: str, command: str, flags: str) -> tuple[str, list[bytes]]:
        self.stored.append((message_set, command, flags))
        return "OK", [b"FLAGS updated"]

    def logout(self) -> tuple[str, Any]:
        self.logged_out = True
        return "OK", [b"LOGOUT completed"]


def make_receiver(client: FakeImapClient, **config: Any) -> ImapEmailReceiver:
    return ImapEmailReceiver(
        ImapReceiverConfig(**config),
        client_factory=lambda _config: client,
    )


def test_poll_returns_normalized_messages() -> None:
    client = FakeImapClient({"1": RAW_REPLY})
    receiver = make_receiver(client, username="hr@example.com", password="secret")

    messages = receiver.poll()

    assert receiver.provider_id == IMAP_PROVIDER_ID
    assert len(messages) == 1
    message = messages[0]
    assert message.from_address == "budi@example.com"
    assert message.message_id == "<reply-1@example.com>"
    assert message.in_reply_to == "<outbound-1@example.com>"
    assert "tertarik untuk lanjut" in message.body.lower()
    assert client.logged_in == ("hr@example.com", "secret")
    assert client.selected == '"INBOX"'
    assert client.searched == ("UNSEEN",)
    assert client.stored == [("1", "+FLAGS", "\\Seen")]
    assert client.logged_out is True


def test_mark_seen_can_be_disabled() -> None:
    client = FakeImapClient({"1": RAW_REPLY})
    receiver = make_receiver(client, mark_seen=False)

    receiver.poll()

    assert client.stored == []


def test_unparseable_mail_is_skipped_but_still_marked() -> None:
    client = FakeImapClient({"1": RAW_REPLY, "2": b"not an email at all"})
    receiver = make_receiver(client)

    messages = receiver.poll()

    assert len(messages) == 1
    assert [stored[0] for stored in client.stored] == ["1", "2"]


def test_message_without_a_sender_is_never_attributed() -> None:
    parsed = parse_message(b"Subject: hello\n\nbody\n")

    assert parsed is None


def test_search_failure_raises_a_transport_error() -> None:
    client = FakeImapClient({"1": RAW_REPLY})
    client.search_status = "NO"
    receiver = make_receiver(client)

    with pytest.raises(TransportError, match="search failed"):
        receiver.poll()


def test_connection_failure_raises_a_transport_error() -> None:
    def factory(_config: ImapReceiverConfig) -> FakeImapClient:
        raise ConnectionRefusedError("mailbox is down")

    receiver = ImapEmailReceiver(ImapReceiverConfig(), client_factory=factory)

    with pytest.raises(TransportError, match="mailbox is down"):
        receiver.poll()


def test_message_numbers_ignores_non_numeric_tokens() -> None:
    assert message_numbers([b"1 2 3", b"nonsense"]) == ["1", "2", "3"]


RAW_APPLICATION = b"""From: Rani Dewi <rani@example.com>
To: hiring@example.com
Subject: Lamaran Backend Engineer
Message-ID: <app-1@example.com>
Date: Tue, 22 Sep 2026 09:15:00 +0700
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="BOUNDARY42"

--BOUNDARY42
Content-Type: text/plain; charset="utf-8"

Please consider my application, CV attached.

--BOUNDARY42
Content-Type: application/pdf; name="cv-rani.pdf"
Content-Disposition: attachment; filename="cv-rani.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQgZmFrZSBjdiBib2R5

--BOUNDARY42
Content-Type: image/png; name="signature.png"
Content-Disposition: attachment; filename="signature.png"
Content-Transfer-Encoding: base64

aVBORw==

--BOUNDARY42--
"""

RAW_BODYLESS_APPLICATION = b"""From: Rani Dewi <rani@example.com>
To: hiring@example.com
Subject: Lamaran Backend Engineer
Message-ID: <app-2@example.com>
Date: Tue, 22 Sep 2026 09:16:00 +0700
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="BOUNDARY43"

--BOUNDARY43
Content-Type: application/pdf; name="cv-rani.pdf"
Content-Disposition: attachment; filename="cv-rani.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQgZmFrZSBjdiBib2R5

--BOUNDARY43--
"""


def test_application_mail_yields_its_cv_and_skips_the_signature() -> None:
    parsed = parse_message(RAW_APPLICATION)

    assert parsed is not None
    assert parsed.from_name == "Rani Dewi"
    assert "consider my application" in parsed.body
    assert [item.filename for item in parsed.attachments] == ["cv-rani.pdf"]
    assert parsed.attachments[0].content_type == "application/pdf"
    assert parsed.attachments[0].size_bytes > 0
    assert parsed.skipped_attachments == ["signature.png: image/png is not a document"]


def test_bodyless_mail_with_cv_still_parses() -> None:
    parsed = parse_message(RAW_BODYLESS_APPLICATION)

    assert parsed is not None
    assert parsed.body == ""
    assert [item.filename for item in parsed.attachments] == ["cv-rani.pdf"]


def test_bodyless_mail_without_attachments_is_still_noise() -> None:
    parsed = parse_message(b"From: x@y.com\nTo: hr@example.com\nSubject: hi\n\n")

    assert parsed is None
