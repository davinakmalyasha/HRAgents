"""Operator-managed provider configuration, encrypted at rest.

The provider layer already declares, per capability, every registered provider
and its config model. This service turns that declaration into an editable
setting: validate the config with the provider's own model, seal it, persist it,
and apply it at the next resolution. The environment still wins when it locks a
capability, because a deployment's pinned wiring is not a suggestion.

A blank secret on update keeps the stored value. The form never receives the
secret back -- only its last four characters -- so requiring a retype would mean
the person cannot change anything else about an entry without also rotating the
credential.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from hr_agents.errors import DomainCode, DomainError
from hr_agents.identity import ActorRef
from hr_agents.logging import get_logger
from hr_agents.models import ProviderSetting, utc_now
from hr_agents.providers.base import Capability, ProviderConfig, ProviderHealth, ProviderSpec
from hr_agents.providers.registry import ProviderRegistry
from hr_agents.providers.settings import (
    ResolvedProvider,
    install_settings_overrides,
    resolve_provider_settings,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.sealing import Sealer

logger = get_logger(__name__)


class ProviderSettingsError(DomainError, RuntimeError):
    """Raised for an invalid or refused provider-setting change."""


class ProviderSettingsStore:
    """In-memory provider settings keyed by capability; the DB adapter overrides."""

    def __init__(self) -> None:
        self._items: dict[str, ProviderSetting] = {}

    def add(self, setting: ProviderSetting) -> None:
        self._items[setting.capability] = setting

    def save(self, setting: ProviderSetting) -> None:
        if setting.capability not in self._items:
            raise KeyError(f"unknown provider setting {setting.capability}")
        self._items[setting.capability] = setting

    def get(self, capability: str) -> ProviderSetting | None:
        return self._items.get(capability)

    def list_all(self) -> list[ProviderSetting]:
        return sorted(self._items.values(), key=lambda item: item.capability)

    def delete(self, capability: str) -> bool:
        return self._items.pop(capability, None) is not None


class ProviderSettingsService:
    """Validated, sealed, audited provider configuration."""

    def __init__(
        self,
        store: ProviderSettingsStore,
        *,
        registry: ProviderRegistry,
        sealer: Sealer | None,
        audit: AuditChain | None = None,
        resolve_env: Callable[[], dict[Capability, ResolvedProvider]] | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._sealer = sealer
        self._audit = audit or AuditChain()
        self._resolve_env = resolve_env or resolve_provider_settings

    @property
    def available(self) -> bool:
        """Configuration writes need a key; without one the surface is read-only."""
        return self._sealer is not None

    def list_all(self) -> list[ProviderSetting]:
        return self._store.list_all()

    def effective(self) -> dict[Capability, ResolvedProvider]:
        """The stored selections, validated against the registry as it is now.

        A row naming a provider that a downgrade removed is skipped rather than
        crashing startup; the providers page still reports the capability from
        the environment/default.
        """
        resolved: dict[Capability, ResolvedProvider] = {}
        for setting in self._store.list_all():
            try:
                capability = Capability(setting.capability)
                spec = self._registry.get(setting.provider_id)
            except ValueError, KeyError:
                logger.warning(
                    "provider_settings.ignored",
                    capability=setting.capability,
                    provider_id=setting.provider_id,
                )
                continue
            if spec.capability is not capability:
                logger.warning(
                    "provider_settings.capability_mismatch",
                    capability=setting.capability,
                    provider_id=setting.provider_id,
                )
                continue
            try:
                spec.make_config(setting.config)
            except Exception:
                logger.warning(
                    "provider_settings.invalid_stored_config",
                    capability=setting.capability,
                )
                continue
            resolved[capability] = ResolvedProvider(
                capability=capability,
                provider_id=setting.provider_id,
                config=setting.config,
                locked=False,
                source="settings",
            )
        return resolved

    def install(self) -> None:
        """Apply the stored selections to the process-wide resolution."""
        install_settings_overrides(self.effective())

    def save(
        self,
        capability: Capability,
        *,
        provider_id: str,
        config: Mapping[str, Any],
        actor: ActorRef,
    ) -> ProviderSetting:
        """Validate, seal and store one capability's selection.

        Refuses when the environment locks the capability: the padlock is not
        decorative, and a UI write that silently loses to an env var would be
        worse than no write at all.
        """
        if not self.available:
            raise ProviderSettingsError(
                "provider configuration needs HRAGENTS_SETTINGS_ENCRYPTION_KEY; "
                "generate one with scripts/settings_key.py"
            )
        actor.require_human("configuring a provider", ProviderSettingsError)
        selection = self._resolve_env().get(capability)
        if selection is not None and selection.locked:
            raise ProviderSettingsError(
                f"{capability.value} is locked by the environment; remove the "
                "HRAGENTS_PROVIDER_..._LOCK setting to edit it here"
            )
        spec = self._spec_for(capability, provider_id)
        merged = self._merge_secrets(capability, provider_id, dict(config), spec.secret_fields)
        self._validate(spec, merged)

        existing = self._store.get(capability.value)
        setting = ProviderSetting(
            id=existing.id if existing is not None else uuid4(),
            capability=capability.value,
            provider_id=provider_id,
            config=merged,
            updated_by=actor.actor_id,
            updated_at=utc_now(),
        )
        if existing is None:
            self._store.add(setting)
        else:
            self._store.save(setting)
        self._audit.append(
            actor=actor.audit_actor(),
            action="provider.configured",
            subject_type="provider_capability",
            subject_id=capability.value,
            payload={
                "provider_id": provider_id,
                "fields": sorted(merged),
                "secret_fields": sorted(spec.secret_fields),
            },
        )
        logger.info(
            "provider.configured",
            capability=capability.value,
            provider_id=provider_id,
            actor=actor.actor_id,
        )
        self.install()
        return setting

    def clear(self, capability: Capability, *, actor: ActorRef) -> bool:
        """Remove the stored selection; the environment or default takes over."""
        actor.require_human("clearing a provider selection", ProviderSettingsError)
        removed = self._store.delete(capability.value)
        if removed:
            self._audit.append(
                actor=actor.audit_actor(),
                action="provider.cleared",
                subject_type="provider_capability",
                subject_id=capability.value,
                payload={},
            )
            logger.info("provider.cleared", capability=capability.value)
            self.install()
        return removed

    async def test(
        self,
        capability: Capability,
        *,
        provider_id: str,
        config: Mapping[str, Any],
        actor: ActorRef,
    ) -> ProviderHealth:
        """Build and probe a candidate configuration without saving it."""
        actor.require_human("testing a provider configuration", ProviderSettingsError)
        spec = self._spec_for(capability, provider_id)
        merged = self._merge_secrets(capability, provider_id, dict(config), spec.secret_fields)
        validated = self._validate(spec, merged)
        return await spec.check_health(validated)

    def _spec_for(self, capability: Capability, provider_id: str) -> ProviderSpec:
        try:
            spec = self._registry.get(provider_id)
        except KeyError as exc:
            raise ProviderSettingsError(
                f"unknown provider {provider_id!r}", code=DomainCode.UNKNOWN_RECORD, status=404
            ) from exc
        if spec.capability is not capability:
            raise ProviderSettingsError(
                f"{provider_id!r} is a {spec.capability.value} provider, not {capability.value}",
                code=DomainCode.VALIDATION_FAILED,
                status=422,
            )
        return spec

    def _validate(self, spec: ProviderSpec, raw: dict[str, Any]) -> ProviderConfig:
        try:
            return spec.make_config(raw)
        except Exception as exc:
            raise ProviderSettingsError(
                f"invalid configuration for {spec.id}: {exc}",
                code=DomainCode.VALIDATION_FAILED,
                status=422,
            ) from exc

    def _merge_secrets(
        self,
        capability: Capability,
        provider_id: str,
        incoming: dict[str, Any],
        secret_fields: list[str],
    ) -> dict[str, Any]:
        """Keep a stored secret when the form left it blank.

        Only the same provider's secrets are reused: switching provider with a
        blank key must fail validation rather than inherit another service's
        credential.
        """
        existing = self._store.get(capability.value)
        if existing is None or existing.provider_id != provider_id:
            return incoming
        for name in secret_fields:
            value = incoming.get(name)
            if (value is None or value == "") and name in existing.config:
                incoming[name] = existing.config[name]
        return incoming


__all__ = [
    "ProviderSettingsError",
    "ProviderSettingsService",
    "ProviderSettingsStore",
]
