from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from hr_agents.main import create_app
from hr_agents.services.ingestion import ApplicationStatus


def make_payload(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "source_channel": "api",
        "consent": {"granted": True, "policy_version": "1.0"},
        "candidate": {
            "full_name": "Budi Santoso",
            "emails": ["budi@example.com"],
        },
        "metadata": {"source": "test"},
    }


def app_at(client: TestClient, status_value: ApplicationStatus) -> str:
    """Submit an application and force its status (test setup, not an API move)."""
    created = client.post("/v1/applications", json=make_payload(str(uuid4())))
    application_id = created.json()["application_id"]
    client.app.state.store.set_status(  # type: ignore[attr-defined]
        UUID(application_id), status_value, event="test.setup"
    )
    return application_id


def test_submit_application_accepted() -> None:
    app = create_app()
    job_id = str(uuid4())
    with TestClient(app) as client:
        response = client.post("/v1/applications", json=make_payload(job_id))

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["application_id"]
    assert body["candidate_id"]


def test_idempotent_replay_returns_same_application() -> None:
    app = create_app()
    job_id = str(uuid4())
    headers = {"Idempotency-Key": "replay-1"}
    with TestClient(app) as client:
        first = client.post("/v1/applications", json=make_payload(job_id), headers=headers)
        second = client.post("/v1/applications", json=make_payload(job_id), headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["application_id"] == second.json()["application_id"]


def test_idempotency_conflict_returns_409_problem() -> None:
    app = create_app()
    headers = {"Idempotency-Key": "conflict-1"}
    with TestClient(app) as client:
        first = client.post("/v1/applications", json=make_payload(str(uuid4())), headers=headers)
        conflicting = client.post(
            "/v1/applications",
            json=make_payload(str(uuid4())),
            headers=headers,
        )

    assert first.status_code == 202
    assert conflicting.status_code == 409
    assert conflicting.headers["content-type"].startswith("application/problem+json")
    assert conflicting.json()["status"] == 409


def test_get_application_status_and_timeline() -> None:
    app = create_app()
    job_id = str(uuid4())
    with TestClient(app) as client:
        created = client.post("/v1/applications", json=make_payload(job_id))
        application_id = created.json()["application_id"]
        status = client.get(f"/v1/applications/{application_id}")

    assert status.status_code == 200
    body = status.json()
    assert body["application_id"] == application_id
    assert body["job_id"] == job_id
    assert body["timeline"][0]["event"] == "application.received"


def test_get_unknown_application_returns_404() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(f"/v1/applications/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_batch_submission() -> None:
    app = create_app()
    job_id = str(uuid4())
    payload = {"items": [make_payload(job_id), make_payload(job_id)]}
    with TestClient(app) as client:
        response = client.post("/v1/applications/batch", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 2
    assert len(body["items"]) == 2


def test_batch_over_limit_rejected() -> None:
    app = create_app()
    job_id = str(uuid4())
    payload = {"items": [make_payload(job_id)] * 501}
    with TestClient(app) as client:
        response = client.post("/v1/applications/batch", json=payload)

    assert response.status_code == 422


def test_queue_lists_submitted_candidates() -> None:
    app = create_app()
    job_id = str(uuid4())
    with TestClient(app) as client:
        client.post("/v1/applications", json=make_payload(job_id))
        client.post("/v1/applications", json=make_payload(job_id))
        response = client.get("/v1/queue", params={"job_id": job_id})

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert all(item["status"] == "queued" for item in items)


def test_queue_empty_for_unknown_job() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/queue", params={"job_id": str(uuid4())})

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_audit_chain_has_submission_entries() -> None:
    app = create_app()
    with TestClient(app) as client:
        client.post("/v1/applications", json=make_payload(str(uuid4())))
        client.post("/v1/applications", json=make_payload(str(uuid4())))

    assert app.state.audit.verify() == -1
    actions = [entry.action for entry in app.state.audit.entries]
    assert actions == ["application.received", "application.received"]


# --- manual stage moves ---------------------------------------------------------------


def test_stage_move_moves_and_records_the_timeline() -> None:
    app = create_app()
    with TestClient(app) as client:
        application_id = app_at(client, ApplicationStatus.EVALUATED)
        response = client.post(
            f"/v1/applications/{application_id}/stage",
            json={
                "target": "gated",
                "reason": "pulled out of auto-schedule for a human look",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "gated"
    assert body["timeline"][-1]["event"] == "application.stage.gated"
    actions = [entry.action for entry in app.state.audit.entries]
    assert "application.stage_changed" in actions
    assert app.state.audit.verify() == -1


def test_stage_move_refuses_gate_bypasses() -> None:
    app = create_app()
    with TestClient(app) as client:
        queued = app_at(client, ApplicationStatus.QUEUED)
        gated = app_at(client, ApplicationStatus.GATED)

        worker = client.post(
            f"/v1/applications/{queued}/stage",
            json={"target": "gated", "reason": "skip the queue"},
        )
        rejection = client.post(
            f"/v1/applications/{gated}/stage",
            json={"target": "rejected", "reason": "no thanks"},
        )
        schedule = client.post(
            f"/v1/applications/{gated}/stage",
            json={"target": "scheduled", "reason": "looks good"},
        )

    assert worker.status_code == 409
    assert "worker" in worker.json()["title"]
    assert rejection.status_code == 409
    assert "sign-off" in rejection.json()["title"]
    assert schedule.status_code == 409
    assert "scheduling is gated" in schedule.json()["title"]


def test_stage_move_refuses_a_caller_supplied_actor() -> None:
    """A client cannot nominate its own actor for a stage move.

    This used to omit ``by`` and assert 403, which was the API's way of asking
    who the caller was. The actor is now the authenticated principal, resolved
    before the route runs, so a body actor is refused rather than obeyed. The
    named-human gate still exists, but it is only reachable where an agent actor
    can exist -- the service, covered in tests/services/test_stages.py.
    """
    app = create_app()
    with TestClient(app) as client:
        application_id = app_at(client, ApplicationStatus.EVALUATED)
        claimed = client.post(
            f"/v1/applications/{application_id}/stage",
            json={"target": "gated", "reason": "automating", "by": "agent:hr_bot"},
        )
        accepted = client.post(
            f"/v1/applications/{application_id}/stage",
            json={"target": "gated", "reason": "automating"},
        )

    assert claimed.status_code == 422
    assert any(error["loc"][-1] == "by" for error in claimed.json()["detail"])
    # The move that does not try to name an actor succeeds as the local operator.
    assert accepted.status_code == 200, accepted.text


def test_stage_move_requires_a_reason() -> None:
    app = create_app()
    with TestClient(app) as client:
        application_id = app_at(client, ApplicationStatus.EVALUATED)
        response = client.post(
            f"/v1/applications/{application_id}/stage",
            json={"target": "gated", "reason": ""},
        )

    assert response.status_code == 422


def test_stage_move_unknown_application_404() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            f"/v1/applications/{uuid4()}/stage",
            json={"target": "gated", "reason": "test"},
        )

    assert response.status_code == 404
