"""Inbound webhook route: the signature is the credential, replay is refused."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from hr_agents.api.routers import webhooks as webhooks_router
from hr_agents.main import create_app
from hr_agents.messaging.webhooks import verified_headers

SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()


def resend_event(**data: object) -> bytes:
    payload = {
        "type": "email.received",
        "data": {
            "from": "Budi Santoso <budi@example.com>",
            "to": ["hr@example.com"],
            "subject": "Re: Your application",
            "text": "Terima kasih, saya tertarik.",
            "message_id": "<inbound-1@example.com>",
            **data,
        },
    }
    return json.dumps(payload).encode()


def signed(body: bytes, *, delivery_id: str = "msg_1") -> dict[str, str]:
    return verified_headers(SECRET, delivery_id, body, timestamp=int(time.time()))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(webhooks_router, "_resend_secret", lambda: SECRET)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_an_unconfigured_webhook_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhooks_router, "_resend_secret", lambda: None)
    with TestClient(create_app()) as client:
        response = client.post("/v1/webhooks/email/resend", content=b"{}")

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


def test_a_valid_delivery_is_accepted_and_stored_or_counted(client: TestClient) -> None:
    body = resend_event()

    response = client.post("/v1/webhooks/email/resend", content=body, headers=signed(body))

    assert response.status_code == 202, response.text
    result = response.json()
    assert result["event"] == "email.received"
    # No candidate matches this sender in a fresh install; the delivery is still
    # acknowledged, because a non-2xx would make the provider retry forever.
    assert result["stored"] == 0
    assert result["unmatched"] == 1


def test_a_tampered_body_is_refused(client: TestClient) -> None:
    body = resend_event()
    headers = signed(body)

    response = client.post("/v1/webhooks/email/resend", content=body + b" ", headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "webhook_refused"


def test_a_replayed_delivery_is_refused(client: TestClient) -> None:
    body = resend_event()
    headers = signed(body)
    assert (
        client.post("/v1/webhooks/email/resend", content=body, headers=headers).status_code == 202
    )

    replayed = client.post("/v1/webhooks/email/resend", content=body, headers=headers)

    assert replayed.status_code == 401
    assert "already accepted" in replayed.json()["detail"]


def test_a_signed_event_this_route_does_not_handle_is_acknowledged(client: TestClient) -> None:
    body = json.dumps({"type": "email.delivered", "data": {}}).encode()

    response = client.post("/v1/webhooks/email/resend", content=body, headers=signed(body))

    assert response.status_code == 202
    assert response.json()["event"] == "email.delivered"
    assert response.json()["stored"] == 0


def test_malformed_json_with_a_valid_signature_is_a_400(client: TestClient) -> None:
    body = b"not json"

    response = client.post("/v1/webhooks/email/resend", content=body, headers=signed(body))

    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"
