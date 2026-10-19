"""Postgres-backed people stores (employee core, contracts, approvals, tasks, rates).

Each adapter subclasses its in-memory counterpart and delegates every method to
the generic mapping helpers; behavior contracts stay in ``services/people_store``.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from hr_agents.db import people_tables as pt
from hr_agents.db.mapping import (
    add_model,
    delete_model,
    get_model,
    list_models,
    model_from_row,
    save_model,
)
from hr_agents.db.session import sync_session_scope
from hr_agents.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApproverRole,
    Contract,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    OrgUnit,
    RateTable,
    TaskItem,
    TaskStatus,
    VerificationStatus,
    business_today,
)
from hr_agents.models.tasks import TERMINAL_STATUSES
from hr_agents.services.people_store import (
    ApprovalStore,
    ContractStore,
    EmployeeStore,
    RateTableStore,
    TaskStore,
)


class DbEmployeeStore(EmployeeStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add_employee(self, employee: Employee) -> None:
        add_model(self._session_factory, employee, pt.EmployeeRecord)

    def save_employee(self, employee: Employee) -> None:
        save_model(self._session_factory, employee, pt.EmployeeRecord)

    def get_employee(self, employee_id: UUID) -> Employee | None:
        return get_model(self._session_factory, Employee, pt.EmployeeRecord, employee_id)

    def list_employees(self) -> list[Employee]:
        employees = list_models(self._session_factory, Employee, pt.EmployeeRecord)
        return sorted(employees, key=lambda item: (item.full_name.lower(), str(item.id)))

    def page_employees(
        self, *, limit: int, offset: int, status: EmployeeStatus | None = None
    ) -> tuple[list[Employee], int]:
        """Predicate, ORDER BY and LIMIT/OFFSET all reach SQL in one transaction.

        The ordering mirrors the in-memory contract ``(lower(full_name), id)``.
        The id tiebreak is doubly load-bearing here: the database evaluates
        OFFSET without a Python stable sort behind it, so equal names must not
        leave the slice boundaries undefined.
        """
        where: list[ColumnElement[bool]] = []
        if status is not None:
            where.append(pt.EmployeeRecord.status == status.value)
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(pt.EmployeeRecord).where(*where)
            )
            rows = (
                session.execute(
                    select(pt.EmployeeRecord)
                    .where(*where)
                    .order_by(func.lower(pt.EmployeeRecord.full_name), pt.EmployeeRecord.id)
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [model_from_row(Employee, row) for row in rows], int(total or 0)

    def add_org_unit(self, unit: OrgUnit) -> None:
        add_model(self._session_factory, unit, pt.OrgUnitRecord)

    def get_org_unit(self, unit_id: UUID) -> OrgUnit | None:
        return get_model(self._session_factory, OrgUnit, pt.OrgUnitRecord, unit_id)

    def list_org_units(self) -> list[OrgUnit]:
        units = list_models(self._session_factory, OrgUnit, pt.OrgUnitRecord)
        return sorted(units, key=lambda item: item.name.lower())

    def add_document(self, document: EmployeeDocument) -> None:
        add_model(self._session_factory, document, pt.EmployeeDocumentRecord)

    def delete_document(self, document_id: UUID) -> bool:
        return delete_model(self._session_factory, pt.EmployeeDocumentRecord, document_id)

    def list_documents(self, employee_id: UUID) -> list[EmployeeDocument]:
        """One employee's vault, in the same order as the whole-vault read.

        This used to call ``all_documents()`` and filter the result in Python,
        which meant every call selected the entire ``employee_documents`` table
        and re-validated every row. The service layer calls it once per employee,
        so an org of 100 issued 100 full-table scans. ``ix_employee_documents_
        employee`` was already there and unused.
        """
        return self._read_documents(where=pt.EmployeeDocumentRecord.employee_id == employee_id)

    def all_documents(self) -> list[EmployeeDocument]:
        """The whole vault, soonest expiry first (records workspace, expiry sweep)."""
        return self._read_documents()

    def page_documents(
        self,
        *,
        employee_id: UUID | None,
        expiring_within_days: int | None,
        status: VerificationStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[EmployeeDocument], int]:
        """Paged vault read: owner, status and expiry window all filter in SQL.

        Ordering mirrors the in-memory contract ``(no-expiry last, expires_on,
        id)``; the count runs over the same predicate in the same transaction,
        so a page and its total cannot disagree.
        """
        where: list[ColumnElement[bool]] = []
        if employee_id is not None:
            where.append(pt.EmployeeDocumentRecord.employee_id == employee_id)
        if status is not None:
            where.append(pt.EmployeeDocumentRecord.status == status.value)
        if expiring_within_days is not None:
            today = business_today()
            where.extend(
                [
                    pt.EmployeeDocumentRecord.expires_on.is_not(None),
                    pt.EmployeeDocumentRecord.expires_on >= today,
                    pt.EmployeeDocumentRecord.expires_on
                    <= today + timedelta(days=expiring_within_days),
                ]
            )
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(pt.EmployeeDocumentRecord).where(*where)
            )
            rows = (
                session.execute(
                    select(pt.EmployeeDocumentRecord)
                    .where(*where)
                    .order_by(
                        pt.EmployeeDocumentRecord.expires_on.is_(None),
                        pt.EmployeeDocumentRecord.expires_on,
                        pt.EmployeeDocumentRecord.id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [model_from_row(EmployeeDocument, row) for row in rows], int(total or 0)

    def _read_documents(
        self, *, where: ColumnElement[bool] | None = None
    ) -> list[EmployeeDocument]:
        """The one place document rows are read, so ordering cannot drift.

        The records endpoints filter in SQL where they can; this keeps the
        tenant-scoped read in one place instead of trusting a Python-side filter.
        """
        with sync_session_scope(self._session_factory) as session:
            query = select(pt.EmployeeDocumentRecord)
            if where is not None:
                query = query.where(where)
            rows = (
                session.execute(
                    query.order_by(
                        pt.EmployeeDocumentRecord.expires_on.is_(None),
                        pt.EmployeeDocumentRecord.expires_on,
                        pt.EmployeeDocumentRecord.uploaded_at,
                    )
                )
                .scalars()
                .all()
            )
            return [model_from_row(EmployeeDocument, row) for row in rows]


class DbContractStore(ContractStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add(self, contract: Contract) -> None:
        add_model(self._session_factory, contract, pt.ContractRecord)

    def save(self, contract: Contract) -> None:
        save_model(self._session_factory, contract, pt.ContractRecord)

    def get(self, contract_id: UUID) -> Contract | None:
        return get_model(self._session_factory, Contract, pt.ContractRecord, contract_id)

    def list_all(self) -> list[Contract]:
        contracts = list_models(self._session_factory, Contract, pt.ContractRecord)
        return sorted(contracts, key=lambda item: item.start_date)

    def list_for_employee(self, employee_id: UUID) -> list[Contract]:
        return [item for item in self.list_all() if item.employee_id == employee_id]

    def page_contracts(
        self,
        *,
        expiring_within_days: int | None,
        as_of: date,
        limit: int,
        offset: int,
    ) -> tuple[list[Contract], int]:
        """The contract list in SQL: the expiry window, or ``(start_date, id)``.

        The window is ``0 <= days remaining <= expiring_within_days``, which is
        ``end_date`` between ``as_of`` and ``as_of + window`` -- the same rule
        ``ContractService.expiring`` applies in Python.
        """
        where: list[ColumnElement[bool]] = []
        if expiring_within_days is None:
            order = (pt.ContractRecord.start_date, pt.ContractRecord.id)
        else:
            window_end = as_of + timedelta(days=expiring_within_days)
            where.extend(
                [
                    pt.ContractRecord.end_date.is_not(None),
                    pt.ContractRecord.end_date >= as_of,
                    pt.ContractRecord.end_date <= window_end,
                ]
            )
            order = (pt.ContractRecord.end_date, pt.ContractRecord.id)
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(pt.ContractRecord).where(*where)
            )
            rows = (
                session.execute(
                    select(pt.ContractRecord)
                    .where(*where)
                    .order_by(*order)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(Contract, row) for row in rows], int(total or 0)


class DbApprovalStore(ApprovalStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add(self, request: ApprovalRequest) -> None:
        add_model(self._session_factory, request, pt.ApprovalRecord)

    def save(self, request: ApprovalRequest) -> None:
        save_model(self._session_factory, request, pt.ApprovalRecord)

    def get(self, request_id: UUID) -> ApprovalRequest | None:
        return get_model(self._session_factory, ApprovalRequest, pt.ApprovalRecord, request_id)

    def list_all(self) -> list[ApprovalRequest]:
        requests = list_models(self._session_factory, ApprovalRequest, pt.ApprovalRecord)
        return sorted(requests, key=lambda item: item.created_at)

    def page_approvals(
        self,
        *,
        role: ApproverRole | None,
        status: ApprovalStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ApprovalRequest], int]:
        """Active-queue predicate, ORDER BY (created_at, id) and LIMIT in SQL."""
        where: list[ColumnElement[bool]] = [
            pt.ApprovalRecord.status.in_(
                [ApprovalStatus.PENDING.value, ApprovalStatus.ESCALATED.value]
            )
        ]
        if role is not None:
            where.append(pt.ApprovalRecord.assignee_role == role.value)
        if status is not None:
            where.append(pt.ApprovalRecord.status == status.value)
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(pt.ApprovalRecord).where(*where)
            )
            rows = (
                session.execute(
                    select(pt.ApprovalRecord)
                    .where(*where)
                    .order_by(pt.ApprovalRecord.created_at, pt.ApprovalRecord.id)
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [model_from_row(ApprovalRequest, row) for row in rows], int(total or 0)


class DbTaskStore(TaskStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add(self, task: TaskItem) -> None:
        add_model(self._session_factory, task, pt.TaskRecord)

    def save(self, task: TaskItem) -> None:
        save_model(self._session_factory, task, pt.TaskRecord)

    def get(self, task_id: UUID) -> TaskItem | None:
        return get_model(self._session_factory, TaskItem, pt.TaskRecord, task_id)

    def list_all(self) -> list[TaskItem]:
        tasks = list_models(self._session_factory, TaskItem, pt.TaskRecord)
        return sorted(tasks, key=lambda item: item.created_at)

    def list_open_by_subject(self, related_subject: str) -> list[TaskItem]:
        """One filtered read, rather than a full table read per lookup.

        ``is_open`` is derived from a stored status, so the predicate is pushed
        into SQL. Filtering the loaded rows in Python would have kept the query
        count flat but still read the whole table on every call, which is the
        cost this exists to remove.
        """
        open_statuses = [status.value for status in TaskStatus if status not in TERMINAL_STATUSES]
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    select(pt.TaskRecord)
                    .where(
                        pt.TaskRecord.related_subject == related_subject,
                        pt.TaskRecord.status.in_(open_statuses),
                    )
                    .order_by(pt.TaskRecord.created_at)
                )
                .scalars()
                .all()
            )
            return [model_from_row(TaskItem, row) for row in rows]

    def page_tasks(
        self, *, overdue_only: bool, as_of: date, limit: int, offset: int
    ) -> tuple[list[TaskItem], int]:
        """The dashboard queue in SQL: open predicate, overdue rank, NULLS LAST.

        The rank matches ``TaskItem.is_overdue`` exactly -- open and due before
        ``as_of`` -- and undated tasks sort last, mirroring ``date.max`` in the
        in-memory store. The id tiebreak keeps OFFSET stable otherwise.
        """
        open_statuses = [status.value for status in TaskStatus if status not in TERMINAL_STATUSES]
        overdue = pt.TaskRecord.due_on.is_not(None) & (pt.TaskRecord.due_on < as_of)
        where: list[ColumnElement[bool]] = [pt.TaskRecord.status.in_(open_statuses)]
        if overdue_only:
            where.append(overdue)
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(select(func.count()).select_from(pt.TaskRecord).where(*where))
            rows = (
                session.execute(
                    select(pt.TaskRecord)
                    .where(*where)
                    .order_by(
                        case((overdue, 0), else_=1),
                        pt.TaskRecord.due_on.asc().nulls_last(),
                        pt.TaskRecord.created_at,
                        pt.TaskRecord.id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(TaskItem, row) for row in rows], int(total or 0)


class DbRateTableStore(RateTableStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add(self, table: RateTable) -> None:
        add_model(self._session_factory, table, pt.RateTableRecord)

    def save(self, table: RateTable) -> None:
        save_model(self._session_factory, table, pt.RateTableRecord)

    def get(self, table_id: UUID) -> RateTable | None:
        return get_model(self._session_factory, RateTable, pt.RateTableRecord, table_id)

    def list_all(self) -> list[RateTable]:
        tables = list_models(self._session_factory, RateTable, pt.RateTableRecord)
        return sorted(tables, key=lambda item: item.name.lower())
