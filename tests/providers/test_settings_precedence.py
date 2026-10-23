"""Stored provider selections: they win, unless the environment locks the capability."""

from __future__ import annotations

from hr_agents.providers.base import Capability
from hr_agents.providers.settings import (
    ResolvedProvider,
    clear_settings_overrides,
    install_settings_overrides,
    merge_settings_overrides,
    resolve_provider_settings,
)


def selection(
    capability: Capability,
    provider_id: str,
    *,
    locked: bool = False,
    source: str = "env",
) -> ResolvedProvider:
    return ResolvedProvider(
        capability=capability,
        provider_id=provider_id,
        config={},
        locked=locked,
        source=source,
    )


def test_a_stored_selection_overrides_an_unlocked_environment_default() -> None:
    env = {Capability.LLM: selection(Capability.LLM, "llm.test")}
    stored = {Capability.LLM: selection(Capability.LLM, "llm.ollama", source="settings")}

    merged = merge_settings_overrides(env, stored)

    assert merged[Capability.LLM].provider_id == "llm.ollama"
    assert merged[Capability.LLM].source == "settings"


def test_an_environment_lock_is_authoritative() -> None:
    env = {Capability.QUEUE: selection(Capability.QUEUE, "queue.redis", locked=True)}
    stored = {Capability.QUEUE: selection(Capability.QUEUE, "queue.memory", source="settings")}

    merged = merge_settings_overrides(env, stored)

    assert merged[Capability.QUEUE].provider_id == "queue.redis"
    assert merged[Capability.QUEUE].locked is True


def test_capabilities_merge_rather_than_replace_each_other() -> None:
    env = {Capability.LLM: selection(Capability.LLM, "llm.test")}
    stored = {Capability.STORAGE: selection(Capability.STORAGE, "storage.s3", source="settings")}

    merged = merge_settings_overrides(env, stored)

    assert set(merged) == {Capability.LLM, Capability.STORAGE}


def test_installed_overrides_reach_the_default_resolution_and_can_be_cleared() -> None:
    """The process-wide path the model runtime and the providers page both read."""
    install_settings_overrides(
        {Capability.STORAGE: selection(Capability.STORAGE, "storage.s3", source="settings")}
    )
    try:
        resolved = resolve_provider_settings()
        assert resolved[Capability.STORAGE].provider_id == "storage.s3"
        assert resolved[Capability.STORAGE].source == "settings"
    finally:
        clear_settings_overrides()

    assert Capability.STORAGE not in resolve_provider_settings()
