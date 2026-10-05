"""Ask HR and handoff-queue adapter tests on in-memory SQLite.

Every test builds a *fresh* adapter instance for each read. That is the point of the
file: it defeats any fallback to the in-process dict, so a store that quietly kept
using its dict instead of the database would fail here rather than in production
after a restart.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.workspace import DbConversationStore, DbWorkspaceRequestStore
from hr_agents.services.chat import ChatTurn, ConversationRecord
from hr_agents.services.workspace_requests import RequestStatus, WorkspaceRequest
from hr_agents.workspaces import WorkspaceId

MOMENT = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)
LATER = MOMENT + timedelta(minutes=5)


def _conversation(owner: str = "sari") -> ConversationRecord:
    return ConversationRecord(
        workspace=WorkspaceId.LEAVE,
        owner=owner,
        turns=[
            ChatTurn(role="user", text="How many leave days do I have left?", at=MOMENT),
            ChatTurn(role="assistant", text="You have 6 remaining.", at=LATER),
        ],
        created_at=MOMENT,
        updated_at=LATER,
    )


def test_conversation_store_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbConversationStore(factory)
    record = _conversation()
    store._persist(record)

    fresh = DbConversationStore(factory)
    loaded = fresh.get(record.id)
    assert loaded is not None
    assert loaded.owner == "sari"
    assert loaded.workspace is WorkspaceId.LEAVE
    assert [turn.role for turn in loaded.turns] == ["user", "assistant"]
    # Timestamps survive the SQLite round trip with their timezone intact; a naive
    # datetime here would make `updated_at` comparison in `list_all` raise.
    assert loaded.created_at.tzinfo is not None
    assert loaded.turns[1].at == LATER

    assert fresh.get(uuid4()) is None
    assert [item.id for item in fresh.list_all()] == [record.id]


def test_conversation_store_update_replaces_the_turns(
    factory: sessionmaker[Session],
) -> None:
    """A continued conversation must append, not silently keep the old turns."""
    store = DbConversationStore(factory)
    record = _conversation()
    store._persist(record)

    updated = record.model_copy(
        update={
            "turns": [
                *record.turns,
                ChatTurn(role="user", text="And last month?", at=LATER),
            ],
            "updated_at": LATER,
        }
    )
    DbConversationStore(factory)._persist(updated)

    loaded = DbConversationStore(factory).get(record.id)
    assert loaded is not None
    assert [turn.text for turn in loaded.turns] == [
        "How many leave days do I have left?",
        "You have 6 remaining.",
        "And last month?",
    ]


def test_conversation_list_all_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """The transcript an employee was already given must still be readable.

    This is the regression the adapter exists for: with the dict-backed store a new
    process returned an empty history, so the assistant appeared to have forgotten.
    """
    DbConversationStore(factory)._persist(_conversation("sari"))
    DbConversationStore(factory)._persist(_conversation("budi"))

    listed = DbConversationStore(factory).list_all()
    assert sorted(item.owner for item in listed) == ["budi", "sari"]


def test_workspace_request_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbWorkspaceRequestStore(factory)
    record = WorkspaceRequest(
        source_workspace=WorkspaceId.RECORDS,
        target_workspace=WorkspaceId.PAYROLL,
        text="Please correct my March payslip.",
        requested_by="sari",
        created_at=MOMENT,
        updated_at=MOMENT,
    )
    store._persist(record)

    loaded = DbWorkspaceRequestStore(factory).get(record.id)
    assert loaded is not None
    assert loaded.source_workspace is WorkspaceId.RECORDS
    assert loaded.target_workspace is WorkspaceId.PAYROLL
    assert loaded.text == "Please correct my March payslip."
    assert loaded.status is RequestStatus.OPEN
    assert loaded.created_at.tzinfo is not None

    assert DbWorkspaceRequestStore(factory).get(uuid4()) is None
    assert [item.id for item in DbWorkspaceRequestStore(factory).list_all()] == [record.id]


def test_workspace_request_status_update_persists(factory: sessionmaker[Session]) -> None:
    """A claimed handoff must not revert to open when the process restarts."""
    store = DbWorkspaceRequestStore(factory)
    record = WorkspaceRequest(
        source_workspace=WorkspaceId.RECORDS,
        target_workspace=WorkspaceId.PAYROLL,
        text="Please correct my March payslip.",
        requested_by="sari",
    )
    store._persist(record)
    store._persist(record.model_copy(update={"status": RequestStatus.CLAIMED, "updated_at": LATER}))

    loaded = DbWorkspaceRequestStore(factory).get(record.id)
    assert loaded is not None
    assert loaded.status is RequestStatus.CLAIMED


def test_handoff_queue_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """An open handoff vanished mid-workflow with the dict-backed store."""
    DbWorkspaceRequestStore(factory)._persist(
        WorkspaceRequest(
            source_workspace=WorkspaceId.RECORDS,
            target_workspace=WorkspaceId.LEAVE,
            text="Approve the carry-over request.",
            requested_by="sari",
        )
    )
    DbWorkspaceRequestStore(factory)._persist(
        WorkspaceRequest(
            source_workspace=WorkspaceId.RECORDS,
            target_workspace=WorkspaceId.GROWTH,
            text="Start the review cycle.",
            requested_by="budi",
            status=RequestStatus.CLOSED,
        )
    )

    listed = DbWorkspaceRequestStore(factory).list_all()
    assert len(listed) == 2
    open_targets = [item.target_workspace for item in listed if item.status is RequestStatus.OPEN]
    assert open_targets == [WorkspaceId.LEAVE]
