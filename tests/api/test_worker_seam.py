"""The API -> queue -> worker seam, end to end.

This is the test whose absence let the product ship inert: the API accepted an
application, returned 202, and nothing ever claimed the message. Here a real
submission travels through the real dispatcher and the real worker, and an
evaluation with a policy decision comes out the other side.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agentset import build_agent_set
from hr_agents.main import create_app
from hr_agents.providers.queue import MemoryQueueBackend
from hr_agents.queue import resolve_queue_backend
from hr_agents.services.dispatch import EvaluationDispatcher
from hr_agents.services.evaluation_job import EVALUATION_TOPIC, EvaluationJobHandler
from hr_agents.services.pipeline import ApplicationPipeline, InMemoryStorage, PipelineConfig
from hr_agents.services.worker import Worker, WorkerConfig

RESUME = """
Budi Santoso
budi@example.com
Senior backend engineer, eight years.
Experience:
- PT Contoh, 2019 to now, backend engineer, Python, PostgreSQL, Redis
- PT Lain, 2017 to 2019, software engineer, Java, MySQL
Skills: Python, PostgreSQL, Redis, Docker, Kubernetes
"""


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as started:
        yield started


@pytest.fixture
def job(client: TestClient) -> dict:
    response = client.post(
        "/v1/jobs",
        json={
            "title": "Backend Engineer",
            "must_have_skills": ["Python", "PostgreSQL"],
            "status": "open",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def app_state(client: TestClient) -> Any:
    return cast(FastAPI, client.app).state


def upload_resume(client: TestClient) -> str:
    response = client.post(
        "/v1/documents",
        files={"file": ("cv.txt", RESUME.encode("utf-8"), "text/plain")},
        data={"kind": "cv"},
    )
    assert response.status_code == 201, response.text
    return response.json()["document_id"]


def run_worker_once(app: Any, queue: MemoryQueueBackend) -> None:
    """Claim and process one batch, exactly as ``scripts/run_worker.py`` does."""
    agent_set = asyncio.run(build_agent_set(audit=app.state.audit, runtime=AgentRuntime.offline()))
    pipeline = ApplicationPipeline(
        deconstructor=agent_set.resume,
        storage=InMemoryStorage(agent_set.tools),
        audit=app.state.audit,
        config=PipelineConfig(scoring_runs=2),
    )
    handler = EvaluationJobHandler(
        pipeline=pipeline,
        applications=app.state.store,
        evaluations=app.state.recruiting.evaluations,
        jobs=app.state.recruiting.jobs,
        audit=app.state.audit,
    )
    worker = Worker(
        queue,
        handler,
        config=WorkerConfig(topic=EVALUATION_TOPIC, max_attempts=2, lease_seconds=60.0),
    )
    asyncio.run(worker.run_once())


def test_a_submitted_application_is_actually_evaluated(client: TestClient, job: dict) -> None:
    """The regression test for the product shipping with no worker at all."""
    document_id = upload_resume(client)
    queue: MemoryQueueBackend = app_state(client).queue

    accepted = client.post(
        "/v1/applications",
        json={
            "job_id": job["id"],
            "source_channel": "api",
            "consent": {"granted": True},
            "candidate": {"full_name": "Budi Santoso", "emails": ["budi@example.com"]},
            "documents": [{"document_id": document_id, "kind": "cv"}],
        },
    )
    assert accepted.status_code == 202, accepted.text
    application_id = accepted.json()["application_id"]

    # The submission is accepted and the work is really on the queue.
    assert client.get(f"/v1/applications/{application_id}").json()["status"] == "queued"
    stats = asyncio.run(queue.stats(EVALUATION_TOPIC))
    assert stats.pending == 1

    run_worker_once(client.app, queue)

    # The queue drained, the status advanced, and an evaluation was registered.
    assert asyncio.run(queue.stats(EVALUATION_TOPIC)).pending == 0
    status = client.get(f"/v1/applications/{application_id}").json()
    assert status["status"] != "queued"
    assert status["s_tech"] is not None

    evaluation = client.get(f"/v1/applications/{application_id}/evaluation")
    assert evaluation.status_code == 200, evaluation.text
    body = evaluation.json()
    assert body["recommendation"] in {"auto_schedule", "human_review", "reject", "reject_signoff"}
    assert body["policy"]["decision"]
    # Every dimension is present and weighted — the score is inspectable.
    assert set(body["mean_vector"]) == {
        "technical_depth",
        "stack_alignment",
        "systems_literacy",
        "verifiable_certifications",
    }
    assert body["sigma"] >= 0.0


def test_an_idempotent_replay_does_not_queue_a_second_evaluation(
    client: TestClient, job: dict
) -> None:
    document_id = upload_resume(client)
    queue: MemoryQueueBackend = app_state(client).queue
    payload = {
        "job_id": job["id"],
        "source_channel": "api",
        "consent": {"granted": True},
        "candidate": {"full_name": "Sari Wijaya", "emails": ["sari@example.com"]},
        "documents": [{"document_id": document_id, "kind": "cv"}],
    }

    first = client.post("/v1/applications", json=payload, headers={"Idempotency-Key": "k-1"})
    second = client.post("/v1/applications", json=payload, headers={"Idempotency-Key": "k-1"})

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["application_id"] == second.json()["application_id"]
    assert asyncio.run(queue.stats(EVALUATION_TOPIC)).pending == 1


def test_a_submission_with_no_document_is_recorded_but_not_queued(
    client: TestClient, job: dict
) -> None:
    """The application still lands; the audit trail says why nothing was queued."""
    queue: MemoryQueueBackend = app_state(client).queue

    accepted = client.post(
        "/v1/applications",
        json={
            "job_id": job["id"],
            "source_channel": "api",
            "consent": {"granted": True},
            "candidate": {"full_name": "No CV"},
        },
    )

    assert accepted.status_code == 202
    assert asyncio.run(queue.stats(EVALUATION_TOPIC)).pending == 0

    events = app_state(client).audit.entries
    received = [entry for entry in events if entry.action == "application.received"]
    assert len(received) == 1
    assert received[0].payload["queued_message_id"] is None
    assert "no readable document" in received[0].payload["dispatch_skipped_reason"]


def test_a_broken_message_is_dead_lettered_not_silently_dropped(
    client: TestClient, job: dict
) -> None:
    queue: MemoryQueueBackend = app_state(client).queue
    asyncio.run(
        queue.publish(EVALUATION_TOPIC, {"application_id": str(uuid4()), "job_id": str(uuid4())})
    )

    # max_attempts=2 means one requeue before dead-lettering, so the worker must
    # actually poll twice for the message to reach the dead-letter queue.
    run_worker_once(client.app, queue)
    assert asyncio.run(queue.stats(EVALUATION_TOPIC)).pending == 1

    run_worker_once(client.app, queue)
    stats = asyncio.run(queue.stats(EVALUATION_TOPIC))
    assert stats.pending == 0
    assert stats.dead == 1
    dead = asyncio.run(queue.dead_letters(EVALUATION_TOPIC))
    assert len(dead) == 1
    # The reason survives the dead-letter, so an operator can see what broke.
    assert dead[0].failed_reason
    assert "resume_text" in dead[0].failed_reason or "unknown application" in dead[0].failed_reason
    assert dead[0].failed_at is not None


def test_the_queue_resolver_honours_the_test_override() -> None:
    """The hermetic environment names the memory queue explicitly."""
    backend = asyncio.run(resolve_queue_backend(prefer=None))

    assert isinstance(backend, MemoryQueueBackend)


def test_the_dispatcher_is_bound_to_the_live_queue(client: TestClient) -> None:
    dispatcher = app_state(client).dispatcher

    assert isinstance(dispatcher, EvaluationDispatcher)
    assert isinstance(app_state(client).queue, MemoryQueueBackend)
