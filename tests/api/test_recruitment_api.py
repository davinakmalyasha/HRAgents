"""Integration tests for the recruitment API surface (documents → jobs → evaluations)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from hr_agents.main import create_app
from hr_agents.models import (
    DimensionScore,
    EvaluationFlag,
    EvidenceRef,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    SourceType,
    TechnicalEvaluation,
)

BASE_SLOT = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)


def make_client() -> TestClient:
    return TestClient(create_app())


def upload_cv(client: TestClient, content: bytes = b"Budi Santoso, backend engineer.") -> dict:
    response = client.post(
        "/v1/documents",
        files={"file": ("cv.txt", content, "text/plain")},
        data={"kind": "cv", "uploaded_by": "api"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_job(client: TestClient) -> dict:
    response = client.post(
        "/v1/jobs",
        json={
            "title": "Backend Engineer",
            "created_by": "hr-admin",
            "must_have_skills": ["python"],
        },
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
    sigma: float = 0.0,
    flags: list[EvaluationFlag] | None = None,
    breakdown: list[DimensionScore] | None = None,
    recommendation: Recommendation = Recommendation.AUTO_SCHEDULE,
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
        sigma=sigma,
        breakdown=breakdown
        or [
            DimensionScore(
                dimension=dimension,
                score=s_tech,
                weight=0.25,
                rationale="evidence",
                evidence=[
                    EvidenceRef(
                        source_type=SourceType.RESUME,
                        locator=f"resume#/{dimension.value}",
                        excerpt="Documented in the attached CV.",
                        confidence=0.9,
                    )
                ],
            )
            for dimension in ScoreDimension
        ],
        flags=flags or [],
        recommendation=recommendation,
    )
    client.app.state.recruiting.evaluations.register(  # type: ignore[attr-defined]
        application_id=UUID(application_id),
        evaluation=evaluation,
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    return evaluation


# --- documents -------------------------------------------------------------------


def test_upload_document_returns_hash() -> None:
    with make_client() as client:
        body = upload_cv(client, b"hello world")

    assert body["kind"] == "cv"
    assert body["size_bytes"] == 11
    assert len(body["sha256"]) == 64


def test_upload_rejects_unknown_kind() -> None:
    with make_client() as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("x.bin", b"x", "application/octet-stream")},
            data={"kind": "photo"},
        )

    assert response.status_code == 422


# --- jobs ------------------------------------------------------------------------


def test_job_crud_flow() -> None:
    with make_client() as client:
        job = create_job(client)
        job_id = job["id"]
        assert job["status"] == "draft"

        listed = client.get("/v1/jobs")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        fetched = client.get(f"/v1/jobs/{job_id}")
        assert fetched.json()["title"] == "Backend Engineer"

        updated = client.patch(
            f"/v1/jobs/{job_id}",
            json={"by": "hr-admin", "description": "Own the API.", "min_years_experience": 3},
        )
        assert updated.status_code == 200
        assert updated.json()["description"] == "Own the API."

        opened = client.post(f"/v1/jobs/{job_id}/status", json={"status": "open", "by": "hr-admin"})
        assert opened.status_code == 200
        assert opened.json()["status"] == "open"

        closed = client.post(
            f"/v1/jobs/{job_id}/status", json={"status": "closed", "by": "hr-admin"}
        )
        assert closed.json()["status"] == "closed"

        reopen = client.post(f"/v1/jobs/{job_id}/status", json={"status": "open", "by": "hr-admin"})
        assert reopen.status_code == 409


def test_job_weight_validation() -> None:
    with make_client() as client:
        response = client.post(
            "/v1/jobs",
            json={
                "title": "X",
                "created_by": "hr-admin",
                "dimension_weights": {"technical_depth": 0.9},
            },
        )

    assert response.status_code == 409
    assert "sum to 1.0" in response.json()["title"]


def test_job_unknown_404() -> None:
    with make_client() as client:
        response = client.get(f"/v1/jobs/{uuid4()}")

    assert response.status_code == 404


# --- evaluations & overrides -------------------------------------------------------


def test_evaluation_missing_until_registered() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        missing = client.get(f"/v1/applications/{application['application_id']}/evaluation")
        evaluation = register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
        )
        found = client.get(f"/v1/applications/{application['application_id']}/evaluation")

    assert missing.status_code == 404
    assert found.status_code == 200
    body = found.json()
    assert body["id"] == str(evaluation.id)
    assert body["breakdown"][0]["evidence"][0]["locator"].startswith("resume#/")
    assert body["breakdown"][0]["evidence"][0]["excerpt"] == "Documented in the attached CV."
    assert body["s_tech"] == 0.90
    assert body["policy"]["decision"] == "auto_schedule"
    assert len(body["breakdown"]) == 4


def test_override_records_receipt_and_updates_application() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        evaluation = register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.75,
            recommendation=Recommendation.REJECT_REQUIRES_SIGNOFF,
        )

        bad_role = client.post(
            f"/v1/evaluations/{evaluation.id}/overrides",
            json={
                "reviewer_id": "manager-1",
                "reviewer_role": "manager",
                "override_decision": "reject_auto",
                "reason_code": "below_bar",
            },
        )
        agent_blocked = client.post(
            f"/v1/evaluations/{evaluation.id}/overrides",
            json={
                "reviewer_id": "agent:screening_coordinator",
                "reviewer_role": "engineering_lead",
                "override_decision": "reject_auto",
                "reason_code": "below_bar",
            },
        )
        recorded = client.post(
            f"/v1/evaluations/{evaluation.id}/overrides",
            json={
                "reviewer_id": "lead-1",
                "reviewer_role": "engineering_lead",
                "override_decision": "reject_auto",
                "reason_code": "below_bar_after_review",
                "notes": "Reviewed with the panel.",
            },
        )
        history = client.get(f"/v1/evaluations/{evaluation.id}/overrides")
        status = client.get(f"/v1/applications/{application['application_id']}")

    assert bad_role.status_code == 403
    assert agent_blocked.status_code == 403
    assert recorded.status_code == 201
    receipt = recorded.json()
    assert len(receipt["entry_hash"]) == 64
    assert receipt["prev_hash"] is None or len(receipt["prev_hash"]) == 64
    assert receipt["seq"] >= 1  # the chain already carries application.received entries
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["reviewer_id"] == "lead-1"
    assert status.json()["status"] == "rejected"


def test_override_unknown_evaluation_404() -> None:
    with make_client() as client:
        response = client.post(
            f"/v1/evaluations/{uuid4()}/overrides",
            json={
                "reviewer_id": "lead-1",
                "reviewer_role": "engineering_lead",
                "override_decision": "auto_schedule",
                "reason_code": "x",
            },
        )

    assert response.status_code == 404


# --- feedback ----------------------------------------------------------------------


def test_feedback_report_served_from_evaluation() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            breakdown=[
                DimensionScore(
                    dimension=ScoreDimension.TECHNICAL_DEPTH,
                    score=0.9,
                    weight=0.4,
                    rationale="strong",
                ),
                DimensionScore(
                    dimension=ScoreDimension.STACK_ALIGNMENT,
                    score=0.5,
                    weight=0.3,
                    rationale="partial",
                ),
                DimensionScore(
                    dimension=ScoreDimension.SYSTEMS_LITERACY,
                    score=0.85,
                    weight=0.2,
                    rationale="strong",
                ),
                DimensionScore(
                    dimension=ScoreDimension.VERIFIABLE_CERTIFICATIONS,
                    score=0.3,
                    weight=0.1,
                    rationale="none",
                ),
            ],
        )

        english = client.get(f"/v1/candidates/{application['candidate_id']}/feedback")
        indonesian = client.get(
            f"/v1/candidates/{application['candidate_id']}/feedback", params={"language": "id"}
        )
        missing = client.get(f"/v1/candidates/{uuid4()}/feedback")

    assert english.status_code == 200
    body = english.json()
    assert body["job_title"] == "Backend Engineer"
    assert [item["dimension"] for item in body["strengths"]] == [
        "technical_depth",
        "systems_literacy",
    ]
    assert len(body["growth_areas"]) == 2
    assert indonesian.json()["language"] == "id"
    assert missing.status_code == 404


# --- scheduling ----------------------------------------------------------------------


def test_scheduling_auto_and_gated_paths() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.92,
        )
        first, second = str(uuid4()), str(uuid4())
        slots = [
            {
                "start_utc": (BASE_SLOT + timedelta(hours=index)).isoformat(),
                "end_utc": (BASE_SLOT + timedelta(hours=index + 1)).isoformat(),
            }
            for index in range(3)
        ]
        client.post(
            "/v1/scheduling/availability",
            json={"interviewer_id": first, "by": "hr-admin", "slots": slots},
        )
        client.post(
            "/v1/scheduling/availability",
            json={"interviewer_id": second, "by": "hr-admin", "slots": slots[:2]},
        )

        proposal_response = client.post(
            "/v1/scheduling/proposals",
            json={
                "candidate_id": application["candidate_id"],
                "job_id": job["id"],
                "interviewer_ids": [first, second],
                "requested_channels": ["whatsapp"],
            },
        )
        gated = client.post(
            "/v1/scheduling/proposals",
            json={
                "candidate_id": application["candidate_id"],
                "job_id": job["id"],
                "interviewer_ids": [str(uuid4())],
            },
        )

    assert proposal_response.status_code == 201, proposal_response.text
    proposal = proposal_response.json()
    assert proposal["payload"]["auto_scheduled"] is True
    assert proposal["requires_human_approval"] is False
    assert proposal["payload"]["channel"] == "whatsapp"
    assert len(proposal["payload"]["slots"]) == 2
    assert gated.status_code == 409  # no availability recorded for that interviewer


def test_scheduling_requires_evaluation() -> None:
    with make_client() as client:
        interviewer = str(uuid4())
        slots = [
            {
                "start_utc": BASE_SLOT.isoformat(),
                "end_utc": (BASE_SLOT + timedelta(hours=1)).isoformat(),
            }
        ]
        client.post(
            "/v1/scheduling/availability",
            json={"interviewer_id": interviewer, "by": "hr-admin", "slots": slots},
        )
        response = client.post(
            "/v1/scheduling/proposals",
            json={
                "candidate_id": str(uuid4()),
                "job_id": str(uuid4()),
                "interviewer_ids": [interviewer],
            },
        )

    assert response.status_code == 409
    assert "no evaluation" in response.json()["title"]


def test_scheduling_flags_force_human_review() -> None:
    with make_client() as client:
        job = create_job(client)
        application = submit_application(client, job["id"])
        register_evaluation(
            client,
            application_id=application["application_id"],
            candidate_id=application["candidate_id"],
            job_id=job["id"],
            s_tech=0.95,
            flags=[EvaluationFlag.INJECTION_SUSPECTED],
        )
        interviewer = str(uuid4())
        slots = [
            {
                "start_utc": (BASE_SLOT + timedelta(hours=index)).isoformat(),
                "end_utc": (BASE_SLOT + timedelta(hours=index + 1)).isoformat(),
            }
            for index in range(3)
        ]
        client.post(
            "/v1/scheduling/availability",
            json={"interviewer_id": interviewer, "by": "hr-admin", "slots": slots},
        )
        response = client.post(
            "/v1/scheduling/proposals",
            json={
                "candidate_id": application["candidate_id"],
                "job_id": job["id"],
                "interviewer_ids": [interviewer],
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["requires_human_approval"] is True
    assert body["payload"]["policy"]["decision"] == "hitl_anomaly"
    assert body["payload"]["auto_scheduled"] is False


# --- scheduling decisions -------------------------------------------------------------


def gated_application(client: TestClient) -> tuple[dict, dict]:
    """A job + application whose evaluation needs a human scheduling decision."""
    job = create_job(client)
    application = submit_application(client, job["id"])
    register_evaluation(
        client,
        application_id=application["application_id"],
        candidate_id=application["candidate_id"],
        job_id=job["id"],
        s_tech=0.80,
        recommendation=Recommendation.HUMAN_REVIEW,
    )
    return job, application


def pending_proposal(client: TestClient, job: dict, application: dict) -> dict:
    interviewer = str(uuid4())
    slots = [
        {
            "start_utc": (BASE_SLOT + timedelta(hours=index)).isoformat(),
            "end_utc": (BASE_SLOT + timedelta(hours=index + 1)).isoformat(),
        }
        for index in range(3)
    ]
    client.post(
        "/v1/scheduling/availability",
        json={"interviewer_id": interviewer, "by": "hr-admin", "slots": slots},
    )
    response = client.post(
        "/v1/scheduling/proposals",
        json={
            "candidate_id": application["candidate_id"],
            "job_id": job["id"],
            "interviewer_ids": [interviewer],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_scheduling_confirm_decides_the_approval_and_schedules() -> None:
    with make_client() as client:
        job, application = gated_application(client)
        proposal = pending_proposal(client, job, application)
        pending = client.get("/v1/approvals")
        decision = client.post(
            f"/v1/scheduling/proposals/{proposal['id']}/decision",
            json={"by": "hr-admin", "decision": "confirm", "reason": "the panel is free"},
        )
        application_after = client.get(f"/v1/applications/{application['application_id']}")
        approvals_after = client.get("/v1/approvals")

    assert proposal["status"] == "pending_approval"
    assert proposal["requires_human_approval"] is True
    subjects = [item["subject"] for item in pending.json()]
    assert "scheduling" in subjects

    assert decision.status_code == 200, decision.text
    body = decision.json()
    assert body["proposal"]["status"] == "confirmed"
    assert body["proposal"]["decided_by"] == "hr-admin"
    assert body["proposal"]["decided_at"] is not None
    assert body["replacement"] is None

    assert application_after.json()["status"] == "scheduled"
    assert approvals_after.json() == []


def test_scheduling_cancel_and_terminal_guards() -> None:
    with make_client() as client:
        job, application = gated_application(client)
        proposal = pending_proposal(client, job, application)
        without_reason = client.post(
            f"/v1/scheduling/proposals/{proposal['id']}/decision",
            json={"by": "hr-admin", "decision": "cancel"},
        )
        cancelled = client.post(
            f"/v1/scheduling/proposals/{proposal['id']}/decision",
            json={"by": "hr-admin", "decision": "cancel", "reason": "interviewer on leave"},
        )
        again = client.post(
            f"/v1/scheduling/proposals/{proposal['id']}/decision",
            json={"by": "hr-admin", "decision": "confirm"},
        )

    assert without_reason.status_code == 409
    assert "reason is required" in without_reason.json()["title"]
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["proposal"]["status"] == "cancelled"
    assert again.status_code == 409
    assert "cannot be decided again" in again.json()["title"]


def test_scheduling_reschedule_creates_a_linked_replacement() -> None:
    with make_client() as client:
        job, application = gated_application(client)
        proposal = pending_proposal(client, job, application)
        rescheduled = client.post(
            f"/v1/scheduling/proposals/{proposal['id']}/decision",
            json={
                "by": "hr-admin",
                "decision": "reschedule",
                "reason": "candidate asked for a later slot",
            },
        )
        original = client.get(f"/v1/scheduling/proposals/{proposal['id']}")

    assert rescheduled.status_code == 200, rescheduled.text
    body = rescheduled.json()
    assert body["proposal"]["status"] == "superseded"
    replacement = body["replacement"]
    assert replacement is not None
    assert replacement["supersedes_id"] == proposal["id"]
    assert replacement["status"] == "pending_approval"
    assert original.json()["status"] == "superseded"


def test_scheduling_decision_requires_a_named_human() -> None:
    with make_client() as client:
        job, application = gated_application(client)
        proposal = pending_proposal(client, job, application)
        response = client.post(
            f"/v1/scheduling/proposals/{proposal['id']}/decision",
            json={"by": "agent:hr_bot", "decision": "confirm"},
        )

    assert response.status_code == 403
    assert "named human" in response.json()["title"]


def test_scheduling_decision_unknown_proposal_404() -> None:
    with make_client() as client:
        response = client.post(
            f"/v1/scheduling/proposals/{uuid4()}/decision",
            json={"by": "hr-admin", "decision": "confirm"},
        )

    assert response.status_code == 404
