"""Email draft queue: consent-gated confirmation and reasoned discard."""

from uuid import uuid4

from fastapi.testclient import TestClient

from hr_agents.identity import ActorRef
from hr_agents.main import create_app
from hr_agents.messaging.drafts import EmailApplicationDraft, draft_dedup_key
from hr_agents.models import business_today

TODAY = business_today()


def make_client() -> TestClient:
    return TestClient(create_app())


def create_job(client: TestClient, title: str = "Backend Engineer") -> dict:
    response = client.post("/v1/jobs", json={"title": title, "status": "open"})
    assert response.status_code == 201, response.text
    return response.json()


_SEED_COUNTER = 0


def seed_draft(client: TestClient, **overrides: object) -> dict:
    global _SEED_COUNTER
    _SEED_COUNTER += 1
    tag = _SEED_COUNTER
    documents = client.app.state.recruiting.documents  # type: ignore[attr-defined]
    stored = documents.upload(
        filename="cv.txt",
        kind="cv",
        content=f"Rani Dewi {tag}\nBackend engineer with five years of Python.".encode(),
        actor=ActorRef.legacy("mail-ingest"),
    )
    payload: dict[str, object] = {
        "provider": "email.imap_poll",
        "provider_message_id": f"<{uuid4()}@example.com>",
        "dedup_key": draft_dedup_key(
            provider="email.imap_poll",
            message_id=None,
            sender="rani@example.com",
            subject="Lamaran Backend Engineer",
            body="Please consider me.",
            file_hashes=[f"file-{tag}"],
        ),
        "sender": "rani@example.com",
        "sender_name": "Rani",
        "subject": "Lamaran Backend Engineer",
        "body": "Please consider me.",
        "attachment_names": ["cv.txt"],
        "document_ids": [stored.id],
        "refused_attachments": [],
    }
    payload.update(overrides)
    draft = EmailApplicationDraft(**payload)  # type: ignore[arg-type]
    client.app.state.messaging.drafts.add(draft)  # type: ignore[attr-defined]
    return EmailApplicationDraft.model_validate(draft).model_dump(mode="json")


def test_list_and_read_drafts() -> None:
    with make_client() as client:
        assert client.get("/v1/applications/email-drafts").json()["total"] == 0
        seeded = seed_draft(client)

        listed = client.get("/v1/applications/email-drafts").json()
        assert listed["total"] == 1
        assert listed["items"][0]["sender"] == "rani@example.com"

        fetched = client.get(f"/v1/applications/email-drafts/{seeded['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "pending"

        assert client.get(f"/v1/applications/email-drafts/{uuid4()}").status_code == 404


def test_confirm_requires_explicit_consent() -> None:
    with make_client() as client:
        job = create_job(client)
        seeded = seed_draft(client)

        refused = client.post(
            f"/v1/applications/email-drafts/{seeded['id']}/confirm",
            json={"job_id": job["id"], "consent_granted": False},
        )
        assert refused.status_code == 422
        assert (
            client.get(f"/v1/applications/email-drafts/{seeded['id']}").json()["status"]
            == "pending"
        )


def test_confirm_unknown_job_is_404() -> None:
    with make_client() as client:
        seeded = seed_draft(client)

        response = client.post(
            f"/v1/applications/email-drafts/{seeded['id']}/confirm",
            json={"job_id": str(uuid4()), "consent_granted": True},
        )
        assert response.status_code == 404


def test_confirm_without_documents_is_409() -> None:
    with make_client() as client:
        job = create_job(client)
        seeded = seed_draft(client, document_ids=[])

        response = client.post(
            f"/v1/applications/email-drafts/{seeded['id']}/confirm",
            json={"job_id": job["id"], "consent_granted": True},
        )
        assert response.status_code == 409


def test_confirm_creates_application_and_freezes_the_draft() -> None:
    with make_client() as client:
        job = create_job(client)
        seeded = seed_draft(client)

        accepted = client.post(
            f"/v1/applications/email-drafts/{seeded['id']}/confirm",
            json={
                "job_id": job["id"],
                "consent_granted": True,
                "candidate_name": "Rani Dewi",
            },
        )
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["status"] == "queued"

        fetched = client.get(f"/v1/applications/email-drafts/{seeded['id']}").json()
        assert fetched["status"] == "confirmed"
        assert fetched["application_id"] == accepted.json()["application_id"]

        again = client.post(
            f"/v1/applications/email-drafts/{seeded['id']}/confirm",
            json={"job_id": job["id"], "consent_granted": True},
        )
        assert again.status_code == 409


def test_discard_needs_a_reason_and_sticks() -> None:
    with make_client() as client:
        seeded = seed_draft(client)

        blank = client.post(
            f"/v1/applications/email-drafts/{seeded['id']}/discard", json={"reason": "  "}
        )
        assert blank.status_code in (409, 422)

        discarded = client.post(
            f"/v1/applications/email-drafts/{seeded['id']}/discard",
            json={"reason": "spam, no CV of value"},
        )
        assert discarded.status_code == 200
        body = discarded.json()
        assert body["status"] == "discarded"
        assert body["discard_reason"] == "spam, no CV of value"

        assert (
            client.post(
                f"/v1/applications/email-drafts/{seeded['id']}/discard",
                json={"reason": "again"},
            ).status_code
            == 409
        )


def test_status_filter_selects_the_queue() -> None:
    with make_client() as client:
        first = seed_draft(client)
        seed_draft(client)
        client.post(
            f"/v1/applications/email-drafts/{first['id']}/discard",
            json={"reason": "duplicate"},
        )

        pending = client.get("/v1/applications/email-drafts", params={"status": "pending"}).json()
        discarded = client.get(
            "/v1/applications/email-drafts", params={"status": "discarded"}
        ).json()
        everything = client.get("/v1/applications/email-drafts").json()

        assert pending["total"] == 1
        assert discarded["total"] == 1
        assert everything["total"] == 2


def test_confirm_unknown_draft_is_404() -> None:
    with make_client() as client:
        job = create_job(client)
        response = client.post(
            f"/v1/applications/email-drafts/{uuid4()}/confirm",
            json={"job_id": job["id"], "consent_granted": True},
        )
        assert response.status_code == 404
