"""Active queue resolution — the one place that decides which backend is live.

The API publishes evaluation work and the worker claims it. Both must resolve the
*same* backend or the pipeline silently never runs, so resolution lives here and
both sides call it.

Resolution walks the capability's fallback chain and returns the first provider
that both **builds and reports healthy**. A process-local queue is refused when it
would be picked *implicitly*: the API process would accept work that a separate
worker can never claim, which is the same silent stall this module exists to
prevent. Naming it explicitly is honoured, because that is a deliberate choice.
"""

from __future__ import annotations

from hr_agents.providers.base import Capability, ProviderHealthStatus
from hr_agents.providers.queue import QueueBackend
from hr_agents.providers.registry import ProviderRegistry, default_registry
from hr_agents.providers.settings import resolve_provider_settings_with_registry

MEMORY_QUEUE_ID = "queue.memory"


class QueueUnavailableError(RuntimeError):
    """No queue provider could be resolved, built, and reached."""


async def resolve_queue_backend(
    *,
    registry: ProviderRegistry | None = None,
    allow_memory: bool = False,
    prefer: str | None = None,
) -> QueueBackend:
    """Build the configured queue backend, skipping candidates that are not usable.

    Order: the env/UI selection (``HRAGENTS_PROVIDER_QUEUE``), then the capability
    fallback chain (``queue.redis`` → ``queue.postgres``). Raises
    :class:`QueueUnavailableError` listing exactly what was tried — a stopped
    pipeline must be loud.

    Passing an explicit ``registry`` also means the caller owns resolution: the
    ambient environment is not consulted, so an isolated test registry is not
    silently overridden by whatever the developer's ``.env`` says.
    """
    reg = registry if registry is not None else default_registry()
    selected = prefer
    if selected is None and registry is None:
        env_settings = resolve_provider_settings_with_registry(None, reg)
        chosen = env_settings.get(Capability.QUEUE)
        if chosen is not None and chosen.provider_id:
            selected = chosen.provider_id
    chain = reg.resolve_chain(Capability.QUEUE, selected)

    tried: list[str] = []
    for spec in chain:
        # A process-local queue is refused when it would be chosen implicitly:
        # the API process would accept work that a separate worker can never
        # claim, which is the same silent stall this module exists to prevent.
        # An explicit HRAGENTS_PROVIDER_QUEUE=queue.memory is honoured, because
        # that is a deliberate choice (single-process demo, eval harness, CI).
        if spec.id == MEMORY_QUEUE_ID and selected is None and not allow_memory:
            tried.append(f"{spec.id} (skipped: process-local, cannot span api+worker)")
            continue
        try:
            config = spec.make_config({})
            health = await spec.check_health(config)
            if health.status is not ProviderHealthStatus.OK:
                tried.append(f"{spec.id} ({health.status.value}: {health.detail})")
                continue
            built = spec.apply(config)
        except Exception as exc:
            tried.append(f"{spec.id} ({type(exc).__name__}: {exc})")
            continue
        if isinstance(built, QueueBackend):
            return built
        tried.append(f"{spec.id} (built {type(built).__name__}, not a QueueBackend)")

    raise QueueUnavailableError(
        "no usable queue provider. Tried: "
        + "; ".join(tried)
        + ". Set HRAGENTS_PROVIDER_QUEUE=queue.postgres for a Postgres-only install."
    )
