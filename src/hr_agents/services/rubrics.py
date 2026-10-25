"""Versioned scoring rubrics: operator data behind a verified gate.

The templates in ``services.dimensions`` ship with the product, but an operator
must be able to tune what counts as evidence for their own roles without
editing code. A version is drafted as a full template, verified by a named human
with a source note, and only then activated; the active verified version scores
new evaluations while the code template remains the fallback for every family
nobody has touched. The evaluation's ``RubricSnapshot`` cites the digest, and the
stored payload is what makes an old score reproducible.
"""

from __future__ import annotations

from uuid import UUID

from hr_agents.errors import DomainCode, DomainError
from hr_agents.identity import ActorRef
from hr_agents.models import JobFamily, RubricSnapshot, RubricVersion, utc_now
from hr_agents.services.audit import AuditChain
from hr_agents.services.audit_events import record_audit
from hr_agents.services.dimensions import (
    DimensionTemplate,
    canonical_payload,
    rubric_digest,
    snapshot_for,
    template_for,
)


class RubricError(DomainError, RuntimeError):
    """Raised for invalid rubric operations."""


class RubricStore:
    """In-memory rubric versions; the database adapter overrides the primitives."""

    def __init__(self) -> None:
        self._items: dict[UUID, RubricVersion] = {}

    def add(self, record: RubricVersion) -> None:
        self._items[record.id] = record

    def save(self, record: RubricVersion) -> None:
        if record.id not in self._items:
            raise KeyError(f"unknown rubric version {record.id}")
        self._items[record.id] = record

    def get(self, version_id: UUID) -> RubricVersion | None:
        return self._items.get(version_id)

    def list_all(self) -> list[RubricVersion]:
        return sorted(self._items.values(), key=lambda item: (item.family.value, item.revision))

    def list_for(self, family: JobFamily) -> list[RubricVersion]:
        return [item for item in self.list_all() if item.family is family]

    def active_for(self, family: JobFamily) -> RubricVersion | None:
        for item in self._items.values():
            if item.family is family and item.active:
                return item
        return None


class RubricRegistry:
    """Draft, verify and activate rubric versions; resolve the one that scores."""

    def __init__(
        self, store: RubricStore | None = None, *, audit: AuditChain | None = None
    ) -> None:
        self._store = store or RubricStore()
        self._audit = audit or AuditChain()

    def versions(self, family: JobFamily) -> list[RubricVersion]:
        return self._store.list_for(family)

    def get(self, version_id: UUID) -> RubricVersion:
        record = self._store.get(version_id)
        if record is None:
            raise RubricError(
                f"unknown rubric version {version_id}",
                code=DomainCode.UNKNOWN_RECORD,
                status=404,
            )
        return record

    def active_version(self, family: JobFamily) -> RubricVersion | None:
        return self._store.active_for(family)

    def resolve(self, family: JobFamily) -> tuple[DimensionTemplate, RubricSnapshot]:
        """The template that scores this family, and the provenance to attach.

        With no activated version the code template is the rubric, so every
        deployment scores exactly as it did before an operator acts. A stored
        payload whose digest does not match its content is refused rather than
        scored: it is either a manual edit or a bug, and neither is a rubric.
        """
        record = self.active_version(family)
        if record is None:
            return template_for(family), snapshot_for(family)
        template = DimensionTemplate.model_validate(record.template)
        if template.family is not family:
            raise RubricError(
                f"stored rubric {record.id} is for {template.family.value}, "
                f"but {family.value} is active"
            )
        if rubric_digest(template) != record.digest:
            raise RubricError(
                f"stored rubric {record.id} does not match its digest; refusing to score",
                code=DomainCode.STATE_CONFLICT,
                status=409,
            )
        return template, RubricSnapshot(
            family=family,
            digest=record.digest,
            template=canonical_payload(template),
        )

    def create_version(
        self,
        *,
        family: JobFamily,
        template: DimensionTemplate,
        actor: ActorRef,
        note: str = "",
    ) -> RubricVersion:
        """Draft a new version. The next number is one past the family's latest."""
        actor.require_human("draft a scoring rubric", RubricError)
        if template.family is not family:
            raise RubricError(
                f"template family {template.family.value} does not match {family.value}"
            )
        digest = rubric_digest(template)
        existing = self._store.list_for(family)
        if any(item.digest == digest for item in existing):
            raise RubricError("an identical rubric is already stored for this family")
        record = RubricVersion(
            family=family,
            revision=max((item.revision for item in existing), default=0) + 1,
            digest=digest,
            template=canonical_payload(template),
            created_by=actor.actor_id,
        )
        self._store.add(record)
        self._record(record, action="rubric.version_created", actor=actor, note=note)
        return record

    def verify(self, version_id: UUID, *, actor: ActorRef, source_note: str) -> RubricVersion:
        """Certify a version. A named human records why the content is trusted."""
        actor.require_human("verify a scoring rubric", RubricError, subject=f"rubric {version_id}")
        if not source_note.strip():
            raise RubricError("verification requires a source note")
        record = self.get(version_id)
        if record.verified_by is not None:
            raise RubricError(f"rubric revision {record.revision} is already verified")
        updated = record.model_copy(
            update={
                "verified_by": actor.actor_id,
                "verified_at": utc_now(),
                "verified_note": source_note.strip(),
            }
        )
        self._store.save(updated)
        self._record(updated, action="rubric.version_verified", actor=actor, note=source_note)
        return updated

    def activate(self, version_id: UUID, *, actor: ActorRef) -> RubricVersion:
        """Make a verified version the one new evaluations are scored by."""
        actor.require_human(
            "activate a scoring rubric", RubricError, subject=f"rubric {version_id}"
        )
        record = self.get(version_id)
        if record.verified_by is None:
            raise RubricError("an unverified rubric cannot be activated")
        for other in self._store.list_for(record.family):
            if other.active and other.id != record.id:
                self._store.save(other.model_copy(update={"active": False}))
        updated = record.model_copy(update={"active": True})
        self._store.save(updated)
        self._record(updated, action="rubric.version_activated", actor=actor)
        return updated

    def _record(
        self,
        record: RubricVersion,
        *,
        action: str,
        actor: ActorRef,
        note: str = "",
    ) -> None:
        record_audit(
            self._audit,
            actor=actor,
            action=action,
            subject_type="rubric_version",
            subject_id=str(record.id),
            payload={
                "family": record.family.value,
                "revision": record.revision,
                "digest": record.digest,
                "note": note.strip(),
            },
        )
