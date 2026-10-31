"""Cross-workspace handoffs: request-only queue items with audit provenance."""

import pytest

from hr_agents.rbac import Principal, RoleId
from hr_agents.services.audit import AuditChain
from hr_agents.services.workspace_requests import (
    HandoffError,
    HandoffService,
    RequestStatus,
    WorkspaceRequestStore,
)
from hr_agents.workspaces import WorkspaceId, default_registry

PRINCIPAL = Principal(actor_id="hr-admin", role=RoleId.HR_ADMIN)


def make_service() -> tuple[HandoffService, AuditChain, WorkspaceRequestStore]:
    audit = AuditChain()
    store = WorkspaceRequestStore()
    service = HandoffService(registry=default_registry(), audit=audit, store=store)
    return service, audit, store


def test_self_target_is_rejected_before_persisting() -> None:
    service, audit, store = make_service()

    with pytest.raises(HandoffError, match="different workspace"):
        service.request(
            message="bantu Budi",
            principal=PRINCIPAL,
            source_workspace=WorkspaceId.ONBOARDING,
            target_workspace=WorkspaceId.ONBOARDING,
        )

    assert store.list_all() == []
    assert audit.entries == ()


def test_blank_message_is_rejected_before_persisting() -> None:
    service, audit, store = make_service()

    with pytest.raises(HandoffError, match="must not be blank"):
        service.request(
            message="   ",
            principal=PRINCIPAL,
            source_workspace=WorkspaceId.POLICY,
            target_workspace=WorkspaceId.ONBOARDING,
        )

    assert store.list_all() == []
    assert audit.entries == ()


def test_request_is_persisted_and_audited_without_text() -> None:
    service, audit, _ = make_service()

    record = service.request(
        message="  Onboard Budi, start Monday  ",
        principal=PRINCIPAL,
        source_workspace=WorkspaceId.POLICY,
        target_workspace=WorkspaceId.ONBOARDING,
    )

    assert record.status is RequestStatus.OPEN
    assert record.text == "Onboard Budi, start Monday"
    assert record.requested_by == "hr-admin"

    entry = audit.entries[-1]
    assert entry.action == "handoff.requested"
    assert entry.actor.actor_id == "hr-admin"
    assert entry.payload == {
        "source": "policy",
        "target": "onboarding",
        "characters": 26,
    }
    assert audit.verify() == -1


def test_open_for_filters_by_target_workspace_and_status() -> None:
    service, _, _ = make_service()
    onboarding = service.request(
        message="Onboard Budi",
        principal=PRINCIPAL,
        source_workspace=WorkspaceId.POLICY,
        target_workspace=WorkspaceId.ONBOARDING,
    )
    payroll = service.request(
        message="Prepare THR",
        principal=PRINCIPAL,
        source_workspace=WorkspaceId.POLICY,
        target_workspace=WorkspaceId.PAYROLL,
    )

    assert [item.id for item in service.open_for(WorkspaceId.ONBOARDING)] == [onboarding.id]
    assert [item.id for item in service.open_for()] == [onboarding.id, payroll.id]

    onboarding.status = RequestStatus.CLAIMED
    assert service.open_for(WorkspaceId.ONBOARDING) == []
    assert [item.id for item in service.open_for()] == [payroll.id]


def test_page_open_counts_and_slices_open_requests_only() -> None:
    service, _, store = make_service()
    records = [
        service.request(
            message=f"Request {index}",
            principal=PRINCIPAL,
            source_workspace=WorkspaceId.POLICY,
            target_workspace=WorkspaceId.ONBOARDING,
        )
        for index in range(3)
    ]
    records[1].status = RequestStatus.CLOSED
    store._persist(records[1])

    first, total = service.page_open(workspace=WorkspaceId.ONBOARDING, limit=1, offset=0)
    second, total_again = service.page_open(workspace=WorkspaceId.ONBOARDING, limit=1, offset=1)

    assert total == total_again == 2
    assert [item.id for item in first] == [records[0].id]
    assert [item.id for item in second] == [records[2].id]


def test_page_open_orders_equal_instants_by_id_for_a_stable_offset() -> None:
    service, _, _ = make_service()
    first = service.request(
        message="First",
        principal=PRINCIPAL,
        source_workspace=WorkspaceId.POLICY,
        target_workspace=WorkspaceId.PAYROLL,
    )
    second = service.request(
        message="Second",
        principal=PRINCIPAL,
        source_workspace=WorkspaceId.POLICY,
        target_workspace=WorkspaceId.PAYROLL,
    )
    stamp = first.created_at
    first.created_at = stamp
    second.created_at = stamp

    page, _ = service.page_open(workspace=None, limit=10, offset=0)

    assert [item.id for item in page] == sorted([first.id, second.id], key=str)
