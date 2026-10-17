"""Pipeline listing: ranked applications, job filter, and read permission."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId
from hr_agents.services.ingestion import ApplicationStatus


def _settings() -> Settings:
    return Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("fin-key"), role=RoleId.FINANCE, actor_id="fin-1"),
        ],
    )


def _settings_with_read() -> Settings:
    return Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("rec-key"), role=RoleId.RECRUITER, actor_id="rec-1"),
        ],
    )


def _submit(client: TestClient, job_id: UUID) -> str:
    response = client.post(
        "/v1/applications",
        json={"job_id": str(job_id), "consent": {"granted": True}},
    )
    assert response.status_code == 202
    return response.json()["application_id"]


def test_pipeline_lists_and_filters_by_job() -> None:
    app = create_app()
    job_a, job_b = uuid4(), uuid4()

    with TestClient(app) as client:
        first = _submit(client, job_a)
        second = _submit(client, job_a)
        third = _submit(client, job_b)

        everything = client.get("/v1/applications")
        assert everything.status_code == 200
        everything_body = everything.json()
        assert everything_body["total"] == 3
        assert {item["application_id"] for item in everything_body["items"]} == {
            first,
            second,
            third,
        }

        scoped = client.get("/v1/applications", params={"job_id": str(job_a)})
        assert {item["application_id"] for item in scoped.json()["items"]} == {first, second}

        empty = client.get("/v1/applications", params={"job_id": str(uuid4())})
        assert empty.json()["items"] == []
        assert empty.json()["total"] == 0


def test_pipeline_ranks_by_priority() -> None:
    app = create_app()
    job = uuid4()

    with TestClient(app) as client:
        first = _submit(client, job)
        second = _submit(client, job)

        record = app.state.store.get(UUID(second))
        assert record is not None
        record.priority_score = 0.99
        app.state.store._persist(record)

        ranked = client.get("/v1/applications", params={"job_id": str(job)}).json()
        assert [item["application_id"] for item in ranked["items"]] == [second, first]


def test_pipeline_summary_carries_stage_and_scores() -> None:
    app = create_app()

    with TestClient(app) as client:
        application_id = _submit(client, uuid4())
        summary = client.get("/v1/applications").json()["items"][0]

        assert summary["application_id"] == application_id
        assert summary["status"] == "queued"
        assert summary["s_tech"] is None
        assert summary["hours_waiting"] >= 0.0


def test_pipeline_requires_recruiting_read() -> None:
    app = create_app(_settings())

    with TestClient(app) as client:
        denied = client.get("/v1/applications", headers={"X-API-Key": "fin-key"})
        assert denied.status_code == 403


def test_recruiter_can_list_and_submit() -> None:
    app = create_app(_settings_with_read())

    with TestClient(app) as client:
        listed = client.get("/v1/applications", headers={"X-API-Key": "rec-key"})
        assert listed.status_code == 200

        submit = client.post(
            "/v1/applications",
            json={"job_id": str(uuid4()), "consent": {"granted": True}},
            headers={"X-API-Key": "rec-key"},
        )
        assert submit.status_code == 202


def test_pipeline_filters_by_status() -> None:
    app = create_app()

    with TestClient(app) as client:
        first = _submit(client, uuid4())
        second = _submit(client, uuid4())

        app.state.store.set_status(UUID(first), ApplicationStatus.GATED, event="evaluation.gated")

        gated = client.get("/v1/applications", params={"status": "gated"}).json()
        assert [item["application_id"] for item in gated["items"]] == [first]

        queued = client.get("/v1/applications", params={"status": "queued"}).json()
        assert [item["application_id"] for item in queued["items"]] == [second]


def test_pipeline_pagination_is_bounded_and_slices() -> None:
    app = create_app()

    with TestClient(app) as client:
        job = str(uuid4())
        for _ in range(3):
            _submit(client, UUID(job))

        full = client.get("/v1/applications", params={"job_id": job}).json()
        all_ids = [item["application_id"] for item in full["items"]]
        assert full["total"] == 3

        page = client.get(
            "/v1/applications", params={"job_id": job, "limit": 2, "offset": 1}
        ).json()
        assert page["total"] == 3
        assert page["limit"] == 2
        assert page["offset"] == 1
        assert [item["application_id"] for item in page["items"]] == all_ids[1:3]

        assert client.get("/v1/applications", params={"limit": 0}).status_code == 422
        assert client.get("/v1/applications", params={"limit": 201}).status_code == 422
        assert client.get("/v1/applications", params={"offset": -1}).status_code == 422
