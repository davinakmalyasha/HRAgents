"""Operator queue actions: the reaper and the audited dead-letter requeue."""

from __future__ import annotations

import pytest

from hr_agents.identity import ActorRef
from hr_agents.providers.queue import MemoryQueueBackend
from hr_agents.services.audit import AuditChain
from hr_agents.services.queue_ops import (
    QueueOpsError,
    reap_expired_leases,
    requeue_dead_letter,
)

TOPIC = "evaluation.evaluate"


async def test_reaping_returns_stale_leases_across_topics() -> None:
    queue = MemoryQueueBackend()
    await queue.publish(TOPIC, {"application_id": "one"})
    await queue.publish("other.topic", {"application_id": "two"})
    await queue.claim(TOPIC, lease_seconds=0.01)
    await queue.claim("other.topic", lease_seconds=0.01)

    import asyncio

    await asyncio.sleep(0.05)

    requeued = await reap_expired_leases(queue, (TOPIC, "other.topic"), grace_seconds=0)

    assert requeued == 2
    assert (await queue.stats(TOPIC)).pending == 1
    assert (await queue.stats("other.topic")).pending == 1


async def test_requeueing_a_dead_letter_is_audited_with_the_reason() -> None:
    queue = MemoryQueueBackend()
    audit = AuditChain()
    message_id = await queue.publish(TOPIC, {"application_id": "one"})
    await queue.claim(TOPIC)
    await queue.fail(message_id, "provider timeout")

    requeued = await requeue_dead_letter(
        queue,
        message_id=message_id,
        reason="provider recovered; model config fixed",
        actor=ActorRef.legacy("hr-admin"),
        audit=audit,
    )

    assert requeued is True
    (entry,) = audit.entries
    assert entry.action == "ops.dead_letter_requeued"
    assert entry.subject_id == message_id
    assert entry.payload["reason"] == "provider recovered; model config fixed"

    # A second attempt finds nothing, and nothing reaches the audit chain.
    assert (
        await requeue_dead_letter(
            queue,
            message_id=message_id,
            reason="again",
            actor=ActorRef.legacy("hr-admin"),
            audit=audit,
        )
        is False
    )
    assert len(audit.entries) == 1


async def test_agents_cannot_requeue_dead_letters() -> None:
    queue = MemoryQueueBackend()
    message_id = await queue.publish(TOPIC, {"application_id": "one"})
    await queue.claim(TOPIC)
    await queue.fail(message_id, "boom")

    with pytest.raises(QueueOpsError, match="named human"):
        await requeue_dead_letter(
            queue,
            message_id=message_id,
            reason="let me retry",
            actor=ActorRef.agent("policy_assistant"),
            audit=AuditChain(),
        )


async def test_a_requeue_requires_a_reason() -> None:
    queue = MemoryQueueBackend()
    message_id = await queue.publish(TOPIC, {"application_id": "one"})
    await queue.claim(TOPIC)
    await queue.fail(message_id, "boom")

    with pytest.raises(QueueOpsError, match="requires a reason"):
        await requeue_dead_letter(
            queue,
            message_id=message_id,
            reason="   ",
            actor=ActorRef.legacy("hr-admin"),
            audit=AuditChain(),
        )
