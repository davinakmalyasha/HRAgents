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

from hr_agents.identity import ActorRef
from hr_agents.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    Urgency,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import ApprovalStore


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
        actor: ActorRef,
        summary: str = "",
        payload: dict[str, Any] | None = None,
        urgency: Urgency = Urgency.NORMAL,
        max_escalations: int = 2,
    ) -> ApprovalRequest:
        """Create a pending approval with its SLA deadline already computed.

        ``requested_by_agent`` is derived from the actor rather than supplied.
        It used to be a separate boolean that a caller could set inconsistently
        with the name it passed, which is how an agent tool ended up recorded on
        the chain as a person.
        """
        request = ApprovalRequest(
            subject=subject,
            subject_id=subject_id,
            title=title,
            summary=summary,
            payload=payload or {},
            requested_by=actor.actor_id,
            requested_by_agent=not actor.is_human,
            assignee_role=assignee_role,
            urgency=urgency,
            max_escalations=max_escalations,
        )
        request = request.model_copy(update={"sla_deadline": request.default_deadline()})
        self._store.add(request)
        self._record(request, action="approval.created", actor=actor)
        return request

    # --- decisions ------------------------------------------------------

    def decide(
        self,
        request_id: UUID,
        *,
        actor: ActorRef,
        approve: bool,
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Record a human decision. Agents can never decide."""
        request = self._require(request_id)
        if not request.active:
            raise ApprovalError(f"approval {request_id} is {request.status.value}; cannot decide")
        actor.require_human("a decision", ApprovalError)

        action = "approved" if approve else "rejected"
        decided = request.model_copy(
            update={
                "status": ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED,
                "decided_by": actor.actor_id,
                "decided_at": utc_now(),
                "decision_reason": reason,
                "updated_at": utc_now(),
            }
        )
        self._store.save(decided)
        self._record(decided, action=f"approval.{action}", actor=actor)
        return ApprovalDecision(request=decided, action=action)

    def withdraw(
        self, request_id: UUID, *, actor: ActorRef, reason: str | None = None
    ) -> ApprovalRequest:
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
        self._record(updated, action="approval.withdrawn", actor=actor)
        return updated

    def reassign(
        self,
        request_id: UUID,
        *,
        actor: ActorRef,
        to_role: ApproverRole,
        reason: str,
    ) -> ApprovalRequest:
        """Route an approval to a different approver role, on the record.

        This is the escape hatch, not a delegation feature. Approvals are routed
        by ``assignee_role`` and enforced against it; when a request is routed
        wrongly -- the wrong department, a conflict of interest, a manager on
        leave -- the alternative was for an operator to hand-edit the store or
        for the request to sit until it expired. Both are worse than an audited
        move by a named person.

        A reason is mandatory. A reassignment with no stated justification is
        indistinguishable, to a later reader of the chain, from quietly moving
        an approval to someone friendlier.
        """
        request = self._require(request_id)
        if not request.active:
            raise ApprovalError(f"approval {request_id} is not active; cannot reassign")
        actor.require_human("a reassignment", ApprovalError)
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ApprovalError("a reassignment requires a reason; it becomes part of the record")

        previous = request.assignee_role
        if previous is to_role:
            raise ApprovalError(f"approval {request_id} is already assigned to {previous.value}")

        updated = request.model_copy(update={"assignee_role": to_role, "updated_at": utc_now()})
        self._store.save(updated)
        self._record(
            updated,
            action="approval.reassigned",
            actor=actor,
            extra={"from_role": previous.value, "to_role": to_role.value, "reason": cleaned_reason},
        )
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

    def find_by_subject(self, subject: ApprovalSubject, subject_id: str) -> ApprovalRequest | None:
        """The most recent request for one domain object, if any."""
        matches = [
            request
            for request in self._store.list_all()
            if request.subject is subject and request.subject_id == subject_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item.created_at)

    def counts_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for request in self._store.list_all():
            counts[request.status.value] = counts.get(request.status.value, 0) + 1
        return counts

    def list_all(self) -> list[ApprovalRequest]:
        """Every request, oldest first (gates and reports walk the whole queue)."""
        return self._store.list_all()

    def find(self, request_id: UUID) -> ApprovalRequest | None:
        """A request by id, or ``None``. Reading a request never changes it."""
        return self._store.get(request_id)

    @property
    def audit(self) -> AuditChain:
        return self._audit

    def mark_executed(self, request_id: UUID, *, actor: ActorRef) -> ApprovalRequest:
        """Consume an approved request, so the same grant cannot fire twice.

        Only an approved, not-yet-executed request can be consumed, and the
        execution is audited with the request id. The actor is usually an agent
        tool acting on a human's approval, which is why this one is not gated on
        a person.
        """
        request = self._require(request_id)
        if request.status is not ApprovalStatus.APPROVED:
            raise ApprovalError(
                f"approval {request_id} is {request.status.value};"
                " only an approved request can be consumed"
            )
        if request.payload.get("executed_at") is not None:
            raise ApprovalError(f"approval {request_id} was already consumed")
        consumed = request.model_copy(
            update={
                "payload": {
                    **request.payload,
                    "executed_at": utc_now().isoformat(),
                    "executed_by": actor.actor_id,
                },
                "updated_at": utc_now(),
            }
        )
        self._store.save(consumed)
        self._record(consumed, action="approval.executed", actor=actor)
        return consumed

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
        self,
        request: ApprovalRequest,
        *,
        action: str,
        actor: ActorRef | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "subject": request.subject.value,
            "subject_id": request.subject_id,
            "assignee_role": request.assignee_role.value,
            "urgency": request.urgency.value,
            "status": request.status.value,
            "escalation_count": request.escalation_count,
            "requested_by_agent": request.requested_by_agent,
        }
        if extra:
            payload.update(extra)
        # The SLA sweep and the expiry pass have no caller to name: they are the
        # engine's own clock, so they say so rather than looking like a person.
        self._audit.append(
            actor=(actor or ActorRef.system("approval-engine")).audit_actor(),
            action=action,
            subject_type="approval",
            subject_id=str(request.id),
            payload=payload,
        )
