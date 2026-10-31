"""Telegram capability provider (Bot API send).

A bot token is required, so this capability has no zero-config default: the
product never claims Telegram is connected when it is not. The dashboard hides
the provider until a token is entered, and the health check says so.
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from hr_agents.providers.base import (
    Capability,
    ProviderConfig,
    ProviderHealth,
    ProviderSpec,
)


class TelegramConfig(ProviderConfig):
    bot_token: SecretStr
    # Telegram does not sign webhook bodies; `setWebhook` registers a secret
    # token that arrives in `X-Telegram-Bot-Api-Secret-Token` on every call.
    webhook_secret: SecretStr | None = None
    base_url: str = "https://api.telegram.org"


def _build(config: ProviderConfig) -> Any:
    from hr_agents.messaging.telegram import build_telegram_sender

    assert isinstance(config, TelegramConfig)
    return build_telegram_sender(config)


def _health(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, TelegramConfig)
    if not config.bot_token.get_secret_value():
        return ProviderHealth.misconfigured("bot_token is required")
    if config.webhook_secret is None or not config.webhook_secret.get_secret_value():
        return ProviderHealth.degraded(
            "send is live; inbound needs webhook_secret to verify Telegram's calls"
        )
    return ProviderHealth.ok(
        "send and inbound are live; register the webhook with the same secret_token"
    )


def telegram_specs() -> list[ProviderSpec]:
    return [
        ProviderSpec(
            id="telegram.bot",
            capability=Capability.TELEGRAM,
            display_name="Telegram bot",
            description=(
                "Send candidate messages through a Telegram bot. Requires a bot token; "
                "there is no offline fallback, because a channel that cannot send is "
                "not a channel."
            ),
            docs_url="https://core.telegram.org/bots/api",
            config_model=TelegramConfig,
            build=_build,
            health_check=_health,
            requires_network=True,
            secret_fields=["bot_token"],
        )
    ]
