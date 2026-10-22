"""Every advertised setting must be a real one.

`.env.example` is what a self-hoster reads. A key that no `Settings` field
reads is a promise the product does not keep -- three of them sat there for
months, advertised and never used -- and a setting nobody can find is worse
than no setting.
"""

from __future__ import annotations

from pathlib import Path

from hr_agents.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def advertised_keys() -> set[str]:
    """The `HRAGENTS_*` names `.env.example` actually sets (not the commented ones)."""
    keys: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        if name.startswith("HRAGENTS_"):
            keys.add(name)
    return keys


def test_every_advertised_key_is_a_setting() -> None:
    fields = {name.lower() for name in Settings.model_fields}

    unknown = sorted(
        key for key in advertised_keys() if key.removeprefix("HRAGENTS_").lower() not in fields
    )

    assert unknown == [], f".env.example advertises settings that do not exist: {unknown}"


def test_the_example_still_carries_the_essentials() -> None:
    """A guard that passes on an empty file is not a guard."""
    keys = advertised_keys()

    assert "HRAGENTS_APP_NAME" in keys
    assert "HRAGENTS_MESSAGING_SANDBOX" in keys
