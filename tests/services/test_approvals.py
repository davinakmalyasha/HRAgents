from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from hr_agents.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    Urgency,
)
from hr_agents.services import ApprovalEngine, ApprovalError
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import ApprovalStore


@pytest.fixture
def engine() -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=AuditChain())


def create_request(
    engine: ApprovalEngine,
    *,
    subject: ApprovalSubject = ApprovalSubject.LEAVE_REQUEST,
    subject_id: str = "leave-1",
    title: str = "Annual leave 3 days",
    assignee_role: ApproverRole = ApproverRole.MANAGER,
    requested_by: str = "sari@example.com",
    urgency: Urgency = Urgency.NORMAL,
    requested_by_agent: bool = False,
    max_escalations: int = 2,
) -> ApprovalRequest:
    return engine.create(
        subject=subject,
        subject_id=subject_id,
        title=title,
        assignee_role=assignee_role,
        requested_by=requested_by,
        urgency=urgency,
        requested_by_agent=requested_by_agent,
        max_escalations=max_escalations,
    )


def test_create_sets_sla_and_audits(engine: ApprovalEngine) -> None:
    request = create_request(engine, urgency=Urgency.HIGH)

    assert request.status is ApprovalStatus.PENDING
    assert request.sla_deadline is not None
    assert request.requested_by_agent is False
    assert engine._audit.verify() == -1
    assert engine._audit.entries[-1].action == "approval.created"


def test_agent_requested_is_labeled(engine: ApprovalEngine) -> None:
    request = create_request(engine, requested_by="screening_coordinator", requested_by_agent=True)
    assert request.requested_by_agent is True
    assert request.requested_by.startswith("agent:")


def test_approve_flow(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    decision = engine.decide(request.id, decided_by="manager-budi", approve=True, reason="ok")

    assert decision.action == "approved"
    assert decision.request.status is ApprovalStatus.APPROVED
    assert decision.request.decided_by == "manager-budi"
    assert engine._audit.entries[-1].action == "approval.approved"


def test_reject_flow(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    decision = engine.decide(
        request.id, decided_by="manager-budi", approve=False, reason="busy week"
    )
    assert decision.request.status is ApprovalStatus.REJECTED


def test_agents_cannot_decide(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    with pytest.raises(ApprovalError, match="named human"):
        engine.decide(request.id, decided_by="agent:policy_assistant", approve=True)


def test_double_decide_rejected(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    engine.decide(request.id, decided_by="manager", approve=True)
    with pytest.raises(ApprovalError, match="cannot decide"):
        engine.decide(request.id, decided_by="manager", approve=False)


def test_withdraw(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    withdrawn = engine.withdraw(request.id, by="sari@example.com", reason="changed plans")
    assert withdrawn.status is ApprovalStatus.WITHDRAWN


def test_unknown_request_raises(engine: ApprovalEngine) -> None:
    with pytest.raises(ApprovalError, match="unknown approval"):
        engine.decide(uuid4(), decided_by="someone", approve=True)


# --- SLA escalation ----------------------------------------------------------


def test_escalation_boosts_urgency_and_counts(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    past = datetime.now(UTC) + timedelta(hours=72)
    changed = engine.escalate_overdue(now=past)

    assert len(changed) == 1
    assert changed[0].status is ApprovalStatus.ESCALATED
    assert changed[0].escalation_count == 1
    assert request.id in {item.id for item in changed}


def test_escalation_respects_max_and_expires(engine: ApprovalEngine) -> None:
    request = create_request(engine, max_escalations=1)
    past = datetime.now(UTC) + timedelta(hours=72)

    engine.escalate_overdue(now=past)  # escalates once
    expired = engine.escalate_overdue(now=past)  # cap reached -> expire

    assert expired
    stored = engine._store.get(request.id)
    assert stored is not None
    assert stored.status is ApprovalStatus.EXPIRED


def test_not_overdue_stays_pending(engine: ApprovalEngine) -> None:
    create_request(engine)
    assert engine.escalate_overdue() == []


def test_requeue_escalated(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    engine.escalate_overdue(now=datetime.now(UTC) + timedelta(hours=72))
    requeued = engine.requeue_escalated(request.id)
    assert requeued.status is ApprovalStatus.PENDING


def test_requeue_requires_escalated_state(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    with pytest.raises(ApprovalError, match="not escalated"):
        engine.requeue_escalated(request.id)


# --- queues ------------------------------------------------------------------


def test_pending_for_role_fifo(engine: ApprovalEngine) -> None:
    first = create_request(engine, title="first")
    second = create_request(engine, title="second")
    other = create_request(engine, title="other", assignee_role=ApproverRole.HR_ADMIN)

    queue = engine.pending_for(ApproverRole.MANAGER)
    assert [item.id for item in queue] == [first.id, second.id]
    assert other.id not in [item.id for item in queue]


def test_escalated_requests_stay_in_queue(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    engine.escalate_overdue(now=datetime.now(UTC) + timedelta(hours=72))
    queue = engine.pending_for(ApproverRole.MANAGER)
    assert [item.id for item in queue] == [request.id]


def test_counts_by_status(engine: ApprovalEngine) -> None:
    first = create_request(engine)
    create_request(engine)
    engine.decide(first.id, decided_by="manager", approve=True)

    counts = engine.counts_by_status()
    assert counts[ApprovalStatus.PENDING.value] == 1
    assert counts[ApprovalStatus.APPROVED.value] == 1
