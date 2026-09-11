from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hr_agents.models import (
    ActorType,
    AuditActor,
    AuditEntry,
    InterviewerAvailability,
    PolicyDecision,
    PolicyEvaluation,
    SchedulingPayload,
    TimeSlot,
)


def slot(start_hour: int, end_hour: int) -> TimeSlot:
    return TimeSlot(
        start_utc=datetime(2026, 9, 15, start_hour, tzinfo=UTC),
        end_utc=datetime(2026, 9, 15, end_hour, tzinfo=UTC),
    )


def test_time_slot_ordering_enforced() -> None:
    with pytest.raises(ValidationError):
        slot(10, 9)


def test_scheduling_payload_requires_interviewer_and_slots() -> None:
    policy = PolicyEvaluation(decision=PolicyDecision.AUTO_SCHEDULE)
    with pytest.raises(ValidationError):
        SchedulingPayload(
            candidate_id=uuid4(),
            job_id=uuid4(),
            interviewer_ids=[],
            slots=[slot(9, 10)],
            policy=policy,
        )
    with pytest.raises(ValidationError):
        SchedulingPayload(
            candidate_id=uuid4(),
            job_id=uuid4(),
            interviewer_ids=[uuid4()],
            slots=[],
            policy=policy,
        )


def test_interviewer_slot_count() -> None:
    availability = InterviewerAvailability(
        interviewer_id=uuid4(), slots=[slot(9, 10), slot(11, 12)]
    )
    assert availability.slot_count == 2


def test_audit_hash_determinism_and_tamper_detection() -> None:
    actor = AuditActor(actor_type=ActorType.SYSTEM, actor_id="policy-engine")
    created = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    digest = AuditEntry.compute_hash(
        prev_hash=None,
        actor=actor,
        action="evaluation.scored",
        subject_type="candidate",
        subject_id="candidate-1",
        payload={"s_tech": 0.91},
        created_at=created,
    )
    assert len(digest) == 64

    entry = AuditEntry(
        seq=0,
        created_at=created,
        actor=actor,
        action="evaluation.scored",
        subject_type="candidate",
        subject_id="candidate-1",
        payload={"s_tech": 0.91},
        prev_hash=None,
        entry_hash=digest,
    )
    assert entry.verify() is True

    tampered = entry.model_copy(update={"payload": {"s_tech": 0.99}})
    assert tampered.verify() is False


def test_audit_hash_chain_links_entries() -> None:
    actor = AuditActor(actor_type=ActorType.HUMAN, actor_id="reviewer-7", display_name="Lead")
    created = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    first_hash = AuditEntry.compute_hash(
        prev_hash=None,
        actor=actor,
        action="rejection.signed_off",
        subject_type="evaluation",
        subject_id="eval-1",
        payload={"reason_code": "below_bar"},
        created_at=created,
    )
    second_hash = AuditEntry.compute_hash(
        prev_hash=first_hash,
        actor=actor,
        action="notification.sent",
        subject_type="candidate",
        subject_id="candidate-1",
        payload={"channel": "email"},
        created_at=created,
    )

    assert first_hash != second_hash
    assert second_hash == AuditEntry.compute_hash(
        prev_hash=first_hash,
        actor=actor,
        action="notification.sent",
        subject_type="candidate",
        subject_id="candidate-1",
        payload={"channel": "email"},
        created_at=created,
    )
