"""Telegram bot transport — one text message through the Bot API.

Like the WhatsApp sender, this only carries a body a named human already
approved. The token is a bearer credential in the URL path (Telegram's design),
so it is never logged; a failure returns ``accepted=False`` and the message stays
queued.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from hr_agents.logging import get_logger
from hr_agents.messaging.base import SendResult
from hr_agents.providers.telegram import TelegramConfig

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
