import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from hr_agents.providers import (
    Capability,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderSpec,
    default_registry,
)


def get_spec(provider_id: str) -> ProviderSpec:
    return default_registry().get(provider_id)


def check(provider_id: str, config: dict[str, object]) -> ProviderHealth:
    """Health-check a provider; invalid/missing required config reads as misconfigured."""
    spec = get_spec(provider_id)
    try:
        parsed = spec.make_config(config)
    except ValidationError:
        return ProviderHealth.misconfigured("required configuration is missing")
    return asyncio.run(spec.check_health(parsed))


def test_all_new_capabilities_registered() -> None:
    registry = default_registry()

    assert "email.smtp" in registry
    assert "email.resend" in registry
    assert "email.imap_poll" in registry
    assert "email.resend_webhook" in registry
    assert "whatsapp.meta_cloud" in registry
    assert "whatsapp.manual_links" in registry
    assert "calendar.manual_slots" in registry
    assert "calendar.google" in registry
    assert "storage.local_disk" in registry
    assert "storage.s3" in registry


def test_capability_resolution_uses_fallbacks() -> None:
    registry = default_registry()

    assert registry.resolve(Capability.EMAIL_SEND).id == "email.smtp"
    assert registry.resolve(Capability.EMAIL_RECEIVE).id == "email.imap_poll"
    assert registry.resolve(Capability.WHATSAPP).id == "whatsapp.manual_links"
    assert registry.resolve(Capability.CALENDAR).id == "calendar.manual_slots"
    assert registry.resolve(Capability.STORAGE).id == "storage.local_disk"


def test_smtp_health_ok() -> None:
    health = check("email.smtp", {"host": "smtp.example.com", "port": 587})
    assert health.status is ProviderHealthStatus.OK


def test_resend_send_health_requires_key() -> None:
    assert check("email.resend", {}).status is ProviderHealthStatus.MISCONFIGURED
    assert check("email.resend", {"api_key": "re-123"}).status is ProviderHealthStatus.OK


def test_imap_health_flags_missing_password() -> None:
    health = check("email.imap_poll", {"host": "imap.example.com", "username": "hr"})
    assert health.status is ProviderHealthStatus.MISCONFIGURED

    ok = check(
        "email.imap_poll",
        {"host": "imap.example.com", "username": "hr", "password": "secret"},
    )
    assert ok.status is ProviderHealthStatus.OK


def test_resend_webhook_requires_secret() -> None:
    assert check("email.resend_webhook", {}).status is ProviderHealthStatus.MISCONFIGURED
    ok = check("email.resend_webhook", {"webhook_secret": "whsec_1"})
    assert ok.status is ProviderHealthStatus.OK


def test_meta_cloud_health_requires_token() -> None:
    bare = check("whatsapp.meta_cloud", {"phone_number_id": "123"})
    assert bare.status is ProviderHealthStatus.MISCONFIGURED

    configured = check(
        "whatsapp.meta_cloud",
        {
            "phone_number_id": "123",
            "access_token": "EAAB-token",
            "webhook_verify_token": "verify-1",
        },
    )
    assert configured.status is ProviderHealthStatus.OK


def test_manual_links_always_available() -> None:
    health = check("whatsapp.manual_links", {})
    assert health.status is ProviderHealthStatus.OK
    assert "manual" in health.detail.lower()


def test_whatsapp_manual_build_shape() -> None:
    spec = get_spec("whatsapp.manual_links")
    built = spec.apply(spec.make_config({"default_country_code": "62"}))
    assert built == {"transport": "manual_links", "default_country_code": "62"}


def test_manual_calendar_always_available() -> None:
    health = check("calendar.manual_slots", {})
    assert health.status is ProviderHealthStatus.OK
    assert "ICS" in health.detail


def test_google_calendar_health_requires_refresh_token() -> None:
    bare = check("calendar.google", {"client_id": "cid", "client_secret": "csec"})
    assert bare.status is ProviderHealthStatus.MISCONFIGURED

    configured = check(
        "calendar.google",
        {"client_id": "cid", "client_secret": "csec", "refresh_token": "rtok"},
    )
    assert configured.status is ProviderHealthStatus.OK


def test_local_storage_health(tmp_path: Path) -> None:
    health = check("storage.local_disk", {"root": str(tmp_path)})
    assert health.status is ProviderHealthStatus.OK

    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    bad = check("storage.local_disk", {"root": str(file_path)})
    assert bad.status is ProviderHealthStatus.MISCONFIGURED


def test_s3_health_requires_access_key() -> None:
    bare = check("storage.s3", {"access_key": ""})
    assert bare.status is ProviderHealthStatus.MISCONFIGURED

    configured = check("storage.s3", {"access_key": "minio", "secret_key": "minio123"})
    assert configured.status is ProviderHealthStatus.OK


def test_secret_fields_declared_everywhere() -> None:
    registry = default_registry()
    assert registry.get("email.resend").secret_fields == ["api_key"]
    assert registry.get("whatsapp.meta_cloud").secret_fields == [
        "access_token",
        "webhook_verify_token",
    ]
    assert registry.get("storage.s3").secret_fields == ["secret_key"]


@pytest.mark.parametrize(
    ("provider_id", "capability"),
    [
        ("email.imap_poll", Capability.EMAIL_RECEIVE),
        ("whatsapp.manual_links", Capability.WHATSAPP),
        ("calendar.manual_slots", Capability.CALENDAR),
        ("storage.local_disk", Capability.STORAGE),
    ],
)
def test_provider_capability_matches(provider_id: str, capability: Capability) -> None:
    assert get_spec(provider_id).capability is capability
