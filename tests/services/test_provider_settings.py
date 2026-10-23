"""Provider settings: validation, secret handling, locks, and the audit payload."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from hr_agents.errors import DomainCode
from hr_agents.identity import ActorRef
from hr_agents.models import ProviderSetting
from hr_agents.providers.base import (
    Capability,
    ProviderConfig,
    ProviderHealth,
    ProviderSpec,
)
from hr_agents.providers.registry import ProviderRegistry
from hr_agents.providers.settings import ResolvedProvider
from hr_agents.services.audit import AuditChain
from hr_agents.services.provider_settings import (
    ProviderSettingsError,
    ProviderSettingsService,
    ProviderSettingsStore,
)
from hr_agents.services.sealing import FernetSealer

HUMAN = ActorRef.legacy("hr-admin")


class DemoConfig(ProviderConfig):
    api_key: SecretStr
    region: str = "id"


def demo_spec(provider_id: str = "llm.demo") -> ProviderSpec:
    return ProviderSpec(
        id=provider_id,
        capability=Capability.LLM,
        display_name="Demo model",
        config_model=DemoConfig,
        health_check=lambda config: ProviderHealth.ok("configuration valid"),
        secret_fields=["api_key"],
    )


def build_service(
    *,
    with_key: bool = True,
    env: Mapping[Capability, ResolvedProvider] | None = None,
) -> ProviderSettingsService:
    registry = ProviderRegistry()
    registry.register(demo_spec())
    registry.register(demo_spec("llm.other"))
    return ProviderSettingsService(
        ProviderSettingsStore(),
        registry=registry,
        sealer=FernetSealer(Fernet.generate_key().decode()) if with_key else None,
        audit=AuditChain(),
        resolve_env=lambda: dict(env or {}),
    )


def test_save_validates_seals_and_audits_without_the_secret() -> None:
    service = build_service()

    setting = service.save(
        Capability.LLM,
        provider_id="llm.demo",
        config={"api_key": "sk-live", "region": "sg"},
        actor=HUMAN,
    )

    assert setting.provider_id == "llm.demo"
    assert setting.updated_by == "hr-admin"
    payload = service._audit.entries[-1].payload
    assert payload["fields"] == ["api_key", "region"]
    assert "sk-live" not in str(payload)


def test_a_blank_secret_on_update_keeps_the_stored_one() -> None:
    service = build_service()
    service.save(
        Capability.LLM,
        provider_id="llm.demo",
        config={"api_key": "sk-live", "region": "id"},
        actor=HUMAN,
    )

    updated = service.save(
        Capability.LLM,
        provider_id="llm.demo",
        config={"api_key": "", "region": "sg"},
        actor=HUMAN,
    )

    assert updated.config == {"api_key": "sk-live", "region": "sg"}


def test_switching_provider_with_a_blank_secret_does_not_inherit_it() -> None:
    service = build_service()
    service.save(
        Capability.LLM,
        provider_id="llm.demo",
        config={"api_key": "sk-live"},
        actor=HUMAN,
    )

    with pytest.raises(ProviderSettingsError) as excinfo:
        service.save(
            Capability.LLM,
            provider_id="llm.other",
            config={},
            actor=HUMAN,
        )

    assert excinfo.value.code is DomainCode.VALIDATION_FAILED
    assert excinfo.value.status == 422


def test_a_provider_from_another_capability_is_refused() -> None:
    service = build_service()

    with pytest.raises(ProviderSettingsError) as excinfo:
        service.save(
            Capability.EMBEDDINGS,
            provider_id="llm.demo",
            config={"api_key": "x"},
            actor=HUMAN,
        )

    assert excinfo.value.status == 422


def test_an_unknown_provider_is_a_404() -> None:
    service = build_service()

    with pytest.raises(ProviderSettingsError) as excinfo:
        service.save(Capability.LLM, provider_id="llm.gone", config={}, actor=HUMAN)

    assert excinfo.value.code is DomainCode.UNKNOWN_RECORD


def test_an_environment_lock_is_not_a_suggestion() -> None:
    locked = {
        Capability.LLM: ResolvedProvider(
            capability=Capability.LLM,
            provider_id="llm.demo",
            config={},
            locked=True,
            source="env",
        )
    }
    service = build_service(env=locked)

    with pytest.raises(ProviderSettingsError, match="locked by the environment"):
        service.save(
            Capability.LLM,
            provider_id="llm.demo",
            config={"api_key": "x"},
            actor=HUMAN,
        )


def test_an_agent_cannot_configure_a_provider() -> None:
    service = build_service()

    with pytest.raises(ProviderSettingsError) as excinfo:
        service.save(
            Capability.LLM,
            provider_id="llm.demo",
            config={"api_key": "x"},
            actor=ActorRef.agent("tool:hr_bot"),
        )

    assert excinfo.value.code is DomainCode.NAMED_HUMAN_REQUIRED
    assert excinfo.value.status == 403


def test_without_a_key_the_surface_refuses_to_write() -> None:
    service = build_service(with_key=False)

    assert service.available is False
    with pytest.raises(ProviderSettingsError, match="ENCRYPTION_KEY"):
        service.save(
            Capability.LLM,
            provider_id="llm.demo",
            config={"api_key": "x"},
            actor=HUMAN,
        )


def test_clearing_a_selection_removes_it_and_is_audited() -> None:
    service = build_service()
    service.save(
        Capability.LLM,
        provider_id="llm.demo",
        config={"api_key": "x"},
        actor=HUMAN,
    )

    assert service.clear(Capability.LLM, actor=HUMAN) is True
    assert service.effective() == {}
    assert service._audit.entries[-1].action == "provider.cleared"
    assert service.clear(Capability.LLM, actor=HUMAN) is False


def test_effective_skips_rows_a_downgrade_left_behind() -> None:
    stale = build_service()
    stale._store.add(
        ProviderSetting(
            capability="llm",
            provider_id="llm.removed",
            config={},
            updated_by="hr-admin",
        )
    )
    assert stale.effective() == {}

    service = build_service()
    service.save(
        Capability.LLM,
        provider_id="llm.demo",
        config={"api_key": "x"},
        actor=HUMAN,
    )
    resolved = service.effective()

    assert set(resolved) == {Capability.LLM}
    assert resolved[Capability.LLM].provider_id == "llm.demo"
    assert resolved[Capability.LLM].source == "settings"


async def test_test_probes_without_saving() -> None:
    service = build_service()

    health = await service.test(
        Capability.LLM,
        provider_id="llm.demo",
        config={"api_key": "sk-live"},
        actor=HUMAN,
    )

    assert health.status.value == "ok"
    assert service.list_all() == []
