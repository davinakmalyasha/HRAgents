from pydantic import SecretStr

from hr_agents.providers import ProviderHealthStatus, ProviderSpec, mask_secrets
from hr_agents.providers.llm import (
    COMMAND_CODE_BASE_URL,
    LLM_SPECS,
    AnthropicLLMConfig,
    CommandCodeLLMConfig,
    ModelRef,
    OllamaLLMConfig,
    OpenAICompatibleLLMConfig,
    TestLLMConfig,
)


def spec(provider_id: str) -> ProviderSpec:
    return next(item for item in LLM_SPECS if item.id == provider_id)


def test_all_llm_specs_have_health_checks() -> None:
    for item in LLM_SPECS:
        assert item.health_check is not None, item.id
        assert item.capability.value == "llm"


def test_test_provider_builds_offline_model() -> None:
    provider = spec("llm.test")
    config = provider.make_config({})
    ref = provider.apply(config)

    assert isinstance(ref, ModelRef)
    assert ref.model_string == "test"
    assert ref.api_key is None


def test_test_provider_health_always_ok() -> None:
    import asyncio

    provider = spec("llm.test")
    health = asyncio.run(provider.check_health(provider.make_config({})))
    assert health.status is ProviderHealthStatus.OK


def test_ollama_provider_builds_openai_compatible_ref() -> None:
    provider = spec("llm.ollama")
    config = provider.make_config({"model": "qwen2.5-coder", "base_url": "http://box:11434/v1"})
    ref = provider.apply(config)

    assert isinstance(config, OllamaLLMConfig)
    assert ref.model_string == "openai:qwen2.5-coder"
    assert ref.base_url == "http://box:11434/v1"


def test_openai_compatible_requires_key_or_base_url_for_health() -> None:
    import asyncio

    provider = spec("llm.openai_compatible")
    bare = provider.make_config({"model": "gpt-4o-mini"})
    health = asyncio.run(provider.check_health(bare))
    assert health.status is ProviderHealthStatus.MISCONFIGURED

    configured = provider.make_config(
        {"model": "gpt-4o-mini", "api_key": "sk-abc", "base_url": "https://api.openai.com/v1"}
    )
    health = asyncio.run(provider.check_health(configured))
    assert health.status is ProviderHealthStatus.OK


def test_openai_compatible_builds_with_secret() -> None:
    provider = spec("llm.openai_compatible")
    config = provider.make_config(
        {
            "model": "llama-3.3-70b",
            "api_key": "sk-or-1234",
            "base_url": "https://openrouter.ai/api/v1",
        }
    )
    ref = provider.apply(config)

    assert isinstance(config, OpenAICompatibleLLMConfig)
    assert ref.model_string == "openai:llama-3.3-70b"
    assert isinstance(ref.api_key, SecretStr)
    assert ref.api_key.get_secret_value() == "sk-or-1234"


def test_anthropic_health_requires_key() -> None:
    import asyncio

    provider = spec("llm.anthropic")
    health = asyncio.run(provider.check_health(provider.make_config({})))
    assert health.status is ProviderHealthStatus.MISCONFIGURED

    config = provider.make_config({"api_key": "sk-ant-1234"})
    health = asyncio.run(provider.check_health(config))
    assert health.status is ProviderHealthStatus.OK


def test_anthropic_builds_model_ref() -> None:
    provider = spec("llm.anthropic")
    config = provider.make_config({"api_key": "sk-ant-1234", "model": "claude-sonnet-4-5"})
    ref = provider.apply(config)

    assert isinstance(config, AnthropicLLMConfig)
    assert ref.model_string == "anthropic:claude-sonnet-4-5"


def test_secret_fields_declared() -> None:
    assert "api_key" in spec("llm.anthropic").secret_fields
    assert "api_key" in spec("llm.openai_compatible").secret_fields
    assert "api_key" in spec("llm.commandcode").secret_fields
    assert spec("llm.test").secret_fields == []


# --- Command Code provider -------------------------------------------------


def test_commandcode_is_registered() -> None:
    provider = spec("llm.commandcode")
    assert provider.display_name.startswith("Command Code")
    assert provider.docs_url


def test_commandcode_defaults_to_mimo() -> None:
    provider = spec("llm.commandcode")
    config = provider.make_config({"api_key": "cmd-key"})
    assert isinstance(config, CommandCodeLLMConfig)
    assert config.model == "xiaomi/mimo-v2.5"
    assert config.base_url == COMMAND_CODE_BASE_URL


def test_commandcode_builds_zdr_headers_by_default() -> None:
    provider = spec("llm.commandcode")
    config = provider.make_config({"api_key": "cmd-key", "model": "xiaomi/mimo-v2.5-pro"})
    ref = provider.apply(config)

    assert ref.provider_id == "llm.commandcode"
    assert ref.model_string == "openai:xiaomi/mimo-v2.5-pro"
    assert ref.base_url == COMMAND_CODE_BASE_URL
    assert ref.extra_headers == {"x-cmd-zdr": "1"}


def test_commandcode_zdr_can_be_disabled() -> None:
    provider = spec("llm.commandcode")
    config = provider.make_config({"api_key": "cmd-key", "zdr": False})
    ref = provider.apply(config)
    assert ref.extra_headers == {}


def test_commandcode_health_requires_key() -> None:
    import asyncio

    provider = spec("llm.commandcode")
    health = asyncio.run(provider.check_health(provider.make_config({})))
    assert health.status is ProviderHealthStatus.MISCONFIGURED

    config = provider.make_config({"api_key": "cmd-key"})
    health = asyncio.run(provider.check_health(config))
    assert health.status is ProviderHealthStatus.OK
    assert "zero data retention" in health.detail


def test_commandcode_api_key_is_masked() -> None:
    provider = spec("llm.commandcode")
    config = provider.make_config({"api_key": "cmd-secret-abcdef"})
    masked = mask_secrets(config)
    assert masked["api_key"] == "…cdef"


def test_model_ref_masks_api_key() -> None:
    ref = ModelRef(
        provider_id="llm.anthropic",
        model_string="anthropic:claude-sonnet-4-5",
        api_key=SecretStr("sk-ant-secret-abcd"),
    )
    masked = mask_secrets(ref)
    assert masked["api_key"] == "…abcd"
    assert masked["model_string"] == "anthropic:claude-sonnet-4-5"


def test_config_defaults_are_sane() -> None:
    assert TestLLMConfig() is not None
    assert OllamaLLMConfig().base_url.startswith("http://localhost")
    assert OpenAICompatibleLLMConfig(model="x").model == "x"
    assert AnthropicLLMConfig().model
