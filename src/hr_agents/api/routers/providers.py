"""Provider status and configuration: what each capability uses, and how to change it.

The status half is the honest answer to "what is wired": the provider in use,
whether the environment locks it, and the provider's own health check.
Configuration writes are sealed in the database (see
``services.provider_settings``); an environment lock is authoritative and shows
as a padlock, because pinned deployment wiring is not a suggestion.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from hr_agents.api.deps import ActorDep, PaginationDep, require_permission
from hr_agents.api.problem import domain_problem
from hr_agents.api.provider_schemas import (
    ProviderConfigureRequest,
    ProviderConfigureView,
    ProviderField,
    ProviderOption,
    ProviderOptionsView,
    ProviderStatusView,
    ProviderTestRequest,
    ProviderTestView,
)
from hr_agents.api.schemas import Page
from hr_agents.providers.base import (
    Capability,
    ProviderHealthStatus,
    ProviderSpec,
    mask_secrets,
)
from hr_agents.providers.registry import ProviderRegistry, default_registry
from hr_agents.providers.settings import ResolvedProvider, resolve_provider_settings
from hr_agents.rbac import Permission
from hr_agents.services.provider_settings import (
    ProviderSettingsError,
    ProviderSettingsService,
)

router = APIRouter(
    prefix="/v1/providers",
    tags=["providers"],
    dependencies=[Depends(require_permission(Permission.ADMIN_MANAGE))],
)


def get_provider_settings(request: Request) -> ProviderSettingsService:
    return request.app.state.provider_settings


SettingsDep = Annotated[ProviderSettingsService, Depends(get_provider_settings)]


@router.get("", response_model=Page[ProviderStatusView])
async def list_providers(
    paging: PaginationDep, settings_service: SettingsDep
) -> Page[ProviderStatusView]:
    """Every capability, with the provider in use and its health.

    An unconfigured capability is not an error: the product ships offline
    defaults for most of them, and saying "not configured" would read as a
    fault where there is none.
    """
    registry = default_registry()
    resolved = resolve_provider_settings()
    items = [
        await _status(
            capability,
            resolved,
            registry,
            editable=settings_service.available,
        )
        for capability in Capability
    ]
    window = items[paging.offset : paging.offset + paging.limit]
    return Page.of(window, total=len(items), limit=paging.limit, offset=paging.offset)


@router.get("/{capability}/options", response_model=ProviderOptionsView)
def provider_options(capability: Capability, settings_service: SettingsDep) -> ProviderOptionsView:
    """The providers registered for one capability, with forms from their schemas."""
    registry = default_registry()
    selected = resolve_provider_settings().get(capability)
    locked = selected.locked if selected is not None else False
    return ProviderOptionsView(
        capability=capability,
        selected_provider_id=selected.provider_id if selected is not None else None,
        source=selected.source if selected is not None else "default",
        locked=locked,
        editable=settings_service.available and not locked,
        providers=[
            ProviderOption(
                provider_id=spec.id,
                display_name=spec.display_name,
                description=spec.description,
                docs_url=spec.docs_url,
                requires_network=spec.requires_network,
                fields=_fields_for(spec),
            )
            for spec in registry.for_capability(capability)
        ],
    )


@router.put("/{capability}", response_model=ProviderConfigureView)
async def configure_provider(
    capability: Capability,
    payload: ProviderConfigureRequest,
    settings_service: SettingsDep,
    actor: ActorDep,
) -> ProviderConfigureView:
    """Store this capability's provider and config, sealed, with a named human.

    The new selection resolves immediately for anything built after this point;
    services constructed at startup (the model runtime, the queue backend) keep
    what they were built with until the process restarts, which the response
    says rather than pretending otherwise.
    """
    try:
        setting = settings_service.save(
            capability,
            provider_id=payload.provider_id,
            config=payload.config,
            actor=actor,
        )
    except ProviderSettingsError as exc:
        raise domain_problem(exc) from exc
    resolved = {
        capability: ResolvedProvider(
            capability=capability,
            provider_id=setting.provider_id,
            config=setting.config,
            locked=False,
            source="settings",
        )
    }
    view = await _status(
        capability, resolved, default_registry(), editable=settings_service.available
    )
    return ProviderConfigureView(status=view)


@router.delete("/{capability}", status_code=status.HTTP_204_NO_CONTENT)
def clear_provider(
    capability: Capability, settings_service: SettingsDep, actor: ActorDep
) -> Response:
    """Remove the stored selection; the environment or default takes over."""
    try:
        removed = settings_service.clear(capability, actor=actor)
    except ProviderSettingsError as exc:
        raise domain_problem(exc) from exc
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no stored provider setting for {capability.value}",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{capability}/test", response_model=ProviderTestView)
async def test_provider(
    capability: Capability,
    payload: ProviderTestRequest,
    settings_service: SettingsDep,
    actor: ActorDep,
) -> ProviderTestView:
    """Build and probe a candidate configuration without saving it.

    This is the Test button: it proves the credential works before it replaces
    one that already does.
    """
    try:
        health = await settings_service.test(
            capability,
            provider_id=payload.provider_id,
            config=payload.config,
            actor=actor,
        )
    except ProviderSettingsError as exc:
        raise domain_problem(exc) from exc
    return ProviderTestView(status=health.status, detail=health.detail)


async def _status(
    capability: Capability,
    resolved: Mapping[Capability, ResolvedProvider],
    registry: ProviderRegistry,
    *,
    editable: bool,
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
            editable=editable and not (selected.locked if selected else False),
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
            editable=editable and not (selected.locked if selected else False),
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
        editable=editable and not (selected.locked if selected else False),
    )


def _fields_for(spec: ProviderSpec) -> list[ProviderField]:
    """The form, derived from the provider's config model.

    A new provider gets editable fields without touching this router: its
    Pydantic model is the declaration, and `secret_fields` says what the form
    must never show back.
    """
    schema = spec.config_model.model_json_schema()
    required = set(schema.get("required", []))
    properties = schema.get("properties", {})
    return [
        ProviderField(
            name=name,
            title=str(definition.get("title") or name),
            type=_field_type(definition),
            required=name in required,
            secret=name in spec.secret_fields,
            description=str(definition.get("description") or ""),
            default=definition.get("default"),
        )
        for name, definition in properties.items()
    ]


def _field_type(definition: dict[str, Any]) -> str:
    kind = definition.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), "string")
    if kind is None:
        for candidate in definition.get("anyOf", []):
            if isinstance(candidate, dict) and candidate.get("type") not in (None, "null"):
                return str(candidate["type"])
        return "string"
    return str(kind)
