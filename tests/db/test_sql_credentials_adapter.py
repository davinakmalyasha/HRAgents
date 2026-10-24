"""Credential registry adapter: round-trip, entries, and the version guard."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.credentials import DbCredentialRegistryStore
from hr_agents.errors import StaleRecordError
from hr_agents.identity import ActorRef
from hr_agents.models import CredentialEntry, VerificationStatus
from hr_agents.services.credentials import CredentialRegistryService

HUMAN = ActorRef.legacy("hr-admin")


def test_a_registry_round_trips_with_entries_and_verification(
    factory: sessionmaker[Session],
) -> None:
    service = CredentialRegistryService(DbCredentialRegistryStore(factory))
    registry = service.create(name="AWS certifications", issuer="AWS", actor=HUMAN)
    service.set_entries(
        registry.id,
        entries=[
            CredentialEntry(
                name="AWS Solutions Architect",
                credential_id="AWS-123",
                expires_on=date(2027, 1, 1),
                notes="verified on the issuer page",
            )
        ],
        actor=HUMAN,
    )
    service.verify(registry.id, actor=HUMAN, source_note="issuer page 2026-10-24")

    fresh = CredentialRegistryService(DbCredentialRegistryStore(factory))
    stored = fresh.require(registry.id)

    assert stored.usable is True
    assert stored.verified_by == "hr-admin"
    assert stored.entries[0].expires_on == date(2027, 1, 1)
    status = fresh.lookup(issuer="AWS", name="AWS Solutions Architect")
    assert status is VerificationStatus.VERIFIED


def test_the_adapter_refuses_a_stale_write(factory: sessionmaker[Session]) -> None:
    store = DbCredentialRegistryStore(factory)
    service = CredentialRegistryService(store)
    registry = service.create(name="AWS", issuer="AWS", actor=HUMAN)
    service.set_entries(registry.id, entries=[CredentialEntry(name="CKA")], actor=HUMAN)
    first = store.get(registry.id)
    second = store.get(registry.id)
    assert first is not None and second is not None

    store.save(first.model_copy(update={"name": "AWS (renamed)"}))

    with pytest.raises(StaleRecordError):
        store.save(second)
