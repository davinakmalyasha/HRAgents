"""Embedding capability providers.

The default is the deterministic offline hash embedding: zero config, zero
cost, stable across processes — good enough for keyword-heavy knowledge
retrieval and for keeping the system fully offline-capable. API-backed
providers improve semantic recall when configured.

RAG policy reminder: embeddings power recall and Q&A only, never scoring.
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


class HashEmbeddingConfig(ProviderConfig):
    dimension: int = Field(default=256, ge=32, le=4096)


class OllamaEmbeddingConfig(ProviderConfig):
    base_url: str = "http://localhost:11434/v1"
    model: str = "nomic-embed-text"
    dimension: int = Field(default=768, ge=32, le=4096)


class OpenAIEmbeddingConfig(ProviderConfig):
    api_key: SecretStr
    model: str = "text-embedding-3-small"
    base_url: str | None = None
    dimension: int = Field(default=1536, ge=32, le=4096)


def _build_hash(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, HashEmbeddingConfig)
    return {"transport": "hash", "dimension": config.dimension}


def _build_ollama(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, OllamaEmbeddingConfig)
    return {
        "transport": "openai_compatible",
        "base_url": config.base_url,
        "model": config.model,
        "dimension": config.dimension,
    }


def _build_openai(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, OpenAIEmbeddingConfig)
    return {
        "transport": "openai_compatible",
        "base_url": config.base_url,
        "model": config.model,
        "dimension": config.dimension,
    }


def _health_hash(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, HashEmbeddingConfig)
    return ProviderHealth.ok(f"offline hash embeddings, dimension {config.dimension}")


def _health_ollama(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, OllamaEmbeddingConfig)
    return ProviderHealth.ok(f"configured for {config.base_url} (probe in Phase 7)")


def _health_openai(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, OpenAIEmbeddingConfig)
    if not config.api_key.get_secret_value():
        return ProviderHealth.misconfigured("api_key is required")
    return ProviderHealth.ok("configuration valid (probe in Phase 7)")


def embedding_specs() -> list[ProviderSpec]:
    return [
        ProviderSpec(
            id="embeddings.hash",
            capability=Capability.EMBEDDINGS,
            display_name="Offline hash embeddings",
            description=(
                "Deterministic, dependency-free embeddings. Zero config, fully "
                "offline. Recommended default."
            ),
            config_model=HashEmbeddingConfig,
            build=_build_hash,
            health_check=_health_hash,
        ),
        ProviderSpec(
            id="embeddings.ollama",
            capability=Capability.EMBEDDINGS,
            display_name="Ollama embeddings (local)",
            description="Local embedding models — documents never leave the machine.",
            docs_url="https://ollama.com",
            config_model=OllamaEmbeddingConfig,
            build=_build_ollama,
            health_check=_health_ollama,
        ),
        ProviderSpec(
            id="embeddings.openai",
            capability=Capability.EMBEDDINGS,
            display_name="OpenAI-compatible embeddings",
            description="OpenAI, Voyage, or any compatible embedding endpoint.",
            config_model=OpenAIEmbeddingConfig,
            build=_build_openai,
            health_check=_health_openai,
            requires_network=True,
            secret_fields=["api_key"],
        ),
    ]
