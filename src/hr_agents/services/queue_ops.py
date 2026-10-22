"""Operator actions on the work queue: the stale-lease reaper and requeueing.

Two distinct semantics, deliberately kept apart:

- the reaper is automatic. A lease that expired because a worker died or
  wedged is returned to pending, and the attempt count goes up, so a message
  that keeps killing its handler still exhausts its retry budget and
  dead-letters instead of looping forever;
- requeueing a dead letter is a human decision: the attempt budget resets,
  because a person judged the cause fixed, and the audit chain records who
  decided and why.
"""

from __future__ import annotations

from collections.abc import Iterable

from hr_agents.errors import DomainError
from hr_agents.identity import ActorRef
from hr_agents.logging import get_logger
from hr_agents.providers.queue import QueueBackend
from hr_agents.services.audit import AuditChain

EXPIRED_LEASE_GRACE_SECONDS = 300.0
"""Long enough that a slow handler is not re-run, short enough that a wedged
worker is visible within a scheduler tick or two (the worker lease is 120s)."""


logger = get_logger(__name__)


class QueueOpsError(DomainError, RuntimeError):
    """Raised for invalid queue operations."""


async def reap_expired_leases(
    queue: QueueBackend,
    topics: Iterable[str],
    *,
    grace_seconds: float = EXPIRED_LEASE_GRACE_SECONDS,
) -> int:
    """Return stale leases to pending across ``topics``; returns how many."""
    requeued = 0
    for topic in topics:
        requeued += await queue.requeue_expired(topic, grace_seconds=grace_seconds)
    return requeued


async def requeue_dead_letter(
    queue: QueueBackend,
    *,
    message_id: str,
    reason: str,
    actor: ActorRef,
    audit: AuditChain,
) -> bool:
    """Requeue one dead letter as a named human act; audited with the reason."""
    actor.require_human("requeue a dead-lettered message", QueueOpsError)
    if not reason.strip():
        raise QueueOpsError("requeueing a dead letter requires a reason")
    requeued = await queue.requeue_dead(message_id)
    if requeued:
        logger.info(
            "ops.dead_letter_requeued",
            message_id=message_id,
            actor=actor.actor_id,
            reason=reason.strip(),
        )
        audit.append(
            actor=actor.audit_actor(),
            action="ops.dead_letter_requeued",
            subject_type="queue_message",
            subject_id=message_id,
            payload={"reason": reason.strip()},
        )
    return requeued
