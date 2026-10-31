"""WhatsApp Cloud API transport — real sends through Meta's Graph API.

The manual-links mode exists so the product works with nothing connected; this
is the connected mode. It sends text only: the queued body is composed and
approved by a named human before it ever reaches this module, and the Cloud API
text limit is enforced here rather than at the provider, because a 131026 from
Meta is a worse error message than a truncation the operator can see.

The HTTP client is injected so tests exercise the exact request without a
network, and a transport failure returns ``accepted=False`` rather than raising:
the outbox records the failure and leaves the message queued.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

import httpx

from hr_agents.logging import get_logger
from hr_agents.messaging.base import SendResult
from hr_agents.messaging.outbox import (
    DispatchOutcome,
    DispatchReport,
    retry_delay,
)
from hr_agents.messaging.whatsapp import normalize_phone
from hr_agents.models import Channel, CommunicationStatus, UtcDateTime, utc_now
from hr_agents.providers.whatsapp import MetaCloudConfig

if TYPE_CHECKING:
    from hr_agents.services.recruiting import CommunicationService

logger = get_logger(__name__)

WHATSAPP_CLOUD_PROVIDER_ID = "whatsapp.meta_cloud"

MAX_TEXT_CHARS = 4096
"""The Cloud API's text body limit; a longer message is refused by Meta."""


class WhatsAppSender(Protocol):
    """The narrow slice the dispatcher needs, so tests can substitute a fake."""

    @property
    def provider_id(self) -> str: ...

    def send(self, *, phone: str, body: str) -> SendResult: ...


class MetaCloudSender:
    """Send one queued message through the official WhatsApp Cloud API."""

    def __init__(
        self,
        config: MetaCloudConfig,
        *,
        client: httpx.Client | None = None,
        base_url: str | None = None,
    ) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=30.0)
        self._base_url = (base_url or config.base_url).rstrip("/")

    @property
    def provider_id(self) -> str:
        return WHATSAPP_CLOUD_PROVIDER_ID

    def send(self, *, phone: str, body: str) -> SendResult:
        number = normalize_phone(phone)
        text = body.strip()
        if not text:
            return SendResult(
                provider=self.provider_id, accepted=False, detail="message body is empty"
            )
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]
        url = f"{self._base_url}/{self._config.api_version}/{self._config.phone_number_id}/messages"
        try:
            response = self._client.post(
                url,
                headers={"Authorization": f"Bearer {self._config.access_token.get_secret_value()}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": number,
                    "type": "text",
                    "text": {"body": text, "preview_url": False},
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("whatsapp.cloud_transport_failed", error=type(exc).__name__)
            return SendResult(
                provider=self.provider_id,
                accepted=False,
                detail=f"{type(exc).__name__}: the Cloud API did not answer",
            )
        if response.status_code >= 400:
            return SendResult(
                provider=self.provider_id,
                accepted=False,
                detail=self._error_detail(response),
            )
        try:
            payload = response.json()
            message_id = str(payload["messages"][0]["id"])
        except ValueError, KeyError, IndexError, TypeError:
            # A 200 without a message id is not evidence of delivery; treating it
            # as accepted would put an unverifiable "sent" on the record.
            return SendResult(
                provider=self.provider_id,
                accepted=False,
                detail="the Cloud API accepted the request without a message id",
            )
        return SendResult(provider=self.provider_id, accepted=True, message_id=message_id)

    def _error_detail(self, response: httpx.Response) -> str:
        try:
            error = response.json().get("error", {})
            message = str(error.get("message") or "")
            code = error.get("code")
        except ValueError, AttributeError:
            message = response.text[:200]
            code = None
        detail = f"http {response.status_code}"
        if code is not None:
            detail += f" (code {code})"
        if message:
            detail += f": {message}"
        return detail[:500]


def build_meta_cloud_sender(config: MetaCloudConfig) -> MetaCloudSender:
    """Provider builder for ``whatsapp.meta_cloud``."""
    return MetaCloudSender(config)


class WhatsAppCloudDispatcher:
    """Carry queued ``channel=whatsapp`` messages over the Meta Cloud API.

    The same boundaries the email outbox keeps: only a message a named human
    queued, a claim before the transport (two overlapping runs must not send the
    same message twice), backoff after a failure, and recorded evidence. The
    report type is shared, so the CLI and the scheduler read one shape.
    """

    def __init__(
        self,
        *,
        communications: CommunicationService,
        sender: WhatsAppSender,
    ) -> None:
        self._communications = communications
        self._sender = sender
        self._dispatcher_id = f"{socket.gethostname()}:{os.getpid()}:wa:{uuid4().hex[:8]}"

    def dispatch_pending(
        self,
        *,
        limit: int = 50,
        started_at: UtcDateTime | None = None,
    ) -> DispatchReport:
        moment = started_at or utc_now()
        report = DispatchReport(started_at=moment, provider=self._sender.provider_id)
        queued = self._communications.list_queued(channel=Channel.WHATSAPP)[: max(limit, 0)]
        for item in queued:
            self._dispatch_one(item.id, report, now=moment)
        return report

    def _dispatch_one(
        self, communication_id: UUID, report: DispatchReport, *, now: datetime
    ) -> None:
        item = self._communications.get(communication_id)
        if item.status is not CommunicationStatus.QUEUED:
            report.skipped += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail=f"no longer queued ({item.status.value})",
                )
            )
            return
        if item.send_attempts > 0 and item.last_attempt_at is not None:
            ready_at = item.last_attempt_at + retry_delay(item.send_attempts)
            if now < ready_at:
                report.deferred += 1
                report.outcomes.append(
                    DispatchOutcome(
                        communication_id=communication_id,
                        ok=False,
                        detail=(
                            f"attempt {item.send_attempts} failed; "
                            f"next try after {ready_at.isoformat()}"
                        ),
                    )
                )
                return
        phone = (item.recipient_phone or "").strip()
        if not phone:
            report.skipped += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail="no WhatsApp number on file",
                )
            )
            return
        claimed = self._communications.claim_for_dispatch(
            communication_id, claimed_by=self._dispatcher_id, now=now
        )
        if claimed is None:
            report.skipped += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail="another dispatcher holds this message",
                )
            )
            return
        result = self._sender.send(phone=phone, body=item.body)
        if not result.accepted:
            self._record_failure(
                communication_id, provider=result.provider, error=result.detail or "refused"
            )
            report.failed += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail=(result.detail or "the transport refused the message")[:500],
                )
            )
            return
        try:
            self._communications.record_whatsapp_dispatch(
                communication_id,
                provider=result.provider,
                recipient_phone=phone,
                message_id=result.message_id,
            )
        except Exception as exc:
            logger.error(
                "whatsapp.dispatch_record_failed",
                communication_id=str(communication_id),
                error=type(exc).__name__,
            )
            report.unrecorded += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail=(
                        "sent by the transport, but the record could not be updated "
                        f"({type(exc).__name__}: {exc}); do not retry blindly"
                    )[:500],
                )
            )
            return
        report.sent += 1
        report.outcomes.append(
            DispatchOutcome(
                communication_id=communication_id, ok=True, detail=f"sent via {result.provider}"
            )
        )

    def _record_failure(self, communication_id: UUID, *, provider: str, error: str) -> None:
        try:
            self._communications.record_dispatch_failure(
                communication_id, provider=provider, error=error
            )
        except Exception:
            logger.error(
                "whatsapp.dispatch_failure_record_failed",
                communication_id=str(communication_id),
                exc_info=True,
            )
