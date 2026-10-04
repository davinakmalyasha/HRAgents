"""People, contracts, approvals, tasks, and rate-table API routers.

All endpoints are thin: validate → call the deterministic service → audit.
No LLM is involved anywhere in these paths.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from hr_agents.api.deps import ActorDep, require_permission
from hr_agents.api.people_schemas import (
    ApprovalCreate,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalView,
    ContractActionRequest,
    ContractCreate,
    ContractView,
    DocumentCreate,
    DocumentVerifyRequest,
    DocumentView,
    EmployeeCreate,
    EmployeeTransitionRequest,
    EmployeeView,
    OrgUnitCreate,
    OrgUnitView,
    RateTableCreate,
    RateTableEntriesUpdate,
    RateTableVerify,
    RateTableView,
    TaskCompleteRequest,
    TaskCreate,
    TaskView,
)
from hr_agents.models import (
    ApprovalStatus,
    ApproverRole,
    EmployeeStatus,
    VerificationStatus,
)
from hr_agents.rbac import Permission
from hr_agents.services import (
    ApprovalError,
    ContractError,
    EmployeeError,
    RateTableError,
    TaskError,
)
from hr_agents.services.people import PeopleServices


def get_people(request: Request) -> PeopleServices:
    return request.app.state.people


PeopleDep = Annotated[PeopleServices, Depends(get_people)]

# The routers below declare only a *read* permission, because reading the
# employee directory is what a manager or a finance key legitimately needs.
# Every mutating route therefore also names the write it actually performs --
# see `tests/route_probe.py` for why the structural fence that asserts this
# could not see these seven routers at all until recently.
employees_router = APIRouter(
    prefix="/v1/employees",
    tags=["employees"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)
org_units_router = APIRouter(
    prefix="/v1/org-units",
    tags=["records"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)
documents_router = APIRouter(
    prefix="/v1/documents",
    tags=["records"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)
contracts_router = APIRouter(
    prefix="/v1/contracts",
    tags=["contracts"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)
approvals_router = APIRouter(
    prefix="/v1/approvals",
    tags=["approvals"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)
tasks_router = APIRouter(
    prefix="/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_permission(Permission.TASKS_WRITE))],
)
rate_tables_router = APIRouter(
    prefix="/v1/rate-tables",
    tags=["rate-tables"],
    dependencies=[Depends(require_permission(Permission.PAYROLL_READ))],
)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# --- employees ---------------------------------------------------------------


@employees_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=EmployeeView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def create_employee(payload: EmployeeCreate, people: PeopleDep, actor: ActorDep) -> EmployeeView:
    try:
        employee = people.employees.create(actor=actor, **payload.model_dump())
    except EmployeeError as exc:
        raise _conflict(exc) from exc
    return EmployeeView.from_model(employee)


@employees_router.get("", response_model=list[EmployeeView])
def list_employees(
    people: PeopleDep,
    employee_status: Annotated[EmployeeStatus | None, Query(alias="status")] = None,
) -> list[EmployeeView]:
    return [
        EmployeeView.from_model(employee)
        for employee in people.employees.list_employees(status=employee_status)
    ]


@employees_router.get("/{employee_id}", response_model=EmployeeView)
def get_employee(employee_id: UUID, people: PeopleDep) -> EmployeeView:
    try:
        return EmployeeView.from_model(people.employees.get(employee_id))
    except EmployeeError as exc:
        raise _not_found(str(exc)) from exc


@employees_router.post(
    "/{employee_id}/transition",
    response_model=EmployeeView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def transition_employee(
    employee_id: UUID, payload: EmployeeTransitionRequest, people: PeopleDep, actor: ActorDep
) -> EmployeeView:
    try:
        employee = people.employees.transition(
            employee_id,
            target=payload.target,
            actor=actor,
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
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def add_document(
    employee_id: UUID, payload: DocumentCreate, people: PeopleDep, actor: ActorDep
) -> DocumentView:
    try:
        document = people.employees.add_document(employee_id, actor=actor, **payload.model_dump())
    except EmployeeError as exc:
        raise _not_found(str(exc)) from exc
    return DocumentView.from_model(document)


@employees_router.get("/{employee_id}/documents", response_model=list[DocumentView])
def employee_documents(employee_id: UUID, people: PeopleDep) -> list[DocumentView]:
    try:
        documents = people.employees.documents_for(employee_id)
    except EmployeeError as exc:
        raise _not_found(str(exc)) from exc
    return [DocumentView.from_model(document) for document in documents]


@employees_router.get("/{employee_id}/contracts", response_model=list[ContractView])
def employee_contracts(employee_id: UUID, people: PeopleDep) -> list[ContractView]:
    return [
        ContractView.from_model(contract) for contract in people.contracts.for_employee(employee_id)
    ]


# --- records: document vault, expiry alerts, org chart ------------------------


@documents_router.get("", response_model=list[DocumentView])
def list_documents(
    people: PeopleDep,
    employee_id: UUID | None = None,
    expiring_within_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    document_status: Annotated[VerificationStatus | None, Query(alias="status")] = None,
) -> list[DocumentView]:
    """The document vault, soonest expiry first, with the records filters."""
    documents = people.employees.document_vault(
        employee_id=employee_id,
        expiring_within_days=expiring_within_days,
        status=document_status,
    )
    return [DocumentView.from_model(document) for document in documents]


@documents_router.post(
    "/{document_id}/verify",
    response_model=DocumentView,
    # Certifying a passport or NPWP is a compliance judgement, not directory
    # access, so it names compliance:write rather than people:write.
    dependencies=[Depends(require_permission(Permission.COMPLIANCE_WRITE))],
)
def verify_document(
    document_id: UUID,
    payload: DocumentVerifyRequest,
    people: PeopleDep,
    actor: ActorDep,
) -> DocumentView:
    """Mark a document verified or rejected; only a named human may judge one.

    The gate itself lives in ``EmployeeService.mark_document_verified`` so that
    non-HTTP callers cannot bypass it; this wrapper only maps the refusal to 403.
    """
    try:
        document = people.employees.mark_document_verified(
            document_id,
            actor=actor,
            verified=payload.verified,
        )
    except EmployeeError as exc:
        if "named human" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        raise _not_found(str(exc)) from exc
    return DocumentView.from_model(document)


@org_units_router.get("", response_model=list[OrgUnitView])
def list_org_units(people: PeopleDep) -> list[OrgUnitView]:
    """Org units with their direct headcount (the workspace nests them itself)."""
    units = people.employees.list_org_units()
    headcount: dict[UUID, int] = {}
    for employee in people.employees.list_employees():
        if employee.org_unit_id is not None:
            headcount[employee.org_unit_id] = headcount.get(employee.org_unit_id, 0) + 1
    return [OrgUnitView.from_model(unit, headcount=headcount.get(unit.id, 0)) for unit in units]


@org_units_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=OrgUnitView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def create_org_unit(payload: OrgUnitCreate, people: PeopleDep, actor: ActorDep) -> OrgUnitView:
    try:
        unit = people.employees.create_org_unit(
            actor=actor,
            name=payload.name,
            parent_id=payload.parent_id,
            cost_center=payload.cost_center,
        )
    except EmployeeError as exc:
        raise _conflict(exc) from exc
    return OrgUnitView.from_model(unit)


# --- contracts ---------------------------------------------------------------


@contracts_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ContractView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def create_contract(payload: ContractCreate, people: PeopleDep, actor: ActorDep) -> ContractView:
    try:
        contract = people.contracts.create(actor=actor, **payload.model_dump())
    except (ContractError, ValueError) as exc:
        raise _conflict(exc) from exc
    return ContractView.from_model(contract)


@contracts_router.get("", response_model=list[ContractView])
def list_contracts(
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
def get_contract(contract_id: UUID, people: PeopleDep) -> ContractView:
    try:
        return ContractView.from_model(people.contracts.get(contract_id))
    except ContractError as exc:
        raise _not_found(str(exc)) from exc


@contracts_router.post(
    "/{contract_id}/activate",
    response_model=ContractView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def activate_contract(
    contract_id: UUID, payload: ContractActionRequest, people: PeopleDep, actor: ActorDep
) -> ContractView:
    try:
        contract = people.contracts.activate(contract_id, actor=actor)
    except ContractError as exc:
        raise _conflict(exc) from exc
    return ContractView.from_model(contract)


@contracts_router.post(
    "/{contract_id}/terminate",
    response_model=ContractView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def terminate_contract(
    contract_id: UUID, payload: ContractActionRequest, people: PeopleDep, actor: ActorDep
) -> ContractView:
    if not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="termination requires a reason",
        )
    try:
        contract = people.contracts.terminate(contract_id, actor=actor, reason=payload.reason)
    except ContractError as exc:
        raise _conflict(exc) from exc
    return ContractView.from_model(contract)


# --- approvals ---------------------------------------------------------------


@approvals_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApprovalView,
    # Raising an approval is not the same authority as deciding one, so this
    # does not reuse `approvals:decide`. `MANAGER` and `FINANCE` both hold that,
    # and if they could also manufacture a request assigned to a role they
    # control they could approve their own request through the assignee check.
    #
    # `people:write` (hr_admin, recruiter) is the honest requirement here: the
    # generic approval surface spans leave, payroll, retention and erasure, all
    # of which are people records. The domain flows -- a payroll submit, a leave
    # request -- do not come through here; they create their own approvals from
    # the service layer, under whatever authorization that service already
    # requires. If this route ever grows a non-people subject it wants a
    # dedicated `approvals:request` permission rather than a broader reuse.
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def create_approval(payload: ApprovalCreate, people: PeopleDep, actor: ActorDep) -> ApprovalView:
    try:
        request = people.approvals.create(actor=actor, **payload.model_dump())
    except ApprovalError as exc:
        raise _conflict(exc) from exc
    return ApprovalView.from_model(request)


@approvals_router.get("", response_model=list[ApprovalView])
def list_approvals(
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


@approvals_router.post(
    "/{approval_id}/decide",
    response_model=ApprovalDecisionResponse,
    dependencies=[Depends(require_permission(Permission.APPROVALS_DECIDE))],
)
def decide_approval(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    people: PeopleDep,
    actor: ActorDep,
) -> ApprovalDecisionResponse:
    try:
        decision = people.approvals.decide(
            approval_id,
            actor=actor,
            approve=payload.approve,
            reason=payload.reason,
        )
    except ApprovalError as exc:
        raise _conflict(exc) from exc
    return ApprovalDecisionResponse(
        request=ApprovalView.from_model(decision.request), action=decision.action
    )


@approvals_router.post(
    "/escalate-overdue",
    response_model=list[ApprovalView],
    dependencies=[Depends(require_permission(Permission.APPROVALS_DECIDE))],
)
def escalate_overdue(people: PeopleDep, actor: ActorDep) -> list[ApprovalView]:
    """Run the SLA escalation sweep now, on top of the scheduler.

    This route used to be declared as ``/{approval_id}/escalate-overdue`` while
    the handler took no such parameter. FastAPI ignores an unmatched path
    parameter, so the id was decorative: any caller holding ``approvals:read``
    could pass a random UUID and escalate *every* overdue approval in the tenant,
    including a finance-assigned payroll sign-off. And because the handler had no
    actor, the chain recorded the mutations as ``system:approval-engine`` -- so the
    audit trail said a timer had expired an approval that a person had triggered.

    Two things changed: the route is what it always meant to be (a global sweep,
    no fake id), and the caller is recorded as the caller.
    """
    changed = people.approvals.escalate_overdue(actor=actor)
    return [ApprovalView.from_model(request) for request in changed]


# --- tasks -------------------------------------------------------------------


@tasks_router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskView)
def create_task(payload: TaskCreate, people: PeopleDep, actor: ActorDep) -> TaskView:
    task = people.tasks.create(actor=actor, **payload.model_dump())
    return TaskView.from_model(task)


@tasks_router.get("", response_model=list[TaskView])
def list_tasks(
    people: PeopleDep,
    overdue_only: Annotated[bool, Query()] = False,
) -> list[TaskView]:
    tasks = people.tasks.overdue() if overdue_only else people.tasks.open_tasks()
    return [TaskView.from_model(task) for task in tasks]


@tasks_router.post("/{task_id}/complete", response_model=TaskView)
def complete_task(
    task_id: UUID, payload: TaskCompleteRequest, people: PeopleDep, actor: ActorDep
) -> TaskView:
    try:
        task = people.tasks.complete(task_id, actor=actor)
    except TaskError as exc:
        raise _conflict(exc) from exc
    return TaskView.from_model(task)


# --- rate tables -------------------------------------------------------------
#
# The verification gate is the hard rule: a table only drives payroll math once a
# named human has entered values, recorded where they came from, and confirmed
# them. RATES_VERIFY is a separate permission from PAYROLL_READ so that being
# able to look at a rate is not the same authority as being able to certify one.


@rate_tables_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=RateTableView,
    # Drafting a table is not certifying it, so this is payroll:write while
    # "/verify" below stays behind RATES_VERIFY.
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
)
def create_rate_table(
    payload: RateTableCreate, people: PeopleDep, actor: ActorDep
) -> RateTableView:
    table = people.rate_tables.create(actor=actor, **payload.model_dump())
    return RateTableView.from_model(table)


@rate_tables_router.get("", response_model=list[RateTableView])
def list_rate_tables(people: PeopleDep) -> list[RateTableView]:
    return [RateTableView.from_model(table) for table in people.rate_tables.list_all()]


@rate_tables_router.get("/unverified", response_model=list[RateTableView])
def unverified_rate_tables(people: PeopleDep) -> list[RateTableView]:
    return [RateTableView.from_model(table) for table in people.rate_tables.unverified()]


@rate_tables_router.get("/{table_id}", response_model=RateTableView)
def get_rate_table(table_id: UUID, people: PeopleDep) -> RateTableView:
    try:
        table = people.rate_tables.get(table_id)
    except RateTableError as exc:
        raise _not_found(str(exc)) from exc
    return RateTableView.from_model(table)


@rate_tables_router.put(
    "/{table_id}/entries",
    response_model=RateTableView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
)
def set_rate_table_entries(
    table_id: UUID,
    payload: RateTableEntriesUpdate,
    people: PeopleDep,
    actor: ActorDep,
) -> RateTableView:
    """Replace a table's rows. Editing values always invalidates verification."""
    try:
        table = people.rate_tables.set_entries(table_id, entries=payload.entries, actor=actor)
    except RateTableError as exc:
        raise _conflict(exc) from exc
    return RateTableView.from_model(table)


@rate_tables_router.post(
    "/{table_id}/verify",
    response_model=RateTableView,
    dependencies=[Depends(require_permission(Permission.RATES_VERIFY))],
)
def verify_rate_table(
    table_id: UUID, payload: RateTableVerify, people: PeopleDep, actor: ActorDep
) -> RateTableView:
    """Certify a rate table against a recorded source. Unblocks payroll compute."""
    try:
        table = people.rate_tables.verify(table_id, actor=actor, source_note=payload.source_note)
    except RateTableError as exc:
        raise _conflict(exc) from exc
    return RateTableView.from_model(table)


# Silence unused-import linters for AuthContext (reserved for RBAC phase).
__all__ = [
    "approvals_router",
    "contracts_router",
    "employees_router",
    "rate_tables_router",
    "tasks_router",
]
