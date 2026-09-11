import pytest

from hr_agents.agents.runtime import AgentRuntime, AgentRuntimeError, RuntimeLimits, build_model
from hr_agents.providers import ModelRef


def test_offline_runtime_builds_test_model() -> None:
    runtime = AgentRuntime.offline()
    assert type(runtime.model).__name__ == "TestModel"
    assert runtime.provider_id == "llm.test"


def test_from_env_defaults_to_offline() -> None:
    runtime = AgentRuntime.from_env({})
    assert runtime.provider_id == "llm.test"


def test_from_env_resolves_test_provider() -> None:
    runtime = AgentRuntime.from_env(
        {"HRAGENTS_PROVIDER_LLM": "llm.test", "HRAGENTS_PROVIDER_LLM_CONFIG": "{}"}
    )
    assert runtime.provider_id == "llm.test"


def test_from_env_builds_openai_compatible_model() -> None:
    runtime = AgentRuntime.from_env(
        {
            "HRAGENTS_PROVIDER_LLM": "llm.openai_compatible",
            "HRAGENTS_PROVIDER_LLM_CONFIG": (
                '{"model": "gpt-4o-mini", "api_key": "sk-test", '
                '"base_url": "https://api.example.com/v1"}'
            ),
        }
    )
    assert runtime.provider_id == "llm.openai_compatible"
    assert type(runtime.model).__name__ == "OpenAIChatModel"


def test_from_env_builds_anthropic_model() -> None:
    runtime = AgentRuntime.from_env(
        {
            "HRAGENTS_PROVIDER_LLM": "llm.anthropic",
            "HRAGENTS_PROVIDER_LLM_CONFIG": '{"api_key": "sk-ant-test"}',
        }
    )
    assert runtime.provider_id == "llm.anthropic"
    assert type(runtime.model).__name__ == "AnthropicModel"


def test_from_env_builds_ollama_model() -> None:
    runtime = AgentRuntime.from_env(
        {"HRAGENTS_PROVIDER_LLM": "llm.ollama", "HRAGENTS_PROVIDER_LLM_CONFIG": "{}"}
    )
    assert runtime.provider_id == "llm.ollama"
    assert type(runtime.model).__name__ == "OpenAIChatModel"


def test_from_env_builds_commandcode_model_with_zdr_headers() -> None:
    runtime = AgentRuntime.from_env(
        {
            "HRAGENTS_PROVIDER_LLM": "llm.commandcode",
            "HRAGENTS_PROVIDER_LLM_CONFIG": (
                '{"api_key": "cmd-test", "model": "xiaomi/mimo-v2.5"}'
            ),
        }
    )
    assert runtime.provider_id == "llm.commandcode"
    model = runtime.model
    assert type(model).__name__ == "OpenAIChatModel"
    # ZDR header is applied through the custom OpenAI client.
    client = model.client
    assert client.default_headers.get("x-cmd-zdr") == "1"
    assert str(client.base_url).rstrip("/") == "https://api.commandcode.ai/provider/v1"


def test_build_model_rejects_unknown_provider() -> None:
    ref = ModelRef(provider_id="llm.weird", model_string="weird:model")
    with pytest.raises(AgentRuntimeError, match="unsupported model provider"):
        build_model(ref)


def test_build_model_rejects_invalid_model_string() -> None:
    ref = ModelRef(provider_id="llm.bad", model_string="no-colon-here")
    with pytest.raises(AgentRuntimeError, match="invalid model string"):
        build_model(ref)


def test_usage_limits_from_runtime_limits() -> None:
    runtime = AgentRuntime.offline(limits=RuntimeLimits(request_limit=3, tool_calls_limit=4))
    limits = runtime.usage_limits()
    assert limits.request_limit == 3
    assert limits.tool_calls_limit == 4


def test_default_limits_are_sane() -> None:
    limits = RuntimeLimits()
    assert limits.request_limit >= 1
    assert limits.total_tokens_limit is None
