"""Leave service — policies, accrual, balances, requests, and calendars.

Deterministic: no LLM. Accrual math is pure date arithmetic over operator-set
policy values. Requests flow through the approval engine (humans decide).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, timedelta
from uuid import UUID

from hr_agents.errors import DomainError
from hr_agents.identity import ActorRef, deciding_actor
from hr_agents.logging import get_logger
from hr_agents.models import (
    AccrualMethod,
    ApprovalSubject,
    Employee,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    LeaveTypePolicy,
    RequestStatus,
    utc_now,
)
from hr_agents.services.approvals import ApprovalEngine, ApprovalError
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService

logger = get_logger(__name__)


class LeaveError(DomainError, RuntimeError):
    """Raised for invalid leave operations."""


WEEKEND_DAYS = frozenset({5, 6})  # Saturday, Sunday


class LeaveService:
    """Leave policies, balances, and request lifecycle."""

    def __init__(
        self,
        *,
        employees: EmployeeService,
        approvals: ApprovalEngine,
        audit: AuditChain | None = None,
        holidays: list[date] | None = None,
    ) -> None:
        self._employees = employees
        self._approvals = approvals
        self._audit = audit or AuditChain()
        self._policies: dict[LeaveType, LeaveTypePolicy] = {}
        self._requests: dict[UUID, LeaveRequest] = {}
        self._adjustments: dict[tuple[UUID, LeaveType, int], float] = {}
        self._holidays: set[date] = set(holidays or [])
        self._holiday_cache: set[date] | None = None

    # --- persistence primitives -----------------------------------------
    #
    # Adapters override only these. Every balance computation, overlap check and
    # lifecycle rule above stays here, where it is testable without a database.
    #
    # These existed because leaving state in plain dicts meant a restart lost
    # approved leave requests, balance adjustments and the holiday calendar. The
    # last two fail *silently* rather than visibly: a lost holiday set under-counts
    # working days, and a lost adjustment overstates the balance.

    def _load_request(self, request_id: UUID) -> LeaveRequest | None:
        return self._requests.get(request_id)

    def _iter_requests(self) -> Iterator[LeaveRequest]:
        return iter(list(self._requests.values()))

    def _save_request(self, request: LeaveRequest) -> None:
        self._requests[request.id] = request

    def _load_policy(self, leave_type: LeaveType) -> LeaveTypePolicy | None:
        return self._policies.get(leave_type)

    def _iter_policies(self) -> Iterator[LeaveTypePolicy]:
        return iter(list(self._policies.values()))

    def _save_policy(self, policy: LeaveTypePolicy) -> None:
        self._policies[policy.leave_type] = policy

    def _load_adjustment(self, employee_id: UUID, leave_type: LeaveType, year: int) -> float:
        return self._adjustments.get((employee_id, leave_type, year), 0.0)

    def _save_adjustment(
        self, employee_id: UUID, leave_type: LeaveType, year: int, days: float
    ) -> None:
        self._adjustments[(employee_id, leave_type, year)] = days

    def _iter_holidays(self) -> Iterator[date]:
        return iter(sorted(self._holidays))

    def _save_holidays(self, holidays: Iterable[date]) -> None:
        self._holidays = set(holidays)
        self._holiday_cache = self._holidays

    def _all_holidays(self) -> set[date]:
        """The whole holiday set, loaded once per process.

        `is_working_day` is called once per candidate day by `working_days`, so
        reading the primitives directly would mean one database round trip per day
        of every range. The calendar is written rarely and only through
        `_save_holidays`, which invalidates the cache.
        """
        if self._holiday_cache is None:
            self._holiday_cache = set(self._iter_holidays())
        return self._holiday_cache

    # --- policy management ----------------------------------------------

    def set_policy(self, policy: LeaveTypePolicy, *, actor: ActorRef) -> LeaveTypePolicy:
        """Install a leave policy. Accrual, caps, and minimum service are money-like
        rules that change for every employee at once, so a named human sets them."""
        actor.require_human("setting a leave policy", LeaveError)
        self._save_policy(policy)
        self._record(
            action="leave.policy_set",
            subject_type="leave_policy",
            subject_id=policy.leave_type.value,
            actor=actor,
            payload={
                "name": policy.name,
                "paid": policy.paid,
                "accrual_method": policy.accrual_method.value,
                "days_per_year": policy.days_per_year,
                "days_per_month": policy.days_per_month,
            },
        )
        return policy

    def get_policy(self, leave_type: LeaveType) -> LeaveTypePolicy:
        policy = self._load_policy(leave_type)
        if policy is None:
            raise LeaveError(f"no policy configured for {leave_type.value}; HR must set it first")
        return policy

    def list_policies(self) -> list[LeaveTypePolicy]:
        return sorted(self._iter_policies(), key=lambda item: item.leave_type.value)

    def set_holidays(self, holidays: list[date], *, actor: ActorRef) -> int:
        """Set public holidays (affects working-day computations)."""
        self._save_holidays(holidays)
        self._record(
            action="leave.holidays_set",
            subject_type="leave_calendar",
            subject_id="public_holidays",
            actor=actor,
            payload={"count": len(holidays)},
        )
        return len(holidays)

    # --- working-day math ------------------------------------------------

    def is_working_day(self, day: date) -> bool:
        return day.weekday() not in WEEKEND_DAYS and day not in self._all_holidays()

    def working_days(self, start: date, end: date) -> float:
        """Count working days in the inclusive range."""
        if end < start:
            raise LeaveError("end date cannot precede start date")
        count = 0
        current = start
        while current <= end:
            if self.is_working_day(current):
                count += 1
            current += timedelta(days=1)
        return float(count)

    def count_days(self, policy: LeaveTypePolicy, start: date, end: date) -> float:
        return (
            self.working_days(start, end)
            if policy.working_days_only
            else float((end - start).days + 1)
        )

    # --- balances --------------------------------------------------------

    def _months_employed(self, employee: Employee, *, as_of: date) -> int:
        if employee.hire_date is None:
            return 0
        months = (as_of.year - employee.hire_date.year) * 12 + (
            as_of.month - employee.hire_date.month
        )
        if as_of.day < employee.hire_date.day:
            months -= 1
        return max(months, 0)

    def _used_days(
        self, employee_id: UUID, leave_type: LeaveType, year: int
    ) -> tuple[float, float]:
        used = 0.0
        pending = 0.0
        for request in self._iter_requests():
            if request.employee_id != employee_id or request.leave_type is not leave_type:
                continue
            if request.start_date.year != year:
                continue
            if request.status is RequestStatus.APPROVED:
                used += request.days
            elif request.status in {RequestStatus.PENDING, RequestStatus.DRAFT}:
                pending += request.days
        return round(used, 4), round(pending, 4)

    def _carryover(self, employee: Employee, leave_type: LeaveType, year: int) -> float:
        """Carryover from the previous year, if the policy allows it."""
        policy = self.get_policy(leave_type)
        if not policy.carryover_allowed or policy.carryover_max_days is None:
            return 0.0
        previous_entitlement = self._entitlement(
            employee, policy, year=year - 1, as_of=date(year - 1, 12, 31)
        )
        previous_used, _ = self._used_days(employee.id, leave_type, year - 1)
        unused = max(previous_entitlement - previous_used, 0.0)
        return round(min(unused, policy.carryover_max_days), 4)

    def _entitlement(
        self,
        employee: Employee,
        policy: LeaveTypePolicy,
        *,
        year: int,
        as_of: date,
    ) -> float:
        if employee.hire_date is None:
            return 0.0
        months_total = self._months_employed(employee, as_of=as_of)
        if months_total < policy.min_service_months:
            return 0.0

        if policy.accrual_method in {AccrualMethod.NONE, AccrualMethod.PER_EVENT_CAP}:
            return 0.0

        if policy.accrual_method is AccrualMethod.FLAT_MONTHLY:
            # Months worked within the target year, capped at 12.
            year_start = date(year, 1, 1)
            months_before_year = self._months_employed(employee, as_of=year_start)
            months_this_year = max(0, min(12, months_total - months_before_year))
            return round((policy.days_per_month or 0.0) * months_this_year, 4)

        # LUMP_SUM_ANNUAL: full entitlement once service requirement is met.
        return policy.days_per_year or 0.0

    def balance(
        self, employee_id: UUID, leave_type: LeaveType, *, year: int | None = None
    ) -> LeaveBalance:
        """An employee's entitlement. A read, so it carries no actor and no gate.

        ``request`` checks that the caller may act for this employee before it
        calls this; the router's ``people:read`` governs who may look. Putting an
        ownership check here would gate a read on the same rule as the write that
        consults it.
        """
        employee = self._require_employee(employee_id)
        policy = self.get_policy(leave_type)
        target_year = year or date.today().year
        today = date.today()

        as_of = (
            min(today, date(target_year, 12, 31))
            if target_year == today.year
            else date(target_year, 12, 31)
        )
        entitled = self._entitlement(employee, policy, year=target_year, as_of=as_of)
        accrued = entitled if policy.accrual_method is AccrualMethod.FLAT_MONTHLY else 0.0
        used, pending = self._used_days(employee_id, leave_type, target_year)
        carried = self._carryover(employee, leave_type, target_year)
        adjustment = self._load_adjustment(employee_id, leave_type, target_year)

        return LeaveBalance(
            employee_id=employee_id,
            leave_type=leave_type,
            year=target_year,
            entitled=entitled,
            accrued=accrued,
            used=used,
            pending=pending,
            carried_over=carried,
            adjustment=adjustment,
        )

    def all_balances(self, employee_id: UUID, *, year: int | None = None) -> list[LeaveBalance]:
        return [
            self.balance(employee_id, policy.leave_type, year=year)
            for policy in self.list_policies()
        ]

    def adjust_balance(
        self,
        employee_id: UUID,
        leave_type: LeaveType,
        *,
        days: float,
        year: int | None = None,
        actor: ActorRef,
        reason: str | None = None,
    ) -> LeaveBalance:
        """Manual adjustment (positive or negative) — always audited.

        A balance is a money-like entitlement, so an agent may not move one; the
        human attribution is what makes the ledger entry reviewable.
        """
        actor.require_human("adjusting a leave balance", LeaveError)
        self._require_employee(employee_id)
        self.get_policy(leave_type)
        target_year = year or date.today().year
        self._save_adjustment(
            employee_id,
            leave_type,
            target_year,
            self._load_adjustment(employee_id, leave_type, target_year) + days,
        )
        self._record(
            action="leave.balance_adjusted",
            subject_type="leave_balance",
            subject_id=str(employee_id),
            actor=actor,
            payload={
                "leave_type": leave_type.value,
                "days": days,
                "year": target_year,
                "reason": reason,
            },
        )
        return self.balance(employee_id, leave_type, year=target_year)

    # --- requests --------------------------------------------------------

    def request(
        self,
        *,
        employee_id: UUID,
        leave_type: LeaveType,
        start_date: date,
        end_date: date,
        actor: ActorRef,
        reason: str | None = None,
        document_id: UUID | None = None,
    ) -> LeaveRequest:
        """Submit a leave request and route it to the approver.

        ``employee_id`` used to be taken on trust: any caller could file leave
        for any employee, which is harmless while only HR can reach this method
        and not harmless the moment employees can request their own. The caller
        must now be that employee, their manager, or hold ``people:write``.
        """
        employee = self._require_employee(employee_id)
        actor.require_may_act_for(
            employee_id,
            "request leave",
            LeaveError,
            owner_manager_id=employee.manager_id,
        )
        policy = self.get_policy(leave_type)

        days = self.count_days(policy, start_date, end_date)
        if days <= 0:
            raise LeaveError("request contains no working days")

        if policy.requires_document and document_id is None:
            raise LeaveError(f"{leave_type.value} leave requires a supporting document")
        if policy.max_days_per_request is not None and days > policy.max_days_per_request:
            raise LeaveError(
                f"{days} days exceeds the {policy.max_days_per_request}-day cap for "
                f"{leave_type.value}"
            )
        if policy.max_consecutive_days is not None and days > policy.max_consecutive_days:
            raise LeaveError(
                f"{days} consecutive days exceeds the limit of {policy.max_consecutive_days}"
            )

        months = self._months_employed(employee, as_of=start_date)
        if months < policy.min_service_months:
            raise LeaveError(
                f"{leave_type.value} requires {policy.min_service_months} months of service "
                f"(employee has {months})"
            )

        balance = self.balance(employee_id, leave_type, year=start_date.year)
        tracks_balance = policy.accrual_method not in {
            AccrualMethod.NONE,
            AccrualMethod.PER_EVENT_CAP,
        }
        if tracks_balance and days > balance.available:
            raise LeaveError(
                f"insufficient balance: requested {days}, available {balance.available}"
            )

        conflicts = self.overlapping(employee_id, start_date, end_date)
        if conflicts:
            raise LeaveError(
                "overlaps an existing request: " + ", ".join(str(item.id) for item in conflicts)
            )

        request = LeaveRequest(
            employee_id=employee_id,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            days=days,
            reason=reason,
            document_id=document_id,
            status=RequestStatus.PENDING,
        )

        if policy.requires_approval:
            approval = self._approvals.create(
                subject=ApprovalSubject.LEAVE_REQUEST,
                subject_id=str(request.id),
                title=(
                    f"{policy.name}: {employee.full_name} "
                    f"({start_date.isoformat()} → {end_date.isoformat()}, {days:g} days)"
                ),
                assignee_role=policy.approver_role,
                actor=actor,
                summary=reason or "",
                payload={
                    "employee_id": str(employee_id),
                    "leave_type": leave_type.value,
                    "days": days,
                },
            )
            request = request.model_copy(update={"approval_id": approval.id})
        else:
            # Auto-tier: no approval required; record the request as approved.
            request = request.model_copy(update={"status": RequestStatus.APPROVED})

        self._save_request(request)
        self._record(
            action="leave.request_submitted",
            subject_type="leave_request",
            subject_id=str(request.id),
            actor=actor,
            payload={
                "employee_id": str(employee_id),
                "leave_type": leave_type.value,
                "days": days,
                "status": request.status.value,
                "approval_id": str(request.approval_id) if request.approval_id else None,
            },
        )
        return request

    def apply_decision(self, approval_id: UUID, *, actor: ActorRef) -> LeaveRequest:
        """Sync a request with its approval's outcome (called by the app layer)."""
        request = next(
            (item for item in self._iter_requests() if item.approval_id == approval_id),
            None,
        )
        if request is None:
            raise LeaveError(f"no leave request linked to approval {approval_id}")

        approval = self._approvals._store.get(approval_id)
        if approval is None:
            raise LeaveError(f"unknown approval {approval_id}")

        from hr_agents.models import ApprovalStatus

        mapping = {
            ApprovalStatus.APPROVED: RequestStatus.APPROVED,
            ApprovalStatus.REJECTED: RequestStatus.REJECTED,
            ApprovalStatus.WITHDRAWN: RequestStatus.CANCELLED,
            ApprovalStatus.EXPIRED: RequestStatus.REJECTED,
        }
        target = mapping.get(approval.status)
        if target is None:
            raise LeaveError(
                f"approval {approval_id} is {approval.status.value}; no request transition"
            )

        updated = request.model_copy(update={"status": target, "updated_at": utc_now()})
        self._save_request(updated)
        self._record(
            action=f"leave.request_{target.value}",
            subject_type="leave_request",
            subject_id=str(updated.id),
            # The approver is the actor; the caller only triggered the sync.
            actor=deciding_actor(approval.decided_by),
            payload={
                "approval_id": str(approval_id),
                "status": target.value,
                "synced_by": actor.actor_id,
            },
        )
        return updated

    def cancel(
        self, request_id: UUID, *, actor: ActorRef, reason: str | None = None
    ) -> LeaveRequest:
        request = self._require_request(request_id)
        # Cancelling somebody else's leave is as consequential as filing it, and this
        # took no ownership check at all: the caller only had to know the id.
        owner = self._require_employee(request.employee_id)
        actor.require_may_act_for(
            request.employee_id,
            "cancel a leave request",
            LeaveError,
            owner_manager_id=owner.manager_id,
        )
        if request.status not in {RequestStatus.PENDING, RequestStatus.DRAFT}:
            raise LeaveError(f"request {request_id} is {request.status.value}; cannot cancel")
        # The router was already accepting a `reason` and then dropping it on the floor,
        # so the record said "cancelled" with no way to tell a withdrawn trip from a
        # change of plan two months later.
        cleaned_reason = (reason or "").strip()
        if not cleaned_reason:
            raise LeaveError("cancelling a leave request requires a reason")
        if request.approval_id is not None:
            try:
                self._approvals.withdraw(
                    request.approval_id,
                    actor=actor,
                    reason=f"request cancelled: {cleaned_reason}",
                )
            except ApprovalError as exc:
                # Only an already-terminal approval is an expected outcome here:
                # cancelling after a decision landed is a no-op, not a failure.
                # Anything else used to disappear into `suppress(Exception)`, which
                # meant an authority refusal left the approval pending and
                # unrecorded while the request showed as cancelled -- two rows
                # disagreeing with no audit entry explaining why.
                self._record(
                    action="leave.approval_not_withdrawn",
                    subject_type="leave_request",
                    subject_id=str(request.id),
                    actor=actor,
                    payload={"approval_id": str(request.approval_id), "reason": str(exc)},
                )
                logger.warning(
                    "leave_approval_not_withdrawn",
                    request_id=str(request.id),
                    approval_id=str(request.approval_id),
                    reason=str(exc),
                )
        updated = request.model_copy(
            update={"status": RequestStatus.CANCELLED, "updated_at": utc_now()}
        )
        self._save_request(updated)
        self._record(
            action="leave.request_cancelled",
            subject_type="leave_request",
            subject_id=str(updated.id),
            actor=actor,
            payload={
                "approval_id": str(request.approval_id) if request.approval_id else None,
                "reason": cleaned_reason,
            },
        )
        return updated

    # --- queries ---------------------------------------------------------

    def get_request(self, request_id: UUID) -> LeaveRequest:
        return self._require_request(request_id)

    def requests_for(self, employee_id: UUID) -> list[LeaveRequest]:
        return sorted(
            (item for item in self._iter_requests() if item.employee_id == employee_id),
            key=lambda item: item.start_date,
        )

    def pending_requests(self) -> list[LeaveRequest]:
        return sorted(
            (item for item in self._iter_requests() if item.status is RequestStatus.PENDING),
            key=lambda item: item.start_date,
        )

    def overlapping(self, employee_id: UUID, start: date, end: date) -> list[LeaveRequest]:
        """Active (non-cancelled/rejected) requests overlapping the range."""
        return [
            item
            for item in self._iter_requests()
            if item.employee_id == employee_id
            and item.status in {RequestStatus.PENDING, RequestStatus.APPROVED, RequestStatus.DRAFT}
            and item.overlaps(start, end)
        ]

    def on_leave(self, *, on_date: date | None = None) -> list[LeaveRequest]:
        """Who is on approved leave that day (calendar view)."""
        target = on_date or date.today()
        return [
            item
            for item in self._iter_requests()
            if item.status is RequestStatus.APPROVED and item.start_date <= target <= item.end_date
        ]

    # --- internals -------------------------------------------------------

    def _require_employee(self, employee_id: UUID) -> Employee:
        try:
            return self._employees.get(employee_id)
        except Exception as exc:
            raise LeaveError(f"unknown employee {employee_id}") from exc

    def _require_request(self, request_id: UUID) -> LeaveRequest:
        request = self._load_request(request_id)
        if request is None:
            raise LeaveError(f"unknown leave request {request_id}")
        return request

    def _record(
        self,
        *,
        action: str,
        subject_type: str,
        subject_id: str,
        actor: ActorRef,
        payload: dict[str, object],
    ) -> None:
        self._audit.append(
            actor=actor.audit_actor(),
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )
