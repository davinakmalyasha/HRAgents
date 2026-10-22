"""The provider status surface: what is wired, and whether it answers."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId

CAPABILITIES = {
    "llm",
    "embeddings",
    "email_send",
    "email_receive",
    "whatsapp",
    "calendar",
    "storage",
    "vector_store",
    "queue",
}


def test_every_capability_is_reported() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/v1/providers")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["total"] == len(CAPABILITIES)
        assert {item["capability"] for item in body["items"]} == CAPABILITIES
        for item in body["items"]:
            assert item["provider_id"]
            assert item["status"] in {"ok", "degraded", "misconfigured", "unavailable"}
            assert item["detail"]


def test_a_locked_provider_is_marked_and_its_secret_is_masked(
    monkeypatch: MonkeyPatch,
) -> None:
    """The environment lock is visible; the secret behind it is not."""
    monkeypatch.setenv("HRAGENTS_PROVIDER_LLM", "llm.openai_compatible")
    monkeypatch.setenv(
        "HRAGENTS_PROVIDER_LLM_CONFIG",
        json.dumps({"api_key": "sk-super-secret-value", "model": "gpt-4o-mini"}),
    )
    monkeypatch.setenv("HRAGENTS_PROVIDER_LLM_LOCK", "true")

    with TestClient(create_app()) as client:
        response = client.get("/v1/providers")
        assert response.status_code == 200, response.text
        body = response.json()

    llm = next(item for item in body["items"] if item["capability"] == "llm")
    assert llm["provider_id"] == "llm.openai_compatible"
    assert llm["locked"] is True
    assert llm["source"] == "env"
    assert "sk-super-secret-value" not in response.text, "a secret must never be returned"
    assert "…alue" in llm["config"].get("api_key", ""), "the masked preview keeps the last four"


def test_the_surface_is_admin_only() -> None:
    settings = Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("rec-key"), role=RoleId.RECRUITER, actor_id="rec-1")
        ],
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/providers", headers={"X-API-Key": "rec-key"})

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
