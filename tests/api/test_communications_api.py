"""Integration tests for the candidate communication outbox endpoints."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from hr_agents.main import create_app
from hr_agents.messaging.store import reply_dedup_key
from hr_agents.models import (
    CandidateReply,
    DimensionScore,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
)


def make_client() -> TestClient:
    return TestClient(create_app())


def create_job(client: TestClient) -> dict:
    response = client.post(
        "/v1/jobs",
        json={"title": "Backend Engineer", "created_by": "hr-admin"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit_application(client: TestClient, job_id: str) -> dict:
    response = client.post(
        "/v1/applications",
        json={
            "job_id": job_id,
            "source_channel": "api",
            "consent": {"granted": True},
            "candidate": {"full_name": "Budi Santoso"},
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def register_evaluation(
    client: TestClient,
    *,
    application_id: str,
    candidate_id: str,
    job_id: str,
    s_tech: float = 0.90,
) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=s_tech,
        stack_alignment=s_tech,
        systems_literacy=s_tech,
        verifiable_certifications=s_tech,
    )
    evaluation = TechnicalEvaluation(
        candidate_id=UUID(candidate_id),
        job_id=UUID(job_id),
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
        mean_vector=vector,
        s_tech=s_tech,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=s_tech, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[],
        recommendation=Recommendation.REJECT if s_tech < 0.70 else Recommendation.AUTO_SCHEDULE,
    )
    client.app.state.recruiting.evaluations.register(  # type: ignore[attr-defined]
        application_id=UUID(application_id),
        evaluation=evaluation,
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    return evaluation


def rejection_payload(by: str = "hr-admin", **extra: object) -> dict:
    return {"by": by, **extra}


# --- rejection -------------------------------------------------------------------


def test_rejection_flow_queues_and_records_dispatch() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.50,
        )

        queued = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/rejection",
            json=rejection_payload(),
        )
        history = client.get(f"/v1/candidates/{application['candidate_id']}/communications")
        sent = client.post(
            f"/v1/communications/{queued.json()['id']}/sent",
            json={"by": "hr-admin"},
        )

    assert queued.status_code == 201, queued.text
    body = queued.json()
    assert body["kind"] == "rejection"
    assert body["status"] == "queued"
    assert body["approved_by"] == "hr-admin"
    assert "Where to strengthen" in body["body"]
    assert body["application_id"] == application["application_id"]

    assert history.status_code == 200
    assert len(history.json()) == 1

    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert sent.json()["sent_by"] == "hr-admin"


def test_gated_rejection_needs_a_recorded_decision() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        evaluation = register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.80,
        )

        blocked = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/rejection",
            json=rejection_payload(by="lead-1"),
        )
        override = client.post(
            f"/v1/evaluations/{evaluation.id}/overrides",
            json={
                "reviewer_id": "lead-1",
                "reviewer_role": "engineering_lead",
                "override_decision": "hitl_soft_rejection",
                "reason_code": "below_bar_after_review",
            },
        )
        allowed = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/rejection",
            json=rejection_payload(by="lead-1", language="id"),
        )

    assert blocked.status_code == 409
    assert "recorded rejection decision" in blocked.json()["title"]
    assert override.status_code == 201
    assert allowed.status_code == 201, allowed.text
    assert "Yang menonjol" in allowed.json()["body"]


def test_rejection_rejects_agent_actors() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.50,
        )

        response = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/rejection",
            json=rejection_payload(by="agent:screening_coordinator"),
        )

    assert response.status_code == 403


def test_rejection_preview_renders_the_message_without_queueing_anything() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.50,
        )
        candidate_id = application["candidate_id"]

        preview = client.post(
            f"/v1/candidates/{candidate_id}/communications/rejection/preview",
            json=rejection_payload(to_email="budi@example.com", to_phone="+628123456789"),
        )
        history = client.get(f"/v1/candidates/{candidate_id}/communications")
        # The queue still works after a preview: nothing was consumed by looking.
        queued = client.post(
            f"/v1/candidates/{candidate_id}/communications/rejection",
            json=rejection_payload(to_email="budi@example.com"),
        )
        after = client.get(f"/v1/candidates/{candidate_id}/communications")

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_queue"] is True
    assert body["blockers"] == []
    assert body["kind"] == "rejection"
    assert body["language"] == "en"
    assert body["recipient"] == "budi@example.com"
    assert body["recipient_phone"] == "+628123456789"
    assert "Where to strengthen" in body["body"]
    assert body["subject"] == queued.json()["subject"]
    assert body["body"] == queued.json()["body"]
    # The preview itself stored nothing: only the explicit queue did.
    assert history.status_code == 200
    assert history.json() == []
    assert queued.status_code == 201, queued.text
    assert len(after.json()) == 1


def test_rejection_preview_reports_the_gates_that_block_queueing() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        candidate_id = application["candidate_id"]

        unknown = client.post(
            f"/v1/candidates/{candidate_id}/communications/rejection/preview",
            json=rejection_payload(),
        )
        evaluation = register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=candidate_id,
            job_id=job["id"],
            s_tech=0.80,
        )
        gated = client.post(
            f"/v1/candidates/{candidate_id}/communications/rejection/preview",
            json=rejection_payload(),
        )
        client.post(
            f"/v1/evaluations/{evaluation.id}/overrides",
            json={
                "reviewer_id": "lead-1",
                "reviewer_role": "engineering_lead",
                "override_decision": "hitl_soft_rejection",
                "reason_code": "below_bar_after_review",
            },
        )
        allowed = client.post(
            f"/v1/candidates/{candidate_id}/communications/rejection/preview",
            json=rejection_payload(language="id"),
        )
        client.post(
            f"/v1/candidates/{candidate_id}/communications/rejection",
            json=rejection_payload(by="lead-1", language="id"),
        )
        duplicate = client.post(
            f"/v1/candidates/{candidate_id}/communications/rejection/preview",
            json=rejection_payload(by="lead-1", language="id"),
        )
        queued = client.get(f"/v1/candidates/{candidate_id}/communications")

    # No evaluation at all.
    assert unknown.status_code == 200
    assert unknown.json()["can_queue"] is False
    assert unknown.json()["blockers"] == ["no evaluation"]
    assert unknown.json()["body"] is None

    # Evaluated, but the rejection has no recorded human decision yet.
    assert gated.json()["can_queue"] is False
    assert len(gated.json()["blockers"]) == 1
    assert "recorded rejection decision" in gated.json()["blockers"][0]

    # After the override the same call renders the Indonesian message.
    assert allowed.json()["can_queue"] is True
    assert allowed.json()["language"] == "id"
    assert "Yang menonjol" in allowed.json()["body"]

    # A second active rejection is the other blocker the queue refuses with.
    assert duplicate.json()["can_queue"] is False
    assert duplicate.json()["blockers"] == [
        "an active rejection message already exists for this candidate"
    ]
    assert len(queued.json()) == 1


def test_rejection_preview_unknown_candidate_and_agent_actor() -> None:
    with make_client() as client:
        unknown = client.post(
            f"/v1/candidates/{uuid4()}/communications/rejection/preview",
            json=rejection_payload(),
        )
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.50,
        )
        agent = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/rejection/preview",
            json=rejection_payload(by="agent:screening_coordinator"),
        )
        blank = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/rejection/preview",
            json=rejection_payload(by="   "),
        )
        history = client.get(f"/v1/candidates/{application['candidate_id']}/communications")

    # A preview is readable for anyone who may queue, including an agent: it is
    # only the queue that needs a named human.
    assert unknown.json()["can_queue"] is False
    assert agent.status_code == 200
    assert agent.json()["can_queue"] is True
    assert blank.status_code == 422
    assert history.json() == []


def test_rejection_unknown_candidate_is_404() -> None:
    with make_client() as client:
        response = client.post(
            f"/v1/candidates/{uuid4()}/communications/rejection",
            json=rejection_payload(),
        )

    assert response.status_code == 404


def test_duplicate_active_rejection_is_409() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.50,
        )
        first = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/rejection",
            json=rejection_payload(),
        )
        second = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/rejection",
            json=rejection_payload(),
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert "already exists" in second.json()["title"]


# --- offer -----------------------------------------------------------------------


def test_offer_queues_human_authored_message_and_blocks_blank() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
        )

        blank = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/offer",
            json={"by": "hr-admin", "body": "   "},
        )
        queued = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/offer",
            json={
                "by": "hr-admin",
                "body": "We would like to offer you the role.",
                "subject": "Offer — Backend Engineer",
            },
        )

    assert blank.status_code == 422
    assert queued.status_code == 201, queued.text
    body = queued.json()
    assert body["kind"] == "offer"
    assert body["subject"] == "Offer — Backend Engineer"
    assert body["approved_by"] == "hr-admin"


def test_mark_sent_rules() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
        )
        queued = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/offer",
            json={"by": "hr-admin", "body": "Offer body"},
        ).json()

        missing = client.post(f"/v1/communications/{uuid4()}/sent", json={"by": "hr-admin"})
        agent = client.post(
            f"/v1/communications/{queued['id']}/sent",
            json={"by": "agent:policy_assistant"},
        )
        first = client.post(f"/v1/communications/{queued['id']}/sent", json={"by": "hr-admin"})
        again = client.post(f"/v1/communications/{queued['id']}/sent", json={"by": "hr-admin"})

    assert missing.status_code == 404
    assert agent.status_code == 403
    assert first.status_code == 200
    assert again.status_code == 409


# --- dispatch evidence and replies -------------------------------------------------


def test_transport_dispatch_evidence_is_visible_on_the_message() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
        )
        queued = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/offer",
            json={"by": "hr-admin", "body": "Offer body", "to_email": "budi@example.com"},
        ).json()
        client.app.state.recruiting.communications.record_dispatch_failure(  # type: ignore[attr-defined]
            UUID(queued["id"]), provider="email.smtp", error="mailbox unavailable"
        )
        client.app.state.recruiting.communications.record_dispatch(  # type: ignore[attr-defined]
            UUID(queued["id"]),
            provider="email.smtp",
            recipient="budi@example.com",
            message_id="<outbound-1@example.com>",
        )
        history = client.get(f"/v1/candidates/{application['candidate_id']}/communications")

    body = history.json()[0]
    assert body["status"] == "sent"
    assert body["recipient"] == "budi@example.com"
    assert body["provider"] == "email.smtp"
    assert body["send_attempts"] == 2
    assert body["last_error"] is None
    assert body["sent_by"] == "transport:email.smtp"


def test_invalid_recipient_is_rejected() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
        )

        response = client.post(
            f"/v1/candidates/{application['candidate_id']}/communications/offer",
            json={"by": "hr-admin", "body": "Offer body", "to_email": "not-an-address"},
        )

    assert response.status_code == 422


def test_inbound_replies_are_listed_per_candidate() -> None:
    candidate_id = uuid4()
    other = uuid4()
    with make_client() as client:
        replies = client.app.state.messaging.replies  # type: ignore[attr-defined]
        replies.add(
            CandidateReply(
                candidate_id=candidate_id,
                sender="budi@example.com",
                subject="Re: Your offer",
                body="Saya tertarik, terima kasih.",
                provider="email.imap_poll",
                provider_message_id="<reply-1@example.com>",
                dedup_key=reply_dedup_key(
                    provider="email.imap_poll",
                    message_id="<reply-1@example.com>",
                    sender="budi@example.com",
                    subject="Re: Your offer",
                    body="Saya tertarik, terima kasih.",
                ),
            )
        )
        replies.add(
            CandidateReply(
                candidate_id=other,
                sender="sari@example.com",
                subject="Question",
                body="Kapan jadwalnya?",
                provider="email.imap_poll",
                provider_message_id="<reply-2@example.com>",
                dedup_key=reply_dedup_key(
                    provider="email.imap_poll",
                    message_id="<reply-2@example.com>",
                    sender="sari@example.com",
                    subject="Question",
                    body="Kapan jadwalnya?",
                ),
            )
        )

        mine = client.get(f"/v1/candidates/{candidate_id}/replies")
        theirs = client.get(f"/v1/candidates/{uuid4()}/replies")

    assert mine.status_code == 200
    assert len(mine.json()) == 1
    assert mine.json()[0]["sender"] == "budi@example.com"
    assert mine.json()[0]["body"] == "Saya tertarik, terima kasih."
    assert theirs.json() == []


# --- manual links (WhatsApp) --------------------------------------------------------


def whatsapp_message(client: TestClient, **extra: object) -> dict:
    job = create_job(client)
    application = submit_application(client, job["id"])
    register_evaluation(
        client,
        application_id=application["application_id"],
        candidate_id=application["candidate_id"],
        job_id=job["id"],
    )
    response = client.post(
        f"/v1/candidates/{application['candidate_id']}/communications/offer",
        json={
            "by": "hr-admin",
            "body": "We would like to offer you the role.",
            "channel": "whatsapp",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def email_message(client: TestClient) -> dict:
    job = create_job(client)
    application = submit_application(client, job["id"])
    register_evaluation(
        client,
        application_id=application["application_id"],
        candidate_id=application["candidate_id"],
        job_id=job["id"],
    )
    response = client.post(
        f"/v1/candidates/{application['candidate_id']}/communications/offer",
        json={
            "by": "hr-admin",
            "body": "We would like to offer you the role.",
            "to_email": "sari@example.com",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_link_is_composed_and_never_marks_the_message_sent() -> None:
    with make_client() as client:
        message = whatsapp_message(client, to_phone="0812-3456-7890")
        link = client.post(
            f"/v1/communications/{message['id']}/dispatch-link",
            json={"by": "Sinta Prabowo"},
        )
        history = client.get(f"/v1/candidates/{message['candidate_id']}/communications")

    assert link.status_code == 200, link.text
    body = link.json()
    assert body["phone"] == "6281234567890"
    assert body["provider"] == "whatsapp.manual_links"
    assert body["url"].startswith("https://wa.me/6281234567890?text=")
    assert body["body"] == "We would like to offer you the role."
    assert history.json()[0]["status"] == "queued"
    assert history.json()[0]["sent_by"] is None
    assert history.json()[0]["recipient_phone"] == "0812-3456-7890"


def test_manual_link_needs_a_number() -> None:
    with make_client() as client:
        message = whatsapp_message(client)
        missing = client.post(
            f"/v1/communications/{message['id']}/dispatch-link",
            json={"by": "Sinta Prabowo"},
        )
        supplied = client.post(
            f"/v1/communications/{message['id']}/dispatch-link",
            json={"by": "Sinta Prabowo", "to_phone": "+62 812 111 222 333"},
        )

    assert missing.status_code == 409
    assert "phone number is required" in missing.json()["title"]
    assert supplied.status_code == 200
    assert supplied.json()["phone"] == "62812111222333"


def test_manual_link_refuses_an_unusable_number() -> None:
    with make_client() as client:
        message = whatsapp_message(client, to_phone="123")

        response = client.post(
            f"/v1/communications/{message['id']}/dispatch-link",
            json={"by": "Sinta Prabowo"},
        )

    assert response.status_code == 400
    assert "not a usable WhatsApp number" in response.json()["title"]


def test_manual_link_requires_a_named_human_and_a_queued_message() -> None:
    with make_client() as client:
        message = whatsapp_message(client, to_phone="0812-3456-7890")
        agent = client.post(
            f"/v1/communications/{message['id']}/dispatch-link",
            json={"by": "agent:screening_coordinator"},
        )
        sent = client.post(f"/v1/communications/{message['id']}/sent", json={"by": "hr-admin"})
        again = client.post(
            f"/v1/communications/{message['id']}/dispatch-link",
            json={"by": "Sinta Prabowo"},
        )
        other = email_message(client)
        wrong_channel = client.post(
            f"/v1/communications/{other['id']}/dispatch-link",
            json={"by": "Sinta Prabowo"},
        )

    assert agent.status_code == 403
    assert sent.status_code == 200
    assert again.status_code == 409
    assert wrong_channel.status_code == 409
    assert "apply to WhatsApp" in wrong_channel.json()["title"]


# --- RBAC ------------------------------------------------------------------------


def test_employee_cannot_read_or_queue_communications(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from hr_agents.config import ApiPrincipalSettings, Settings
    from hr_agents.rbac import RoleId

    settings = Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("emp-key"), role=RoleId.EMPLOYEE, actor_id="emp-1"),
            ApiPrincipalSettings(
                key=SecretStr("hr-key"), role=RoleId.HR_ADMIN, actor_id="hr-admin"
            ),
        ],
    )
    candidate_id = uuid4()

    with TestClient(create_app(settings)) as client:
        listed = client.get(
            f"/v1/candidates/{candidate_id}/communications",
            headers={"X-API-Key": "emp-key"},
        )
        queued = client.post(
            f"/v1/candidates/{candidate_id}/communications/rejection",
            json=rejection_payload(),
            headers={"X-API-Key": "emp-key"},
        )
        admin = client.get(
            f"/v1/candidates/{candidate_id}/communications",
            headers={"X-API-Key": "hr-key"},
        )

    assert listed.status_code == 403
    assert queued.status_code == 403
    assert admin.status_code == 200
    assert admin.json() == []
