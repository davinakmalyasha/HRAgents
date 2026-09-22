"""Integration tests for the candidate communication outbox endpoints."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from hr_agents.main import create_app
from hr_agents.models import (
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
        runs=[ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector)],
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
    monkeypatch.setattr("hr_agents.api.deps.get_settings", lambda: settings)
    candidate_id = uuid4()

    with TestClient(create_app()) as client:
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
