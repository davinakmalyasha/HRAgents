"""Telegram bot transport — one text message through the Bot API.

Like the WhatsApp sender, this only carries a body a named human already
approved. The token is a bearer credential in the URL path (Telegram's design),
so it is never logged; a failure returns ``accepted=False`` and the message stays
queued.
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
from hr_agents.messaging.outbox import DispatchOutcome, DispatchReport, retry_delay
from hr_agents.models import Channel, CommunicationStatus, UtcDateTime, utc_now
from hr_agents.providers.telegram import TelegramConfig

if TYPE_CHECKING:
    from hr_agents.services.recruiting import CommunicationService

logger = get_logger(__name__)

TELEGRAM_PROVIDER_ID = "telegram.bot"

MAX_TEXT_CHARS = 4096
"""The Bot API's text limit."""


class TelegramSenderPort(Protocol):
    @property
    def provider_id(self) -> str: ...

    def send(self, *, chat_id: str, body: str) -> SendResult: ...


class TelegramSender:
    """Send one queued message to a chat id."""

    def __init__(
        self,
        config: TelegramConfig,
        *,
        client: httpx.Client | None = None,
        base_url: str | None = None,
    ) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=30.0)
        self._base_url = (base_url or config.base_url).rstrip("/")

    @property
    def provider_id(self) -> str:
        return TELEGRAM_PROVIDER_ID

    def send(self, *, chat_id: str, body: str) -> SendResult:
        target = chat_id.strip()
        if not target:
            return SendResult(provider=self.provider_id, accepted=False, detail="chat id is empty")
        text = body.strip()
        if not text:
            return SendResult(
                provider=self.provider_id, accepted=False, detail="message body is empty"
            )
        url = f"{self._base_url}/bot{self._config.bot_token.get_secret_value()}/sendMessage"
        try:
            response = self._client.post(
                url,
                json={
                    "chat_id": target,
                    "text": text[:MAX_TEXT_CHARS],
                    "disable_web_page_preview": True,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("telegram.transport_failed", error=type(exc).__name__)
            return SendResult(
                provider=self.provider_id,
                accepted=False,
                detail=f"{type(exc).__name__}: the Bot API did not answer",
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or payload.get("ok") is not True:
            description = str(payload.get("description") or response.text[:200])
            return SendResult(
                provider=self.provider_id,
                accepted=False,
                detail=f"http {response.status_code}: {description}"[:500],
            )
        result = payload.get("result") or {}
        message_id = result.get("message_id")
        return SendResult(
            provider=self.provider_id,
            accepted=True,
            message_id=None if message_id is None else str(message_id),
        )


def build_telegram_sender(config: TelegramConfig) -> TelegramSender:
    return TelegramSender(config)


class TelegramDispatcher:
    """Carry queued ``channel=telegram`` messages over the Bot API.

    Same boundaries as the email and WhatsApp dispatchers: a message a named
    human queued, a lease before the transport, backoff after a failure, and the
    provider's message id as evidence. The chat id is the address the queue
    previously had no field for.
    """

    def __init__(
        self,
        *,
        communications: CommunicationService,
        sender: TelegramSenderPort,
    ) -> None:
        self._communications = communications
        self._sender = sender
        self._dispatcher_id = f"{socket.gethostname()}:{os.getpid()}:tg:{uuid4().hex[:8]}"

    def dispatch_pending(
        self,
        *,
        limit: int = 50,
        started_at: UtcDateTime | None = None,
    ) -> DispatchReport:
        moment = started_at or utc_now()
        report = DispatchReport(started_at=moment, provider=self._sender.provider_id)
        queued = self._communications.list_queued(channel=Channel.TELEGRAM)[: max(limit, 0)]
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
        chat_id = (item.recipient_telegram_chat_id or "").strip()
        if not chat_id:
            report.skipped += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail="no Telegram chat id on file",
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
        result = self._sender.send(chat_id=chat_id, body=item.body)
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
            self._communications.record_telegram_dispatch(
                communication_id,
                provider=result.provider,
                recipient_chat_id=chat_id,
                message_id=result.message_id,
            )
        except Exception as exc:
            logger.error(
                "telegram.dispatch_record_failed",
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
                "telegram.dispatch_failure_record_failed",
                communication_id=str(communication_id),
                exc_info=True,
            )
