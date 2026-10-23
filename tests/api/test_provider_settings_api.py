"""Provider configuration through the API: sealed writes, locks, masking, tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.providers.settings import clear_settings_overrides
from hr_agents.rbac import RoleId

ADMIN = {"X-API-Key": "admin-key"}
MANAGER = {"X-API-Key": "manager-key"}


@pytest.fixture(autouse=True)
def _no_override_leaks() -> Iterator[None]:
    yield
    clear_settings_overrides()


def configured_settings() -> Settings:
    return Settings(
        settings_encryption_key=Fernet.generate_key().decode(),
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("admin-key"), role=RoleId.HR_ADMIN, actor_id="rina"),
            ApiPrincipalSettings(
                key=SecretStr("manager-key"), role=RoleId.MANAGER, actor_id="sari"
            ),
        ],
    )


def llm_row(client: TestClient, headers: dict[str, str] = ADMIN) -> dict:
    body = client.get("/v1/providers", headers=headers).json()
    return next(item for item in body["items"] if item["capability"] == "llm")


def test_without_a_key_the_surface_is_read_only() -> None:
    with TestClient(create_app(Settings(api_keys=["admin-key"]))) as client:
        listed = client.get("/v1/providers", headers=ADMIN)
        assert listed.status_code == 200
        assert all(item["editable"] is False for item in listed.json()["items"])

        refused = client.put(
            "/v1/providers/llm",
            json={"provider_id": "llm.test", "config": {}},
            headers=ADMIN,
        )
        assert refused.status_code == 409
        assert "ENCRYPTION_KEY" in refused.json()["detail"]


def test_only_an_admin_may_configure_a_provider() -> None:
    with TestClient(create_app(configured_settings())) as client:
        response = client.put(
            "/v1/providers/llm",
            json={"provider_id": "llm.test", "config": {}},
            headers=MANAGER,
        )
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"


def test_configure_list_and_clear() -> None:
    with TestClient(create_app(configured_settings())) as client:
        saved = client.put(
            "/v1/providers/llm",
            json={"provider_id": "llm.test", "config": {}},
            headers=ADMIN,
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["status"]["provider_id"] == "llm.test"
        assert body["status"]["source"] == "settings"
        assert body["restart_required"] is True

        assert llm_row(client)["source"] == "settings"

        options = client.get("/v1/providers/llm/options", headers=ADMIN).json()
        assert options["selected_provider_id"] == "llm.test"
        assert options["editable"] is True
        assert "llm.test" in {item["provider_id"] for item in options["providers"]}

        assert client.delete("/v1/providers/llm", headers=ADMIN).status_code == 204
        assert llm_row(client)["source"] != "settings"
        assert client.delete("/v1/providers/llm", headers=ADMIN).status_code == 404


def test_a_secret_is_masked_and_a_blank_one_keeps_the_stored_value() -> None:
    app = create_app(configured_settings())
    with TestClient(app) as client:
        first = client.put(
            "/v1/providers/llm",
            json={
                "provider_id": "llm.anthropic",
                "config": {"api_key": "sk-super-secret", "model": "claude-sonnet-4-5"},
            },
            headers=ADMIN,
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"]["config"]["api_key"] == "…cret"
        assert "sk-super-secret" not in first.text

        second = client.put(
            "/v1/providers/llm",
            json={
                "provider_id": "llm.anthropic",
                "config": {"api_key": "", "model": "claude-opus-4-1"},
            },
            headers=ADMIN,
        )
        assert second.status_code == 200, second.text
        assert second.json()["status"]["config"]["api_key"] == "…cret"

        stored = app.state.provider_settings.list_all()[0]
        assert stored.config["api_key"] == "sk-super-secret"
        assert stored.config["model"] == "claude-opus-4-1"


def test_the_test_button_probes_without_saving() -> None:
    app = create_app(configured_settings())
    with TestClient(app) as client:
        unconfigured = client.post(
            "/v1/providers/llm/test",
            json={"provider_id": "llm.anthropic", "config": {}},
            headers=ADMIN,
        )
        assert unconfigured.status_code == 200
        assert unconfigured.json()["status"] == "misconfigured"

        invalid = client.post(
            "/v1/providers/llm/test",
            json={"provider_id": "llm.anthropic", "config": {"model": {"nested": True}}},
            headers=ADMIN,
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "validation_failed"

        healthy = client.post(
            "/v1/providers/llm/test",
            json={
                "provider_id": "llm.anthropic",
                "config": {"api_key": "sk-test", "model": "claude-sonnet-4-5"},
            },
            headers=ADMIN,
        )
        assert healthy.status_code == 200, healthy.text
        assert healthy.json()["status"] == "ok"
        assert app.state.provider_settings.list_all() == []


def test_an_env_locked_capability_cannot_be_edited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HRAGENTS_PROVIDER_LLM", "llm.test")
    monkeypatch.setenv("HRAGENTS_PROVIDER_LLM_LOCK", "true")
    with TestClient(create_app(configured_settings())) as client:
        row = llm_row(client)
        assert row["locked"] is True
        assert row["editable"] is False

        refused = client.put(
            "/v1/providers/llm",
            json={"provider_id": "llm.test", "config": {}},
            headers=ADMIN,
        )
        assert refused.status_code == 409
        assert "locked by the environment" in refused.json()["detail"]

        options = client.get("/v1/providers/llm/options", headers=ADMIN).json()
        assert options["locked"] is True
        assert options["editable"] is False
