"""Approval engine — the shared human-in-the-loop queue for every department.

The engine owns the lifecycle: create → (assign) → decide / escalate → expire.
Every transition is audited. Escalation and expiry are driven by explicit calls
(a scheduler invokes them; tests drive them with fixed clocks), keeping the
engine deterministic and fully testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from hr_agents.models import (
    ActorType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    AuditActor,
    Urgency,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import ApprovalStore

AGENT_ACTOR_PREFIX = "agent:"


class ApprovalError(RuntimeError):
    """Raised for invalid approval operations."""


@dataclass
class ApprovalDecision:
    request: ApprovalRequest
    action: str  # "approved" | "rejected"


class ApprovalEngine:
    """Create and decide approval requests with SLA escalation."""

    def __init__(self, store: ApprovalStore, *, audit: AuditChain | None = None) -> None:
        self._store = store
        self._audit = audit or AuditChain()

    # --- creation -------------------------------------------------------

    def create(
        self,
        *,
        subject: ApprovalSubject,
        subject_id: str,
        title: str,
        assignee_role: ApproverRole,
        requested_by: str,
        summary: str = "",
        payload: dict[str, Any] | None = None,
        urgency: Urgency = Urgency.NORMAL,
        requested_by_agent: bool = False,
        max_escalations: int = 2,
    ) -> ApprovalRequest:
        """Create a pending approval with its SLA deadline already computed."""
        if requested_by_agent and not requested_by.startswith(AGENT_ACTOR_PREFIX):
            requested_by = f"{AGENT_ACTOR_PREFIX}{requested_by}"

        request = ApprovalRequest(
            subject=subject,
            subject_id=subject_id,
            title=title,
            summary=summary,
            payload=payload or {},
            requested_by=requested_by,
            requested_by_agent=requested_by_agent or requested_by.startswith(AGENT_ACTOR_PREFIX),
            assignee_role=assignee_role,
            urgency=urgency,
            max_escalations=max_escalations,
        )
        request = request.model_copy(update={"sla_deadline": request.default_deadline()})
        self._store.add(request)
        self._record(request, action="approval.created")
        return request

    # --- decisions ------------------------------------------------------

    def decide(
        self,
        request_id: UUID,
        *,
        decided_by: str,
        approve: bool,
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Record a human decision. Agents can never decide."""
        request = self._require(request_id)
        if not request.active:
            raise ApprovalError(f"approval {request_id} is {request.status.value}; cannot decide")
        if not decided_by or decided_by.startswith(AGENT_ACTOR_PREFIX):
            raise ApprovalError("decisions require a named human actor")

        action = "approved" if approve else "rejected"
        decided = request.model_copy(
            update={
                "status": ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED,
                "decided_by": decided_by,
                "decided_at": utc_now(),
                "decision_reason": reason,
                "updated_at": utc_now(),
            }
        )
        self._store.save(decided)
        self._record(decided, action=f"approval.{action}", actor_id=decided_by)
        return ApprovalDecision(request=decided, action=action)

    def withdraw(self, request_id: UUID, *, by: str, reason: str | None = None) -> ApprovalRequest:
        request = self._require(request_id)
        if not request.active:
            raise ApprovalError(f"approval {request_id} is {request.status.value}; cannot withdraw")
        updated = request.model_copy(
            update={
                "status": ApprovalStatus.WITHDRAWN,
                "decision_reason": reason,
                "updated_at": utc_now(),
            }
        )
        self._store.save(updated)
        self._record(updated, action="approval.withdrawn", actor_id=by)
        return updated

    # --- time-driven ----------------------------------------------------

    def escalate_overdue(self, *, now: datetime | None = None) -> list[ApprovalRequest]:
        """Escalate every overdue active request (up to max_escalations).

        Returns the requests that changed. A scheduler calls this; the engine
        itself performs no background work.
        """
        moment = now or utc_now()
        changed: list[ApprovalRequest] = []
        for request in self._store.list_all():
            if not request.is_overdue(now=moment):
                continue
            if request.escalation_count >= request.max_escalations:
                self._expire(request)
                changed.append(self._require(request.id))
                continue
            escalated = request.model_copy(
                update={
                    "status": ApprovalStatus.ESCALATED,
                    "escalation_count": request.escalation_count + 1,
                    "updated_at": utc_now(),
                }
            )
            self._store.save(escalated)
            self._record(escalated, action="approval.escalated")
            changed.append(escalated)
        return changed

    def expire_stale(self, *, now: datetime | None = None) -> list[ApprovalRequest]:
        """Expire every active request that exhausted its escalations."""
        moment = now or utc_now()
        expired: list[ApprovalRequest] = []
        for request in self._store.list_all():
            if not request.active or not request.is_overdue(now=moment):
                continue
            if request.escalation_count >= request.max_escalations:
                expired.append(self._expire(request))
            else:
                # Not yet at the escalation cap: escalate first.
                escalated = request.model_copy(
                    update={
                        "status": ApprovalStatus.ESCALATED,
                        "escalation_count": request.escalation_count + 1,
                        "updated_at": utc_now(),
                    }
                )
                self._store.save(escalated)
                self._record(escalated, action="approval.escalated")
        return expired

    def requeue_escalated(self, request_id: UUID) -> ApprovalRequest:
        """Put an escalated request back into the pending queue."""
        request = self._require(request_id)
        if request.status is not ApprovalStatus.ESCALATED:
            raise ApprovalError(f"approval {request_id} is not escalated")
        updated = request.model_copy(
            update={"status": ApprovalStatus.PENDING, "updated_at": utc_now()}
        )
        self._store.save(updated)
        self._record(updated, action="approval.requeued")
        return updated

    # --- queries --------------------------------------------------------

    def pending_for(self, role: ApproverRole) -> list[ApprovalRequest]:
        """The review queue for one role: pending + escalated, oldest first."""
        return sorted(
            (
                request
                for request in self._store.list_all()
                if request.assignee_role is role and request.active
            ),
            key=lambda item: item.created_at,
        )

    def counts_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for request in self._store.list_all():
            counts[request.status.value] = counts.get(request.status.value, 0) + 1
        return counts

    # --- internals ------------------------------------------------------

    def _require(self, request_id: UUID) -> ApprovalRequest:
        request = self._store.get(request_id)
        if request is None:
            raise ApprovalError(f"unknown approval {request_id}")
        return request

    def _expire(self, request: ApprovalRequest) -> ApprovalRequest:
        expired = request.model_copy(
            update={
                "status": ApprovalStatus.EXPIRED,
                "updated_at": utc_now(),
            }
        )
        self._store.save(expired)
        self._record(expired, action="approval.expired")
        return expired

    def _record(
        self, request: ApprovalRequest, *, action: str, actor_id: str = "approval-engine"
    ) -> None:
        actor_type = (
            ActorType.HUMAN if not actor_id.startswith(AGENT_ACTOR_PREFIX) else ActorType.AGENT
        )
        if actor_id in {"approval-engine", "system"}:
            actor_type = ActorType.SYSTEM
        self._audit.append(
            actor=AuditActor(actor_type=actor_type, actor_id=actor_id),
            action=action,
            subject_type="approval",
            subject_id=str(request.id),
            payload={
                "subject": request.subject.value,
                "subject_id": request.subject_id,
                "assignee_role": request.assignee_role.value,
                "urgency": request.urgency.value,
                "status": request.status.value,
                "escalation_count": request.escalation_count,
                "requested_by_agent": request.requested_by_agent,
            },
        )
