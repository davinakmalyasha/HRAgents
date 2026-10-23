"""Web Push: subscriptions, delivery, and approval fan-out.

The product promise is that a person gates every consequential outcome, which
only works if they learn about it before the SLA expires. Push is the PWA's
last missing surface: a browser subscription reaches the approver's device
without an email account or a third-party account.

Two boundaries are deliberate:

* A notification is a pointer, never a record. The payload names the subject
  ("A leave request is waiting"), not the candidate or the amount, because the
  lock screen is a public surface.
* Delivery is best-effort and out-of-band. Submitting a notification never
  raises into the approval path: an unreachable push service must not stop a
  leave request from being filed or a payroll from being signed off.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from hr_agents.errors import DomainError
from hr_agents.logging import get_logger
from hr_agents.models import ApprovalRequest, PushSubscription, utc_now
from hr_agents.rbac import RoleId, approver_holders

logger = get_logger(__name__)


class PushError(DomainError, RuntimeError):
    """Raised for invalid push operations."""


class PushExpired(RuntimeError):
    """The push service answered 404/410; the browser has dropped the endpoint."""


class PushDeliveryError(RuntimeError):
    """Delivery failed for a reason that retrying may fix (network, 5xx)."""


class PushSender(Protocol):
    """The network edge, swappable so tests never leave the process."""

    def send(self, subscription: PushSubscription, payload: Mapping[str, object]) -> None: ...


class Submitter(Protocol):
    """The narrow slice of an executor this service uses."""

    def submit(self, fn: Callable[..., object], *args: object) -> object: ...


RoleLookup = Callable[[str], RoleId | None]
"""Resolve a live role for an actor; ``None`` means the identity is gone."""


@dataclass(frozen=True)
class DeliveryReport:
    """What one explicit delivery attempt did, for the test button and logs."""

    attempted: int
    delivered: int
    pruned: int
    failed: int


class _ThreadSubmitter:
    """The default executor: small, named, and only created on first use."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push")

    def submit(self, fn: Callable[..., object], *args: object) -> object:
        return self._pool.submit(fn, *args)


class PushStore:
    """In-memory subscriptions; the database adapter overrides the primitives."""

    def __init__(self) -> None:
        self._items: dict[UUID, PushSubscription] = {}

    def add(self, subscription: PushSubscription) -> None:
        self._items[subscription.id] = subscription

    def save(self, subscription: PushSubscription) -> None:
        if subscription.id not in self._items:
            raise KeyError(f"unknown push subscription {subscription.id}")
        self._items[subscription.id] = subscription

    def get(self, subscription_id: UUID) -> PushSubscription | None:
        return self._items.get(subscription_id)

    def list_all(self) -> list[PushSubscription]:
        return sorted(self._items.values(), key=lambda item: (item.created_at, item.id))

    def for_actor(self, actor_id: str) -> list[PushSubscription]:
        return [item for item in self.list_all() if item.actor_id == actor_id]

    def for_endpoint(self, actor_id: str, endpoint: str) -> PushSubscription | None:
        for item in self._items.values():
            if item.actor_id == actor_id and item.endpoint == endpoint:
                return item
        return None

    def for_roles(self, roles: Collection[str]) -> list[PushSubscription]:
        wanted = set(roles)
        return [item for item in self.list_all() if item.role in wanted]

    def delete(self, subscription_id: UUID) -> bool:
        return self._items.pop(subscription_id, None) is not None


