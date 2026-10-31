"""Secrets never leave the process: the redaction pass over real provider shapes.

A secret is only safe if two things hold: every field the registry calls a
secret is actually typed as one, and masking a nested payload never returns the
raw value. The first is structural (a plain ``str`` token would bypass
``mask_secrets`` entirely), the second is fuzzed because provider payloads nest
dicts, lists and config models.
"""

from __future__ import annotations

from typing import get_args

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import SecretStr

from hr_agents.providers.base import ProviderConfig, mask_secrets
from hr_agents.providers.registry import default_registry


class _Payload(ProviderConfig):
    api_key: SecretStr
    note: str = "visible"


def _is_secret_type(annotation: object) -> bool:
    return annotation is SecretStr or SecretStr in get_args(annotation)


def test_every_declared_secret_field_is_a_secret_type() -> None:
    """``secret_fields`` must point at SecretStr (or ``SecretStr | None``).

    A plain string listed there would be returned, logged and audited in the
    clear, because ``mask_secrets`` only recognizes SecretStr.
    """
    registry = default_registry()
    offenders: list[str] = []
    for provider_id in registry.ids():
        spec = registry.get(provider_id)
        for field_name in spec.secret_fields:
            field = spec.config_model.model_fields[field_name]
            if not _is_secret_type(field.annotation):
                offenders.append(f"{provider_id}.{field_name}: {field.annotation}")

    assert offenders == []


@settings(max_examples=50)
@given(
    secret=st.text(
        min_size=1,
        max_size=64,
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    )
)
def test_masking_never_returns_the_raw_secret(secret: str) -> None:
    masked = mask_secrets(
        {
            "config": _Payload(api_key=SecretStr(secret)),
            "nested": {"items": [SecretStr(secret), {"again": SecretStr(secret)}]},
        }
    )

    assert masked["config"]["api_key"] != secret
    assert masked["nested"]["items"][0] != secret
    assert masked["nested"]["items"][1]["again"] != secret
    assert secret not in masked["config"]["api_key"]
    assert secret not in masked["nested"]["items"][0]


def test_masking_keeps_non_secret_fields_readable() -> None:
    masked = mask_secrets(_Payload(api_key=SecretStr("sk-1234567890abcd")))

    assert masked["api_key"] == "…abcd"
    assert masked["note"] == "visible"
