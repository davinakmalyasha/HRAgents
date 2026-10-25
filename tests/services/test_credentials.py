"""Credential registries: the verified gate and what it does to scoring claims."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from hr_agents.errors import DomainCode
from hr_agents.identity import ActorRef
from hr_agents.models import (
    CertificationClaim,
    CredentialEntry,
    CredentialRegistry,
    VerificationStatus,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.credentials import (
    CredentialRegistryError,
    CredentialRegistryService,
    CredentialRegistryStore,
)

HUMAN = ActorRef.legacy("hr-admin")
TODAY = date(2026, 10, 24)


def service() -> CredentialRegistryService:
    return CredentialRegistryService(CredentialRegistryStore(), audit=AuditChain())


def usable(
    registry_service: CredentialRegistryService,
    *,
    issuer: str = "AWS",
    name: str = "AWS certifications",
    entries: list[CredentialEntry] | None = None,
) -> CredentialRegistry:
    registry = registry_service.create(name=name, issuer=issuer, actor=HUMAN)
    registry_service.set_entries(
        registry.id,
        entries=entries or [CredentialEntry(name="AWS Solutions Architect")],
        actor=HUMAN,
    )
    return registry_service.verify(registry.id, actor=HUMAN, source_note="issuer page")


def claim(name: str = "AWS Solutions Architect", issuer: str | None = "AWS") -> CertificationClaim:
    return CertificationClaim(name=name, issuer=issuer)


def test_with_no_usable_registry_claims_are_untouched() -> None:
    registry_service = service()
    draft = registry_service.create(name="AWS", issuer="AWS", actor=HUMAN)
    registry_service.set_entries(
        draft.id, entries=[CredentialEntry(name="AWS Solutions Architect")], actor=HUMAN
    )
    claims = [claim()]

    assert registry_service.has_usable() is False
    assert registry_service.verify_claims(claims) == claims


def test_a_verified_registry_answers_matched_and_unmatched_claims() -> None:
    registry_service = service()
    usable(registry_service)

    claims = registry_service.verify_claims(
        [
            claim(),
            claim(name="A Coursera badge", issuer="Coursera"),
            claim(name="AWS Solutions Architect", issuer=None),
        ]
    )

    assert claims[0].status is VerificationStatus.VERIFIED
    assert claims[1].status is VerificationStatus.UNVERIFIED
    assert claims[2].status is VerificationStatus.UNVERIFIED


def test_matching_is_case_insensitive_and_status_survives() -> None:
    registry_service = service()
    usable(
        registry_service,
        entries=[CredentialEntry(name="AWS Solutions Architect", status=VerificationStatus.FAILED)],
    )

    assert registry_service.lookup(issuer=" aws ", name="aws solutions architect") is (
        VerificationStatus.FAILED
    )


def test_an_expired_entry_answers_expired() -> None:
    registry_service = service()
    usable(
        registry_service,
        entries=[CredentialEntry(name="AWS Solutions Architect", expires_on=date(2025, 1, 1))],
    )

    assert (
        registry_service.lookup(issuer="AWS", name="AWS Solutions Architect", as_of=TODAY)
        is VerificationStatus.EXPIRED
    )


def test_conflicting_registries_refuse_to_pick_a_winner() -> None:
    registry_service = service()
    usable(registry_service, name="AWS professional", entries=[CredentialEntry(name="CKA")])
    usable(
        registry_service,
        name="AWS associate",
        entries=[CredentialEntry(name="CKA", status=VerificationStatus.FAILED)],
    )

    assert registry_service.lookup(issuer="AWS", name="CKA") is None


def test_verification_needs_a_named_human_and_at_least_one_entry() -> None:
    registry_service = service()
    registry = registry_service.create(name="AWS", issuer="AWS", actor=HUMAN)

    with pytest.raises(CredentialRegistryError) as empty:
        registry_service.verify(registry.id, actor=HUMAN, source_note="issuer page")
    assert empty.value.code is DomainCode.VALIDATION_FAILED

    registry_service.set_entries(registry.id, entries=[CredentialEntry(name="CKA")], actor=HUMAN)
    with pytest.raises(CredentialRegistryError) as agent:
        registry_service.verify(
            registry.id, actor=ActorRef.agent("tool:hr_bot"), source_note="issuer page"
        )
    assert agent.value.code is DomainCode.NAMED_HUMAN_REQUIRED


def test_editing_entries_invalidates_verification() -> None:
    registry_service = service()
    registry = usable(registry_service)
    assert registry.usable is True

    edited = registry_service.set_entries(
        registry.id,
        entries=[CredentialEntry(name="AWS Solutions Architect"), CredentialEntry(name="CKA")],
        actor=HUMAN,
    )

    assert edited.usable is False
    assert edited.verified_by is None
    assert registry_service._audit.entries[-1].action == "credential_registry.entries_updated"


def test_an_unknown_registry_is_a_404() -> None:
    with pytest.raises(CredentialRegistryError) as excinfo:
        service().require(uuid4())
    assert excinfo.value.code is DomainCode.UNKNOWN_RECORD


def test_deleting_a_registry_removes_it_and_is_audited() -> None:
    registry_service = service()
    registry = usable(registry_service)

    assert registry_service.delete(registry.id, actor=HUMAN) is True
    assert registry_service.list_all() == []
    assert registry_service._audit.entries[-1].action == "credential_registry.deleted"
    assert registry_service.delete(registry.id, actor=HUMAN) is False


def test_an_agent_cannot_delete_a_registry() -> None:
    registry_service = service()
    registry = usable(registry_service)

    with pytest.raises(CredentialRegistryError) as excinfo:
        registry_service.delete(registry.id, actor=ActorRef.agent("tool:hr_bot"))
    assert excinfo.value.code is DomainCode.NAMED_HUMAN_REQUIRED
