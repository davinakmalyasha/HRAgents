from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.actors import (
    approver,
)
from tests.actors import (
    finance as finance_principal,
)
from tests.actors import (
    hr_admin as hr_admin_principal,
)
from tests.actors import (
    manager as manager_principal,
)

from hr_agents.identity import ActorError, ActorProvenance, ActorRef
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


def reloaded(engine: ApprovalEngine, request: ApprovalRequest) -> ApprovalRequest:
    """The stored request, asserting it is still there.

    Used to prove a refused operation left no trace: the gate has to fail
    *before* it writes, not after.
    """
    found = engine.find(request.id)
    assert found is not None, f"approval {request.id} disappeared"
    return found


def hr_admin(actor_id: str) -> ActorRef:
    """An authenticated principal carrying the HR admin role.

    The self-approval exemption keys on the role claim, so tests that want it
    need an actor the auth layer could actually have produced. The construction
    itself lives in `tests/actors.py` now that `decide` checks authority too.
    """
    return hr_admin_principal(actor_id)


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
    # The engine derives `requested_by_agent` from the actor's type now, so the
    # helper states the kind of actor it means rather than the derived flag.
    actor = ActorRef.agent(requested_by) if requested_by_agent else ActorRef.legacy(requested_by)
    return engine.create(
        subject=subject,
        subject_id=subject_id,
        title=title,
        assignee_role=assignee_role,
        actor=actor,
        urgency=urgency,
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
    decision = engine.decide(
        request.id, actor=manager_principal("manager-budi"), approve=True, reason="ok"
    )

    assert decision.action == "approved"
    assert decision.request.status is ApprovalStatus.APPROVED
    assert decision.request.decided_by == "manager-budi"
    assert engine._audit.entries[-1].action == "approval.approved"


def test_reject_flow(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    decision = engine.decide(
        request.id, actor=manager_principal("manager-budi"), approve=False, reason="busy week"
    )
    assert decision.request.status is ApprovalStatus.REJECTED


def test_agents_cannot_decide(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    with pytest.raises(ApprovalError, match="named human"):
        engine.decide(request.id, actor=ActorRef.agent("policy_assistant"), approve=True)


def test_the_requester_cannot_decide_their_own_request(engine: ApprovalEngine) -> None:
    """An approval the requester decides is not an approval.

    Nothing stopped the person who raised a request from being the person who
    signed it off, so the two-of-the-box control that every consequential screen
    in this product depends on was a single click by one person wearing two
    hats. The audit chain recorded both events, but nothing flagged them.
    """
    request = create_request(engine, requested_by="Budi")

    with pytest.raises(ApprovalError, match="you cannot decide what you raised"):
        engine.decide(request.id, actor=manager_principal("Budi"), approve=True)

    unchanged = engine.find(request.id)
    assert unchanged is not None
    assert unchanged.status is ApprovalStatus.PENDING


def test_a_different_human_may_decide(engine: ApprovalEngine) -> None:
    request = create_request(engine, requested_by="Budi")
    decision = engine.decide(request.id, actor=manager_principal("Rina"), approve=True, reason="ok")

    assert decision.action == "approved"
    assert decision.request.decided_by == "Rina"


def test_hr_admin_may_decide_what_they_raised(engine: ApprovalEngine) -> None:
    """The exemption is explicit, and only for an authenticated admin role.

    At a small company the requester and the approver are frequently the same
    person, and refusing would leave the request stuck rather than safer. The
    chain still shows one actor on both events, so the shortcut is visible to
    whoever reads it -- which is why it is allowed for a role claim rather than
    being dropped.
    """
    request = create_request(engine, requested_by="Rina")
    decision = engine.decide(request.id, actor=hr_admin("Rina"), approve=True)

    assert decision.action == "approved"
    assert decision.request.decided_by == "Rina"


def test_a_legacy_string_actor_is_not_an_admin_claim(engine: ApprovalEngine) -> None:
    """The exemption keys on the role, not on the actor's display name.

    Otherwise the check would be bypassed by calling yourself ``hr-admin`` --
    which is exactly what every caller in this suite does.
    """
    request = create_request(engine, requested_by="hr-admin")

    with pytest.raises(ApprovalError, match="you cannot decide what you raised"):
        engine.decide(request.id, actor=ActorRef.legacy("hr-admin"), approve=True)


def test_double_decide_rejected(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    engine.decide(request.id, actor=manager_principal("manager"), approve=True)
    with pytest.raises(ApprovalError, match="cannot decide"):
        engine.decide(request.id, actor=manager_principal("manager"), approve=False)


def test_withdraw(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    withdrawn = engine.withdraw(
        request.id, actor=manager_principal("sari@example.com"), reason="changed plans"
    )
    assert withdrawn.status is ApprovalStatus.WITHDRAWN


def test_unknown_request_raises(engine: ApprovalEngine) -> None:
    with pytest.raises(ApprovalError, match="unknown approval"):
        engine.decide(uuid4(), actor=ActorRef.legacy("someone"), approve=True)


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
    requeued = engine.requeue_escalated(request.id, actor=manager_principal("Budi"))
    assert requeued.status is ApprovalStatus.PENDING


def test_requeue_requires_escalated_state(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    with pytest.raises(ApprovalError, match="not escalated"):
        engine.requeue_escalated(request.id, actor=manager_principal("Budi"))


# --- authority: who may decide an approval assigned to a role ------------------


def test_a_manager_may_not_sign_off_a_finance_approval(engine: ApprovalEngine) -> None:
    """`MANAGER` and `FINANCE` both hold `approvals:decide`, and that is the gap.

    `RoleId.MANAGER` holds `APPROVALS_DECIDE` so a manager can run a review; it
    does not hold the `finance` approver role. Before this check existed, a
    manager key could decide an approval assigned to `finance` -- a payroll
    sign-off -- through the same permission that lets them decide a leave request.

    `APPROVER_ROLE_HOLDERS` and `may_decide_for` were written for exactly this,
    unit-tested, and validated at startup by `validate_approver_coverage` so an
    unsatisfiable approver role would fail loudly. They had no production call
    site. This is the test that says they are now load-bearing.
    """
    request = create_request(engine, assignee_role=ApproverRole.FINANCE, requested_by="Budi")

    with pytest.raises(ApprovalError, match="assigned to finance"):
        engine.decide(request.id, actor=manager_principal("Rina"), approve=True, reason="ok")

    unchanged = reloaded(engine, request)
    assert unchanged.status is ApprovalStatus.PENDING
    assert unchanged.decided_by is None


def test_finance_may_not_sign_off_a_data_protection_erasure(engine: ApprovalEngine) -> None:
    """An erasure request is the most consequential approval in the system.

    `data_protection` maps to `HR_ADMIN` alone in this deployment -- `rbac.py`
    says so rather than inventing a data-protection-officer role that does not
    exist. So `FINANCE` and `MANAGER` must both be refused it.
    """
    for actor in (manager_principal("Rina"), finance_principal("Sari")):
        request = create_request(
            engine,
            subject=ApprovalSubject.ERASURE_REQUEST,
            assignee_role=ApproverRole.DATA_PROTECTION,
            requested_by="Budi",
        )
        with pytest.raises(ApprovalError, match="assigned to data_protection"):
            engine.decide(request.id, actor=actor, approve=True)


def test_the_refusal_names_who_could_have_decided_it(engine: ApprovalEngine) -> None:
    """An operator reading this needs to know what to do, not just that they cannot."""
    request = create_request(engine, assignee_role=ApproverRole.FINANCE)

    with pytest.raises(ApprovalError) as caught:
        engine.decide(request.id, actor=manager_principal("Rina"), approve=True)

    message = str(caught.value)
    assert "finance, hr_admin" in message
    assert "Rina" in message and "manager" in message


def test_an_actor_with_no_role_cannot_decide(engine: ApprovalEngine) -> None:
    """`ActorRef.legacy(...)` is a bare string; it cannot demonstrate authority.

    Every decision in production arrives through `ActorDep`, which resolves the
    role from the API key, so this refuses only callers that never crossed the
    trust boundary. It is the rule that keeps the previous check from being
    bypassed by simply omitting a role.
    """
    request = create_request(engine, requested_by="Budi")

    with pytest.raises(ApprovalError, match="carries no role"):
        engine.decide(request.id, actor=ActorRef.legacy("Rina"), approve=True)


def test_an_agent_may_not_withdraw_a_pending_payroll_sign_off(engine: ApprovalEngine) -> None:
    """`withdraw` had no named-human gate at all, unlike `decide` and `reassign`."""
    request = create_request(engine, assignee_role=ApproverRole.FINANCE, requested_by="Budi")

    with pytest.raises(ApprovalError, match="named human"):
        engine.withdraw(request.id, actor=ActorRef.agent("payroll_bot"), reason="no longer needed")

    assert reloaded(engine, request).status is ApprovalStatus.PENDING


def test_an_agent_may_not_requeue_an_escalated_approval(engine: ApprovalEngine) -> None:
    """Requeueing walks an SLA backwards, so it takes a person and the authority.

    `_record` defaulted to `ActorRef.system("approval-engine")` when no actor was
    passed, so a human who requeued by hand was recorded on the chain as the
    engine doing it, and an agent could do it at all.
    """
    request = create_request(engine, assignee_role=ApproverRole.FINANCE, requested_by="Budi")
    engine.escalate_overdue(now=datetime.now(UTC) + timedelta(hours=72))

    with pytest.raises(ApprovalError, match="named human"):
        engine.requeue_escalated(request.id, actor=ActorRef.agent("payroll_bot"))

    assert reloaded(engine, request).status is ApprovalStatus.ESCALATED


def test_requeue_records_the_person_who_did_it(engine: ApprovalEngine) -> None:
    """Not `system:approval-engine` -- the whole point of threading the actor."""
    chain = engine._audit
    request = create_request(engine, requested_by="Budi")
    engine.escalate_overdue(now=datetime.now(UTC) + timedelta(hours=72))
    engine.requeue_escalated(request.id, actor=manager_principal("Rina"))

    requeued = [entry for entry in chain.entries if entry.action == "approval.requeued"]
    assert len(requeued) == 1
    assert requeued[0].actor.actor_id == "Rina"
    assert requeued[0].actor.provenance is ActorProvenance.AUTHENTICATED


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
    engine.decide(first.id, actor=manager_principal("manager"), approve=True)

    counts = engine.counts_by_status()
    assert counts[ApprovalStatus.PENDING.value] == 1
    assert counts[ApprovalStatus.APPROVED.value] == 1


# --- reassignment -------------------------------------------------------------
#
# Negative first: the gate must refuse before it moves anything.


def test_reassign_refuses_a_non_human_actor(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    for actor in ("agent:screening", "system:scheduler", "system"):
        with pytest.raises(ApprovalError):
            engine.reassign(
                request.id,
                actor=ActorRef.legacy(actor),
                to_role=ApproverRole.FINANCE,
                reason="wrong queue",
            )
    # A blank actor is refused one step earlier: there is nothing to gate. The
    # old test fed "  " to reassign and asserted the gate caught it, which left a
    # state change followed by a failed audit append as the alternative.
    with pytest.raises(ActorError):
        ActorRef.legacy("  ")
    assert reloaded(engine, request).assignee_role is ApproverRole.MANAGER


def test_reassign_requires_a_reason(engine: ApprovalEngine) -> None:
    """An unjustified move is indistinguishable from moving it to a friend."""
    request = create_request(engine)
    for reason in ("", "   "):
        with pytest.raises(ApprovalError, match="requires a reason"):
            engine.reassign(
                request.id,
                actor=ActorRef.legacy("Rina"),
                to_role=ApproverRole.FINANCE,
                reason=reason,
            )
    assert reloaded(engine, request).assignee_role is ApproverRole.MANAGER


def test_reassign_refuses_a_no_op_route(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    with pytest.raises(ApprovalError, match="already assigned"):
        engine.reassign(
            request.id,
            actor=ActorRef.legacy("Rina"),
            to_role=ApproverRole.MANAGER,
            reason="same role",
        )


def test_reassign_refuses_a_decided_approval(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    engine.decide(request.id, actor=manager_principal("Budi"), approve=True)
    with pytest.raises(ApprovalError):
        engine.reassign(
            request.id,
            actor=ActorRef.legacy("Rina"),
            to_role=ApproverRole.FINANCE,
            reason="too late",
        )


def test_reassign_refuses_an_unknown_approval(engine: ApprovalEngine) -> None:
    with pytest.raises(ApprovalError):
        engine.reassign(
            uuid4(), actor=ActorRef.legacy("Rina"), to_role=ApproverRole.FINANCE, reason="wrong id"
        )


def test_reassign_moves_the_approval_and_records_why(engine: ApprovalEngine) -> None:
    request = create_request(engine, assignee_role=ApproverRole.MANAGER)

    moved = engine.reassign(
        request.id,
        actor=ActorRef.legacy("Rina"),
        to_role=ApproverRole.FINANCE,
        reason="wrong department",
    )

    assert moved.assignee_role is ApproverRole.FINANCE
    assert engine.pending_for(ApproverRole.FINANCE) == [moved]
    assert engine.pending_for(ApproverRole.MANAGER) == []


def test_reassign_is_on_the_audit_chain(engine: ApprovalEngine) -> None:
    request = create_request(engine)
    engine.reassign(
        request.id,
        actor=ActorRef.legacy("Rina"),
        to_role=ApproverRole.HR_ADMIN,
        reason="conflict of interest",
    )

    entry = engine.audit.entries[-1]
    assert entry.action == "approval.reassigned"
    assert entry.actor.actor_id == "Rina"
    assert entry.payload["from_role"] == "manager"
    assert entry.payload["to_role"] == "hr_admin"
    assert entry.payload["reason"] == "conflict of interest"


def test_reassign_keeps_the_approval_decidable(engine: ApprovalEngine) -> None:
    """The escape hatch must not produce a request nobody can sign."""
    request = create_request(engine, assignee_role=ApproverRole.MANAGER)
    moved = engine.reassign(
        request.id,
        actor=ActorRef.legacy("Rina"),
        to_role=ApproverRole.DATA_PROTECTION,
        reason="DPO review",
    )
    engine.decide(moved.id, actor=approver(moved.assignee_role, "Rina"), approve=True)
    assert reloaded(engine, moved).status is ApprovalStatus.APPROVED
