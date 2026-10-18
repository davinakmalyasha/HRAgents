"""The operator dead-letter endpoints: metadata listing and audited requeue."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.providers.queue import QueueMessage
from hr_agents.rbac import RoleId

TOPIC = "evaluation.evaluate"


class FakeQueue:
    def __init__(self) -> None:
        self.messages = [
            QueueMessage(
                id="m-old",
                topic=TOPIC,
                payload={
                    "application_id": str(uuid4()),
                    "resume_text": "candidate-secret-text",
                },
                attempts=3,
                failed_reason="provider timeout",
            ),
            QueueMessage(
                id="m-new",
                topic=TOPIC,
                payload={"job_id": "job-1"},
                attempts=1,
                failed_reason="schema validation",
            ),
        ]
        self.requeued: list[str] = []

    async def dead_letters(self, topic: str | None = None) -> list[QueueMessage]:
        return list(self.messages)

    async def requeue_dead(self, message_id: str) -> bool:
        for message in list(self.messages):
            if message.id == message_id:
                self.messages.remove(message)
                self.requeued.append(message_id)
                return True
        return False


def test_dead_letters_list_metadata_but_never_payload_values() -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.queue = FakeQueue()
        response = client.get("/v1/ops/dead-letters")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        item = next(entry for entry in body["items"] if entry["message_id"] == "m-old")
        assert item["topic"] == TOPIC
        assert item["attempts"] == 3
        assert item["failed_reason"] == "provider timeout"
        assert item["payload_keys"] == ["application_id", "resume_text"]
        assert item["application_id"] is not None
        assert "candidate-secret-text" not in response.text


def test_requeueing_a_dead_letter_records_the_reason_on_the_chain() -> None:
    app = create_app()
    with TestClient(app) as client:
        queue = FakeQueue()
        app.state.queue = queue
        response = client.post(
            "/v1/ops/dead-letters/m-old/requeue",
            json={"reason": "provider recovered; retry the evaluation"},
        )

        assert response.status_code == 200
        assert response.json() == {"requeued": True}
        assert queue.requeued == ["m-old"]

        entry = app.state.audit.entries[-1]
        assert entry.action == "ops.dead_letter_requeued"
        assert entry.subject_id == "m-old"
        assert entry.payload["reason"] == "provider recovered; retry the evaluation"


def test_an_unknown_dead_letter_is_a_404_and_an_empty_reason_is_a_422() -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.queue = FakeQueue()
        missing = client.post("/v1/ops/dead-letters/nope/requeue", json={"reason": "retry"})
        empty_reason = client.post("/v1/ops/dead-letters/m-old/requeue", json={"reason": ""})

        assert missing.status_code == 404
        assert empty_reason.status_code == 422


def test_ops_answers_503_when_the_queue_is_not_resolved() -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.queue = None

        response = client.get("/v1/ops/dead-letters")

        assert response.status_code == 503


def test_only_an_admin_manage_principal_reaches_the_ops_surface() -> None:
    settings = Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("fin-key"), role=RoleId.FINANCE, actor_id="fin-1")
        ],
    )
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.queue = FakeQueue()
        headers = {"X-API-Key": "fin-key"}

        listing = client.get("/v1/ops/dead-letters", headers=headers)
        requeue = client.post(
            "/v1/ops/dead-letters/m-old/requeue",
            json={"reason": "retry"},
            headers=headers,
        )

        assert listing.status_code == 403
        assert requeue.status_code == 403
