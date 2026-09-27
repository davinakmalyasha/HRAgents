"""WhatsApp manual-links transport — compose a ``wa.me`` link, never send.

The degraded WhatsApp mode: the system produces a deterministic link to the
candidate's chat with the queued body prefilled, and the recruiter sends it from
their own WhatsApp, then records the dispatch like any other manual send. This
module never talks to a WhatsApp server, so it works with nothing connected.

``whatsapp.meta_cloud`` remains config-only until its public webhook is wired.
"""

from __future__ import annotations

from urllib.parse import quote

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.providers.whatsapp import ManualLinksConfig

WHATSAPP_MANUAL_PROVIDER_ID = "whatsapp.manual_links"

WA_LINK_BASE = "https://wa.me"

MIN_PHONE_DIGITS = 7
MAX_PHONE_DIGITS = 15


class WhatsappLinkError(ValueError):
    """Raised when a phone number cannot be turned into a wa.me link."""


class WhatsappDispatchLink(StrictModel):
    """A ready-to-open chat link; the human still has to send the message."""

    provider: str = Field(min_length=1, max_length=64)
    phone: str = Field(min_length=1, max_length=32)
    url: str = Field(min_length=1, max_length=2000)


def normalize_phone(raw: str, *, default_country_code: str = "62") -> str:
    """E.164 digits for a candidate number (``+62``, ``62``, or ``08…``)."""
    digits = "".join(character for character in raw if character.isdigit())
    if digits.startswith("0"):
        digits = f"{default_country_code}{digits.lstrip('0')}"
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        raise WhatsappLinkError(
            f"{raw!r} is not a usable WhatsApp number "
            f"({MIN_PHONE_DIGITS}-{MAX_PHONE_DIGITS} digits after normalization)"
        )
    return digits


def wa_link(phone: str, body: str, *, default_country_code: str = "62") -> WhatsappDispatchLink:
    """Compose the click-to-chat link for a queued message body."""
    number = normalize_phone(phone, default_country_code=default_country_code)
    return WhatsappDispatchLink(
        provider=WHATSAPP_MANUAL_PROVIDER_ID,
        phone=number,
        url=f"{WA_LINK_BASE}/{number}?text={quote(body, safe='')}",
    )


class ManualWhatsappLinks:
    """Composes click-to-chat links; dispatch stays a human action."""

    def __init__(self, config: ManualLinksConfig | None = None) -> None:
        self._config = config or ManualLinksConfig()

    @property
    def provider_id(self) -> str:
        return WHATSAPP_MANUAL_PROVIDER_ID

    @property
    def default_country_code(self) -> str:
        return self._config.default_country_code

    def compose(self, phone: str, body: str) -> WhatsappDispatchLink:
        return wa_link(phone, body, default_country_code=self._config.default_country_code)


def build_manual_links(config: ManualLinksConfig) -> ManualWhatsappLinks:
    """Provider builder for ``whatsapp.manual_links``."""
    return ManualWhatsappLinks(config)
