"""Suite-wide hermetic setup.

A developer's local ``.env`` must never change what the tests do: a configured
LLM provider or Redis queue would make the suite reach the network, and API
keys or a Postgres backend would change the auth and store paths under test.
This session fixture pins the offline model, the in-memory defaults, and the
sandboxed transports, then restores the environment afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from hr_agents.config import get_settings
from hr_agents.providers import settings as provider_settings

LEAKY_ENV_PREFIXES = ("HRAGENTS_PROVIDER_",)

LEAKY_ENV_KEYS = frozenset(
    {
        "HRAGENTS_LLM_MODEL",
        "HRAGENTS_MESSAGING_SANDBOX",
        "HRAGENTS_SMTP_HOST",
        "HRAGENTS_SMTP_PORT",
        "HRAGENTS_SMTP_FROM",
        "HRAGENTS_STORE_BACKEND",
        "HRAGENTS_API_KEYS",
        "HRAGENTS_API_PRINCIPALS",
    }
)

FORCED_ENV = {
    "HRAGENTS_LLM_MODEL": "test",
    "HRAGENTS_MESSAGING_SANDBOX": "true",
}


def _is_leaky(key: str) -> bool:
    return key in LEAKY_ENV_KEYS or key.startswith(LEAKY_ENV_PREFIXES)


@pytest.fixture(autouse=True, scope="session")
def hermetic_environment() -> Iterator[None]:
    """Pin offline defaults for the whole session; never read ``.env``."""
    saved = {key: value for key, value in os.environ.items() if _is_leaky(key)}
    provider_settings._DOTENV_LOADED = True
    for key in saved:
        os.environ.pop(key, None)
    os.environ.update(FORCED_ENV)
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key in [key for key in os.environ if _is_leaky(key)]:
            os.environ.pop(key, None)
        os.environ.update(saved)
        get_settings.cache_clear()
