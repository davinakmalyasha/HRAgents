"""People, contracts, approvals, tasks, and rate-table API routers.

All endpoints are thin: validate → call the deterministic service → audit.
No LLM is involved anywhere in these paths.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from hr_agents.api.deps import require_api_key
from hr_agents.api.people_schemas import (
    ApprovalCreate,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalView,
    ContractActionRequest,
    ContractCreate,
    ContractView,
    DocumentCreate,
    DocumentView,
    EmployeeCreate,
    EmployeeTransitionRequest,
    EmployeeView,
    RateTableCreate,
    RateTableView,
    TaskCompleteRequest,
    TaskCreate,
    TaskView,
)
from hr_agents.models import ApprovalStatus, ApproverRole, EmployeeStatus
from hr_agents.services import (
    ApprovalError,
    ContractError,
    EmployeeError,
    TaskError,
)
from hr_agents.services.people import PeopleServices


def get_people(request: Request) -> PeopleServices:
    return request.app.state.people


PeopleDep = Annotated[PeopleServices, Depends(get_people)]

employees_router = APIRouter(
    prefix="/v1/employees", tags=["employees"], dependencies=[Depends(require_api_key)]
)
contracts_router = APIRouter(
    prefix="/v1/contracts", tags=["contracts"], dependencies=[Depends(require_api_key)]
)
approvals_router = APIRouter(
    prefix="/v1/approvals", tags=["approvals"], dependencies=[Depends(require_api_key)]
)
tasks_router = APIRouter(
    prefix="/v1/tasks", tags=["tasks"], dependencies=[Depends(require_api_key)]
)
rate_tables_router = APIRouter(
    prefix="/v1/rate-tables", tags=["rate-tables"], dependencies=[Depends(require_api_key)]
)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# --- employees ---------------------------------------------------------------


@employees_router.post("", status_code=status.HTTP_201_CREATED, response_model=EmployeeView)
async def create_employee(payload: EmployeeCreate, people: PeopleDep) -> EmployeeView:
    try:
        employee = people.employees.create(**payload.model_dump())
    except EmployeeError as exc:
        raise _conflict(exc) from exc
    return EmployeeView.from_model(employee)


@employees_router.get("", response_model=list[EmployeeView])
async def list_employees(
    people: PeopleDep,
    employee_status: Annotated[EmployeeStatus | None, Query(alias="status")] = None,
) -> list[EmployeeView]:
    return [
        EmployeeView.from_model(employee)
        for employee in people.employees.list_employees(status=employee_status)
    ]


@employees_router.get("/{employee_id}", response_model=EmployeeView)
async def get_employee(employee_id: UUID, people: PeopleDep) -> EmployeeView:
    try:
        return EmployeeView.from_model(people.employees.get(employee_id))
    except EmployeeError as exc:
        raise _not_found(str(exc)) from exc


@employees_router.post("/{employee_id}/transition", response_model=EmployeeView)
async def transition_employee(
    employee_id: UUID, payload: EmployeeTransitionRequest, people: PeopleDep
) -> EmployeeView:
    try:
        employee = people.employees.transition(
            employee_id,
            target=payload.target,
            by=payload.by,
            force=payload.force,
            reason=payload.reason,
        )
    except EmployeeError as exc:
        raise _conflict(exc) from exc
    return EmployeeView.from_model(employee)


@employees_router.post(
    "/{employee_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentView,
)
async def add_document(
    employee_id: UUID, payload: DocumentCreate, people: PeopleDep
) -> DocumentView:
    try:
        document = people.employees.add_document(employee_id, **payload.model_dump())
    except EmployeeError as exc:
        raise _not_found(str(exc)) from exc
    return DocumentView.from_model(document)


@employees_router.get("/{employee_id}/contracts", response_model=list[ContractView])
async def employee_contracts(employee_id: UUID, people: PeopleDep) -> list[ContractView]:
    return [
        ContractView.from_model(contract) for contract in people.contracts.for_employee(employee_id)
    ]


# --- contracts ---------------------------------------------------------------


@contracts_router.post("", status_code=status.HTTP_201_CREATED, response_model=ContractView)
async def create_contract(payload: ContractCreate, people: PeopleDep) -> ContractView:
    try:
        contract = people.contracts.create(**payload.model_dump())
    except (ContractError, ValueError) as exc:
        raise _conflict(exc) from exc
    return ContractView.from_model(contract)


@contracts_router.get("", response_model=list[ContractView])
async def list_contracts(
    people: PeopleDep,
    expiring_within_days: Annotated[int | None, Query(ge=0, le=365)] = None,
) -> list[ContractView]:
    contracts = (
        people.contracts.expiring(within_days=expiring_within_days)
        if expiring_within_days is not None
        else people.contracts._store.list_all()
    )
    return [ContractView.from_model(contract) for contract in contracts]


@contracts_router.get("/{contract_id}", response_model=ContractView)
async def get_contract(contract_id: UUID, people: PeopleDep) -> ContractView:
    try:
        return ContractView.from_model(people.contracts.get(contract_id))
    except ContractError as exc:
        raise _not_found(str(exc)) from exc


@contracts_router.post("/{contract_id}/activate", response_model=ContractView)
async def activate_contract(
    contract_id: UUID, payload: ContractActionRequest, people: PeopleDep
) -> ContractView:
    try:
        contract = people.contracts.activate(contract_id, by=payload.by)
    except ContractError as exc:
        raise _conflict(exc) from exc
    return ContractView.from_model(contract)


@contracts_router.post("/{contract_id}/terminate", response_model=ContractView)
async def terminate_contract(
    contract_id: UUID, payload: ContractActionRequest, people: PeopleDep
) -> ContractView:
    if not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="termination requires a reason",
        )
    try:
        contract = people.contracts.terminate(contract_id, by=payload.by, reason=payload.reason)
    except ContractError as exc:
        raise _conflict(exc) from exc
    return ContractView.from_model(contract)


# --- approvals ---------------------------------------------------------------


@approvals_router.post("", status_code=status.HTTP_201_CREATED, response_model=ApprovalView)
async def create_approval(payload: ApprovalCreate, people: PeopleDep) -> ApprovalView:
    try:
        request = people.approvals.create(**payload.model_dump())
    except ApprovalError as exc:
        raise _conflict(exc) from exc
    return ApprovalView.from_model(request)


@approvals_router.get("", response_model=list[ApprovalView])
async def list_approvals(
    people: PeopleDep,
    role: Annotated[ApproverRole | None, Query()] = None,
    approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
) -> list[ApprovalView]:
    if role is not None:
        requests = people.approvals.pending_for(role)
    else:
        requests = [r for r in people.approvals._store.list_all() if r.active]

    if approval_status is not None:
        requests = [r for r in requests if r.status is approval_status]
    return [ApprovalView.from_model(request) for request in requests]


@approvals_router.post("/{approval_id}/decide", response_model=ApprovalDecisionResponse)
async def decide_approval(
    approval_id: UUID, payload: ApprovalDecisionRequest, people: PeopleDep
) -> ApprovalDecisionResponse:
    try:
        decision = people.approvals.decide(
            approval_id,
            decided_by=payload.decided_by,
            approve=payload.approve,
            reason=payload.reason,
        )
    except ApprovalError as exc:
        raise _conflict(exc) from exc
    return ApprovalDecisionResponse(
        request=ApprovalView.from_model(decision.request), action=decision.action
    )


@approvals_router.post("/{approval_id}/escalate-overdue", response_model=list[ApprovalView])
async def escalate_overdue(people: PeopleDep) -> list[ApprovalView]:
    """Ops endpoint: run the SLA escalation sweep (also driven by a scheduler)."""
    changed = people.approvals.escalate_overdue()
    return [ApprovalView.from_model(request) for request in changed]


# --- tasks -------------------------------------------------------------------


@tasks_router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskView)
async def create_task(payload: TaskCreate, people: PeopleDep) -> TaskView:
    task = people.tasks.create(**payload.model_dump())
    return TaskView.from_model(task)


@tasks_router.get("", response_model=list[TaskView])
async def list_tasks(
    people: PeopleDep,
    overdue_only: Annotated[bool, Query()] = False,
) -> list[TaskView]:
    tasks = people.tasks.overdue() if overdue_only else people.tasks.open_tasks()
    return [TaskView.from_model(task) for task in tasks]


@tasks_router.post("/{task_id}/complete", response_model=TaskView)
async def complete_task(task_id: UUID, payload: TaskCompleteRequest, people: PeopleDep) -> TaskView:
    try:
        task = people.tasks.complete(task_id, by=payload.by)
    except TaskError as exc:
        raise _conflict(exc) from exc
    return TaskView.from_model(task)


# --- rate tables -------------------------------------------------------------


@rate_tables_router.post("", status_code=status.HTTP_201_CREATED, response_model=RateTableView)
async def create_rate_table(payload: RateTableCreate, people: PeopleDep) -> RateTableView:
    table = people.rate_tables.create(**payload.model_dump())
    return RateTableView.from_model(table)


@rate_tables_router.get("", response_model=list[RateTableView])
async def list_rate_tables(people: PeopleDep) -> list[RateTableView]:
    return [RateTableView.from_model(table) for table in people.rate_tables.list_all()]


@rate_tables_router.get("/unverified", response_model=list[RateTableView])
async def unverified_rate_tables(people: PeopleDep) -> list[RateTableView]:
    return [RateTableView.from_model(table) for table in people.rate_tables.unverified()]


# Silence unused-import linters for AuthContext (reserved for RBAC phase).
__all__ = [
    "approvals_router",
    "contracts_router",
    "employees_router",
    "rate_tables_router",
    "tasks_router",
]
