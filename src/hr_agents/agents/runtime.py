"""Agent runtime: provider-driven model resolution, limits, and tracing hooks.

The runtime is the only place that turns a provider :class:`ModelRef` into a
PydanticAI model object. Tests inject deterministic models directly; production
resolves through the provider settings layer.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.providers import Capability, ModelRef
from hr_agents.providers.settings import resolve_provider_settings


class AgentRuntimeError(RuntimeError):
    """Raised when the runtime cannot build a model."""


class RuntimeLimits(StrictModel):
    """Per-run guards against runaway loops and cost."""

    request_limit: int = Field(default=12, ge=1)
    tool_calls_limit: int = Field(default=12, ge=1)
    total_tokens_limit: int | None = Field(default=None, ge=1)
    output_retries: int = Field(default=3, ge=0)


# Providers whose OpenAI-compatible endpoints do not reliably support
# tool-call structured output. For these we ask for JSON in the prompt and
# validate with Pydantic — equally safe, far more reliable on open models.
PROMPTED_OUTPUT_PROVIDERS = frozenset({"llm.commandcode", "llm.ollama", "llm.openai_compatible"})


class AgentRuntime:
    """Resolves the model used by every agent and carries run limits."""

    def __init__(
        self,
        model: Any | None = None,
        *,
        limits: RuntimeLimits | None = None,
        provider_id: str = "llm.test",
    ) -> None:
        self._model = model
        self._limits = limits or RuntimeLimits()
        self._provider_id = provider_id

    # --- constructors ---------------------------------------------------

    @classmethod
    def offline(cls, *, limits: RuntimeLimits | None = None) -> AgentRuntime:
        """Deterministic in-process model for tests, CI, and demos."""
        from pydantic_ai.models.test import TestModel

        return cls(TestModel(), limits=limits, provider_id="llm.test")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AgentRuntime:
        """Resolve the configured LLM provider from the environment.

        Falls back to the offline model when no LLM provider is configured, so
        the platform never hard-fails on missing credentials.
        """
        settings = resolve_provider_settings(env)
        selection = settings.get(Capability.LLM)
        if selection is None or selection.provider_id is None:
            return cls.offline()

        from hr_agents.providers.registry import default_registry

        spec = default_registry().get(selection.provider_id)
        config = spec.make_config(selection.config)
        ref = spec.apply(config)
        if not isinstance(ref, ModelRef):
            raise AgentRuntimeError(
                f"LLM provider {selection.provider_id!r} did not return a ModelRef"
            )
        return cls(build_model(ref), provider_id=ref.provider_id)

    # --- accessors ------------------------------------------------------

    @property
    def model(self) -> Any:
        if self._model is None:
            raise AgentRuntimeError("runtime has no model: construct via offline() or from_env()")
        return self._model

    @property
    def limits(self) -> RuntimeLimits:
        return self._limits

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def usage_limits(self) -> Any:
        """PydanticAI UsageLimits built from the runtime limits."""
        from pydantic_ai.usage import UsageLimits

        return UsageLimits(
            request_limit=self._limits.request_limit,
            tool_calls_limit=self._limits.tool_calls_limit,
            total_tokens_limit=self._limits.total_tokens_limit,
        )

    def structured_output(self, model_type: type[Any]) -> Any:
        """Choose the structured-output strategy for the active provider.

        Tool-call structured output is default for providers that support it
        reliably (Anthropic, test model). OpenAI-compatible open-model
        endpoints get prompted JSON output, which is validated by Pydantic
        exactly the same way.
        """
        if self._provider_id in PROMPTED_OUTPUT_PROVIDERS:
            from pydantic_ai import PromptedOutput

            return PromptedOutput(model_type)
        return model_type


def build_model(ref: ModelRef) -> Any:
    """Build a PydanticAI model from a provider-resolved reference."""
    model_string = ref.model_string
    if model_string == "test":
        from pydantic_ai.models.test import TestModel

        return TestModel()

    provider_name, _, model_name = model_string.partition(":")
    if not provider_name or not model_name:
        raise AgentRuntimeError(f"invalid model string: {model_string!r}")

    api_key = ref.api_key.get_secret_value() if ref.api_key is not None else None

    if provider_name == "openai":
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        if ref.extra_headers:
            client = AsyncOpenAI(
                api_key=api_key or "unused",
                base_url=ref.base_url,
                default_headers=ref.extra_headers,
            )
            openai_provider = OpenAIProvider(openai_client=client)
        else:
            openai_provider = OpenAIProvider(api_key=api_key, base_url=ref.base_url)
        return OpenAIChatModel(model_name, provider=openai_provider)

    if provider_name == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        anthropic_provider = AnthropicProvider(api_key=api_key, base_url=ref.base_url)
        return AnthropicModel(model_name, provider=anthropic_provider)

    raise AgentRuntimeError(f"unsupported model provider: {provider_name!r}")
