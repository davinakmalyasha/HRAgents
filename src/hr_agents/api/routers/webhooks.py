"""Inbound provider webhooks — the provider is the caller and the signature is the credential.

These routes sit outside the API-key scheme on purpose: a mail provider cannot
hold a role, and minting one for it would put a machine identity on the same
footing as a person. What it can do is prove it signed the bytes, which
`messaging/webhooks.py` verifies before anything is read.

Nothing here decides anything. An inbound reply is stored as evidence (the
reply bridge already attributes it or refuses it); an event this route does not
understand is acknowledged so the provider stops retrying, not acted on.
"""

from __future__ import annotations

import json
from email.utils import parseaddr
from html import unescape
from re import sub
from typing import Any

from fastapi import APIRouter, Request, status

from hr_agents.api.problem import ProblemCode, problem
from hr_agents.messaging.base import MAX_INBOUND_BODY_CHARS, InboundEmail
from hr_agents.messaging.webhooks import (
    ReplayGuard,
    WebhookError,
    WebhookScheme,
    verify_webhook,
)
from hr_agents.models import StrictModel
from hr_agents.providers.base import Capability
from hr_agents.providers.settings import resolve_provider_settings

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])

RESEND_PROVIDER_ID = "email.resend_webhook"

HTML_TAG = r"<[^>]+>"


class InboundWebhookResult(StrictModel):
    """What one delivery did; the provider only needs a 2xx to stop retrying."""

    accepted: bool = True
    event: str = ""
    stored: int = 0
    unmatched: int = 0
    duplicates: int = 0


def _strip_html(value: str) -> str:
    """Plain text from an HTML body, good enough for a reply and no dependency.

    Providers that send only HTML are rare but real; refusing the reply because
    the sender's client chose markup would lose evidence a human may need.
    """
    return unescape(sub(HTML_TAG, " ", value)).strip()


def _resend_message(payload: dict[str, Any]) -> InboundEmail | None:
    """Normalize one Resend ``email.received`` event; unattributable mail is None."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    sender_name, sender = parseaddr(str(data.get("from") or ""))
    if not sender:
        return None
    body = data.get("text")
    if not isinstance(body, str) or not body.strip():
        html = data.get("html")
        body = _strip_html(html) if isinstance(html, str) else ""
    recipients = data.get("to")
    if isinstance(recipients, list) and recipients:
        to_address = str(recipients[0])
    elif isinstance(recipients, str):
        to_address = recipients
    else:
        to_address = ""
    headers = data.get("headers")
    header_map = (
        {str(key).lower(): str(value) for key, value in headers.items()}
        if isinstance(headers, dict)
        else {}
    )
    references = header_map.get("references", "").split()
    message_id = str(data.get("message_id") or data.get("email_id") or "").strip()
    return InboundEmail(
        provider=RESEND_PROVIDER_ID,
        from_address=sender,
        from_name=sender_name.strip()[:320],
        to_address=to_address[:320],
        subject=str(data.get("subject") or "")[:500],
        body=body[:MAX_INBOUND_BODY_CHARS],
        message_id=message_id or None,
        in_reply_to=(header_map.get("in-reply-to") or "").strip() or None,
        references=references[:50],
    )


def _resend_secret() -> str | None:
    """The configured webhook signing secret, settings row or environment."""
    resolved = resolve_provider_settings().get(Capability.EMAIL_RECEIVE)
    if resolved is None or resolved.provider_id != RESEND_PROVIDER_ID:
        return None
    secret = resolved.config.get("webhook_secret")
    return secret if isinstance(secret, str) and secret else None


@router.post(
    "/email/resend",
    response_model=InboundWebhookResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resend inbound email (Svix-signed)",
)
async def resend_inbound(request: Request) -> InboundWebhookResult:
    """Verify, then store the reply. The signature check happens before parsing."""
    raw = await request.body()
    secret = _resend_secret()
    if secret is None:
        raise problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ProblemCode.SERVICE_UNAVAILABLE,
            "the Resend inbound webhook is not configured",
        )
    guard: ReplayGuard | None = getattr(request.app.state, "webhook_replay_guard", None)
    try:
        verify_webhook(
            scheme=WebhookScheme.SVIX,
            headers=dict(request.headers),
            body=raw,
            secret=secret,
            guard=guard,
        )
    except WebhookError as exc:
        raise problem(status.HTTP_401_UNAUTHORIZED, ProblemCode.WEBHOOK_REFUSED, str(exc)) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise problem(
            status.HTTP_400_BAD_REQUEST,
            ProblemCode.VALIDATION_FAILED,
            "webhook body is not valid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise problem(
            status.HTTP_400_BAD_REQUEST,
            ProblemCode.VALIDATION_FAILED,
            "webhook body must be a JSON object",
        )

    event = str(payload.get("type") or "")
    if event != "email.received":
        # A signed event this deployment does not handle: acknowledge it so the
        # provider stops retrying. Acting on an unknown shape would be guessing.
        return InboundWebhookResult(event=event)

    message = _resend_message(payload)
    if message is None:
        return InboundWebhookResult(event=event)

    messaging = getattr(request.app.state, "messaging", None)
    recruiting = getattr(request.app.state, "recruiting", None)
    if messaging is None or recruiting is None:
        raise problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ProblemCode.SERVICE_UNAVAILABLE,
            "the reply bridge is not available",
        )
    ingestor = messaging.ingestor(recruiting.communications, audit=request.app.state.audit)
    report = ingestor.ingest([message])
    return InboundWebhookResult(
        event=event,
        stored=report.matched,
        unmatched=report.unmatched,
        duplicates=report.duplicates,
    )
