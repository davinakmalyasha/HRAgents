"""Provider layer: adaptive, universal integrations.

Every external dependency is a *capability* (LLM, email, WhatsApp, calendar,
storage, embeddings, vector store, queue) with interchangeable *providers*
behind one interface. See ``docs/architecture/providers.md``.
"""

from hr_agents.providers.base import (
    Capability,
    ProviderConfig,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderSpec,
    mask_secrets,
)
from hr_agents.providers.llm import ModelRef
from hr_agents.providers.registry import ProviderRegistry, default_registry
from hr_agents.providers.settings import (
    ResolvedProvider,
    resolve_provider_settings,
)

__all__ = [
    "Capability",
    "ModelRef",
    "ProviderConfig",
    "ProviderHealth",
    "ProviderHealthStatus",
    "ProviderRegistry",
    "ProviderSpec",
    "ResolvedProvider",
    "default_registry",
    "mask_secrets",
    "resolve_provider_settings",
]
