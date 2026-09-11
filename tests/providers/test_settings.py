import pytest

from hr_agents.providers import Capability, ResolvedProvider
from hr_agents.providers.registry import ProviderNotFoundError, default_registry
from hr_agents.providers.settings import (
    ProviderSettingsError,
    active_provider,
    resolve_provider_settings_with_registry,
)


def resolve(env: dict[str, str]) -> dict[Capability, ResolvedProvider]:
    return resolve_provider_settings_with_registry(env, default_registry())


def test_no_env_yields_empty_selection() -> None:
    assert resolve({}) == {}


def test_queue_provider_selected_from_env() -> None:
    resolved = resolve(
        {
            "HRAGENTS_PROVIDER_QUEUE": "queue.memory",
            "HRAGENTS_PROVIDER_QUEUE_CONFIG": "{}",
        }
    )
    selection = resolved[Capability.QUEUE]
    assert selection.provider_id == "queue.memory"
    assert selection.source == "env"
    assert selection.locked is False


def test_lock_flag_parsed() -> None:
    resolved = resolve(
        {
            "HRAGENTS_PROVIDER_QUEUE": "queue.memory",
            "HRAGENTS_PROVIDER_QUEUE_LOCK": "true",
            "HRAGENTS_PROVIDER_QUEUE_CONFIG": "{}",
        }
    )
    assert resolved[Capability.QUEUE].locked is True


def test_llm_provider_with_config() -> None:
    config_json = '{"api_key": "sk-test-1234", "model": "claude-sonnet-4-5"}'
    resolved = resolve(
        {
            "HRAGENTS_PROVIDER_LLM": "llm.anthropic",
            "HRAGENTS_PROVIDER_LLM_CONFIG": config_json,
        }
    )
    selection = resolved[Capability.LLM]
    assert selection.provider_id == "llm.anthropic"
    assert selection.config["model"] == "claude-sonnet-4-5"


def test_invalid_json_config_rejected() -> None:
    with pytest.raises(ProviderSettingsError, match="not valid JSON"):
        resolve(
            {"HRAGENTS_PROVIDER_QUEUE": "queue.memory", "HRAGENTS_PROVIDER_QUEUE_CONFIG": "{oops"}
        )


def test_non_object_config_rejected() -> None:
    with pytest.raises(ProviderSettingsError, match="must be a JSON object"):
        resolve(
            {"HRAGENTS_PROVIDER_QUEUE": "queue.memory", "HRAGENTS_PROVIDER_QUEUE_CONFIG": "[1,2]"}
        )


def test_unknown_provider_id_rejected() -> None:
    with pytest.raises(ProviderNotFoundError, match="unknown provider"):
        resolve({"HRAGENTS_PROVIDER_QUEUE": "queue.does_not_exist"})


def test_wrong_capability_provider_rejected() -> None:
    with pytest.raises(ProviderSettingsError, match="but was configured for"):
        resolve({"HRAGENTS_PROVIDER_QUEUE": "llm.test"})


def test_invalid_provider_config_rejected() -> None:
    with pytest.raises(ProviderSettingsError, match="invalid configuration"):
        resolve(
            {
                "HRAGENTS_PROVIDER_QUEUE": "queue.redis",
                "HRAGENTS_PROVIDER_QUEUE_CONFIG": '{"redis_url": 12345}',
            }
        )


def test_config_without_provider_id_rejected() -> None:
    with pytest.raises(ProviderSettingsError, match="is required"):
        resolve({"HRAGENTS_PROVIDER_QUEUE_CONFIG": "{}"})


def test_lock_without_provider_id_rejected() -> None:
    with pytest.raises(ProviderSettingsError, match="is required"):
        resolve({"HRAGENTS_PROVIDER_QUEUE_LOCK": "true"})


def test_redis_config_overrides_defaults() -> None:
    config_json = '{"redis_url": "redis://custom:6380/2", "key_prefix": "x"}'
    resolved = resolve(
        {
            "HRAGENTS_PROVIDER_QUEUE": "queue.redis",
            "HRAGENTS_PROVIDER_QUEUE_CONFIG": config_json,
        }
    )
    assert resolved[Capability.QUEUE].config["redis_url"] == "redis://custom:6380/2"


async def test_active_provider_builds_memory_backend() -> None:
    resolved = resolve(
        {
            "HRAGENTS_PROVIDER_QUEUE": "queue.memory",
            "HRAGENTS_PROVIDER_QUEUE_CONFIG": "{}",
        }
    )
    result = active_provider(Capability.QUEUE, registry=default_registry(), resolved=resolved)

    assert result is not None
    built, _config = result
    message_id = await built.publish("t", {"x": 1})  # type: ignore[attr-defined]
    assert message_id


async def test_active_provider_none_when_capability_unavailable() -> None:
    # An empty registry has no provider for anything - must degrade to None.
    from hr_agents.providers import ProviderRegistry

    result = active_provider(Capability.EMBEDDINGS, registry=ProviderRegistry(), resolved={})
    assert result is None


async def test_whatsapp_falls_back_to_manual_mode() -> None:
    # With nothing configured, WhatsApp resolves to the always-available manual
    # transport instead of failing.
    result = active_provider(Capability.WHATSAPP, registry=default_registry(), resolved={})
    assert result is not None
    built, _config = result
    assert built["transport"] == "manual_links"  # type: ignore[index]


def test_active_provider_none_on_invalid_config() -> None:
    registry = default_registry()
    broken = {
        Capability.QUEUE: ResolvedProvider(
            capability=Capability.QUEUE,
            provider_id="queue.redis",
            config={"redis_url": 999},  # invalid type
            source="env",
        )
    }
    assert active_provider(Capability.QUEUE, registry=registry, resolved=broken) is None
