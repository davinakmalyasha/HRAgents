"""Integration tests for the rubric registry and its gates."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId
from hr_agents.services.dimensions import ENGINEERING, rubric_digest


def make_client() -> TestClient:
    return TestClient(create_app())


def template_payload(**overrides: object) -> dict:
    payload = ENGINEERING.model_dump(mode="json")
    payload.update(overrides)
    return payload


def engineering_summary(client: TestClient) -> dict:
    body = client.get("/v1/rubrics").json()
    return next(item for item in body["items"] if item["family"] == "engineering")


def test_code_rubrics_are_the_default() -> None:
    with make_client() as client:
        body = client.get("/v1/rubrics").json()
        assert body["total"] == 8
        engineering = engineering_summary(client)
        assert engineering["source"] == "code"
        assert engineering["digest"] == rubric_digest(ENGINEERING)
        assert engineering["revision"] is None
        assert engineering["verified_by"] is None


def test_draft_verify_activate_flips_the_active_rubric() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/rubrics/engineering/versions",
            json=template_payload(breadth_saturation=99),
        )
        assert created.status_code == 201, created.text
        draft = created.json()
        assert draft["revision"] == 1
        assert draft["active"] is False
        assert draft["verified_by"] is None

        duplicate = client.post(
            "/v1/rubrics/engineering/versions",
            json=template_payload(breadth_saturation=99),
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "state_conflict"

        unverified = client.post(f"/v1/rubrics/versions/{draft['id']}/activate")
        assert unverified.status_code == 409

        verified = client.post(
            f"/v1/rubrics/versions/{draft['id']}/verify",
            json={"source_note": "HR policy review"},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["verified_by"] == draft["created_by"]
        assert verified.json()["verified_note"] == "HR policy review"

        activated = client.post(f"/v1/rubrics/versions/{draft['id']}/activate")
        assert activated.status_code == 200
        assert activated.json()["active"] is True

        engineering = engineering_summary(client)
        assert engineering["source"] == "registry"
        assert engineering["revision"] == 1
        assert engineering["digest"] == draft["digest"]
        assert engineering["verified_by"] == draft["created_by"]
        assert engineering["verified_at"] is not None

        versions = client.get("/v1/rubrics/engineering/versions", params={"limit": 1})
        assert versions.status_code == 200
        body = versions.json()
        assert body["total"] == 1
        assert body["items"][0]["template"]["breadth_saturation"] == 99


def test_only_a_human_with_the_verify_permission_can_certify() -> None:
    settings = Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("rec-key"), role=RoleId.RECRUITER, actor_id="rec-1"),
        ],
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/v1/rubrics/engineering/versions",
            json=template_payload(),
            headers={"X-API-Key": "rec-key"},
        )
        assert created.status_code == 201, created.text
        draft = created.json()

        denied = client.post(
            f"/v1/rubrics/versions/{draft['id']}/verify",
            json={"source_note": "a recruiter cannot certify the rubric"},
            headers={"X-API-Key": "rec-key"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "permission_denied"