class PushService:
    """Owns subscriptions and the best-effort delivery edge."""

    def __init__(
        self,
        store: PushStore,
        *,
        sender: PushSender | None = None,
        executor: Submitter | None = None,
        role_lookup: RoleLookup | None = None,
    ) -> None:
        self._store = store
        self._sender = sender
        self._executor = executor
        self._role_lookup = role_lookup

    @property
    def configured(self) -> bool:
        """Push is configured only when the operator supplied a sender."""
        return self._sender is not None

    def subscribe(
        self,
        *,
        actor_id: str,
        role: str,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None = None,
    ) -> PushSubscription:
        """Register or refresh one browser endpoint.

        An endpoint is unique per person, so re-subscribing the same browser
        updates the keys instead of accumulating dead rows. The endpoint must be
        HTTPS: the server sends to whatever URL is stored here, and accepting
        plain HTTP would make the subscription table an outbound-request gadget.
        """
        if not endpoint.startswith("https://"):
            raise PushError("a push endpoint must use HTTPS")
        subscription = PushSubscription(
            actor_id=actor_id,
            role=role,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
        )
        existing = self._store.for_endpoint(actor_id, endpoint)
        if existing is not None:
            subscription = subscription.model_copy(
                update={
                    "id": existing.id,
                    "created_at": existing.created_at,
                    "last_seen_at": utc_now(),
                }
            )
            self._store.save(subscription)
            return subscription
        self._store.add(subscription)
        return subscription

    def unsubscribe(self, *, actor_id: str, subscription_id: UUID) -> bool:
        """Remove one subscription, and only its owner's."""
        existing = self._store.get(subscription_id)
        if existing is None or existing.actor_id != actor_id:
            return False
        return self._store.delete(subscription_id)

    def list_for(self, actor_id: str) -> list[PushSubscription]:
        return self._store.for_actor(actor_id)

    def approval_created(self, request: ApprovalRequest) -> None:
        """Fan an approval out to the roles that may decide it.

        Called from `ApprovalEngine.create`; must never raise. The recipient set
        is the approver roles for the assigned role, intersected with live
        identities on the sending side.
        """
        roles = approver_holders(request.assignee_role.value)
        if not roles:
            return
        subject = request.subject.value.replace("_", " ")
        self.notify_role_holders(
            roles,
            {
                "title": "Approval waiting",
                "body": f"A {subject} needs your decision ({request.urgency.value}).",
                "url": "/app/",
                "tag": f"approval-{request.id}",
            },
        )

    def notify_role_holders(
        self,
        roles: Collection[RoleId],
        payload: Mapping[str, object],
    ) -> int:
        """Queue a delivery to every live subscription holding one of ``roles``.

        Returns the number of endpoints selected. The sends run on the executor
        so an unreachable push service cannot delay the decision that created
        the notification.
        """
        if self._sender is None:
            return 0
        recipients = self._recipients(roles)
        for subscription in recipients:
            self._submit(subscription, payload)
        if recipients:
            logger.info(
                "push.notification_queued",
                recipients=len(recipients),
                title=payload.get("title"),
            )
        return len(recipients)

    def send_test(self, *, actor_id: str) -> DeliveryReport:
        """Deliver one immediate notification to the caller's own endpoints."""
        subscriptions = self._store.for_actor(actor_id)
        if not subscriptions:
            raise PushError("no push subscription is registered for this principal")
        payload = {
            "title": "HRAgents",
            "body": "Notifications are working. Approval pings will arrive here.",
            "url": "/app/",
            "tag": "push-test",
        }
        delivered = pruned = failed = 0
        for subscription in subscriptions:
            outcome = self._deliver(subscription, payload)
            if outcome == "delivered":
                delivered += 1
            elif outcome == "pruned":
                pruned += 1
            else:
                failed += 1
        return DeliveryReport(
            attempted=len(subscriptions),
            delivered=delivered,
            pruned=pruned,
            failed=failed,
        )

    def _recipients(self, roles: Collection[RoleId]) -> list[PushSubscription]:
        wanted = {role.value for role in roles}
        recipients: list[PushSubscription] = []
        for subscription in self._store.for_roles(wanted):
            if self._role_lookup is not None:
                current = self._role_lookup(subscription.actor_id)
                if current is None or current.value not in wanted:
                    continue
            recipients.append(subscription)
        return recipients

    def _submit(self, subscription: PushSubscription, payload: Mapping[str, object]) -> None:
        if self._sender is None:
            return
        if self._executor is None:
            self._executor = _ThreadSubmitter()
        self._executor.submit(self._deliver, subscription, payload)

    def _deliver(self, subscription: PushSubscription, payload: Mapping[str, object]) -> str:
        if self._sender is None:
            return "failed"
        try:
            self._sender.send(subscription, payload)
        except PushExpired:
            self._store.delete(subscription.id)
            logger.info("push.subscription_expired", actor_id=subscription.actor_id)
            return "pruned"
        except PushDeliveryError as exc:
            logger.warning(
                "push.delivery_failed",
                actor_id=subscription.actor_id,
                reason=str(exc),
            )
            return "failed"
        except Exception:
            logger.exception("push.delivery_error", actor_id=subscription.actor_id)
            return "failed"
        return "delivered"


class PyWebPushSender:
    """The real Web Push edge: VAPID-signed, encrypted delivery.

    Imported lazily so an install without pywebpush (or without configured
    keys) can still run everything else; `PushService` only constructs this
    when the operator configured a key pair.
    """

    def __init__(self, *, private_key: str, subject: str, ttl: int = 300) -> None:
        if not private_key:
            raise PushError("a VAPID private key is required to send push notifications")
        if not (subject.startswith("mailto:") or subject.startswith("https://")):
            raise PushError("the VAPID subject must be a mailto: or https:// URL")
        self._private_key = private_key
        self._subject = subject
        self._ttl = ttl

    def send(self, subscription: PushSubscription, payload: Mapping[str, object]) -> None:
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=json.dumps(dict(payload)),
                vapid_private_key=self._private_key,
                vapid_claims={"sub": self._subject},
                ttl=self._ttl,
                timeout=5,
            )
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code in (404, 410):
                raise PushExpired(f"push endpoint is gone ({status_code})") from exc
            raise PushDeliveryError(
                f"push delivery failed ({status_code or 'no response'})"
            ) from exc
