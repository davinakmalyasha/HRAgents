from uuid import uuid4

from fastapi.testclient import TestClient

from hr_agents.main import create_app


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
