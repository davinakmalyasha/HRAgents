"""Calendar capability providers.

``calendar.manual_slots`` is the zero-config default: HR enters availability
windows manually and the system generates ICS invites — which every calendar
client accepts. Google/Microsoft/CalDAV providers plug in the same way.
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


class ManualSlotsConfig(ProviderConfig):
    """No credentials. Manual slot entry + ICS invites."""

    default_timezone: str = "Asia/Jakarta"


class GoogleCalendarConfig(ProviderConfig):
    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    refresh_token: SecretStr
    calendar_id: str = "primary"
    default_timezone: str = "Asia/Jakarta"


def _build_manual(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, ManualSlotsConfig)
    return {"transport": "manual_slots", "timezone": config.default_timezone}


def _build_google(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, GoogleCalendarConfig)
    return {
        "transport": "google",
        "calendar_id": config.calendar_id,
        "timezone": config.default_timezone,
    }


def _health_manual(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, ManualSlotsConfig)
    return ProviderHealth.ok(f"manual mode: ICS invites, timezone {config.default_timezone}")


def _health_google(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, GoogleCalendarConfig)
    if not config.refresh_token.get_secret_value():
        return ProviderHealth.misconfigured("refresh_token is required")
    return ProviderHealth.ok("configuration valid (free/busy probe in Phase 7)")


def calendar_specs() -> list[ProviderSpec]:
    return [
        ProviderSpec(
            id="calendar.manual_slots",
            capability=Capability.CALENDAR,
            display_name="Manual slots + ICS invites",
            description=(
                "Zero-config: HR enters availability, the system generates ICS "
                "invites that work with every calendar client."
            ),
            config_model=ManualSlotsConfig,
            build=_build_manual,
            health_check=_health_manual,
        ),
        ProviderSpec(
            id="calendar.google",
            capability=Capability.CALENDAR,
            display_name="Google Calendar",
            description="Free/busy lookup, slot proposals, invites, reschedules.",
            docs_url="https://developers.google.com/calendar",
            config_model=GoogleCalendarConfig,
            build=_build_google,
            health_check=_health_google,
            requires_network=True,
            secret_fields=["client_secret", "refresh_token"],
        ),
    ]
