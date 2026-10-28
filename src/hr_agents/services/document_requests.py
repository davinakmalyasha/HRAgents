"""Approval-backed requests for employee documents.

Asking an employee for identity documents (KTP, bank details, certificates) is
a sensitive act in itself: an agent that could demand documents directly could
phish. So a request creates an approval, not a task. A named human decides,
and only an approved request becomes a task for the employee. There is no
auto-collection path, no stored request record to drift, and no separate
decision on the task -- the task is the approved outcome, completed by a
human once the document is in the vault.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from hr_agents.errors import DomainCode, DomainError
from hr_agents.identity import ActorRef
from hr_agents.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    DocumentKind,
    TaskItem,
    business_today,
)
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.audit_events import record_audit
from hr_agents.services.employees import EmployeeService
from hr_agents.services.tasks import TaskEngine

DOCUMENT_REQUEST_TASK_SUBJECT = "document_request"


class DocumentRequestError(DomainError, RuntimeError):
    """Raised for invalid document-request operations."""


class DocumentRequestService:
    """Request documents from employees through the human approval queue."""

    def __init__(
        self,
        *,
        employees: EmployeeService,
        tasks: TaskEngine,
        approvals: ApprovalEngine,
        audit: AuditChain | None = None,
    ) -> None:
        self._employees = employees
        self._tasks = tasks
        self._approvals = approvals
        self._audit = audit or AuditChain()

    def request_document(
        self,
        *,
        employee_id: UUID,
        kind: DocumentKind,
        reason: str,
        actor: ActorRef,
        due_on: date | None = None,
    ) -> ApprovalRequest:
        """Ask for a human decision to demand a document from an employee.

        Creating the approval is open to agents: it demands nothing by itself.
        The demand only becomes real when a named human approves it and the
        approval is synced into a task.
        """
        employee = self._employees.get(employee_id)
        if not reason.strip():
            raise DocumentRequestError(
                "a reason is required: demanding an identity document without "
                "stating why is not a request",
                code=DomainCode.VALIDATION_FAILED,
                status=422,
            )
        if due_on is not None and due_on < business_today():
            raise DocumentRequestError(
                f"due_on {due_on.isoformat()} is in the past",
                code=DomainCode.VALIDATION_FAILED,
                status=422,
            )
        existing = self._find_open(employee_id, kind)
        if existing is not None:
            return existing
        request = self._approvals.create(
            subject=ApprovalSubject.DOCUMENT_REQUEST,
            subject_id=str(employee.id),
            title=f"Request {kind.value} from {employee.full_name}",
            summary=reason,
            assignee_role=ApproverRole.MANAGER,
            actor=actor,
            payload={
                "employee_id": str(employee.id),
                "kind": kind.value,
                "reason": reason,
                "due_on": due_on.isoformat() if due_on is not None else None,
            },
        )
        record_audit(
            self._audit,
            actor=actor,
            action="document.requested",
            subject_type="document_request",
            subject_id=str(request.id),
            payload={
                "approval_id": str(request.id),
                "employee_id": str(employee.id),
                "kind": kind.value,
            },
        )
        return request

    def sync_from_approval(self, approval_id: UUID, *, actor: ActorRef) -> TaskItem:
        """Turn an approved request into the employee's task, at most once.

        Only ``APPROVED`` syncs: a rejection, withdrawal or expiry means no
        document was ever demanded, so there is nothing to create and the
        refusal names the outcome instead of an empty task.
        """
        approval = self._approvals.decided(
            approval_id,
            error=DocumentRequestError,
            allowed=(ApprovalStatus.APPROVED,),
            subject="document request",
        )
        existing = self._tasks.open_for_related(
            related_subject=DOCUMENT_REQUEST_TASK_SUBJECT,
            related_id=str(approval.id),
        )
        if existing:
            return existing[0]
        payload = approval.payload
        employee = self._employees.get(UUID(str(payload["employee_id"])))
        kind = str(payload["kind"])
        due_on = (
            date.fromisoformat(str(payload["due_on"]))
            if payload.get("due_on") is not None
            else None
        )
        task = self._tasks.create(
            title=f"Upload requested document — {kind.upper()}",
            description=(
                f"{payload['reason']}\n\nRequested under approval {approval.id}, "
                f"approved by {approval.decided_by}. Upload the document in "
                f"Records → {employee.full_name}'s vault, then complete this task."
            ),
            actor=actor,
            assignee_id=str(employee.id),
            due_on=due_on,
            related_subject=DOCUMENT_REQUEST_TASK_SUBJECT,
            related_id=str(approval.id),
        )
        record_audit(
            self._audit,
            actor=actor,
            action="document.task_created",
            subject_type="task",
            subject_id=str(task.id),
            payload={
                "approval_id": str(approval.id),
                "employee_id": str(employee.id),
                "kind": kind,
            },
        )
        return task

    def _find_open(self, employee_id: UUID, kind: DocumentKind) -> ApprovalRequest | None:
        for request in self._approvals.list_all():
            if request.subject is not ApprovalSubject.DOCUMENT_REQUEST:
                continue
            if request.status not in {
                ApprovalStatus.PENDING,
                ApprovalStatus.ESCALATED,
                ApprovalStatus.APPROVED,
            }:
                continue
            if (
                request.payload.get("employee_id") == str(employee_id)
                and request.payload.get("kind") == kind.value
            ):
                return request
        return None
