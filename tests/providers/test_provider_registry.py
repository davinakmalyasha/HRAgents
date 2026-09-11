import pytest

from hr_agents.providers import (
    Capability,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderRegistry,
    ProviderSpec,
)
from hr_agents.providers.base import ProviderConfig
from hr_agents.providers.registry import ProviderNotFoundError, default_registry


class EmptyConfig(ProviderConfig):
    pass


def make_spec(provider_id: str, capability: Capability) -> ProviderSpec:
    return ProviderSpec(
        id=provider_id,
        capability=capability,
        display_name=provider_id,
        config_model=EmptyConfig,
        build=lambda config: provider_id,
        health_check=lambda config: ProviderHealth.ok(),
    )


def test_register_and_lookup() -> None:
    registry = ProviderRegistry()
    spec = make_spec("demo.one", Capability.LLM)
    registry.register(spec)

    assert registry.get("demo.one") is spec
    assert "demo.one" in registry
    assert len(registry) == 1


def test_duplicate_registration_rejected() -> None:
    registry = ProviderRegistry()
    registry.register(make_spec("demo.one", Capability.LLM))
    with pytest.raises(ValueError, match="duplicate provider id"):
        registry.register(make_spec("demo.one", Capability.LLM))


def test_unknown_provider_raises() -> None:
    registry = ProviderRegistry()
    with pytest.raises(ProviderNotFoundError, match="unknown provider"):
        registry.get("nope.nope")


def test_for_capability_sorted() -> None:
    registry = ProviderRegistry()
    registry.register(make_spec("demo.b", Capability.QUEUE))
    registry.register(make_spec("demo.a", Capability.QUEUE))
    registry.register(make_spec("demo.c", Capability.LLM))

    assert [spec.id for spec in registry.for_capability(Capability.QUEUE)] == [
        "demo.a",
        "demo.b",
    ]
    assert registry.capabilities() == [Capability.LLM, Capability.QUEUE]


def test_resolve_follows_fallback_chain() -> None:
    registry = ProviderRegistry()
    registry.register(make_spec("queue.memory", Capability.QUEUE))
    registry.register(make_spec("queue.postgres", Capability.QUEUE))

    # Default chain is redis -> postgres -> memory; redis absent, so postgres wins.
    assert registry.resolve(Capability.QUEUE).id == "queue.postgres"


def test_resolve_memory_when_it_is_all_that_exists() -> None:
    registry = ProviderRegistry()
    registry.register(make_spec("queue.memory", Capability.QUEUE))
    assert registry.resolve(Capability.QUEUE).id == "queue.memory"


def test_resolve_preferred_overrides_chain() -> None:
    registry = ProviderRegistry()
    registry.register(make_spec("queue.memory", Capability.QUEUE))
    registry.register(make_spec("queue.postgres", Capability.QUEUE))

    assert registry.resolve(Capability.QUEUE, "queue.memory").id == "queue.memory"


def test_resolve_preferred_wrong_capability() -> None:
    registry = ProviderRegistry()
    registry.register(make_spec("demo.llm", Capability.LLM))
    with pytest.raises(ValueError, match=r"not queue"):
        registry.resolve(Capability.QUEUE, "demo.llm")


def test_resolve_no_provider_raises() -> None:
    registry = ProviderRegistry()
    with pytest.raises(ProviderNotFoundError, match="no provider registered"):
        registry.resolve(Capability.WHATSAPP)


def test_resolve_chain_preferred_first_then_fallbacks() -> None:
    registry = ProviderRegistry()
    registry.register(make_spec("queue.memory", Capability.QUEUE))
    registry.register(make_spec("queue.redis", Capability.QUEUE))

    chain = registry.resolve_chain(Capability.QUEUE, "queue.memory")
    assert [spec.id for spec in chain] == ["queue.memory", "queue.redis"]


async def test_health_report_skips_invalid_default_configs() -> None:

    class RequiresModel(ProviderConfig):
        model: str

    registry = ProviderRegistry()
    registry.register(
        ProviderSpec(
            id="demo.needs_model",
            capability=Capability.LLM,
            display_name="Needs model",
            config_model=RequiresModel,
            build=lambda config: config,
            health_check=lambda config: ProviderHealth.ok(),
        )
    )
    registry.register(make_spec("demo.one", Capability.LLM))

    report = await registry.health_report(
        {
            "demo.one": registry.get("demo.one"),
            "demo.needs_model": registry.get("demo.needs_model"),
        }
    )
    assert report["demo.one"].status is ProviderHealthStatus.OK
    assert report["demo.needs_model"].status is ProviderHealthStatus.MISCONFIGURED


def test_default_registry_contains_builtins() -> None:
    registry = default_registry()

    assert "queue.memory" in registry
    assert "queue.redis" in registry
    assert "queue.postgres" in registry
    assert "llm.test" in registry
    assert "llm.ollama" in registry
    assert "llm.openai_compatible" in registry
    assert "llm.anthropic" in registry
