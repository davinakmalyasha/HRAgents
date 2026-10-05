"""Postgres-backed leave store.

`LeaveService` keeps every balance computation, overlap check and lifecycle rule in
the service class; this adapter implements only the persistence primitives it
exposes, so all of that stays testable without a database.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.leave_tables import (
    LeaveAdjustmentRecord,
    LeaveHolidayRecord,
    LeavePolicyRecord,
    LeaveRequestRecord,
)
from hr_agents.db.session import sync_session_scope
from hr_agents.models.common import utc_now
from hr_agents.models.leave import LeaveType, LeaveTypePolicy, RequestStatus
from hr_agents.services.leave import LeaveRequest, LeaveService


def _aware(moment: datetime) -> datetime:
    """Stamp a naive datetime as UTC; SQLite drops the tzinfo SQLite has no zone."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class DbLeaveService(LeaveService):
    """Durable leave service on the ``leave_*`` tables."""

    def __init__(self, session_factory: sessionmaker[Session], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._session_factory = session_factory

    # --- requests --------------------------------------------------------

    def _load_request(self, request_id: UUID) -> LeaveRequest | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(LeaveRequestRecord, request_id)
            return None if row is None else self._to_request(row)

    def _iter_requests(self) -> Iterator[LeaveRequest]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(LeaveRequestRecord)).scalars().all()
            # Materialised inside the session: a lazy iterator would read through a
            # closed session.
            return iter([self._to_request(row) for row in rows])

    def _save_request(self, request: LeaveRequest) -> None:
        with sync_session_scope(self._session_factory) as session:
            existing = session.get(LeaveRequestRecord, request.id)
            values = {
                "employee_id": request.employee_id,
                "leave_type": request.leave_type.value,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "days": request.days,
                "reason": request.reason,
                "document_id": request.document_id,
                "status": request.status.value,
                "approval_id": request.approval_id,
                "created_at": _aware(request.created_at),
                "updated_at": _aware(request.updated_at),
            }
            if existing is None:
                session.add(LeaveRequestRecord(id=request.id, **values))
            else:
                for column, value in values.items():
                    setattr(existing, column, value)

    @staticmethod
    def _to_request(row: LeaveRequestRecord) -> LeaveRequest:
        return LeaveRequest(
            id=row.id,
            employee_id=row.employee_id,
            leave_type=LeaveType(row.leave_type),
            start_date=row.start_date,
            end_date=row.end_date,
            days=row.days,
            reason=row.reason,
            document_id=row.document_id,
            status=RequestStatus(row.status),
            approval_id=row.approval_id,
            created_at=_aware(row.created_at),
            updated_at=_aware(row.updated_at),
        )

    # --- policies --------------------------------------------------------

    def _load_policy(self, leave_type: LeaveType) -> LeaveTypePolicy | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(LeavePolicyRecord).where(LeavePolicyRecord.leave_type == leave_type.value)
            ).scalar_one_or_none()
            return None if row is None else LeaveTypePolicy.model_validate(row.policy)

    def _iter_policies(self) -> Iterator[LeaveTypePolicy]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(LeavePolicyRecord)).scalars().all()
            return iter([LeaveTypePolicy.model_validate(row.policy) for row in rows])

    def _save_policy(self, policy: LeaveTypePolicy) -> None:
        with sync_session_scope(self._session_factory) as session:
            existing = session.execute(
                select(LeavePolicyRecord).where(
                    LeavePolicyRecord.leave_type == policy.leave_type.value
                )
            ).scalar_one_or_none()
            payload = policy.model_dump(mode="json")
            if existing is None:
                session.add(
                    LeavePolicyRecord(
                        leave_type=policy.leave_type.value,
                        policy=payload,
                        created_at=utc_now(),
                    )
                )
            else:
                existing.policy = payload
                existing.updated_at = utc_now()

    # --- balance adjustments ---------------------------------------------

    def _load_adjustment(self, employee_id: UUID, leave_type: LeaveType, year: int) -> float:
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(LeaveAdjustmentRecord).where(
                    LeaveAdjustmentRecord.employee_id == employee_id,
                    LeaveAdjustmentRecord.leave_type == leave_type.value,
                    LeaveAdjustmentRecord.target_year == year,
                )
            ).scalar_one_or_none()
            return 0.0 if row is None else row.days

    def _save_adjustment(
        self, employee_id: UUID, leave_type: LeaveType, year: int, days: float
    ) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(LeaveAdjustmentRecord).where(
                    LeaveAdjustmentRecord.employee_id == employee_id,
                    LeaveAdjustmentRecord.leave_type == leave_type.value,
                    LeaveAdjustmentRecord.target_year == year,
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    LeaveAdjustmentRecord(
                        employee_id=employee_id,
                        leave_type=leave_type.value,
                        target_year=year,
                        days=days,
                        created_at=utc_now(),
                    )
                )
            else:
                row.days = days
                row.updated_at = utc_now()

    # --- holiday calendar -------------------------------------------------

    def _iter_holidays(self) -> Iterator[date]:
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(select(LeaveHolidayRecord.day).order_by(LeaveHolidayRecord.day))
                .scalars()
                .all()
            )
            return iter(list(rows))

    def _save_holidays(self, holidays: Iterable[date]) -> None:
        """Replace the calendar wholesale.

        `set_holidays` is a whole-calendar replacement by contract -- it returns the
        new count, not a delta -- so deleting and reinserting matches what the
        in-memory implementation does. Rows are removed one tenant at a time by the
        RLS policy, which scopes the delete to the caller's tenant automatically.
        """
        wanted = sorted(set(holidays))
        with sync_session_scope(self._session_factory) as session:
            session.execute(delete(LeaveHolidayRecord))
            session.add_all([LeaveHolidayRecord(day=day, created_at=utc_now()) for day in wanted])
