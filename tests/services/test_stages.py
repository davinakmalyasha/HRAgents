"""Manual stage moves: the designed transition table, named humans, no gate bypass.

Negative tests first — every refused path names its reason (worker-owned,
sign-off required, scheduling gated, system target, agent actor, no-op).
"""

from uuid import uuid4

import pytest

from hr_agents.services import ApplicationStore, AuditChain, SubmissionInput
from hr_agents.services.ingestion import ApplicationStatus
from hr_agents.services.stages import (
    STAGE_TRANSITIONS,
    StageTransitionError,
    StageTransitionService,
)


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


def store_at(status: ApplicationStatus) -> tuple[ApplicationStore, object]:
    store = ApplicationStore()
    record, _ = store.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    if status is not ApplicationStatus.QUEUED:
        store.set_status(record.id, status, event="test.setup")
    return store, record.id


def move(
    store: ApplicationStore,
    audit: AuditChain,
    application_id: object,
    *,
    target: ApplicationStatus,
    by: str = "hr-admin",
    reason: str = "reviewed with the panel",
) -> None:
    StageTransitionService(store=store, audit=audit).move(
        application_id,  # type: ignore[arg-type]
        target=target,
        by=by,
        reason=reason,
    )


# --- refused moves ------------------------------------------------------------------


def test_worker_states_are_never_manual(audit: AuditChain) -> None:
    for source in (ApplicationStatus.QUEUED, ApplicationStatus.PROCESSING):
        store, application_id = store_at(source)
        with pytest.raises(StageTransitionError, match="set by the worker"):
            move(store, audit, application_id, target=ApplicationStatus.GATED)


def test_rejection_requires_a_recorded_signoff_first(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.GATED)
    with pytest.raises(StageTransitionError, match="rejection sign-off first"):
        move(store, audit, application_id, target=ApplicationStatus.REJECTED)


def test_scheduling_is_gated_behind_proposal_or_override(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.GATED)
    with pytest.raises(StageTransitionError, match="scheduling is gated"):
        move(store, audit, application_id, target=ApplicationStatus.SCHEDULED)


def test_system_owned_targets_are_refused(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.SCHEDULED)
    for target in (ApplicationStatus.QUEUED, ApplicationStatus.EVALUATED):
        with pytest.raises(StageTransitionError, match="system-owned"):
            move(store, audit, application_id, target=target)


def test_agents_cannot_move_cards(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.GATED)
    with pytest.raises(StageTransitionError, match="named human"):
        move(store, audit, application_id, target=ApplicationStatus.WITHDRAWN, by="agent:hr_bot")


def test_blank_actor_is_refused(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.GATED)
    with pytest.raises(StageTransitionError, match="named human"):
        move(store, audit, application_id, target=ApplicationStatus.WITHDRAWN, by="   ")


def test_blank_reason_is_refused(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.GATED)
    with pytest.raises(StageTransitionError, match="reason is required"):
        move(
            store,
            audit,
            application_id,
            target=ApplicationStatus.WITHDRAWN,
            reason="   ",
        )


def test_noop_same_status_is_refused(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.GATED)
    with pytest.raises(StageTransitionError, match="already gated"):
        move(store, audit, application_id, target=ApplicationStatus.GATED)


def test_disallowed_pair_is_refused(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.REJECTED)
    with pytest.raises(StageTransitionError, match="cannot move"):
        move(store, audit, application_id, target=ApplicationStatus.WITHDRAWN)


def test_unknown_application_is_refused(audit: AuditChain) -> None:
    store = ApplicationStore()
    with pytest.raises(StageTransitionError, match="not found"):
        move(store, audit, uuid4(), target=ApplicationStatus.GATED)


def test_transition_table_covers_every_status() -> None:
    assert set(STAGE_TRANSITIONS) == set(ApplicationStatus)


# --- allowed moves ------------------------------------------------------------------


def test_evaluated_to_gated_moves_and_audits(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.EVALUATED)
    record = StageTransitionService(store=store, audit=audit).move(
        application_id,  # type: ignore[arg-type]
        target=ApplicationStatus.GATED,
        by="hr-admin",
        reason="pulled out of auto-schedule for a human look",
    )

    assert record.status is ApplicationStatus.GATED
    assert record.timeline[-1][1] == "application.stage.gated"
    entries = [entry for entry in audit.entries if entry.action == "application.stage_changed"]
    assert len(entries) == 1
    assert entries[0].payload["from"] == "evaluated"
    assert entries[0].payload["to"] == "gated"
    assert entries[0].actor.actor_id == "hr-admin"
    assert audit.verify() == -1


def test_reopen_a_rejection_back_to_review(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.REJECTED)
    record = StageTransitionService(store=store, audit=audit).move(
        application_id,  # type: ignore[arg-type]
        target=ApplicationStatus.GATED,
        by="hr-admin",
        reason="candidate appealed; reopening for review",
    )

    assert record.status is ApplicationStatus.GATED
    assert audit.verify() == -1


def test_withdraw_after_scheduling(audit: AuditChain) -> None:
    store, application_id = store_at(ApplicationStatus.SCHEDULED)
    record = StageTransitionService(store=store, audit=audit).move(
        application_id,  # type: ignore[arg-type]
        target=ApplicationStatus.WITHDRAWN,
        by="hr-admin",
        reason="candidate withdrew by phone",
    )

    assert record.status is ApplicationStatus.WITHDRAWN
    assert audit.verify() == -1
