"""The approval outbox: one transaction for the decision and the sync it owes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.people import DbApprovalStore, DbPendingSyncStore
from hr_agents.errors import StaleRecordError
from hr_agents.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
)
from hr_agents.services.people_store import PendingApprovalSync

NOW = datetime(2026, 10, 31, 3, 0, tzinfo=UTC)


def make_request() -> ApprovalRequest:
    return ApprovalRequest(
        subject=ApprovalSubject.LEAVE_REQUEST,
        subject_id=str(uuid4()),
        title="Approve leave",
        summary="",
        requested_by="sari",
        assignee_role=ApproverRole.MANAGER,
        created_at=NOW,
        updated_at=NOW,
    )


def make_sync(request: ApprovalRequest) -> PendingApprovalSync:
    return PendingApprovalSync(
        approval_id=request.id,
        subject=request.subject,
        subject_id=request.subject_id,
        decision=ApprovalStatus.APPROVED,
        created_at=NOW,
    )


def test_the_decision_and_its_outbox_row_commit_together(
    factory: sessionmaker[Session],
) -> None:
    store = DbApprovalStore(factory)
    request = make_request()
    store.add(request)

    decided = request.model_copy(
        update={
            "status": ApprovalStatus.APPROVED,
            "decided_by": "budi",
            "decided_at": NOW,
            "updated_at": NOW,
        }
    )
    store.persist_decision(decided, make_sync(decided))

    # A fresh adapter sees both: the decision is durable and the sync is queued.
    fresh = DbApprovalStore(factory)
    stored = fresh.get(request.id)
    assert stored is not None and stored.status is ApprovalStatus.APPROVED
    pending = fresh.list_pending_syncs()
    assert len(pending) == 1
    assert pending[0].approval_id == request.id
    assert pending[0].decision is ApprovalStatus.APPROVED


def test_a_stale_decision_rolls_the_outbox_row_back(
    factory: sessionmaker[Session],
) -> None:
    """The crash-window test: a refused save must not queue work.

    Two writers read the same approval; the first saves, the second's decision is
    refused by the version predicate. If the outbox row were a separate commit it
    would survive and the reconciler would apply a decision that never landed.
    One transaction means both disappear.
    """
    store = DbApprovalStore(factory)
    request = make_request()
    store.add(request)
    stale = DbApprovalStore(factory).get(request.id)
    assert stale is not None

    winner = DbApprovalStore(factory).get(request.id)
    assert winner is not None
    winner = winner.model_copy(update={"title": "Edited by someone else"})
    DbApprovalStore(factory).save(winner)

    decided = stale.model_copy(
        update={
            "status": ApprovalStatus.REJECTED,
            "decided_by": "budi",
            "decided_at": NOW,
            "updated_at": NOW,
        }
    )
    with pytest.raises(StaleRecordError):
        DbApprovalStore(factory).persist_decision(decided, make_sync(decided))

    assert DbPendingSyncStore(factory).list_all() == []
    unchanged = DbApprovalStore(factory).get(request.id)
    assert unchanged is not None and unchanged.status is ApprovalStatus.PENDING


def test_one_outbox_row_per_approval_even_if_the_decision_is_replayed(
    factory: sessionmaker[Session],
) -> None:
    store = DbApprovalStore(factory)
    request = make_request()
    store.add(request)
    decided = request.model_copy(
        update={
            "status": ApprovalStatus.APPROVED,
            "decided_by": "budi",
            "decided_at": NOW,
            "updated_at": NOW,
        }
    )
    sync = make_sync(decided)
    store.persist_decision(decided, sync)

    with pytest.raises(IntegrityError):
        store.persist_decision(decided, sync)

    assert len(DbPendingSyncStore(factory).list_all()) == 1


def test_consuming_a_sync_is_durable(factory: sessionmaker[Session]) -> None:
    store = DbApprovalStore(factory)
    request = make_request()
    store.add(request)
    decided = request.model_copy(
        update={
            "status": ApprovalStatus.APPROVED,
            "decided_by": "budi",
            "decided_at": NOW,
            "updated_at": NOW,
        }
    )
    store.persist_decision(decided, make_sync(decided))

    pending = store.list_pending_syncs()
    store.save_pending_sync(
        pending[0].model_copy(update={"consumed_at": NOW, "outcome": "applied"})
    )

    fresh = DbApprovalStore(factory)
    assert fresh.list_pending_syncs() == []
    assert fresh.list_all_syncs()[0].outcome == "applied"
