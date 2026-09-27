"""WhatsApp manual-links transport (offline — nothing is ever sent here)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from hr_agents.messaging.whatsapp import (
    WA_LINK_BASE,
    ManualWhatsappLinks,
    WhatsappLinkError,
    normalize_phone,
    wa_link,
)
from hr_agents.providers.registry import default_registry
from hr_agents.providers.whatsapp import ManualLinksConfig


def test_local_number_is_normalized_to_e164() -> None:
    assert normalize_phone("0812-3456-7890") == "6281234567890"
    assert normalize_phone("+62 812 3456 7890") == "6281234567890"


def test_a_number_without_a_leading_zero_is_treated_as_international() -> None:
    # Deterministic rule, not a guess: "0…" is the national format, anything else
    # is already prefixed, so HR types the full number when it isn't local.
    assert normalize_phone("81234567890", default_country_code="1") == "81234567890"


def test_international_number_keeps_its_own_prefix() -> None:
    assert normalize_phone("+1 (415) 555-0132") == "14155550132"


@pytest.mark.parametrize("raw", ["", "123", "not-a-number", "0"])
def test_unusable_numbers_are_refused(raw: str) -> None:
    with pytest.raises(WhatsappLinkError):
        normalize_phone(raw)


def test_link_carries_the_queued_body_verbatim() -> None:
    link = wa_link("0812 3456 7890", "Halo Budi,\nTawaran Anda siap.")

    parsed = urlparse(link.url)
    assert parsed.netloc == "wa.me"
    assert parsed.path == "/6281234567890"
    assert parse_qs(parsed.query)["text"] == ["Halo Budi,\nTawaran Anda siap."]
    assert link.phone == "6281234567890"
    assert link.provider == "whatsapp.manual_links"


def test_composer_uses_the_configured_country_code() -> None:
    transport = ManualWhatsappLinks(ManualLinksConfig(default_country_code="44"))

    link = transport.compose("07700 900123", "Hello")

    assert link.phone == "447700900123"
    assert link.url.startswith(f"{WA_LINK_BASE}/447700900123?text=")
    assert transport.provider_id == "whatsapp.manual_links"


def test_provider_builds_the_live_transport() -> None:
    spec = default_registry().get("whatsapp.manual_links")
    built = spec.apply(spec.make_config({"default_country_code": "62"}))

    assert isinstance(built, ManualWhatsappLinks)
    assert built.default_country_code == "62"
