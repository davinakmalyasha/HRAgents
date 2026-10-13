"""Fully offline operation — the provider set, and that it stays credential-free.

`docs/deployment.md` §8 tells an operator how to keep candidate and employee data
on the machine. A documented configuration is one edit away from being wrong, so
these tests hold the two halves together: every provider id the section names
exists in the registry with the capability it claims, and the set resolves with
no secret anywhere in it.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re

from hr_agents.providers import Capability, ProviderHealthStatus
from hr_agents.providers.registry import default_registry
from hr_agents.providers.settings import resolve_provider_settings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPLOYMENT_DOC = REPO_ROOT / "docs" / "deployment.md"

OFFLINE_ENV = {
    "HRAGENTS_PROVIDER_LLM": "llm.ollama",
    "HRAGENTS_PROVIDER_LLM_CONFIG": json.dumps({"model": "qwen2.5:7b"}),
    "HRAGENTS_PROVIDER_EMBEDDINGS": "embeddings.ollama",
    "HRAGENTS_PROVIDER_EMBEDDINGS_CONFIG": json.dumps({"model": "nomic-embed-text"}),
    "HRAGENTS_PROVIDER_STORAGE": "storage.local_disk",
    "HRAGENTS_PROVIDER_STORAGE_CONFIG": json.dumps({"root": "data/documents"}),
    "HRAGENTS_PROVIDER_QUEUE": "queue.memory",
    "HRAGENTS_PROVIDER_WHATSAPP": "whatsapp.manual_links",
    "HRAGENTS_PROVIDER_CALENDAR": "calendar.manual_slots",
}

EXPECTED_OFFLINE = {
    Capability.LLM: "llm.ollama",
    Capability.EMBEDDINGS: "embeddings.ollama",
    Capability.STORAGE: "storage.local_disk",
    Capability.QUEUE: "queue.memory",
    Capability.WHATSAPP: "whatsapp.manual_links",
    Capability.CALENDAR: "calendar.manual_slots",
}

SECRET_HINTS = ("api_key", "password", "token", "secret", "credential")

# `HRAGENTS_PROVIDER_<CAPABILITY>=<id>`; `_CONFIG` and `_LOCK` are values for a
# capability, not ids, so the suffix must be exactly the capability name.
ENV_LINE = re.compile(r"^HRAGENTS_PROVIDER_(?P<suffix>[A-Z_]+)=(?P<value>\S+)$", re.MULTILINE)


def offline_section() -> str:
    """The §8 text, from its heading to the next `## ` heading."""
    text = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    start = text.index("## 8. Fully offline")
    rest = text[start + 1 :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def test_the_documented_provider_ids_all_exist() -> None:
    """A typo in the docs fails here rather than at an operator's startup."""
    registry = default_registry()
    matches = ENV_LINE.findall(offline_section())
    ids = [
        value
        for suffix, value in matches
        if not suffix.endswith(("_CONFIG", "_LOCK")) and value.lower() not in {"true", "false"}
    ]
    assert ids, "the offline section names no providers; did the heading move?"

    for provider_id in ids:
        assert provider_id in registry, f"docs name unknown provider {provider_id!r}"


def test_the_offline_set_resolves_to_local_providers() -> None:
    resolved = resolve_provider_settings(OFFLINE_ENV)

    assert {cap: item.provider_id for cap, item in resolved.items()} == EXPECTED_OFFLINE


def test_no_offline_provider_carries_a_secret() -> None:
    """The claim is that data stays on the machine.

    A capability whose config holds an api_key contradicts that claim even when
    it happens to run locally, so the assertion is on the values, not on the ids.
    """
    resolved = resolve_provider_settings(OFFLINE_ENV)

    for capability, item in resolved.items():
        for key, value in item.config.items():
            assert not any(hint in key.lower() for hint in SECRET_HINTS), (
                f"{capability.value} configures {key!r}; the offline set must not hold credentials"
            )
            assert value in (None, "", 0, False) or not any(
                hint in str(value).lower() for hint in SECRET_HINTS
            )


def test_the_local_llm_never_points_at_a_hosted_service() -> None:
    """`llm.ollama` builds a ModelRef whose base_url is the local daemon.

    If the default ever changed to a hosted endpoint, 'runs models locally' would
    keep reading as true on the settings screen while every CV went over the wire.
    """
    resolved = resolve_provider_settings(OFFLINE_ENV)
    spec = default_registry().get("llm.ollama")
    config = spec.make_config(resolved[Capability.LLM].config)

    model = spec.apply(config)

    assert model.base_url is not None
    assert "localhost" in model.base_url or "127.0.0.1" in model.base_url


def test_hash_embeddings_need_no_model_download() -> None:
    """The documented no-download fallback: changing the model is the only field."""
    resolved = resolve_provider_settings(
        {
            "HRAGENTS_PROVIDER_EMBEDDINGS": "embeddings.hash",
            "HRAGENTS_PROVIDER_EMBEDDINGS_CONFIG": json.dumps({"dimension": 256}),
        }
    )

    item = resolved[Capability.EMBEDDINGS]
    assert item.provider_id == "embeddings.hash"
    assert "model" not in item.config
    assert "base_url" not in item.config


def test_no_providers_configured_is_still_a_valid_offline_install() -> None:
    """The zero-provider defaults are the most offline install there is.

    Resolution returns nothing rather than inventing a hosted default, and the
    deterministic core plus the built-in `test` model keep the product usable.
    """
    assert resolve_provider_settings({}) == {}


def test_every_offline_provider_reports_configured() -> None:
    """No provider in the documented set may report itself misconfigured.

    Health is where an incomplete configuration surfaces; a set that claims to be
    fully offline must not contain one that is waiting for a key nobody will
    supply.
    """
    registry = default_registry()
    resolved = resolve_provider_settings(OFFLINE_ENV)

    for capability, item in resolved.items():
        spec = registry.get(item.provider_id or "")
        config = spec.make_config(item.config)
        health = asyncio.run(spec.check_health(config))
        assert health.status is not ProviderHealthStatus.MISCONFIGURED, (
            f"{capability.value} ({item.provider_id}) reports {health.detail!r}"
        )


def test_the_contrast_the_docs_draw_is_real() -> None:
    """A hosted provider without its key reports misconfigured.

    This is what makes 'point every capability at something local' a statement
    about more than data flow: the hosted option is visibly unusable until a
    credential is supplied, while every offline option is ready as configured.
    """
    spec = default_registry().get("llm.anthropic")
    config = spec.make_config({"model": "claude-sonnet-4-5"})

    health = asyncio.run(spec.check_health(config))

    assert health.status is ProviderHealthStatus.MISCONFIGURED
    assert "api_key" in health.detail
