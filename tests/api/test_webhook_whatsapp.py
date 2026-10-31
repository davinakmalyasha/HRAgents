"""Meta WhatsApp webhook: the handshake, the signature, and the replay guard."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from hr_agents.api.routers import webhooks as webhooks_router
from hr_agents.main import create_app

VERIFY_TOKEN = "verify-1"
APP_SECRET = "app-secret-1"


def meta_payload(phone: str = "6281234567890") -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": "123"},
                                "messages": [
                                    {
                                        "from": phone,
                                        "id": "wamid.1",
                                        "timestamp": "1760000000",
                                        "type": "text",
                                        "text": {"body": "Halo, saya tertarik."},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()


def signed(body: bytes, *, delivery_id: str = "delivery-1") -> dict[str, str]:
    signature = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={signature}",
        "X-Hub-Delivery-Id": delivery_id,
        "Content-Type": "application/json",
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(webhooks_router, "_meta_secrets", lambda: (VERIFY_TOKEN, APP_SECRET))
    with TestClient(create_app()) as test_client:
        yield test_client


def test_the_subscription_handshake_echoes_the_challenge(client: TestClient) -> None:
    response = client.get(
        "/v1/webhooks/whatsapp/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "12345",
        },
    )

    assert response.status_code == 200
    assert response.text == "12345"


def test_a_wrong_verification_token_is_refused(client: TestClient) -> None:
    response = client.get(
        "/v1/webhooks/whatsapp/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "nope",
            "hub.challenge": "12345",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "webhook_refused"


def test_an_unconfigured_route_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhooks_router, "_meta_secrets", lambda: None)
    with TestClient(create_app()) as client:
        response = client.get("/v1/webhooks/whatsapp/meta")
        post = client.post("/v1/webhooks/whatsapp/meta", content=b"{}")

    assert response.status_code == 503
    assert post.status_code == 503


def test_a_valid_delivery_is_acknowledged_even_with_no_matching_number(
    client: TestClient,
) -> None:
    body = meta_payload()

    response = client.post("/v1/webhooks/whatsapp/meta", content=body, headers=signed(body))

    assert response.status_code == 202, response.text
    assert response.json()["unmatched"] == 1


def test_a_tampered_body_is_refused(client: TestClient) -> None:
    body = meta_payload()

    response = client.post("/v1/webhooks/whatsapp/meta", content=body + b" ", headers=signed(body))

    assert response.status_code == 401
    assert response.json()["code"] == "webhook_refused"


def test_a_replayed_delivery_is_refused(client: TestClient) -> None:
    body = meta_payload()
    headers = signed(body)
    assert (
        client.post("/v1/webhooks/whatsapp/meta", content=body, headers=headers).status_code == 202
    )

    replayed = client.post("/v1/webhooks/whatsapp/meta", content=body, headers=headers)

    assert replayed.status_code == 401
    assert "already accepted" in replayed.json()["detail"]


def test_a_payload_without_messages_is_acknowledged(client: TestClient) -> None:
    body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()

    response = client.post("/v1/webhooks/whatsapp/meta", content=body, headers=signed(body))

    assert response.status_code == 202
    assert response.json()["stored"] == 0
