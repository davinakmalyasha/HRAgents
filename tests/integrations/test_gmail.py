"""Gmail send: OAuth refresh, RFC 2822 composition, and the exact API request."""

from __future__ import annotations

import base64
import json
from email import message_from_bytes
from email.policy import default as default_policy

import httpx
import respx
from pydantic import SecretStr

from hr_agents.integrations.gmail import (
    GMAIL_PROVIDER_ID,
    GmailSender,
    compose_raw,
)
from hr_agents.messaging.base import OutboundEmail
from hr_agents.providers.email import GmailSenderConfig

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

CONFIG = GmailSenderConfig(
    client_id="client-1",
    client_secret=SecretStr("secret-1"),
    refresh_token=SecretStr("refresh-1"),
    from_address="hr@example.com",
)


def token_response(token: str = "access-1", expires_in: int = 3600) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": token, "expires_in": expires_in, "token_type": "Bearer"}
    )


def gmail_response(message_id: str = "g-1") -> httpx.Response:
    return httpx.Response(200, json={"id": message_id, "threadId": "t-1"})


@respx.mock
def test_sends_the_composed_message_and_returns_its_id() -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response())
    send = respx.post(SEND_URL).mock(return_value=gmail_response())

    result = GmailSender(CONFIG).send(
        OutboundEmail(to="sari@example.com", subject="Interview", body="Halo Sari,")
    )

    assert (result.provider, result.accepted, result.message_id) == (
        GMAIL_PROVIDER_ID,
        True,
        "g-1",
    )
    request = send.calls[0].request
    assert request.headers["Authorization"] == "Bearer access-1"
    raw = base64.urlsafe_b64decode(json.loads(request.content)["raw"])
    parsed = message_from_bytes(raw, policy=default_policy)
    assert parsed["To"] == "sari@example.com"
    assert parsed["From"] == "hr@example.com"
    assert parsed["Subject"] == "Interview"
    assert "Halo Sari," in parsed.get_content()


@respx.mock
def test_threading_headers_survive_the_round_trip() -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response())
    send = respx.post(SEND_URL).mock(return_value=gmail_response())

    GmailSender(CONFIG).send(
        OutboundEmail(
            to="sari@example.com",
            subject="Re: Interview",
            body="Selasa bisa.",
            in_reply_to="<out-1@example.com>",
            references=["<out-1@example.com>"],
        )
    )

    raw = base64.urlsafe_b64decode(json.loads(send.calls[0].request.content)["raw"])
    parsed = message_from_bytes(raw, policy=default_policy)
    assert parsed["In-Reply-To"] == "<out-1@example.com>"
    assert parsed["References"] == "<out-1@example.com>"


@respx.mock
def test_the_access_token_is_cached_between_sends() -> None:
    tokens = respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.post(SEND_URL).mock(return_value=gmail_response())
    sender = GmailSender(CONFIG)

    sender.send(OutboundEmail(to="a@example.com", body="one"))
    sender.send(OutboundEmail(to="b@example.com", body="two"))

    assert tokens.call_count == 1


@respx.mock
def test_a_rejected_send_is_a_named_refusal() -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.post(SEND_URL).mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "message": "Request had insufficient authentication scopes.",
                    "status": "PERMISSION_DENIED",
                }
            },
        )
    )

    result = GmailSender(CONFIG).send(OutboundEmail(to="a@example.com", body="one"))

    assert result.accepted is False
    assert "gmail api http 403" in result.detail
    assert "insufficient authentication scopes" in result.detail


@respx.mock
def test_a_refused_token_grant_never_reaches_the_send_endpoint() -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    send = respx.post(SEND_URL).mock(return_value=gmail_response())

    result = GmailSender(CONFIG).send(OutboundEmail(to="a@example.com", body="one"))

    assert result.accepted is False
    assert "invalid_grant" in result.detail
    assert send.call_count == 0


def test_a_200_without_an_id_is_not_delivery() -> None:
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=token_response())
        respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"threadId": "t-1"}))
        result = GmailSender(CONFIG).send(OutboundEmail(to="a@example.com", body="one"))
    assert result.accepted is False
    assert "message id" in result.detail


def test_a_transport_error_is_a_refusal_not_a_crash() -> None:
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=token_response())
        respx.post(SEND_URL).mock(side_effect=httpx.ConnectError("no route"))
        result = GmailSender(CONFIG).send(OutboundEmail(to="a@example.com", body="one"))
    assert result.accepted is False
    assert "ConnectError" in result.detail


def test_the_provider_is_registered_with_a_health_check() -> None:
    from hr_agents.providers.email import GmailSenderConfig, email_specs

    spec = next(item for item in email_specs() if item.id == "email.gmail")
    assert spec.config_model is GmailSenderConfig
    assert spec.build is not None
    assert spec.secret_fields == ["client_secret", "refresh_token"]


def test_composition_defaults_a_missing_subject() -> None:
    raw = compose_raw(OutboundEmail(to="a@example.com", body="one"), from_address="hr@example.com")
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw), policy=default_policy)
    assert parsed["Subject"] == "(no subject)"
