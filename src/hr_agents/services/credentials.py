"""Credential registry service: verified data behind an explicit gate.

The rule is opt-in and conservatively one-way. With no usable registry, claims
are returned untouched — an install that has not imported anything keeps the
scoring it had. With at least one usable registry, a claim that matches becomes
the registry's answer (including expired/failed), and a claim that matches
nothing becomes `unverified`, because the operator has told the system which
issuer records are trusted.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from hr_agents.errors import DomainCode, DomainError
from hr_agents.identity import ActorRef
from hr_agents.logging import get_logger
from hr_agents.models import (
    CertificationClaim,
    CredentialEntry,
    CredentialRegistry,
    VerificationStatus,
    business_today,
    utc_now,
)
from hr_agents.services.audit import AuditChain

logger = get_logger(__name__)

_REGISTRY_ANSWERABLE = {
    VerificationStatus.VERIFIED,
    VerificationStatus.FAILED,
    VerificationStatus.EXPIRED,
}


class CredentialRegistryError(DomainError, RuntimeError):
    """Raised for invalid credential registry operations."""


class CredentialRegistryStore:
    """In-memory registries; the database adapter overrides the primitives."""

    def __init__(self) -> None:
        self._items: dict[UUID, CredentialRegistry] = {}

    def add(self, registry: CredentialRegistry) -> None:
        self._items[registry.id] = registry

    def save(self, registry: CredentialRegistry) -> None:
        if registry.id not in self._items:
            raise KeyError(f"unknown credential registry {registry.id}")
        self._items[registry.id] = registry

    def get(self, registry_id: UUID) -> CredentialRegistry | None:
        return self._items.get(registry_id)

    def list_all(self) -> list[CredentialRegistry]:
        return sorted(self._items.values(), key=lambda item: (item.issuer.casefold(), item.name))

    def delete(self, registry_id: UUID) -> bool:
        return self._items.pop(registry_id, None) is not None


class CredentialRegistryService:
    """Create, verify and apply operator-owned credential registries."""

    def __init__(self, store: CredentialRegistryStore, *, audit: AuditChain | None = None) -> None:
        self._store = store
        self._audit = audit or AuditChain()

    def create(self, *, name: str, issuer: str, actor: ActorRef) -> CredentialRegistry:
        for existing in self._store.list_all():
            if (
                existing.issuer.casefold() == issuer.casefold()
                and existing.name.casefold() == name.casefold()
            ):
                raise CredentialRegistryError(
                    f"a registry named {name!r} for {issuer!r} already exists"
                )
        registry = CredentialRegistry(name=name, issuer=issuer)
        self._store.add(registry)
        self._record(registry, action="credential_registry.created", actor=actor)
        return registry

    def set_entries(
        self,
        registry_id: UUID,
        *,
        entries: list[CredentialEntry],
        actor: ActorRef,
    ) -> CredentialRegistry:
        """Replace entries. Editing invalidates verification, as rate tables do."""
        registry = self.require(registry_id)
        updated = registry.model_copy(
            update={
                "entries": entries,
                "verified": False,
                "verified_by": None,
                "verified_at": None,
                "updated_at": utc_now(),
            }
        )
        self._store.save(updated)
        self._record(
            updated,
            action="credential_registry.entries_updated",
            actor=actor,
            extra={"entry_count": len(entries)},
        )
        return updated

    def verify(self, registry_id: UUID, *, actor: ActorRef, source_note: str) -> CredentialRegistry:
        """Certify the imported rows, with a named human and a source."""
        registry = self.require(registry_id)
        actor.require_human("verifying a credential registry", CredentialRegistryError)
        if not registry.entries:
            raise CredentialRegistryError(
                "a registry needs at least one entry before it can be verified",
                code=DomainCode.VALIDATION_FAILED,
                status=422,
            )
        verified = registry.mark_verified(verified_by=actor.actor_id, source_note=source_note)
        self._store.save(verified)
        self._record(verified, action="credential_registry.verified", actor=actor)
        return verified

    def require(self, registry_id: UUID) -> CredentialRegistry:
        registry = self._store.get(registry_id)
        if registry is None:
            raise CredentialRegistryError(
                f"unknown credential registry {registry_id}",
                code=DomainCode.UNKNOWN_RECORD,
                status=404,
            )
        return registry

    def get(self, registry_id: UUID) -> CredentialRegistry | None:
        return self._store.get(registry_id)

    def delete(self, registry_id: UUID, *, actor: ActorRef) -> bool:
        """Remove a registry and its rows, on the record.

        A mistaken import should be removable rather than left as an inert row
        named after the wrong issuer. Deleting is audited like every other
        accepted change to the set of facts the scorer trusts.
        """
        registry = self._store.get(registry_id)
        if registry is None:
            return False
        actor.require_human("deleting a credential registry", CredentialRegistryError)
        removed = self._store.delete(registry_id)
        if removed:
            self._audit.append(
                actor=actor.audit_actor(),
                action="credential_registry.deleted",
                subject_type="credential_registry",
                subject_id=str(registry_id),
                payload={"name": registry.name, "issuer": registry.issuer},
            )
            logger.info(
                "credential_registry.deleted",
                registry_id=str(registry_id),
                actor=actor.actor_id,
            )
        return removed

    def list_all(self) -> list[CredentialRegistry]:
        return self._store.list_all()

    def unverified(self) -> list[CredentialRegistry]:
        return [item for item in self._store.list_all() if not item.usable]

    def has_usable(self) -> bool:
        return any(item.usable for item in self._store.list_all())

    def lookup(
        self, *, issuer: str | None, name: str, as_of: date | None = None
    ) -> VerificationStatus | None:
        """The registry's answer for a claim, or None when nothing matches.

        Two usable registries that disagree produce None: the system refuses to
        pick a winner, and the claim stays unverified.
        """
        if issuer is None:
            return None
        today = as_of or business_today()
        wanted_issuer = issuer.strip().casefold()
        wanted_name = name.strip().casefold()
        answers: set[VerificationStatus] = set()
        for registry in self._store.list_all():
            if not registry.usable or registry.issuer.strip().casefold() != wanted_issuer:
                continue
            for entry in registry.entries:
                if entry.name.strip().casefold() != wanted_name:
                    continue
                status = entry.effective_status(as_of=today)
                if status in _REGISTRY_ANSWERABLE:
                    answers.add(status)
        if len(answers) == 1:
            return next(iter(answers))
        return None

    def verify_claims(
        self, claims: Iterable[CertificationClaim], *, as_of: date | None = None
    ) -> list[CertificationClaim]:
        """Apply the registries to a profile's claims.

        With no usable registry this is the identity function, so an install
        that has imported nothing keeps its existing scores. Once something is
        usable, an unmatched claim is `unverified` rather than silently trusted.
        """
        claims = list(claims)
        if not self.has_usable():
            return claims
        updated: list[CertificationClaim] = []
        for claim in claims:
            status = self.lookup(issuer=claim.issuer, name=claim.name, as_of=as_of)
            updated.append(
                claim.model_copy(
                    update={
                        "status": status if status is not None else VerificationStatus.UNVERIFIED
                    }
                )
            )
        return updated

    def _record(
        self,
        registry: CredentialRegistry,
        *,
        action: str,
        actor: ActorRef,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "name": registry.name,
            "issuer": registry.issuer,
            "entry_count": len(registry.entries),
        }
        payload.update(extra or {})
        self._audit.append(
            actor=actor.audit_actor(),
            action=action,
            subject_type="credential_registry",
            subject_id=str(registry.id),
            payload=payload,
        )
        logger.info(
            action.replace(".", "_"),
            registry_id=str(registry.id),
            issuer=registry.issuer,
            actor=actor.actor_id,
        )
