"""Provider status: what each capability is wired to, and whether it answers.

The provider settings *forms* are still to come, and they need an encrypted
settings store to write into. This is the half that can be honest today: for
every capability, which provider is in use, whether the environment locks it,
and what that provider's own health check says. Configuration comes back
masked -- the last four characters of a secret, never the secret.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from hr_agents.api.deps import PaginationDep, require_permission
from hr_agents.api.provider_schemas import ProviderStatusView
from hr_agents.api.schemas import Page
from hr_agents.providers.base import Capability, ProviderHealthStatus, mask_secrets
from hr_agents.providers.registry import ProviderRegistry, default_registry
from hr_agents.providers.settings import ResolvedProvider, resolve_provider_settings
from hr_agents.rbac import Permission

router = APIRouter(
    prefix="/v1/providers",
    tags=["providers"],
    dependencies=[Depends(require_permission(Permission.ADMIN_MANAGE))],
)


@router.get("", response_model=Page[ProviderStatusView])
async def list_providers(paging: PaginationDep) -> Page[ProviderStatusView]:
    """Every capability, with the provider in use and its health.

    An unconfigured capability is not an error: the product ships offline
    defaults for most of them, and saying "not configured" would read as a
    fault where there is none.
    """
    registry = default_registry()
    resolved = resolve_provider_settings()
    items = [await _status(capability, resolved, registry) for capability in Capability]
    window = items[paging.offset : paging.offset + paging.limit]
    return Page.of(window, total=len(items), limit=paging.limit, offset=paging.offset)


async def _status(
    capability: Capability,
    resolved: dict[Capability, ResolvedProvider],
    registry: ProviderRegistry,
) -> ProviderStatusView:
    """One capability's provider, health, and whether the environment locked it."""
    selected = resolved.get(capability)
    try:
        spec = registry.resolve(capability, selected.provider_id if selected else None)
    except Exception as exc:  # a capability with no registered provider
        return ProviderStatusView(
            capability=capability,
            provider_id="unresolved",
            display_name=capability.value,
            status=ProviderHealthStatus.MISCONFIGURED,
            detail=str(exc),
            locked=selected.locked if selected else False,
            source=selected.source if selected else "default",
            requires_network=False,
        )

    raw = selected.config if selected else {}
    try:
        config = spec.make_config(raw)
    except Exception as exc:
        return ProviderStatusView(
            capability=capability,
            provider_id=spec.id,
            display_name=spec.display_name,
            status=ProviderHealthStatus.MISCONFIGURED,
            detail=str(exc),
            locked=selected.locked if selected else False,
            source=selected.source if selected else "default",
            requires_network=spec.requires_network,
            docs_url=spec.docs_url,
        )

    health = await spec.check_health(config)
    masked = mask_secrets(config)
    return ProviderStatusView(
        capability=capability,
        provider_id=spec.id,
        display_name=spec.display_name,
        status=health.status,
        detail=health.detail,
        locked=selected.locked if selected else False,
        source=selected.source if selected else "default",
        requires_network=spec.requires_network,
        docs_url=spec.docs_url,
        config=masked if isinstance(masked, dict) else {},
    )
