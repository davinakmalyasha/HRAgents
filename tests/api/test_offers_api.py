"""Integration tests for the offer API surface."""

from uuid import UUID, uuid4

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


def terms_payload(**overrides: object) -> dict:
    base: dict[str, object] = {
        "position_title": "Backend Engineer",
        "employment_type": "pkwtt",
        "start_date": "2026-11-01",
        "probation_months": 3,
        "salary_amount": 25_000_000.0,
        "salary_currency": "IDR",
    }
    base.update(overrides)
    return base


def seeded_application(client: TestClient) -> dict:
    """A job + application with a registered evaluation (offers need one)."""
    job = client.post("/v1/jobs", json={"title": "Backend Engineer"}).json()
    application = client.post(
        "/v1/applications",
        json={
            "job_id": job["id"],
            "source_channel": "api",
            "consent": {"granted": True},
            "candidate": {"full_name": "Budi Santoso"},
        },
    ).json()
    vector = ScoreVector(
        technical_depth=0.9,
        stack_alignment=0.9,
        systems_literacy=0.9,
        verifiable_certifications=0.9,
    )
    evaluation = TechnicalEvaluation(
        candidate_id=UUID(application["candidate_id"]),
        job_id=UUID(job["id"]),
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
        mean_vector=vector,
        s_tech=0.9,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=0.9, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[],
        recommendation=Recommendation.AUTO_SCHEDULE,
    )
    client.app.state.recruiting.evaluations.register(  # type: ignore[attr-defined]
        application_id=UUID(application["application_id"]),
        evaluation=evaluation,
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    return application


def test_offer_full_flow() -> None:
    with make_client() as client:
        application = seeded_application(client)

        created = client.post(
            "/v1/offers",
            json={
                "application_id": application["application_id"],
                "terms": terms_payload(),
            },
        )
        offer = created.json()

        revised = client.patch(
            f"/v1/offers/{offer['id']}",
            json={"terms": terms_payload(salary_amount=27_000_000.0)},
        )
        submitted = client.post(f"/v1/offers/{offer['id']}/submit", json={})
        pending = client.get("/v1/approvals")
        approved = client.post(
            f"/v1/offers/{offer['id']}/decision",
            json={"decision": "approve"},
        )
        messaged = client.post(f"/v1/offers/{offer['id']}/message", json={})
        accepted = client.post(
            f"/v1/offers/{offer['id']}/acceptance",
            json={"accepted": True},
        )
        communications = client.get(f"/v1/candidates/{application['candidate_id']}/communications")

    assert created.status_code == 201, created.text
    assert offer["status"] == "draft"
    assert len(offer["revisions"]) == 1

    assert revised.status_code == 200
    assert len(revised.json()["revisions"]) == 2

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_approval"
    assert any(item["subject"] == "offer" for item in pending.json())

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by"] == "local-dev"

    assert messaged.status_code == 200, messaged.text
    assert messaged.json()["status"] == "queued"

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["accepted_at"] is not None

    messages = communications.json()
    assert len(messages) == 1
    assert messages[0]["kind"] == "offer"
    assert "Backend Engineer" in messages[0]["body"]


def test_offer_guards_and_terminal_states() -> None:
    with make_client() as client:
        application = seeded_application(client)
        created = client.post(
            "/v1/offers",
            json={
                "application_id": application["application_id"],
                "terms": terms_payload(),
            },
        ).json()

        premature = client.post(f"/v1/offers/{created['id']}/message", json={})
        client.post(f"/v1/offers/{created['id']}/submit", json={})
        late_revision = client.patch(
            f"/v1/offers/{created['id']}",
            json={"terms": terms_payload(salary_amount=30_000_000.0)},
        )
        unknown = client.get(f"/v1/offers/{uuid4()}")

    assert premature.status_code == 409
    assert "approved offer" in premature.json()["title"]
    assert late_revision.status_code == 409
    assert "draft" in late_revision.json()["title"]
    assert unknown.status_code == 404


def test_offer_refuses_a_caller_supplied_actor() -> None:
    """A body cannot name the actor, and the field is refused rather than ignored.

    The old assertion here was a 403 with "named human" in the message: a request
    body that said ``by="agent:hr_bot"``. Over HTTP a request can no longer name
    an actor at all, so the same attempt is a 422 naming the field. That is the
    stronger property — the difference between a field the server refuses and a
    field a user might believe they overrode. The named-human gate itself moved
    to the service layer, where an agent actor can still be constructed, and
    ``tests/services/test_offers.py`` covers it there.
    """
    with make_client() as client:
        application = seeded_application(client)
        body = {
            "application_id": application["application_id"],
            "terms": terms_payload(),
        }
        create_refused = client.post("/v1/offers", json={**body, "by": "agent:hr_bot"})
        created = client.post("/v1/offers", json=body).json()
        client.post(f"/v1/offers/{created['id']}/submit", json={})
        decide_refused = client.post(
            f"/v1/offers/{created['id']}/decision",
            json={"decision": "approve", "by": "agent:hr_bot"},
        )
        decided = client.post(
            f"/v1/offers/{created['id']}/decision",
            json={"decision": "approve"},
        )

    assert create_refused.status_code == 422
    assert any(error["loc"][-1] == "by" for error in create_refused.json()["detail"])
    assert decide_refused.status_code == 422
    assert any(error["loc"][-1] == "by" for error in decide_refused.json()["detail"])
    # and the same call without the field is attributed to the key's holder
    assert decided.status_code == 200
    assert decided.json()["decided_by"] == "local-dev"


def test_offer_withdrawal_withdraws_the_approval() -> None:
    with make_client() as client:
        application = seeded_application(client)
        created = client.post(
            "/v1/offers",
            json={
                "application_id": application["application_id"],
                "terms": terms_payload(),
            },
        ).json()
        client.post(f"/v1/offers/{created['id']}/submit", json={})

        without_reason = client.post(
            f"/v1/offers/{created['id']}/decision",
            json={"decision": "withdraw"},
        )
        withdrawn = client.post(
            f"/v1/offers/{created['id']}/decision",
            json={"decision": "withdraw", "reason": "headcount frozen"},
        )
        approvals = client.get("/v1/approvals")

    assert without_reason.status_code == 409
    assert "reason is required" in without_reason.json()["title"]
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "withdrawn"
    assert approvals.json() == []
