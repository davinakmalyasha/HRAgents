"""Scheduled job runner — time-driven chores across the department engines.

Every job calls an existing engine with an explicit clock; the scheduler owns
no domain rules. Mutating jobs are idempotent by construction (deduplicated
task creation or terminal transitions). The retention sweep is a dry run by
default and only purges with ``purge=True``; breaches are reported, never
acted on, because breach response is a human decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING

from hr_agents.models import (
    ApproverRole,
    StrictModel,
    TaskItem,
    TaskSource,
    UtcDateTime,
    utc_now,
)

if TYPE_CHECKING:
    from hr_agents.messaging.store import ReplyStore
    from hr_agents.services.employees import EmployeeService
    from hr_agents.services.people import PeopleServices
    from hr_agents.services.recruiting import CommunicationService, RecruitingServices
    from hr_agents.services.tasks import TaskEngine

JOB_APPROVALS = "approvals"
JOB_RETENTION = "retention"
JOB_BREACHES = "breaches"
JOB_GROWTH = "growth"
JOB_CONTRACT_EXPIRY = "contract-expiry"
JOB_DOCUMENT_EXPIRY = "document-expiry"
JOB_OFFER_EXPIRY = "offer-expiry"
JOB_TASKS_OVERDUE = "tasks-overdue"
JOB_AUDIT_VERIFY = "audit-verify"
JOB_REPLY_SLA = "reply-sla"

JOB_NAMES: tuple[str, ...] = (
    JOB_APPROVALS,
    JOB_RETENTION,
    JOB_BREACHES,
    JOB_GROWTH,
    JOB_CONTRACT_EXPIRY,
    JOB_DOCUMENT_EXPIRY,
    JOB_OFFER_EXPIRY,
    JOB_TASKS_OVERDUE,
    JOB_AUDIT_VERIFY,
    JOB_REPLY_SLA,
)

DOCUMENT_EXPIRY_WINDOW_DAYS = 60

REPLY_SLA_HOURS = 72
"""Anti-ghosting window: a dispatched message with no reply gets a follow-up task."""


class ScheduledJobResult(StrictModel):
    """Outcome of one scheduled job: counts, never raw records."""

    name: str
    ok: bool = True
    changed: int = 0
    detail: str = ""
    error: str | None = None


class SchedulerReport(StrictModel):
    """One run across the selected jobs."""

    started_at: UtcDateTime
    finished_at: UtcDateTime
    dry_run: bool
    jobs: list[ScheduledJobResult]


def document_expiry_tasks(
    employees: EmployeeService,
    tasks: TaskEngine,
    *,
    within_days: int = DOCUMENT_EXPIRY_WINDOW_DAYS,
    as_of: date | None = None,
) -> list[TaskItem]:
    """Create reminder tasks for expiring employee documents (once per document)."""
    today = as_of or date.today()
    existing = {(task.related_subject, task.related_id) for task in tasks.open_tasks()}
    created: list[TaskItem] = []
    for document in employees.expiring_documents(within_days=within_days):
        key = ("employee_document", str(document.id))
        if key in existing or document.expires_on is None:
            continue
        days = (document.expires_on - today).days
        created.append(
            tasks.create(
                title=f"Document expiring in {days} days — {document.kind.value.upper()}",
                created_by="system",
                description=(
                    "Collect a fresh copy before "
                    f"{document.expires_on.isoformat()} and verify it in the vault."
                ),
                assignee_role=ApproverRole.HR_ADMIN,
                due_on=document.expires_on,
                source=TaskSource.SYSTEM,
                related_subject="employee_document",
                related_id=str(document.id),
            )
        )
    return created


def reply_sla_tasks(
    communications: CommunicationService,
    tasks: TaskEngine,
    replies: ReplyStore,
    *,
    within_hours: int = REPLY_SLA_HOURS,
    as_of: datetime | None = None,
) -> list[TaskItem]:
    """Flag dispatched messages that went unanswered (one task per message).

    A candidate who never heard back is the failure mode this prevents. The
    window is counted from the dispatch, and any reply the candidate sent after
    that moment counts as an answer — nothing is chased automatically, a person
    picks the task up.
    """
    moment = as_of or utc_now()
    existing = {(task.related_subject, task.related_id) for task in tasks.open_tasks()}
    created: list[TaskItem] = []
    for message in communications.list_sent():
        if message.sent_at is None:
            continue
        deadline = message.sent_at.timestamp() + within_hours * 3600
        if moment.timestamp() < deadline:
            continue
        key = ("candidate_communication", str(message.id))
        if key in existing:
            continue
        answered = any(
            reply.candidate_id == message.candidate_id and reply.received_at >= message.sent_at
            for reply in replies.list_for(message.candidate_id)
        )
        if answered:
            continue
        created.append(
            tasks.create(
                title=f"No reply to the {message.kind.value} message in {within_hours}h",
                created_by="system",
                description=(
                    f"Sent to {message.recipient or message.recipient_phone or 'the candidate'} "
                    f"on {message.sent_at.isoformat()} with no answer since. Follow up, or "
                    "close the loop deliberately."
                ),
                assignee_role=ApproverRole.RECRUITER_LEAD,
                due_on=moment.date(),
                source=TaskSource.SYSTEM,
                related_subject="candidate_communication",
                related_id=str(message.id),
            )
        )
    return created


def format_report(report: SchedulerReport) -> str:
    """Human-readable one-line-per-job summary for logs and the CLI."""
    headline = f"Scheduler run at {report.started_at.isoformat()}"
    if report.dry_run:
        headline += " (dry run)"
    lines = [headline]
    for job in report.jobs:
        status = "ok" if job.ok else f"FAILED: {job.error}"
        summary = f"  {job.name}: {status} - changed {job.changed}"
        if job.detail:
            summary += f" ({job.detail})"
        lines.append(summary)
    return "\n".join(lines)


class Scheduler:
    """Run the department clock chores against live service containers."""

    def __init__(
        self,
        *,
        people: PeopleServices,
        recruiting: RecruitingServices,
        replies: ReplyStore | None = None,
    ) -> None:
        self._people = people
        self._recruiting = recruiting
        self._replies = replies

    def run(
        self,
        jobs: Sequence[str] | None = None,
        *,
        now: datetime | None = None,
        purge: bool = False,
    ) -> SchedulerReport:
        """Run the selected jobs (all by default); unknown names are refused."""
        names = list(JOB_NAMES) if jobs is None else list(jobs)
        unknown = [name for name in names if name not in JOB_NAMES]
        if unknown:
            raise ValueError(f"unknown scheduled job(s): {', '.join(sorted(unknown))}")
        started = now or utc_now()
        results = [self.run_job(name, now=started, purge=purge) for name in names]
        return SchedulerReport(
            started_at=started,
            finished_at=utc_now(),
            dry_run=not purge,
            jobs=results,
        )

    def run_job(self, name: str, *, now: datetime, purge: bool) -> ScheduledJobResult:
        """Run one job and record (never raise) its failure."""
        handler = _HANDLERS[name]
        try:
            changed, detail = handler(self, now, purge)
        except Exception as exc:  # keep the rest of the run alive
            return ScheduledJobResult(name=name, ok=False, detail="", error=str(exc))
        return ScheduledJobResult(name=name, ok=True, changed=changed, detail=detail)

    # job implementations (thin wrappers over the engines)

    def _run_approvals(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        escalated = self._people.approvals.escalate_overdue(now=moment)
        expired = self._people.approvals.expire_stale(now=moment)
        return len(escalated) + len(expired), f"escalated {len(escalated)}, expired {len(expired)}"

    def _run_retention(self, moment: datetime, purge: bool) -> tuple[int, str]:
        report = self._people.compliance.execute_purge(by="system", as_of=moment, dry_run=not purge)
        detail = f"purged {len(report.purged)}, held {len(report.held)}"
        if not purge:
            return 0, detail + " (dry run)"
        return len(report.purged), detail

    def _run_breaches(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        steps = self._people.compliance.overdue_steps(as_of=moment)
        return 0, f"{len(steps)} overdue step(s) awaiting a human"

    def _run_growth(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        reminders = self._people.growth.run_reminders(as_of=moment.date())
        return len(reminders), f"{len(reminders)} review reminder task(s)"

    def _run_contract_expiry(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        tasks = self._people.contracts.create_expiry_tasks(as_of=moment.date())
        return len(tasks), f"{len(tasks)} contract reminder task(s)"

    def _run_document_expiry(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        tasks = document_expiry_tasks(
            self._people.employees, self._people.tasks, as_of=moment.date()
        )
        return len(tasks), f"{len(tasks)} document reminder task(s)"

    def _run_offer_expiry(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        expired = self._recruiting.offers.expire_overdue(now=moment)
        return len(expired), f"{len(expired)} offer(s) expired"

    def _run_tasks_overdue(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        items = self._people.tasks.overdue(as_of=moment.date())
        return 0, f"{len(items)} open overdue task(s)"

    def _run_audit_verify(self, _moment: datetime, _purge: bool) -> tuple[int, str]:
        report = self._people.compliance.verify_audit_chain(checked_by="system")
        state = "intact" if report.intact else f"BROKEN at seq {report.first_invalid_seq}"
        return 0, f"chain {state} ({report.entry_count} entries)"

    def _run_reply_sla(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        if self._replies is None:
            return 0, "no reply store attached; inbound capture is not running"
        tasks = reply_sla_tasks(
            self._recruiting.communications,
            self._people.tasks,
            self._replies,
            as_of=moment,
        )
        return len(tasks), f"{len(tasks)} unanswered message(s) flagged for follow-up"


_HANDLERS = {
    JOB_APPROVALS: Scheduler._run_approvals,
    JOB_RETENTION: Scheduler._run_retention,
    JOB_BREACHES: Scheduler._run_breaches,
    JOB_GROWTH: Scheduler._run_growth,
    JOB_CONTRACT_EXPIRY: Scheduler._run_contract_expiry,
    JOB_DOCUMENT_EXPIRY: Scheduler._run_document_expiry,
    JOB_OFFER_EXPIRY: Scheduler._run_offer_expiry,
    JOB_TASKS_OVERDUE: Scheduler._run_tasks_overdue,
    JOB_AUDIT_VERIFY: Scheduler._run_audit_verify,
    JOB_REPLY_SLA: Scheduler._run_reply_sla,
}
