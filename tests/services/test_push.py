"""Web Push: subscription ownership, role fan-out, and best-effort delivery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from uuid import uuid4

import pytest
from structlog.testing import CapturingLogger

from hr_agents.models import (
    ApprovalRequest,
    ApprovalSubject,
    ApproverRole,
    PushSubscription,
    Urgency,
)
from hr_agents.rbac import RoleId
from hr_agents.services import push as push_module
from hr_agents.services.push import (
    PushDeliveryError,
    PushError,
    PushExpired,
    PushService,
    PushStore,
    PyWebPushSender,
)

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc-123"
KEYS = {"p256dh": "B" * 80, "auth": "a" * 24}


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[PushSubscription, Mapping[str, object]]] = []
        self.fail: dict[str, Exception] = {}

    def send(self, subscription: PushSubscription, payload: Mapping[str, object]) -> None:
        error = self.fail.get(subscription.endpoint)
        if error is not None:
            raise error
        self.sent.append((subscription, payload))


class InlineExecutor:
    def submit(self, fn: Callable[..., object], *args: object) -> object:
        return fn(*args)


def service(
    *,
    sender: RecordingSender | None = None,
    role_lookup: Callable[[str], RoleId | None] | None = None,
) -> PushService:
    return PushService(
        PushStore(),
        sender=sender,
        executor=InlineExecutor(),
        role_lookup=role_lookup,
    )


def subscribe(
    push: PushService, *, actor_id: str = "rina", role: RoleId = RoleId.MANAGER
) -> PushSubscription:
    return push.subscribe(
        actor_id=actor_id,
        role=role.value,
        endpoint=f"{ENDPOINT}-{actor_id}",
        user_agent="Firefox 140",
        **KEYS,
    )


def test_a_subscription_round_trips_and_is_scoped_to_its_owner() -> None:
    push = service()
    subscription = subscribe(push)

    assert push.list_for("rina") == [subscription]
    assert push.list_for("budi") == []


def test_re_subscribing_the_same_endpoint_refreshes_instead_of_duplicating() -> None:
    push = service()
    first = subscribe(push)
    second = push.subscribe(
        actor_id="rina",
        role="manager",
        endpoint=first.endpoint,
        p256dh="C" * 80,
        auth="b" * 24,
    )

    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.p256dh == "C" * 80
    assert len(push.list_for("rina")) == 1


def test_an_endpoint_must_be_https() -> None:
    push = service()
    with pytest.raises(PushError, match="HTTPS"):
        push.subscribe(
            actor_id="rina",
            role="manager",
            endpoint="http://example.com/push",
            **KEYS,
        )


def test_unsubscribing_somebody_elses_endpoint_is_refused() -> None:
    push = service()
    subscription = subscribe(push)

    assert not push.unsubscribe(actor_id="budi", subscription_id=subscription.id)
    assert push.list_for("rina") == [subscription]
    assert push.unsubscribe(actor_id="rina", subscription_id=subscription.id)
    assert push.list_for("rina") == []


def test_fan_out_selects_only_the_roles_that_may_decide() -> None:
    sender = RecordingSender()
    push = service(sender=sender)
    manager = subscribe(push, actor_id="rina", role=RoleId.MANAGER)
    subscribe(push, actor_id="sari", role=RoleId.EMPLOYEE)

    assert push.notify_role_holders({RoleId.MANAGER}, {"title": "Approval waiting"}) == 1
    assert [item[0].id for item in sender.sent] == [manager.id]


def test_a_revoked_or_demoted_identity_stops_receiving_pushes() -> None:
    sender = RecordingSender()
    roles = {"rina": RoleId.MANAGER, "budi": RoleId.EMPLOYEE}
    push = service(sender=sender, role_lookup=roles.get)
    subscribe(push, actor_id="rina", role=RoleId.MANAGER)
    subscribe(push, actor_id="budi", role=RoleId.MANAGER)

    push.notify_role_holders({RoleId.MANAGER}, {"title": "Approval waiting"})

    assert [item[0].actor_id for item in sender.sent] == ["rina"]

    del roles["rina"]
    assert push.notify_role_holders({RoleId.MANAGER}, {"title": "Approval waiting"}) == 0


def test_nothing_is_sent_when_the_deployment_is_not_configured() -> None:
    push = service(sender=None)
    subscribe(push)

    assert push.configured is False
    assert push.notify_role_holders({RoleId.MANAGER}, {"title": "Approval waiting"}) == 0


def test_an_expired_endpoint_is_pruned_and_a_failure_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(push_module, "logger", logger)
    sender = RecordingSender()
    push = service(sender=sender)
    gone = subscribe(push, actor_id="rina")
    flaky = push.subscribe(
        actor_id="budi",
        role="manager",
        endpoint=f"{ENDPOINT}-budi",
        **KEYS,
    )
    sender.fail[gone.endpoint] = PushExpired("gone")
    sender.fail[flaky.endpoint] = PushDeliveryError("503 from the push service")

    assert push.notify_role_holders({RoleId.MANAGER}, {"title": "x"}) == 2

    assert push.list_for("rina") == [], "a 410 means the browser dropped the endpoint"
    assert len(push.list_for("budi")) == 1, "a transient failure is retried, not written off"
    events = [call.args[0] for call in logger.calls if call.args]
    assert "push.subscription_expired" in events
    assert "push.delivery_failed" in events


def test_the_test_button_delivers_only_to_the_caller() -> None:
    sender = RecordingSender()
    push = service(sender=sender)
    subscribe(push, actor_id="rina")
    push.subscribe(
        actor_id="budi",
        role="manager",
        endpoint=f"{ENDPOINT}-budi",
        **KEYS,
    )

    report = push.send_test(actor_id="rina")

    assert (report.attempted, report.delivered, report.failed, report.pruned) == (1, 1, 0, 0)
    assert [item[0].actor_id for item in sender.sent] == ["rina"]


def test_the_test_button_says_when_there_is_no_subscription() -> None:
    with pytest.raises(PushError, match="no push subscription"):
        service(sender=RecordingSender()).send_test(actor_id="rina")


def test_approval_payloads_name_the_subject_not_the_person() -> None:
    sender = RecordingSender()
    push = service(sender=sender)
    subscribe(push, actor_id="rina")

    push.approval_queued(
        ApprovalRequest(
            subject=ApprovalSubject.LEAVE_REQUEST,
            subject_id="leave-1",
            title="Annual leave for Sari",
            summary="Sari wants three days",
            assignee_role=ApproverRole.MANAGER,
            requested_by="sari",
            urgency=Urgency.HIGH,
        )
    )

    payload = sender.sent[0][1]
    assert payload["title"] == "Approval waiting"
    assert "leave request" in str(payload["body"])
    assert "Sari" not in str(payload["body"])
    assert payload["url"] == "/app/"


def test_an_escalation_says_the_sla_already_slipped() -> None:
    sender = RecordingSender()
    push = service(sender=sender)
    subscribe(push, actor_id="rina", role=RoleId.FINANCE)

    push.approval_queued(
        ApprovalRequest(
            subject=ApprovalSubject.PAYROLL_RUN,
            subject_id="run-1",
            title="March payroll",
            assignee_role=ApproverRole.FINANCE,
            requested_by="finance-bot",
            urgency=Urgency.CRITICAL,
        ),
        event="escalated",
    )

    payload = sender.sent[0][1]
    assert payload["title"] == "Approval overdue"
    assert "past its SLA" in str(payload["body"])


def test_the_sender_refuses_configuration_it_cannot_use() -> None:
    with pytest.raises(PushError, match="private key"):
        PyWebPushSender(private_key="", subject="mailto:ops@example.com")
    with pytest.raises(PushError, match="mailto"):
        PyWebPushSender(private_key="key", subject="ops@example.com")


def test_an_unknown_subscription_is_not_deletable() -> None:
    assert not service().unsubscribe(actor_id="rina", subscription_id=uuid4())
