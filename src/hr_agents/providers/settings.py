"""Provider settings resolution — environment layer.

Precedence (docs/architecture/providers.md §4): the Settings UI wins by default;
an env var can lock a capability, in which case the env value is authoritative
and the UI shows a padlock. This module implements the env layer; the encrypted
DB layer arrives with tenancy in Phase 5.

Environment variables (``HRAGENTS_`` prefix)::

    HRAGENTS_PROVIDER_LLM=llm.anthropic
    HRAGENTS_PROVIDER_LLM_CONFIG={"api_key": "sk-...", "model": "claude-sonnet-4-5"}
    HRAGENTS_PROVIDER_LOCK_LLM=true
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.providers.base import Capability, ProviderConfig
from hr_agents.providers.registry import ProviderRegistry

ENV_PREFIX = "HRAGENTS_PROVIDER_"


class ProviderSettingsError(ValueError):
    """Raised when provider configuration from the environment is invalid."""


class ResolvedProvider(StrictModel):
    """The effective provider selection for one capability."""

    capability: Capability
    provider_id: str | None = None
    config: dict = Field(default_factory=dict)
    locked: bool = False
    source: str = "default"


def _env_key(capability: Capability, suffix: str) -> str:
    return f"{ENV_PREFIX}{capability.value.upper()}{suffix}"


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_provider_settings(
    env: Mapping[str, str] | None = None,
) -> dict[Capability, ResolvedProvider]:
    """Read provider selections from the environment.

    When ``env`` is not provided, the project ``.env`` file is loaded first
    (existing process environment variables always win), then selections are
    validated against the registry. Fail fast: a broken provider configuration
    should stop startup, not surface later as a runtime mystery.
    """
    from hr_agents.providers.registry import default_registry

    return resolve_provider_settings_with_registry(env, default_registry())


def _load_dotenv_once() -> None:
    """Load the nearest ``.env`` without overriding real environment variables."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover — dotenv ships with pydantic-settings
        _DOTENV_LOADED = True
        return
    load_dotenv(find_dotenv(usecwd=True), override=False)
    _DOTENV_LOADED = True


_DOTENV_LOADED = False


def resolve_provider_settings_with_registry(
    env: Mapping[str, str] | None,
    registry: ProviderRegistry,
) -> dict[Capability, ResolvedProvider]:
    if env is None:
        _load_dotenv_once()
    environment = dict(os.environ if env is None else env)
    resolved: dict[Capability, ResolvedProvider] = {}

    for capability in Capability:
        provider_id = environment.get(_env_key(capability, ""))
        config_raw = environment.get(_env_key(capability, "_CONFIG"))
        locked = _parse_bool(environment.get(_env_key(capability, "_LOCK"), "false"))

        if provider_id is None and config_raw is None and not locked:
            continue

        config: dict = {}
        if config_raw:
            try:
                parsed = json.loads(config_raw)
            except json.JSONDecodeError as exc:
                raise ProviderSettingsError(
                    f"{_env_key(capability, '_CONFIG')} is not valid JSON: {exc}"
                ) from exc
            if not isinstance(parsed, dict):
                raise ProviderSettingsError(
                    f"{_env_key(capability, '_CONFIG')} must be a JSON object"
                )
            config = parsed

        if provider_id is None:
            raise ProviderSettingsError(
                f"{_env_key(capability, '')} is required when a config or lock is set"
            )

        spec = registry.get(provider_id)  # raises ProviderNotFoundError with a clear message
        if spec.capability is not capability:
            raise ProviderSettingsError(
                f"{provider_id!r} is a {spec.capability.value} provider, "
                f"but was configured for {capability.value}"
            )

        if config:
            try:
                spec.make_config(config)
            except Exception as exc:
                raise ProviderSettingsError(
                    f"invalid configuration for provider {provider_id!r}: {exc}"
                ) from exc

        resolved[capability] = ResolvedProvider(
            capability=capability,
            provider_id=provider_id,
            config=config,
            locked=locked,
            source="env",
        )

    return resolved


def active_provider(
    capability: Capability,
    *,
    registry: ProviderRegistry,
    resolved: Mapping[Capability, ResolvedProvider] | None = None,
) -> tuple[object, ProviderConfig] | None:
    """Resolve, validate, and build the active provider for a capability.

    Returns ``(built, config)`` or ``None`` when the capability is entirely
    unconfigured — callers then apply the documented degradation behavior.
    """
    settings = resolved if resolved is not None else resolve_provider_settings()
    selected = settings.get(capability)

    preferred = selected.provider_id if selected else None
    try:
        spec = registry.resolve(capability, preferred)
    except Exception:
        return None

    raw_config = selected.config if selected else {}
    try:
        config = spec.make_config(raw_config)
    except Exception:
        return None

    try:
        built = spec.apply(config)
    except NotImplementedError:
        return None
    return built, config
