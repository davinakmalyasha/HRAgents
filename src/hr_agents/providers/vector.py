"""Vector store capability providers.

``vector.in_memory`` keeps the retriever fully in-process (small corpora,
tests, offline installs). ``vector.pgvector`` uses the platform database — the
production default, no extra service.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from hr_agents.providers.base import (
    Capability,
    ProviderConfig,
    ProviderHealth,
    ProviderSpec,
)


class InMemoryVectorConfig(ProviderConfig):
    """No configuration. Index lives with the process."""


class PgVectorConfig(ProviderConfig):
    table_name: str = Field(default="knowledge_chunks", pattern=r"^[a-z][a-z0-9_]*$")
    index: str = Field(default="hnsw", pattern=r"^(hnsw|ivfflat)$")
    distance: str = Field(default="cosine", pattern=r"^(cosine|l2|inner)$")


def _build_memory(config: ProviderConfig) -> dict[str, Any]:
    return {"transport": "in_memory"}


def _build_pgvector(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, PgVectorConfig)
    return {
        "transport": "pgvector",
        "table_name": config.table_name,
        "index": config.index,
        "distance": config.distance,
    }


def _health_memory(config: ProviderConfig) -> ProviderHealth:
    return ProviderHealth.ok("in-process index (no persistence)")


def _health_pgvector(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, PgVectorConfig)
    return ProviderHealth.ok(
        f"pgvector table {config.table_name} ({config.index}, {config.distance})"
    )


def vector_specs() -> list[ProviderSpec]:
    return [
        ProviderSpec(
            id="vector.in_memory",
            capability=Capability.VECTOR_STORE,
            display_name="In-memory vector store",
            description="Process-local index. Simple and fast for small corpora.",
            config_model=InMemoryVectorConfig,
            build=_build_memory,
            health_check=_health_memory,
        ),
        ProviderSpec(
            id="vector.pgvector",
            capability=Capability.VECTOR_STORE,
            display_name="PostgreSQL + pgvector",
            description="Production default — vector search inside the platform database.",
            docs_url="https://github.com/pgvector/pgvector",
            config_model=PgVectorConfig,
            build=_build_pgvector,
            health_check=_health_pgvector,
        ),
    ]
