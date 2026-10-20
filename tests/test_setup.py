"""The first-run environment renderer: one admin principal, no secrets committed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dotenv import dotenv_values

from hr_agents.setup import (
    generate_api_key,
    render_env,
    setup_actor,
    validate_timezone,
    write_env,
)


def test_rendered_env_round_trips_the_admin_principal(tmp_path: Path) -> None:
    key = "test-key-123"
    content = render_env(
        operator="Rina Wijaya",
        api_key=key,
        app_name="Nusantara HR",
        timezone="Asia/Jakarta",
        store_backend="postgres",
        llm_model="test",
    )
    path = tmp_path / ".env"
    write_env(path, content)

    values = dotenv_values(path)
    assert values["HRAGENTS_ACTOR_NAME"] == "Rina Wijaya"
    assert values["HRAGENTS_APP_NAME"] == "Nusantara HR"
    assert values["HRAGENTS_TIMEZONE"] == "Asia/Jakarta"
    assert values["HRAGENTS_STORE_BACKEND"] == "postgres"
    principal = json.loads(values["HRAGENTS_API_PRINCIPALS"] or "[]")[0]
    assert principal == {"key": key, "role": "hr_admin", "actor_id": "rina-wijaya"}


def test_write_env_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_env(path, "new")
    assert path.read_text(encoding="utf-8") == "old"

    write_env(path, "new", force=True)
    assert path.read_text(encoding="utf-8") == "new"


def test_unknown_timezone_and_invalid_values_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown timezone"):
        validate_timezone("Mars/Olympus")
    with pytest.raises(ValueError, match="operator"):
        render_env(operator="   ", api_key="key")
    with pytest.raises(ValueError, match="store_backend"):
        render_env(operator="Rina", api_key="key", store_backend="sqlite")


def test_generated_keys_are_distinct_and_the_actor_is_stable() -> None:
    first = generate_api_key()
    second = generate_api_key()
    assert len(first) >= 32
    assert first != second

    actor = setup_actor("Rina Wijaya")
    assert actor.actor_id == "rina-wijaya"
    assert actor.role == "hr_admin"
