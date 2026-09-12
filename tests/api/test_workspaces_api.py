"""Workspace metadata API: navigation packs, auth, and web locale parity."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId
from hr_agents.workspaces import WorkspaceId, default_registry

REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings() -> Settings:
    return Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("emp-key"), role=RoleId.EMPLOYEE, actor_id="emp-1"),
        ],
    )


def test_lists_every_workspace_in_deterministic_order() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/v1/workspaces")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [
        workspace.value for workspace in WorkspaceId
    ]


def test_workspace_view_mirrors_the_pack_copy() -> None:
    with TestClient(create_app()) as client:
        body = client.get("/v1/workspaces").json()

    for item in body:
        pack = default_registry().get(WorkspaceId(item["id"]))
        assert item["name_en"] == pack.name_en
        assert item["name_id"] == pack.name_id
        assert item["summary_en"] == pack.summary_en
        assert item["summary_id"] == pack.summary_id


def test_requires_auth_when_keys_are_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hr_agents.api.deps.get_settings", _settings)
    app = create_app()

    with TestClient(app) as client:
        anonymous = client.get("/v1/workspaces")
        assert anonymous.status_code == 401

        employee = client.get("/v1/workspaces", headers={"X-API-Key": "emp-key"})
        assert employee.status_code == 200


def test_web_locale_workspace_names_match_the_packs() -> None:
    for language, field in (("en", "name_en"), ("id", "name_id")):
        locale_path = REPO_ROOT / "web" / "src" / "i18n" / "locales" / f"{language}.json"
        locale = json.loads(locale_path.read_text(encoding="utf-8"))

        for pack in default_registry().list_all():
            assert locale["workspaces"][pack.id.value]["name"] == getattr(pack, field)
