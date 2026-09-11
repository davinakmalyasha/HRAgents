"""LLM capability: provider-agnostic model references.

Providers produce a :class:`ModelRef` — the agent runtime (Phase 4.4) is the
only place that converts it into a PydanticAI model object. Keeping vendors out
of this module means providers stay unit-testable without any SDK.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, SecretStr

from hr_agents.providers.base import (
    Capability,
    ProviderConfig,
    ProviderHealth,
    ProviderSpec,
)


class ModelRef(ProviderConfig):
    """Resolved model target consumed by the agent runtime."""

    provider_id: str
    model_string: str = Field(
        description="PydanticAI model string, e.g. 'test', 'anthropic:claude-sonnet-4-5'"
    )
    base_url: str | None = None
    api_key: SecretStr | None = None
    extra_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional request headers (e.g. zero-data-retention flags).",
    )


class TestLLMConfig(ProviderConfig):
    """Offline model used in development, tests, and CI. No network, no keys."""

    __test__ = False


class OllamaLLMConfig(ProviderConfig):
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3.1"


class OpenAICompatibleLLMConfig(ProviderConfig):
    """Any OpenAI-compatible endpoint: OpenAI, OpenRouter, Groq, vLLM, gateways."""

    api_key: SecretStr | None = None
    model: str = Field(min_length=1)
    base_url: str | None = None


class AnthropicLLMConfig(ProviderConfig):
    api_key: SecretStr | None = None
    model: str = "claude-sonnet-4-5"


COMMAND_CODE_BASE_URL = "https://api.commandcode.ai/provider/v1"


class CommandCodeLLMConfig(ProviderConfig):
    """Command Code Provider API — every top model on one OpenAI-compatible endpoint.

    Zero data retention is on by default (``x-cmd-zdr: 1``): requests route only
    through ZDR-capable upstreams or fail — the right default for candidate data
    under UU PDP.
    """

    api_key: SecretStr = SecretStr("")
    model: str = "xiaomi/mimo-v2.5"
    base_url: str = COMMAND_CODE_BASE_URL
    zdr: bool = True


def _build_test(config: ProviderConfig) -> ModelRef:
    return ModelRef(provider_id="llm.test", model_string="test")


def _build_ollama(config: ProviderConfig) -> ModelRef:
    assert isinstance(config, OllamaLLMConfig)
    return ModelRef(
        provider_id="llm.ollama",
        model_string=f"openai:{config.model}",
        base_url=config.base_url,
    )


def _build_openai_compatible(config: ProviderConfig) -> ModelRef:
    assert isinstance(config, OpenAICompatibleLLMConfig)
    return ModelRef(
        provider_id="llm.openai_compatible",
        model_string=f"openai:{config.model}",
        base_url=config.base_url,
        api_key=config.api_key,
    )


def _build_anthropic(config: ProviderConfig) -> ModelRef:
    assert isinstance(config, AnthropicLLMConfig)
    return ModelRef(
        provider_id="llm.anthropic",
        model_string=f"anthropic:{config.model}",
        api_key=config.api_key,
    )


def _build_commandcode(config: ProviderConfig) -> ModelRef:
    assert isinstance(config, CommandCodeLLMConfig)
    headers = {"x-cmd-zdr": "1"} if config.zdr else {}
    return ModelRef(
        provider_id="llm.commandcode",
        model_string=f"openai:{config.model}",
        base_url=config.base_url,
        api_key=config.api_key,
        extra_headers=headers,
    )


def _health_test(config: ProviderConfig) -> ProviderHealth:
    return ProviderHealth.ok("offline test model — always available")


def _health_ollama(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, OllamaLLMConfig)
    return ProviderHealth.ok(f"configured for {config.base_url} (probe in Phase 7)")


def _health_openai_compatible(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, OpenAICompatibleLLMConfig)
    if config.base_url is None and config.api_key is None:
        return ProviderHealth.misconfigured("api_key or base_url required")
    return ProviderHealth.ok("configuration valid (live probe in Phase 7)")


def _health_anthropic(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, AnthropicLLMConfig)
    if config.api_key is None:
        return ProviderHealth.misconfigured("api_key is required")
    return ProviderHealth.ok("configuration valid (live probe in Phase 7)")


def _health_commandcode(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, CommandCodeLLMConfig)
    if not config.api_key.get_secret_value():
        return ProviderHealth.misconfigured(
            "api_key is required (create one in Command Code Studio)"
        )
    detail = "configuration valid"
    if config.zdr:
        detail += "; zero data retention enforced (x-cmd-zdr)"
    return ProviderHealth.ok(detail)


LLM_SPECS: list[ProviderSpec] = [
    ProviderSpec(
        id="llm.test",
        capability=Capability.LLM,
        display_name="Offline test model",
        description="Deterministic in-process model for development and CI. No network.",
        config_model=TestLLMConfig,
        build=_build_test,
        health_check=_health_test,
    ),
    ProviderSpec(
        id="llm.ollama",
        capability=Capability.LLM,
        display_name="Ollama (local models)",
        description="Runs models locally — candidate data never leaves the machine.",
        docs_url="https://ollama.com",
        config_model=OllamaLLMConfig,
        build=_build_ollama,
        health_check=_health_ollama,
    ),
    ProviderSpec(
        id="llm.openai_compatible",
        capability=Capability.LLM,
        display_name="OpenAI-compatible API",
        description="OpenAI, OpenRouter, Groq, vLLM, or any compatible gateway.",
        config_model=OpenAICompatibleLLMConfig,
        build=_build_openai_compatible,
        health_check=_health_openai_compatible,
        requires_network=True,
        secret_fields=["api_key"],
    ),
    ProviderSpec(
        id="llm.anthropic",
        capability=Capability.LLM,
        display_name="Anthropic (Claude)",
        description="Claude models via the Anthropic API.",
        docs_url="https://docs.anthropic.com",
        config_model=AnthropicLLMConfig,
        build=_build_anthropic,
        health_check=_health_anthropic,
        requires_network=True,
        secret_fields=["api_key"],
    ),
    ProviderSpec(
        id="llm.commandcode",
        capability=Capability.LLM,
        display_name="Command Code Provider API",
        description=(
            "Every top model on one OpenAI-compatible endpoint. Zero data retention "
            "on by default. Default model: xiaomi/mimo-v2.5."
        ),
        docs_url="https://commandcode.ai/docs/provider",
        config_model=CommandCodeLLMConfig,
        build=_build_commandcode,
        health_check=_health_commandcode,
        requires_network=True,
        secret_fields=["api_key"],
    ),
]


def model_ref_from(config: Any) -> ModelRef:
    """Convert any provider config into a ModelRef (used by the runtime)."""
    if isinstance(config, ModelRef):
        return config
    raise TypeError(f"expected ModelRef, got {type(config).__name__}")
