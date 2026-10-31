"""Telegram webhook: the secret-token header is the only credential."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from hr_agents.api.routers import webhooks as webhooks_router
from hr_agents.main import create_app

SECRET = "tg-secret-1"


def telegram_payload(chat_id: int = 55501) -> bytes:
    return json.dumps(
        {
            "update_id": 1001,
            "message": {
                "message_id": 41,
                "from": {"id": chat_id, "is_bot": False, "first_name": "Sari"},
                "chat": {"id": chat_id, "type": "private"},
                "date": 1760000000,
                "text": "Halo, saya tertarik.",
            },
        }
    ).encode()


def headers(secret: str = SECRET) -> dict[str, str]:
    return {"X-Telegram-Bot-Api-Secret-Token": secret, "Content-Type": "application/json"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(webhooks_router, "_telegram_secret", lambda: SECRET)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_a_valid_delivery_is_acknowledged_even_with_no_matching_chat(
    client: TestClient,
) -> None:
    response = client.post("/v1/webhooks/telegram", content=telegram_payload(), headers=headers())

    assert response.status_code == 202, response.text
    assert response.json()["unmatched"] == 1


def test_a_wrong_secret_is_refused(client: TestClient) -> None:
    response = client.post(
        "/v1/webhooks/telegram", content=telegram_payload(), headers=headers("nope")
    )

    assert response.status_code == 401
    assert response.json()["code"] == "webhook_refused"


def test_a_missing_secret_is_refused(client: TestClient) -> None:
    response = client.post("/v1/webhooks/telegram", content=telegram_payload())

    assert response.status_code == 401


def test_an_unconfigured_route_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhooks_router, "_telegram_secret", lambda: None)
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/webhooks/telegram", content=telegram_payload(), headers=headers()
        )

    assert response.status_code == 503


def test_an_update_without_text_is_acknowledged(client: TestClient) -> None:
    body = json.dumps(
        {
            "update_id": 1002,
            "message": {
                "message_id": 42,
                "chat": {"id": 55501, "type": "private"},
                "date": 1760000000,
                "photo": [{"file_id": "abc"}],
            },
        }
    ).encode()

    response = client.post("/v1/webhooks/telegram", content=body, headers=headers())

    assert response.status_code == 202
    assert response.json()["stored"] == 0


def test_a_body_that_is_not_json_is_refused(client: TestClient) -> None:
    response = client.post("/v1/webhooks/telegram", content=b"not json", headers=headers())

    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"
