"""Integration tests for Web Push subscription routes and the approval seam."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.api.auth import settings_role_lookup
from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.identity import ActorRef
from hr_agents.main import create_app
from hr_agents.models import ApprovalSubject, ApproverRole, PushSubscription, Urgency
from hr_agents.rbac import Principal, RoleId
from hr_agents.services.push import PushService, PushStore

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc-123"
KEYS = {"p256dh": "B" * 80, "auth": "a" * 24}
MANAGER = {"X-API-Key": "manager-key"}
EMPLOYEE = {"X-API-Key": "employee-key"}


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[PushSubscription, Mapping[str, object]]] = []

    def send(self, subscription: PushSubscription, payload: Mapping[str, object]) -> None:
        self.sent.append((subscription, payload))


class InlineExecutor:
    def submit(self, fn: Callable[..., object], *args: object) -> object:
        return fn(*args)


def configured_settings() -> Settings:
    return Settings(
        vapid_private_key="test-private-key",
        vapid_public_key="BEsRg_ltY1gzc4u92aQw9Vko_hOGcRCOcBTJd4AiKQqqtC6Vs8TZ3v154LIqYVFavmCmn5UuT3c6Ctf7Nf5rI2c",
        vapid_subject="mailto:ops@example.com",
        api_principals=[
            ApiPrincipalSettings(
                key=SecretStr("manager-key"), role=RoleId.MANAGER, actor_id="rina"
            ),
            ApiPrincipalSettings(
                key=SecretStr("employee-key"), role=RoleId.EMPLOYEE, actor_id="sari"
            ),
        ],
    )


def with_fake_sender(app: FastAPI) -> RecordingSender:
    sender = RecordingSender()
    app.state.push = PushService(
        PushStore(),
        sender=sender,
        executor=InlineExecutor(),
        role_lookup=settings_role_lookup(app.state.settings),
    )
    app.state.people.approvals.set_notifier(app.state.push)
    return sender


def subscription_payload(endpoint: str = ENDPOINT) -> dict[str, object]:
    return {"endpoint": endpoint, "keys": KEYS, "user_agent": "Firefox 140"}


def test_an_unconfigured_deployment_says_so_and_cannot_send() -> None:
    with TestClient(create_app()) as client:
        config = client.get("/v1/push/config")
        assert config.status_code == 200
        assert config.json() == {"enabled": False, "public_key": None}

        created = client.post("/v1/push/subscriptions", json=subscription_payload())
        assert created.status_code == 201, created.text

        sent = client.post("/v1/push/test")
        assert sent.status_code == 409
        assert "not configured" in sent.json()["detail"]


def test_a_configured_deployment_serves_the_public_key_only() -> None:
    with TestClient(create_app(configured_settings())) as client:
        body = client.get("/v1/push/config", headers=MANAGER).json()
        assert body["enabled"] is True
        assert body["public_key"].startswith("BEsRg")
        assert "private" not in body


def test_subscribe_list_and_unsubscribe_are_scoped_to_the_caller() -> None:
    with TestClient(create_app(configured_settings())) as client:
        created = client.post(
            "/v1/push/subscriptions", json=subscription_payload(), headers=MANAGER
        )
        assert created.status_code == 201, created.text
        view = created.json()
        assert view["endpoint"] == ENDPOINT
        assert "p256dh" not in view and "auth" not in view, "the keys are not echoed"
        subscription_id = view["id"]

        listed = client.get("/v1/push/subscriptions", headers=MANAGER).json()
        assert listed["total"] == 1
        assert listed["items"][0]["id"] == subscription_id

        assert client.get("/v1/push/subscriptions", headers=EMPLOYEE).json()["total"] == 0
        stolen = client.delete(f"/v1/push/subscriptions/{subscription_id}", headers=EMPLOYEE)
        assert stolen.status_code == 404
        assert client.get("/v1/push/subscriptions", headers=MANAGER).json()["total"] == 1

        removed = client.delete(f"/v1/push/subscriptions/{subscription_id}", headers=MANAGER)
        assert removed.status_code == 204
        assert client.get("/v1/push/subscriptions", headers=MANAGER).json()["total"] == 0


def test_a_plain_http_endpoint_is_refused() -> None:
    with TestClient(create_app(configured_settings())) as client:
        response = client.post(
            "/v1/push/subscriptions",
            json=subscription_payload("http://example.com/push"),
            headers=MANAGER,
        )
        assert response.status_code == 409
        assert "HTTPS" in response.json()["detail"]


def test_the_test_button_reports_what_it_delivered() -> None:
    app = create_app(configured_settings())
    with TestClient(app) as client:
        sender = with_fake_sender(app)
        client.post("/v1/push/subscriptions", json=subscription_payload(), headers=MANAGER)

        sent = client.post("/v1/push/test", headers=MANAGER)

        assert sent.status_code == 200, sent.text
        assert sent.json() == {"attempted": 1, "delivered": 1, "pruned": 0, "failed": 0}
        assert sender.sent[0][1]["tag"] == "push-test"


def test_an_approval_created_by_any_department_reaches_push() -> None:
    """The engine's notifier is wired at composition, not by each caller."""
    app = create_app(configured_settings())
    with TestClient(app) as client:
        sender = with_fake_sender(app)
        client.post("/v1/push/subscriptions", json=subscription_payload(), headers=MANAGER)

        app.state.people.approvals.create(
            subject=ApprovalSubject.LEAVE_REQUEST,
            subject_id="leave-1",
            title="Annual leave for Sari",
            summary="Three days",
            assignee_role=ApproverRole.MANAGER,
            actor=ActorRef.from_principal(Principal(actor_id="sari", role=RoleId.EMPLOYEE)),
            urgency=Urgency.HIGH,
        )

        assert len(sender.sent) == 1
        payload = sender.sent[0][1]
        assert payload["title"] == "Approval waiting"
        assert "Sari" not in str(payload["body"])


def test_deleting_an_unknown_subscription_is_a_404() -> None:
    with TestClient(create_app(configured_settings())) as client:
        response = client.delete(f"/v1/push/subscriptions/{uuid4()}", headers=MANAGER)
        assert response.status_code == 404
        assert "no such push subscription" in response.json()["detail"]
