"""Provider registry: registration, discovery, resolution, fallback chains."""

from __future__ import annotations

from collections.abc import Iterable

from hr_agents.providers.base import (
    Capability,
    ProviderHealth,
    ProviderSpec,
)

# Documented fallback chains per capability (docs/architecture/providers.md §2/§5).
# Resolution order when the preferred provider is missing or unhealthy.
DEFAULT_FALLBACKS: dict[Capability, tuple[str, ...]] = {
    Capability.LLM: (
        "llm.ollama",
        "llm.commandcode",
        "llm.openai_compatible",
        "llm.anthropic",
        "llm.test",
    ),
    Capability.EMBEDDINGS: ("hash", "embeddings.ollama", "embeddings.openai"),
    Capability.EMAIL_SEND: ("email.smtp", "email.resend"),
    Capability.EMAIL_RECEIVE: ("email.imap_poll", "email.resend_webhook"),
    # Zero-config/degraded providers resolve first: they always work. A company
    # that connects the live provider selects it explicitly (env/UI preference).
    Capability.WHATSAPP: ("whatsapp.manual_links", "whatsapp.meta_cloud"),
    Capability.CALENDAR: ("calendar.manual_slots", "calendar.google"),
    Capability.STORAGE: ("storage.local_disk", "storage.s3"),
    Capability.VECTOR_STORE: ("vector.pgvector", "vector.in_memory"),
    Capability.QUEUE: ("queue.redis", "queue.postgres", "queue.memory"),
}


class ProviderNotFoundError(KeyError):
    """Raised when a provider id is not registered."""


class ProviderRegistry:
    """Central registration surface for all providers.

    Built-in providers self-register via :func:`default_registry`; tests create
    isolated registries.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ProviderSpec] = {}

    # --- registration ---------------------------------------------------

    def register(self, spec: ProviderSpec) -> None:
        if spec.id in self._providers:
            raise ValueError(f"duplicate provider id: {spec.id!r}")
        self._providers[spec.id] = spec

    def register_all(self, specs: Iterable[ProviderSpec]) -> None:
        for spec in specs:
            self.register(spec)

    # --- lookup ---------------------------------------------------------

    def get(self, provider_id: str) -> ProviderSpec:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ProviderNotFoundError(f"unknown provider: {provider_id!r}") from exc

    def for_capability(self, capability: Capability) -> list[ProviderSpec]:
        return sorted(
            (spec for spec in self._providers.values() if spec.capability is capability),
            key=lambda spec: spec.id,
        )

    def capabilities(self) -> list[Capability]:
        return sorted({spec.capability for spec in self._providers.values()})

    def ids(self) -> list[str]:
        return sorted(self._providers)

    # --- resolution -----------------------------------------------------

    def resolve(self, capability: Capability, preferred: str | None = None) -> ProviderSpec:
        """Resolve the active provider for a capability.

        Uses ``preferred`` when given and registered; otherwise follows the
        capability's fallback chain; otherwise falls back to any registered
        provider of that capability (alphabetical for determinism).
        """
        if preferred is not None:
            spec = self.get(preferred)
            if spec.capability is not capability:
                raise ValueError(f"provider {preferred!r} is {spec.capability}, not {capability}")
            return spec

        for candidate_id in DEFAULT_FALLBACKS.get(capability, ()):
            candidate = self._providers.get(candidate_id)
            if candidate is not None and candidate.capability is capability:
                return candidate

        available = self.for_capability(capability)
        if not available:
            raise ProviderNotFoundError(f"no provider registered for capability {capability!r}")
        return available[0]

    def resolve_chain(
        self, capability: Capability, preferred: str | None = None
    ) -> list[ProviderSpec]:
        """Ordered candidates: preferred first, then the fallback chain."""
        chain: list[ProviderSpec] = []
        seen: set[str] = set()

        if preferred is not None:
            spec = self.get(preferred)
            chain.append(spec)
            seen.add(spec.id)

        for candidate_id in DEFAULT_FALLBACKS.get(capability, ()):
            if candidate_id in seen:
                continue
            candidate = self._providers.get(candidate_id)
            if candidate is not None and candidate.capability is capability:
                chain.append(candidate)
                seen.add(candidate.id)

        for spec in self.for_capability(capability):
            if spec.id not in seen:
                chain.append(spec)
                seen.add(spec.id)

        return chain

    # --- health ---------------------------------------------------------

    async def health_report(
        self, configs: dict[str, ProviderSpec] | None = None
    ) -> dict[str, ProviderHealth]:
        """Health-check providers that have a validated config available.

        ``configs`` maps provider id → spec with a config already validated by
        the caller; providers without configs are skipped.
        """
        report: dict[str, ProviderHealth] = {}
        for provider_id, spec in (configs or {}).items():
            del provider_id
            try:
                default_config = spec.make_config({})
            except Exception as exc:
                report[spec.id] = ProviderHealth.misconfigured(
                    f"default configuration invalid: {exc}"
                )
                continue
            report[spec.id] = await spec.check_health(default_config)
        return report

    def __len__(self) -> int:
        return len(self._providers)

    def __contains__(self, provider_id: object) -> bool:
        return isinstance(provider_id, str) and provider_id in self._providers


def default_registry() -> ProviderRegistry:
    """Build a registry with all built-in providers registered."""
    registry = ProviderRegistry()
    registry.register_all(_builtin_specs())
    return registry


def _builtin_specs() -> list[ProviderSpec]:
    from hr_agents.providers.builtin import all_specs

    return all_specs()
