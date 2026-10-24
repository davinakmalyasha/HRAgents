"""Postgres-backed credential registries; verification stays in the service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.mapping import add_model, get_model, list_models, save_model
from hr_agents.models import CredentialRegistry
from hr_agents.services.credentials import CredentialRegistryStore


class DbCredentialRegistryStore(CredentialRegistryStore):
    """Registries in ``credential_registries``."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add(self, registry: CredentialRegistry) -> None:
        add_model(self._session_factory, registry, t.CredentialRegistryRecord)

    def save(self, registry: CredentialRegistry) -> None:
        save_model(self._session_factory, registry, t.CredentialRegistryRecord)

    def get(self, registry_id: UUID) -> CredentialRegistry | None:
        return get_model(
            self._session_factory,
            CredentialRegistry,
            t.CredentialRegistryRecord,
            registry_id,
        )

    def list_all(self) -> list[CredentialRegistry]:
        records = list_models(self._session_factory, CredentialRegistry, t.CredentialRegistryRecord)
        return sorted(records, key=lambda item: (item.issuer.casefold(), item.name))
