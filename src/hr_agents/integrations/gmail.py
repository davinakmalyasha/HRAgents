"""Gmail send adapter — RFC 2822 over the Gmail API.

Same credential shape as the calendar adapter: an operator's OAuth client and
refresh token, with a short-lived access token minted and cached by
``RefreshTokenOAuth``. The message is composed locally as a real RFC 2822
document and sent base64url-encoded, which is what the Gmail API accepts — no
SMTP password, no app-specific password, and threading headers survive because
the composed message carries them.

The sender implements the existing ``EmailSender`` port, so the outbox's
approval, lease, backoff and evidence rules apply unchanged; only the transport
underneath is different.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from email.message import EmailMessage

import httpx

from hr_agents.integrations.google_oauth import GoogleOAuthError, RefreshTokenOAuth
from hr_agents.logging import get_logger
from hr_agents.messaging.base import OutboundEmail, SendResult
from hr_agents.providers.email import GmailSenderConfig

logger = get_logger(__name__)

GMAIL_PROVIDER_ID = "email.gmail"


class GmailSender:
    """Send one queued email through ``users.messages.send``."""

    def __init__(
        self,
        config: GmailSenderConfig,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=30.0)
        self._oauth = RefreshTokenOAuth(
            client_id=config.client_id,
            client_secret=config.client_secret.get_secret_value(),
            refresh_token=config.refresh_token.get_secret_value(),
            token_url=config.token_url,
            client=self._client,
            clock=clock,
            provider="gmail",
        )

    @property
    def provider_id(self) -> str:
        return GMAIL_PROVIDER_ID

    def send(self, message: OutboundEmail) -> SendResult:
        try:
            token = self._oauth.token()
        except GoogleOAuthError as exc:
            return SendResult(provider=self.provider_id, accepted=False, detail=str(exc)[:500])
        url = (
            f"{self._config.base_url.rstrip('/')}/gmail/v1/users/"
            f"{self._config.user_id}/messages/send"
        )
        try:
            response = self._client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"raw": compose_raw(message, from_address=self._config.from_address)},
            )
        except httpx.HTTPError as exc:
            logger.warning("gmail.transport_failed", error=type(exc).__name__)
            return SendResult(
                provider=self.provider_id,
                accepted=False,
                detail=f"{type(exc).__name__}: the Gmail API did not answer",
            )
        if response.status_code >= 400:
            return SendResult(
                provider=self.provider_id, accepted=False, detail=_error_detail(response)
            )
        try:
            message_id = str(response.json()["id"])
        except ValueError, KeyError, TypeError:
            # A 200 without a message id is not evidence of delivery.
            return SendResult(
                provider=self.provider_id,
                accepted=False,
                detail="the Gmail API accepted the request without a message id",
            )
        return SendResult(provider=self.provider_id, accepted=True, message_id=message_id)


def compose_raw(message: OutboundEmail, *, from_address: str) -> str:
    """The RFC 2822 document, base64url-encoded for ``raw``."""
    email = EmailMessage()
    email["To"] = message.to
    email["From"] = from_address
    email["Subject"] = message.subject or "(no subject)"
    if message.in_reply_to:
        email["In-Reply-To"] = message.in_reply_to
    if message.references:
        email["References"] = " ".join(message.references)
    email.set_content(message.body)
    return base64.urlsafe_b64encode(email.as_bytes()).decode("ascii")


def _error_detail(response: httpx.Response) -> str:
    """Gmail's error message, bounded; credentials and bodies never appear."""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "")
            status = error.get("status")
        else:
            message = str(error or "")
            status = None
    except ValueError:
        message = response.text[:200]
        status = None
    detail = f"gmail api http {response.status_code}"
    if status:
        detail += f" ({status})"
    if message:
        detail += f": {message}"
    return detail[:500]


def build_gmail_sender(config: GmailSenderConfig) -> GmailSender:
    return GmailSender(config)
