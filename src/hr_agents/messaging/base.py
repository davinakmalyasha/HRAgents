"""Messaging transport ports — the single interface the candidate outbox talks to.

Sending and receiving are provider capabilities: anything that implements
:class:`EmailSender` / :class:`EmailReceiver` can carry queued candidate
messages and poll replies. The outbox never approves anything; a transport only
moves messages a named human already queued, and reports back what happened.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import EmailStr, Field

from hr_agents.models import StrictModel, UtcDateTime, utc_now


class TransportError(RuntimeError):
    """Raised when a transport cannot carry a message."""


class OutboundEmail(StrictModel):
    """One email handed to a transport for delivery."""

    to: EmailStr
    subject: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    in_reply_to: str | None = Field(default=None, max_length=500)
    references: list[str] = Field(default_factory=list, max_length=50)


class SendResult(StrictModel):
    """What a transport reports back; ``accepted`` is the delivery evidence."""

    provider: str = Field(min_length=1, max_length=64)
    accepted: bool
    message_id: str | None = Field(default=None, max_length=500)
    detail: str = Field(default="", max_length=500)


class InboundAttachment(StrictModel):
    """One file carried by inbound mail: a CV until proven otherwise."""

    filename: str = Field(min_length=1, max_length=320)
    content_type: str = Field(default="", max_length=160)
    size_bytes: int = Field(ge=0)
    content: bytes


class InboundEmail(StrictModel):
    """One polled message, normalized across receive providers."""

    provider: str = Field(min_length=1, max_length=64)
    from_address: EmailStr
    from_name: str = Field(default="", max_length=320)
    to_address: str = Field(default="", max_length=320)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    message_id: str | None = Field(default=None, max_length=500)
    in_reply_to: str | None = Field(default=None, max_length=500)
    references: list[str] = Field(default_factory=list, max_length=50)
    attachments: list[InboundAttachment] = Field(default_factory=list)
    skipped_attachments: list[str] = Field(default_factory=list)
    received_at: UtcDateTime = Field(default_factory=utc_now)


@runtime_checkable
class EmailSender(Protocol):
    """Capability port for delivering a queued message."""

    @property
    def provider_id(self) -> str: ...

    def send(self, message: OutboundEmail) -> SendResult: ...


@runtime_checkable
class EmailReceiver(Protocol):
    """Capability port for polling inbound mail."""

    @property
    def provider_id(self) -> str: ...

    def poll(self) -> list[InboundEmail]: ...
