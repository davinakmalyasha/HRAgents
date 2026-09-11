"""Provider contracts: capabilities, specs, configs, and health.

A provider is one module that declares a :class:`ProviderSpec`: a config model
(the UI form is generated from its JSON Schema), a builder, and a health check.
Nothing else in the codebase knows which provider is active.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, SecretStr

from hr_agents.models import StrictModel, UtcDateTime, utc_now


class Capability(StrEnum):
    """External capabilities the platform consumes."""

    LLM = "llm"
    EMBEDDINGS = "embeddings"
    EMAIL_SEND = "email_send"
    EMAIL_RECEIVE = "email_receive"
    WHATSAPP = "whatsapp"
    CALENDAR = "calendar"
    STORAGE = "storage"
    VECTOR_STORE = "vector_store"
    QUEUE = "queue"


class ProviderHealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    MISCONFIGURED = "misconfigured"
    UNAVAILABLE = "unavailable"


class ProviderHealth(StrictModel):
    """Result of a provider health check, shown as a badge in Settings."""

    status: ProviderHealthStatus
    detail: str = ""
    checked_at: UtcDateTime = Field(default_factory=utc_now)

    @classmethod
    def ok(cls, detail: str = "") -> ProviderHealth:
        return cls(status=ProviderHealthStatus.OK, detail=detail)

    @classmethod
    def misconfigured(cls, detail: str) -> ProviderHealth:
        return cls(status=ProviderHealthStatus.MISCONFIGURED, detail=detail)

    @classmethod
    def unavailable(cls, detail: str) -> ProviderHealth:
        return cls(status=ProviderHealthStatus.UNAVAILABLE, detail=detail)


class ProviderConfig(StrictModel):
    """Base class for provider configuration models.

    Subclasses declare fields; the Settings UI renders a form from the model's
    JSON Schema and masks every :class:`~pydantic.SecretStr` field.
    """

    def masked(self) -> dict[str, Any]:
        return mask_secrets(self)


def mask_secrets(value: Any) -> Any:
    """Recursively replace ``SecretStr`` values with a masked preview.

    Used for API responses, logs, and audit payloads — raw secrets never leave
    the config object.
    """
    if isinstance(value, SecretStr):
        raw = value.get_secret_value()
        return f"…{raw[-4:]}" if len(raw) > 4 else "…"
    if isinstance(value, ProviderConfig):
        return {key: mask_secrets(item) for key, item in value.model_dump().items()}
    if isinstance(value, dict):
        return {key: mask_secrets(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_secrets(item) for item in value]
    return value


BuildFn = Callable[[ProviderConfig], Any]
HealthFn = Callable[[ProviderConfig], ProviderHealth | Awaitable[ProviderHealth]]
ConfigFactory = Callable[[dict[str, Any]], ProviderConfig]


class ProviderSpec(StrictModel):
    """Declarative description of one provider.

    ``build`` produces whatever the consumer needs (for the queue capability:
    a backend instance; for the LLM capability: a model reference).
    ``health_check`` validates configuration and, where practical, reachability.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z_]+\.[a-z0-9_]+$")
    capability: Capability
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    docs_url: str | None = None
    config_model: type[ProviderConfig]
    build: BuildFn | None = Field(default=None, exclude=True)
    health_check: HealthFn | None = Field(default=None, exclude=True)
    requires_network: bool = False
    secret_fields: list[str] = Field(default_factory=list)

    def make_config(self, raw: dict[str, Any] | None = None) -> ProviderConfig:
        """Validate raw configuration against this provider's config model."""
        return self.config_model.model_validate(raw or {})

    async def check_health(self, config: ProviderConfig) -> ProviderHealth:
        """Run the provider's health check (sync or async)."""
        if self.health_check is None:
            return ProviderHealth.ok("no health check declared")
        result = self.health_check(config)
        if isinstance(result, ProviderHealth):
            return result
        return await result

    def apply(self, config: ProviderConfig) -> Any:
        """Build the provider consumer object from configuration."""
        if self.build is None:
            raise NotImplementedError(f"provider {self.id!r} does not implement build()")
        return self.build(config)
