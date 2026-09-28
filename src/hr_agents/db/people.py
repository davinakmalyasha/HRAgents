"""Postgres-backed people stores (employee core, contracts, approvals, tasks, rates).

Each adapter subclasses its in-memory counterpart and delegates every method to
the generic mapping helpers; behavior contracts stay in ``services/people_store``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import people_tables as pt
from hr_agents.db.mapping import add_model, get_model, list_models, model_from_row, save_model
from hr_agents.db.session import sync_session_scope
from hr_agents.models import (
    ApprovalRequest,
    Contract,
    Employee,
    EmployeeDocument,
    OrgUnit,
    RateTable,
    TaskItem,
)
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
        return sorted(employees, key=lambda item: item.full_name.lower())

    def add_org_unit(self, unit: OrgUnit) -> None:
        add_model(self._session_factory, unit, pt.OrgUnitRecord)

    def get_org_unit(self, unit_id: UUID) -> OrgUnit | None:
        return get_model(self._session_factory, OrgUnit, pt.OrgUnitRecord, unit_id)

    def list_org_units(self) -> list[OrgUnit]:
        units = list_models(self._session_factory, OrgUnit, pt.OrgUnitRecord)
        return sorted(units, key=lambda item: item.name.lower())

    def add_document(self, document: EmployeeDocument) -> None:
        add_model(self._session_factory, document, pt.EmployeeDocumentRecord)

    def list_documents(self, employee_id: UUID) -> list[EmployeeDocument]:
        return [doc for doc in self.all_documents() if doc.employee_id == employee_id]

    def all_documents(self) -> list[EmployeeDocument]:
        """The whole vault, soonest expiry first (records workspace, expiry sweep).

        The records endpoints filter in SQL where they can; this keeps the
        tenant-scoped read in one place instead of trusting a Python-side filter.
        """
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    select(pt.EmployeeDocumentRecord).order_by(
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
