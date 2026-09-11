"""WhatsApp capability providers.

- ``whatsapp.meta_cloud`` — official WhatsApp Business Cloud API (webhook push).
- ``whatsapp.manual_links`` — degraded mode: the system drafts messages and
  produces ``wa.me`` links; HR sends from the normal WhatsApp app. Always
  available, needs nothing connected.

Telegram and Twilio/Qontak BSP providers join later behind the same spec shape.
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


class MetaCloudConfig(ProviderConfig):
    phone_number_id: str = Field(min_length=1)
    access_token: SecretStr
    webhook_verify_token: SecretStr
    api_version: str = "v21.0"


class ManualLinksConfig(ProviderConfig):
    """No credentials needed. HR sends from their own WhatsApp."""

    default_country_code: str = Field(default="62", pattern=r"^\d{1,4}$")


def _build_meta_cloud(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, MetaCloudConfig)
    return {
        "transport": "meta_cloud",
        "phone_number_id": config.phone_number_id,
        "api_version": config.api_version,
    }


def _build_manual_links(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, ManualLinksConfig)
    return {"transport": "manual_links", "default_country_code": config.default_country_code}


def _health_meta_cloud(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, MetaCloudConfig)
    if not config.access_token.get_secret_value():
        return ProviderHealth.misconfigured("access_token is required")
    return ProviderHealth.ok(
        "configuration valid; webhook must be reachable (Cloudflare Tunnel for self-host)"
    )


def _health_manual_links(config: ProviderConfig) -> ProviderHealth:
    return ProviderHealth.ok("manual mode: drafts and wa.me links only")


def whatsapp_specs() -> list[ProviderSpec]:
    return [
        ProviderSpec(
            id="whatsapp.meta_cloud",
            capability=Capability.WHATSAPP,
            display_name="WhatsApp Business (Meta Cloud API)",
            description=(
                "Official send/receive. Inbound requires a public HTTPS webhook; "
                "self-host deployments use a Cloudflare Tunnel."
            ),
            docs_url="https://developers.facebook.com/docs/whatsapp/cloud-api",
            config_model=MetaCloudConfig,
            build=_build_meta_cloud,
            health_check=_health_meta_cloud,
            requires_network=True,
            secret_fields=["access_token", "webhook_verify_token"],
        ),
        ProviderSpec(
            id="whatsapp.manual_links",
            capability=Capability.WHATSAPP,
            display_name="Manual mode (wa.me links)",
            description=(
                "Degraded mode: agents draft messages, HR sends from WhatsApp. "
                "Always available with zero configuration."
            ),
            config_model=ManualLinksConfig,
            build=_build_manual_links,
            health_check=_health_manual_links,
        ),
    ]
