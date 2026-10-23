"""Provider settings adapter: sealed rows, version guard, delete."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.provider_settings import DbProviderSettingsStore
from hr_agents.db.session import sync_session_scope
from hr_agents.errors import StaleRecordError
from hr_agents.models import ProviderSetting
from hr_agents.services.sealing import FernetSealer


def store(factory: sessionmaker[Session], sealer: FernetSealer) -> DbProviderSettingsStore:
    return DbProviderSettingsStore(factory, sealer)


def setting(api_key: str = "sk-live") -> ProviderSetting:
    return ProviderSetting(
        capability="llm",
        provider_id="llm.demo",
        config={"api_key": api_key, "region": "id"},
        updated_by="hr-admin",
    )


def test_a_setting_round_trips_and_the_row_holds_no_plaintext(
    factory: sessionmaker[Session],
) -> None:
    sealer = FernetSealer(Fernet.generate_key().decode())
    created = setting()
    store(factory, sealer).add(created)

    fresh = store(factory, sealer)
    stored = fresh.get("llm")

    assert stored is not None
    assert stored.id == created.id
    assert stored.config == {"api_key": "sk-live", "region": "id"}
    assert [item.capability for item in fresh.list_all()] == ["llm"]

    with sync_session_scope(factory) as session:
        row = session.get(t.ProviderSettingRecord, created.id)
        assert row is not None
        assert "sk-live" not in row.config_sealed
        assert "region" not in row.config_sealed


def test_a_stale_copy_cannot_overwrite_a_newer_one(
    factory: sessionmaker[Session],
) -> None:
    sealer = FernetSealer(Fernet.generate_key().decode())
    adapter = store(factory, sealer)
    adapter.add(setting())
    first = adapter.get("llm")
    second = adapter.get("llm")
    assert first is not None and second is not None

    adapter.save(first.model_copy(update={"config": {"api_key": "sk-new"}}))

    with pytest.raises(StaleRecordError):
        adapter.save(second)


def test_delete_says_whether_it_removed_something(
    factory: sessionmaker[Session],
) -> None:
    sealer = FernetSealer(Fernet.generate_key().decode())
    adapter = store(factory, sealer)
    adapter.add(setting())

    assert adapter.delete("llm") is True
    assert adapter.delete("llm") is False
    assert adapter.get("llm") is None
