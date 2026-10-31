"""Scheduled job runner — time-driven chores across the department engines.

Every job calls an existing engine with an explicit clock; the scheduler owns
no domain rules. Mutating jobs are idempotent by construction (deduplicated
task creation or terminal transitions). The retention sweep is a dry run by
default and only purges with ``purge=True``; breaches are reported, never
acted on, because breach response is a human decision.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from hr_agents.errors import DomainError
from hr_agents.identity import ActorRef, deciding_actor
from hr_agents.logging import get_logger
from hr_agents.models import (
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    StrictModel,
    TaskItem,
    TaskSource,
    UtcDateTime,
    business_today,
    utc_now,
)
from hr_agents.services.queue_ops import EXPIRED_LEASE_GRACE_SECONDS

logger = get_logger(__name__)

if TYPE_CHECKING:
    from hr_agents.messaging.store import ReplyStore
    from hr_agents.providers.queue import QueueBackend
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
JOB_QUEUE_REAPER = "queue-reaper"
JOB_APPROVAL_RECONCILE = "approval-reconcile"
JOB_CALENDAR_SYNC = "calendar-sync"

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
    JOB_QUEUE_REAPER,
    JOB_APPROVAL_RECONCILE,
    JOB_CALENDAR_SYNC,
)

DOCUMENT_EXPIRY_WINDOW_DAYS = 60

REPLY_SLA_HOURS = 72

APPROVAL_SYNC_MAX_ATTEMPTS = 5
"""After this many failed applies the outbox row is closed as ``gave_up`` so one
broken subject cannot occupy the reconciler forever; the last error stays on it."""

APPROVAL_RECONCILE_LIMIT = 500
"""Anti-ghosting window: a dispatched message with no reply gets a follow-up task."""


class ScheduledJobResult(StrictModel):
    """Outcome of one scheduled job: counts, never raw records."""

    name: str
    ok: bool = True
    changed: int = 0
    detail: str = ""
    error: str | None = None


class ApprovalSyncDeferred(RuntimeError):
    """The subject needs a human choice the approval did not carry.

    A scheduling approval approves a proposal that may have offered several
    slots; no single time was agreed, so confirming one here would invent it.
    The decision is applied when the proposal itself says which slot was chosen.
    """


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
    today = as_of or business_today()
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
                actor=ActorRef.system("scheduler"),
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
                actor=ActorRef.system("scheduler"),
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
        queue: QueueBackend | None = None,
        queue_reaper_grace_seconds: float = EXPIRED_LEASE_GRACE_SECONDS,
        calendar: object | None = None,
    ) -> None:
        self._people = people
        self._recruiting = recruiting
        self._replies = replies
        # Tests inject a backend; production resolves it inside the reaper so
        # the async client is created on the loop that will use it.
        self._queue = queue
        self._queue_reaper_grace_seconds = queue_reaper_grace_seconds
        # Injectable free/busy adapter; production resolves it from the provider.
        self._calendar = calendar

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

    def _run_calendar_sync(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        """Refresh mapped interviewers' availability from their calendars."""
        from hr_agents.config import get_settings
        from hr_agents.models import business_timezone
        from hr_agents.services.scheduling_calendar import free_slots

        adapter = self._calendar or _resolve_calendar_adapter()
        if adapter is None:
            return 0, "no calendar provider configured; availability stays manual"
        mappings = self._recruiting.scheduling.list_calendar_mappings()
        if not mappings:
            return 0, "no interviewer has a calendar mapped"
        settings = get_settings()
        timezone = business_timezone()
        start = moment.astimezone(timezone).date()
        end = moment + timedelta(days=settings.calendar_sync_days)
        refreshed = 0
        failed = 0
        for interviewer_id, calendar_id in mappings:
            try:
                busy = adapter.busy(  # type: ignore[attr-defined]
                    start=moment, end=end, calendar_id=calendar_id
                )
            except Exception:
                logger.warning(
                    "scheduler.calendar_sync_failed",
                    interviewer_id=str(interviewer_id),
                    exc_info=True,
                )
                failed += 1
                continue
            slots = free_slots(
                busy,
                start_date=start,
                days=settings.calendar_sync_days,
                work_start_hour=settings.calendar_work_start_hour,
                work_end_hour=settings.calendar_work_end_hour,
                timezone=business_timezone().key,
                now=moment,
            )
            self._recruiting.scheduling.set_availability(
                interviewer_id, slots=slots, actor=ActorRef.system("calendar-sync")
            )
            refreshed += 1
        return refreshed, (
            f"refreshed {refreshed} interviewer calendar(s), {failed} failed "
            f"of {len(mappings)} mapped"
        )

    def _run_approvals(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        escalated = self._people.approvals.escalate_overdue(now=moment)
        expired = self._people.approvals.expire_stale(now=moment)
        return len(escalated) + len(expired), f"escalated {len(escalated)}, expired {len(expired)}"

    def _run_approval_reconcile(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        """Consume the durable outbox a decision committed with its approval.

        The decision and this row are written in one transaction, so a crash
        cannot leave a decided approval whose subject never hears about it. The
        row is applied idempotently: a domain refusal means the subject is
        already settled, while a transport/store failure is retried with a
        bounded attempt count so one bad record cannot wedge the queue forever.
        """
        pending = self._people.approvals.pending_syncs[:APPROVAL_RECONCILE_LIMIT]
        actor = ActorRef.system("approval-reconcile")
        applied = 0
        settled = 0
        failed = 0
        for item in pending:
            apply = self._decision_applier(item.subject)
            outcome: str | None = None
            if apply is None:
                outcome = "no_sync_path"
                settled += 1
            else:
                try:
                    apply(item.approval_id, actor=actor)
                    outcome = "applied"
                    applied += 1
                except ApprovalSyncDeferred:
                    # The decision itself is recorded; what is missing is a choice
                    # only a person can make (which proposed slot was agreed).
                    outcome = "needs_human"
                    settled += 1
                except DomainError:
                    # The subject refused because it is already in the target
                    # state (a replayed decision, or a human settled it first).
                    outcome = "already_settled"
                    settled += 1
                except Exception as exc:
                    attempts = item.attempts + 1
                    failed += 1
                    if attempts < APPROVAL_SYNC_MAX_ATTEMPTS:
                        self._people.approvals.save_pending_sync(
                            item.model_copy(
                                update={"attempts": attempts, "last_error": str(exc)[:500]}
                            )
                        )
                        continue
                    outcome = "gave_up"
                    self._people.approvals.save_pending_sync(
                        item.model_copy(
                            update={
                                "attempts": attempts,
                                "last_error": str(exc)[:500],
                                "consumed_at": moment,
                                "outcome": outcome,
                            }
                        )
                    )
                    continue
            self._people.approvals.save_pending_sync(
                item.model_copy(update={"consumed_at": moment, "outcome": outcome})
            )
        return applied, (
            f"applied {applied}, settled {settled}, failed {failed} "
            f"of {len(pending)} pending sync(s)"
        )

    def _decision_applier(self, subject: ApprovalSubject) -> Callable[..., object] | None:
        """The sync method for the subjects whose engine exposes one."""
        if subject is ApprovalSubject.LEAVE_REQUEST:
            return self._people.leave.apply_decision
        if subject in {ApprovalSubject.PAYROLL_RUN, ApprovalSubject.PAYROLL_ANOMALY}:
            return self._people.payroll.apply_decision
        if subject is ApprovalSubject.ERASURE_REQUEST:
            return self._people.compliance.apply_decision
        if subject is ApprovalSubject.OFFER:
            return self._apply_offer_sync
        if subject is ApprovalSubject.SCHEDULING:
            return self._apply_scheduling_sync
        return None

    def _apply_offer_sync(self, approval_id: UUID, *, actor: ActorRef) -> object:
        """Replay an offer approval's outcome onto the offer record.

        The approval decision is the gate; an offer still `pending_approval`
        after it is the half-state this closes. A rejection withdraws the offer
        with the decision's reason rather than approving it, and a status with no
        offer transition is a domain refusal the reconciler treats as settled.
        """
        approval = self._people.approvals.find(approval_id)
        if approval is None or approval.decided_by is None:
            raise DomainError(f"approval {approval_id} has no named decider to replay")
        human = deciding_actor(approval.decided_by)
        offer_id = UUID(approval.subject_id)
        if approval.status is ApprovalStatus.APPROVED:
            return self._recruiting.offers.decide(offer_id, decision="approve", actor=human)
        if approval.status is ApprovalStatus.REJECTED:
            reason = (approval.decision_reason or "").strip() or (
                "the linked offer approval was rejected"
            )
            return self._recruiting.offers.decide(
                offer_id, decision="withdraw", actor=human, reason=reason
            )
        raise DomainError(f"approval is {approval.status.value}; no offer transition")

    def _apply_scheduling_sync(self, approval_id: UUID, *, actor: ActorRef) -> object:
        """Apply a scheduling decision only when the agreed time is unambiguous."""
        approval = self._people.approvals.find(approval_id)
        if approval is None or approval.decided_by is None:
            raise DomainError(f"approval {approval_id} has no named decider to replay")
        human = deciding_actor(approval.decided_by)
        proposal = self._recruiting.scheduling.get(UUID(approval.subject_id))
        if approval.status is ApprovalStatus.APPROVED:
            if len(proposal.payload.slots) != 1:
                raise ApprovalSyncDeferred(
                    "the proposal offered several slots; a human must choose which was agreed"
                )
            return self._recruiting.scheduling.decide(proposal.id, decision="confirm", actor=human)
        if approval.status is ApprovalStatus.REJECTED:
            reason = (approval.decision_reason or "").strip() or (
                "the linked scheduling approval was rejected"
            )
            return self._recruiting.scheduling.decide(
                proposal.id, decision="cancel", actor=human, reason=reason
            )
        raise DomainError(f"approval is {approval.status.value}; no scheduling transition")

    def _run_retention(self, moment: datetime, purge: bool) -> tuple[int, str]:
        report = self._people.compliance.execute_purge(
            actor=ActorRef.system("retention-sweep"), as_of=moment, dry_run=not purge
        )
        detail = f"purged {len(report.purged)}, held {len(report.held)}"
        if report.skipped:
            entities = ", ".join(sorted({item.entity.value for item in report.skipped}))
            detail += f", SKIPPED {len(report.skipped)} with no store handler ({entities})"
        if not purge:
            return 0, detail + " (dry run)"
        return len(report.purged), detail

    def _run_breaches(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        steps = self._people.compliance.overdue_steps(as_of=moment)
        return 0, f"{len(steps)} overdue step(s) awaiting a human"

    def _run_growth(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        # The scheduler really is the cause here, so it says so rather than
        # borrowing an operator's name. The HTTP route passes the person instead.
        reminders = self._people.growth.run_reminders(
            as_of=moment.date(), actor=ActorRef.system("scheduler")
        )
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
        expired = self._recruiting.offers.expire_overdue(
            now=moment, actor=ActorRef.system("offer-expiry")
        )
        return len(expired), f"{len(expired)} offer(s) expired"

    def _run_tasks_overdue(self, moment: datetime, _purge: bool) -> tuple[int, str]:
        items = self._people.tasks.overdue(as_of=moment.date())
        return 0, f"{len(items)} open overdue task(s)"

    def _run_audit_verify(self, _moment: datetime, _purge: bool) -> tuple[int, str]:
        report = self._people.compliance.verify_audit_chain(actor=ActorRef.system("audit-verify"))
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

    def _run_queue_reaper(self, _moment: datetime, _purge: bool) -> tuple[int, str]:
        """Return leases whose worker died or wedged to the pending list.

        ``claim`` already recovers an expired lease lazily; this runs from the
        scheduler's separate process, so a worker stuck *on the handler* can
        have its message retried without waiting for that worker to loop again.
        """
        import asyncio

        from hr_agents.queue import QueueUnavailableError, resolve_queue_backend
        from hr_agents.services.evaluation_job import EVALUATION_TOPIC
        from hr_agents.services.queue_ops import reap_expired_leases

        async def reap() -> int:
            queue = self._queue if self._queue is not None else await resolve_queue_backend()
            return await reap_expired_leases(
                queue,
                (EVALUATION_TOPIC,),
                grace_seconds=self._queue_reaper_grace_seconds,
            )

        try:
            requeued = asyncio.run(reap())
        except QueueUnavailableError:
            return 0, "no queue backend available; nothing to reap"
        return requeued, f"{requeued} stale lease(s) requeued"


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
    JOB_QUEUE_REAPER: Scheduler._run_queue_reaper,
    JOB_APPROVAL_RECONCILE: Scheduler._run_approval_reconcile,
    JOB_CALENDAR_SYNC: Scheduler._run_calendar_sync,
}


def _resolve_calendar_adapter() -> object | None:
    """Build the configured free/busy adapter, or ``None`` when calendar is manual."""
    from hr_agents.providers.base import Capability
    from hr_agents.providers.registry import default_registry
    from hr_agents.providers.settings import resolve_provider_settings

    resolved = resolve_provider_settings().get(Capability.CALENDAR)
    if resolved is None or resolved.provider_id != "calendar.google":
        return None
    spec = default_registry().get(resolved.provider_id)
    if spec.build is None:
        return None
    try:
        return spec.build(spec.make_config(resolved.config))
    except Exception:
        logger.warning("scheduler.calendar_unavailable", exc_info=True)
        return None


def alert_payload(report: SchedulerReport) -> dict[str, object]:
    """A Slack-compatible summary of a failed run, with no secrets in it.

    The report contains job names, counts and error strings; it never contains a
    record, a person or a configured credential. That is what makes it safe to
    send to a chat channel an operator watches.
    """
    failed = [job for job in report.jobs if not job.ok]
    detail = "; ".join(f"{job.name}: {job.error or 'unknown error'}" for job in failed)
    return {
        "text": (
            f"HRAgents scheduler: {len(failed)} of {len(report.jobs)} job(s) failed"
            + (f" — {detail}" if detail else "")
        ),
        "started_at": report.started_at.isoformat(),
        "dry_run": report.dry_run,
        "failed_jobs": [{"name": job.name, "error": job.error} for job in failed],
    }


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _alert_url_is_allowed(url: str, *, allow_insecure_http: bool) -> bool:
    """HTTPS always; plain HTTP only for loopback or an explicit opt-in.

    Parse rather than ``startswith``: ``https://`` as a prefix accepts
    ``https://user:pass@host`` and ``https://host\\@evil`` shapes, and a scheme
    check that a parser does not agree with is not a check.
    """
    parts = urlsplit(url)
    if parts.scheme == "https":
        return bool(parts.hostname)
    if parts.scheme != "http" or not parts.hostname:
        return False
    if allow_insecure_http:
        return True
    return parts.hostname.lower() in _LOOPBACK_HOSTS


def send_failure_alert(
    report: SchedulerReport,
    webhook: str,
    *,
    post: Callable[..., object] | None = None,
    timeout: float = 5.0,
    allow_insecure_http: bool = False,
) -> bool:
    """POST the failure summary when a run failed; True only if a request went out.

    Never raises: an unreachable chat channel must not turn a failed job into a
    crashed clock. The webhook URL is a bearer credential, so it stays out of
    the payload and the log line.

    HTTPS only unless the operator opts in or the target is loopback: an alert
    names failed jobs and their errors, and sending that in cleartext across a
    network is a leak the operator did not ask for. A LAN relay
    (Mattermost/Rocket.Chat over plain HTTP) still works through the explicit
    flag, and a local development sink needs no flag at all.
    """
    if not webhook or all(job.ok for job in report.jobs):
        return False
    if not _alert_url_is_allowed(webhook, allow_insecure_http=allow_insecure_http):
        logger.warning(
            "scheduler.alert_skipped",
            reason="webhook must be https (or loopback / explicitly allowed http)",
        )
        return False
    sender = post or httpx.post
    try:
        response = sender(webhook, json=alert_payload(report), timeout=timeout)
    except Exception:
        logger.warning("scheduler.alert_failed", reason="transport", exc_info=True)
        return False
    status_code = getattr(response, "status_code", 0)
    if status_code >= 400:
        logger.warning("scheduler.alert_failed", reason="response", status=status_code)
        return False
    logger.info("scheduler.alerted", failed=sum(1 for job in report.jobs if not job.ok))
    return True
