"""Credential registry API: the admin gate, the verification gate, and masking-free rows."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId

ADMIN = {"X-API-Key": "admin-key"}
EMPLOYEE = {"X-API-Key": "employee-key"}


def settings() -> Settings:
    return Settings(
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("admin-key"), role=RoleId.HR_ADMIN, actor_id="rina"),
            ApiPrincipalSettings(
                key=SecretStr("employee-key"), role=RoleId.EMPLOYEE, actor_id="sari"
            ),
        ]
    )


def test_only_an_admin_may_reach_the_registry() -> None:
    with TestClient(create_app(settings())) as client:
        assert client.get("/v1/credentials", headers=ADMIN).status_code == 200
        response = client.get("/v1/credentials", headers=EMPLOYEE)
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"


def test_import_verify_and_list() -> None:
    with TestClient(create_app(settings())) as client:
        created = client.post(
            "/v1/credentials",
            json={"name": "AWS certifications", "issuer": "AWS"},
            headers=ADMIN,
        )
        assert created.status_code == 201, created.text
        registry_id = created.json()["id"]
        assert created.json()["usable"] is False

        imported = client.put(
            f"/v1/credentials/{registry_id}/entries",
            json={
                "entries": [
                    {
                        "name": "AWS Solutions Architect",
                        "status": "verified",
                        "credential_id": "AWS-123",
                        "expires_on": "2027-01-01",
                    }
                ]
            },
            headers=ADMIN,
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["entries"][0]["credential_id"] == "AWS-123"
        assert imported.json()["usable"] is False

        certified = client.post(
            f"/v1/credentials/{registry_id}/verify",
            json={"source_note": "issuer page, 2026-10-24"},
            headers=ADMIN,
        )
        assert certified.status_code == 200, certified.text
        assert certified.json()["usable"] is True
        assert certified.json()["verified_by"] == "rina"

        listed = client.get("/v1/credentials", headers=ADMIN).json()
        assert listed["total"] == 1
        assert listed["items"][0]["verified"] is True


def test_an_empty_registry_cannot_be_verified() -> None:
    with TestClient(create_app(settings())) as client:
        created = client.post(
            "/v1/credentials",
            json={"name": "Empty", "issuer": "Nobody"},
            headers=ADMIN,
        ).json()

        refused = client.post(
            f"/v1/credentials/{created['id']}/verify",
            json={"source_note": "nothing to check"},
            headers=ADMIN,
        )
        assert refused.status_code == 422
        assert refused.json()["code"] == "validation_failed"


def test_a_registry_can_be_removed() -> None:
    with TestClient(create_app(settings())) as client:
        created = client.post(
            "/v1/credentials",
            json={"name": "Mistake", "issuer": "Wrong"},
            headers=ADMIN,
        ).json()

        assert client.delete(f"/v1/credentials/{created['id']}", headers=ADMIN).status_code == 204
        assert client.get("/v1/credentials", headers=ADMIN).json()["total"] == 0
        assert client.delete(f"/v1/credentials/{created['id']}", headers=ADMIN).status_code == 404
