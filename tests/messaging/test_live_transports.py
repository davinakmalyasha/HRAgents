"""Live messaging transports: WhatsApp Cloud and Telegram, exercised over respx.

No test leaves the process. The assertions are on the exact request Meta and
Telegram receive, because a payload shape is the part of an integration that
cannot be discovered from the SDK's success.
"""

from __future__ import annotations

import json

import httpx
import respx
from pydantic import SecretStr

from hr_agents.messaging.base import SendResult
from hr_agents.messaging.telegram import TelegramSender
from hr_agents.messaging.whatsapp_cloud import (
    MAX_TEXT_CHARS,
    MetaCloudSender,
    build_meta_cloud_sender,
)
from hr_agents.providers.telegram import TelegramConfig
from hr_agents.providers.whatsapp import MetaCloudConfig

META = MetaCloudConfig(
    phone_number_id="123456",
    access_token=SecretStr("EAAB-test-token"),
    webhook_verify_token=SecretStr("verify-1"),
    api_version="v21.0",
)
TELEGRAM = TelegramConfig(bot_token=SecretStr("123:ABC"))


@respx.mock
def test_whatsapp_cloud_posts_a_text_message() -> None:
    route = respx.post("https://graph.facebook.com/v21.0/123456/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.ABC"}]})
    )
    sender = build_meta_cloud_sender(META)

    result = sender.send(phone="0812-3456-7890", body="  Halo, wawancara besok?  ")

    assert result.accepted is True
    assert result.message_id == "wamid.ABC"
    assert result.provider == "whatsapp.meta_cloud"
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer EAAB-test-token"
    body = json.loads(request.content)
    assert body == {
        "messaging_product": "whatsapp",
        "to": "6281234567890",
        "type": "text",
        "text": {"body": "Halo, wawancara besok?", "preview_url": False},
    }


@respx.mock
def test_whatsapp_cloud_reports_the_graph_error() -> None:
    respx.post("https://graph.facebook.com/v21.0/123456/messages").mock(
        return_value=httpx.Response(
            400,
            json={"error": {"message": "Recipient is not on WhatsApp", "code": 131026}},
        )
    )

    result = build_meta_cloud_sender(META).send(phone="0812-3456-7890", body="Halo")

    assert result.accepted is False
    assert "131026" in result.detail
    assert "not on WhatsApp" in result.detail


@respx.mock
def test_whatsapp_cloud_a_200_without_a_message_id_is_not_delivery() -> None:
    respx.post("https://graph.facebook.com/v21.0/123456/messages").mock(
        return_value=httpx.Response(200, json={"messages": []})
    )

    result = build_meta_cloud_sender(META).send(phone="0812-3456-7890", body="Halo")

    assert result.accepted is False
    assert "message id" in result.detail


@respx.mock
def test_whatsapp_cloud_truncates_at_the_api_limit() -> None:
    route = respx.post("https://graph.facebook.com/v21.0/123456/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.ABC"}]})
    )

    build_meta_cloud_sender(META).send(phone="081234567890", body="x" * (MAX_TEXT_CHARS + 10))

    body = json.loads(route.calls[0].request.content)
    assert len(body["text"]["body"]) == MAX_TEXT_CHARS


@respx.mock
def test_whatsapp_cloud_a_transport_error_is_a_refusal_not_a_crash() -> None:
    respx.post("https://graph.facebook.com/v21.0/123456/messages").mock(
        side_effect=httpx.ConnectError("no route")
    )

    result = build_meta_cloud_sender(META).send(phone="081234567890", body="Halo")

    assert result.accepted is False
    assert "ConnectError" in result.detail


@respx.mock
def test_telegram_posts_a_message_to_the_bot() -> None:
    route = respx.post("https://api.telegram.org/bot123:ABC/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})
    )
    sender = TelegramSender(TELEGRAM)

    result = sender.send(chat_id="55501", body="Halo")

    assert result == SendResult(provider="telegram.bot", accepted=True, message_id="77")
    body = json.loads(route.calls[0].request.content)
    assert body == {"chat_id": "55501", "text": "Halo", "disable_web_page_preview": True}


@respx.mock
def test_telegram_an_error_is_a_refusal() -> None:
    respx.post("https://api.telegram.org/bot123:ABC/sendMessage").mock(
        return_value=httpx.Response(
            403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}
        )
    )

    result = TelegramSender(TELEGRAM).send(chat_id="55501", body="Halo")

    assert result.accepted is False
    assert "blocked by the user" in result.detail


@respx.mock
def test_telegram_does_not_treat_a_200_with_ok_false_as_delivery() -> None:
    respx.post("https://api.telegram.org/bot123:ABC/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": False, "description": "chat not found"})
    )

    result = TelegramSender(TELEGRAM).send(chat_id="55501", body="Halo")

    assert result.accepted is False
    assert "chat not found" in result.detail


def test_an_empty_body_never_reaches_a_provider() -> None:
    assert MetaCloudSender(META).send(phone="081234567890", body="   ").accepted is False
    assert TelegramSender(TELEGRAM).send(chat_id="55501", body="").accepted is False
