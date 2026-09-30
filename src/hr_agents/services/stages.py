"""Manual application stage moves — the board's designed transition policy.

A drag on the pipeline board is only a request: this service validates it
against ``STAGE_TRANSITIONS`` (see ``docs/architecture/board-transitions.md``),
requires a named human and a reason, refuses anything that would bypass the
HITL gates, and writes one ``application.stage_changed`` audit entry per move.

Database adapters override the store's persistence primitives; the policy lives
here and is storage-agnostic.
"""

from __future__ import annotations

from uuid import UUID

from hr_agents.identity import ActorRef
from hr_agents.services.audit import AuditChain
from hr_agents.services.ingestion import (
    ApplicationRecord,
    ApplicationStatus,
    ApplicationStore,
)

AGENT_ACTOR_PREFIX = "agent:"

# The only status pairs a named human may move directly (docs: board-transitions).
STAGE_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.QUEUED: frozenset(),
    ApplicationStatus.PROCESSING: frozenset(),
    ApplicationStatus.EVALUATED: frozenset({ApplicationStatus.GATED, ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.GATED: frozenset({ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.SCHEDULED: frozenset({ApplicationStatus.GATED, ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.REJECTED: frozenset({ApplicationStatus.GATED}),
    ApplicationStatus.WITHDRAWN: frozenset({ApplicationStatus.GATED}),
}

_SYSTEM_OWNED = frozenset({ApplicationStatus.QUEUED, ApplicationStatus.PROCESSING})
_SYSTEM_TARGETS = _SYSTEM_OWNED | {ApplicationStatus.EVALUATED}


class StageTransitionError(RuntimeError):
    """Invalid manual stage move; the router maps messages to HTTP statuses."""


class StageTransitionService:
    """Gate every manual board move behind the designed transition table."""

    def __init__(self, *, store: ApplicationStore, audit: AuditChain | None = None) -> None:
        self._store = store
        self._audit = audit or AuditChain()

    def move(
        self,
        application_id: UUID,
        *,
        target: ApplicationStatus,
        actor: ActorRef,
        reason: str,
    ) -> ApplicationRecord:
        record = self._store.get(application_id)
        if record is None:
            raise StageTransitionError(f"application {application_id} not found")

        actor.require_human("a stage move", StageTransitionError)
        if not reason.strip():
            raise StageTransitionError("a reason is required for a stage move")

        source = record.status
        if source is target:
            raise StageTransitionError(f"application is already {target.value}")
        if source in _SYSTEM_OWNED:
            raise StageTransitionError(
                f"{source.value} is set by the worker; extraction and scoring are not manual moves"
            )
        if target in _SYSTEM_TARGETS:
            raise StageTransitionError(
                f"{target.value} is a system-owned state and cannot be set manually"
            )
        if target is ApplicationStatus.REJECTED:
            raise StageTransitionError(
                "record a rejection sign-off first (review queue override); the board follows"
            )
        if target is ApplicationStatus.SCHEDULED:
            raise StageTransitionError(
                "scheduling is gated: create a proposal or record an approved override"
            )
        if target not in STAGE_TRANSITIONS[source]:
            raise StageTransitionError(
                f"cannot move an application from {source.value} to {target.value}"
            )

        record.status = target
        record.note(f"application.stage.{target.value}")
        self._store.save(record)
        self._audit.append(
            actor=actor.audit_actor(),
            action="application.stage_changed",
            subject_type="application",
            subject_id=str(application_id),
            payload={"from": source.value, "to": target.value, "reason": reason.strip()},
        )
        return record
