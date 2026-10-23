"""Postgres-backed provider settings, sealed before they touch the row.

The encryption lives here rather than in the service because this is the layer
that writes to durable storage: an in-memory deployment has nothing to seal yet,
and a database has everything to lose. The version check is the same one every
other adapter uses, so two operators editing the same capability cannot
silently overwrite one another.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.mapping import check_version
from hr_agents.db.session import sync_session_scope
from hr_agents.models import ProviderSetting
from hr_agents.services.provider_settings import ProviderSettingsStore
from hr_agents.services.sealing import Sealer


class DbProviderSettingsStore(ProviderSettingsStore):
    """Sealed provider configuration in ``provider_settings``."""

    def __init__(self, session_factory: sessionmaker[Session], sealer: Sealer) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._sealer = sealer

    def add(self, setting: ProviderSetting) -> None:
        with sync_session_scope(self._session_factory) as session:
            session.add(
                t.ProviderSettingRecord(
                    id=setting.id,
                    capability=setting.capability,
                    provider_id=setting.provider_id,
                    config_sealed=self._sealer.seal(setting.config),
                    updated_by=setting.updated_by,
                    updated_at=setting.updated_at,
                )
            )
            session.flush()

    def save(self, setting: ProviderSetting) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.ProviderSettingRecord, setting.id)
            if row is None:
                raise KeyError(f"unknown provider setting {setting.capability}")
            check_version(row, setting)
            row.provider_id = setting.provider_id
            row.config_sealed = self._sealer.seal(setting.config)
            row.updated_by = setting.updated_by
            row.updated_at = setting.updated_at
            session.flush()

    def get(self, capability: str) -> ProviderSetting | None:
        row = t.ProviderSettingRecord
        with sync_session_scope(self._session_factory) as session:
            record = (
                session.execute(select(row).where(row.capability == capability)).scalars().first()
            )
            return None if record is None else self._to_model(record)

    def list_all(self) -> list[ProviderSetting]:
        row = t.ProviderSettingRecord
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(row).order_by(row.capability)).scalars().all()
            return [self._to_model(item) for item in rows]

    def delete(self, capability: str) -> bool:
        row = t.ProviderSettingRecord
        with sync_session_scope(self._session_factory) as session:
            record = (
                session.execute(select(row).where(row.capability == capability)).scalars().first()
            )
            if record is None:
                return False
            session.delete(record)
            session.flush()
            return True

    def _to_model(self, record: t.ProviderSettingRecord) -> ProviderSetting:
        return ProviderSetting(
            id=record.id,
            capability=record.capability,
            provider_id=record.provider_id,
            config=self._sealer.open(record.config_sealed),
            updated_by=record.updated_by,
            updated_at=_aware(record.updated_at),
            version=record.version,
        )


def _aware(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment
