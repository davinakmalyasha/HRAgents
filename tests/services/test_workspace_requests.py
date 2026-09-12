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
