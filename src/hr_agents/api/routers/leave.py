"""Leave API router — policies, balances, requests, calendar."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from hr_agents.api.deps import ActorDep, PaginationDep, require_permission
from hr_agents.api.leave_schemas import (
    BalanceAdjust,
    BalanceView,
    HolidaySet,
    LeaveRequestCreate,
    LeaveRequestView,
    PolicySet,
    PolicyView,
    RequestAction,
)
from hr_agents.api.problem import conflict, not_found
from hr_agents.api.schemas import Page
from hr_agents.models import LeaveType
from hr_agents.rbac import Permission
from hr_agents.services.leave import LeaveError, LeaveService

router = APIRouter(
    prefix="/v1/leave",
    tags=["leave"],
    dependencies=[Depends(require_permission(Permission.PEOPLE_READ))],
)


def get_leave(request: Request) -> LeaveService:
    return request.app.state.leave


LeaveDep = Annotated[LeaveService, Depends(get_leave)]


# --- policies ----------------------------------------------------------------


@router.put(
    "/policies",
    response_model=PolicyView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def set_policy(payload: PolicySet, leave: LeaveDep, actor: ActorDep) -> PolicyView:
    try:
        policy = leave.set_policy(payload.to_policy(), actor=actor)
    except (ValueError, LeaveError) as exc:
        raise conflict(exc) from exc
    return PolicyView.from_model(policy)


@router.get("/policies", response_model=Page[PolicyView])
def list_policies(leave: LeaveDep, paging: PaginationDep) -> Page[PolicyView]:
    return Page.slice(
        [PolicyView.from_model(policy) for policy in leave.list_policies()],
        limit=paging.limit,
        offset=paging.offset,
    )


@router.put(
    "/calendar/holidays",
    response_model=dict,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def set_holidays(payload: HolidaySet, leave: LeaveDep, actor: ActorDep) -> dict[str, int]:
    count = leave.set_holidays(payload.holidays, actor=actor)
    return {"holidays_set": count}


# --- balances ----------------------------------------------------------------


@router.get("/balances/{employee_id}", response_model=Page[BalanceView])
def employee_balances(
    employee_id: UUID,
    leave: LeaveDep,
    paging: PaginationDep,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
) -> Page[BalanceView]:
    try:
        balances = leave.all_balances(employee_id, year=year)
    except LeaveError as exc:
        raise not_found(str(exc)) from exc
    return Page.slice(
        [BalanceView.from_model(balance) for balance in balances],
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/balances/{employee_id}/{leave_type}", response_model=BalanceView)
def employee_balance(
    employee_id: UUID,
    leave_type: LeaveType,
    leave: LeaveDep,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
) -> BalanceView:
    try:
        balance = leave.balance(employee_id, leave_type, year=year)
    except LeaveError as exc:
        raise not_found(str(exc)) from exc
    return BalanceView.from_model(balance)


@router.post(
    "/balances/{employee_id}/{leave_type}/adjust",
    response_model=BalanceView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def adjust_balance(
    employee_id: UUID,
    leave_type: LeaveType,
    payload: BalanceAdjust,
    leave: LeaveDep,
    actor: ActorDep,
) -> BalanceView:
    try:
        balance = leave.adjust_balance(
            employee_id,
            leave_type,
            days=payload.days,
            year=payload.year,
            actor=actor,
            reason=payload.reason,
        )
    except LeaveError as exc:
        raise conflict(exc) from exc
    return BalanceView.from_model(balance)


# --- requests ----------------------------------------------------------------


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=LeaveRequestView,
    dependencies=[Depends(require_permission(Permission.SELF_SERVICE))],
)
def submit_request(
    payload: LeaveRequestCreate, leave: LeaveDep, actor: ActorDep
) -> LeaveRequestView:
    try:
        request = leave.request(actor=actor, **payload.model_dump())
    except LeaveError as exc:
        raise conflict(exc) from exc
    return LeaveRequestView.from_model(request)


@router.get("", response_model=Page[LeaveRequestView])
def list_requests(
    leave: LeaveDep,
    paging: PaginationDep,
    employee_id: Annotated[UUID | None, Query()] = None,
    pending_only: Annotated[bool, Query()] = False,
) -> Page[LeaveRequestView]:
    if pending_only:
        employee_id = None
    requests, total = leave.page_requests(
        employee_id=employee_id, limit=paging.limit, offset=paging.offset
    )
    return Page.of(
        [LeaveRequestView.from_model(request) for request in requests],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/calendar", response_model=Page[LeaveRequestView])
def calendar(
    leave: LeaveDep,
    paging: PaginationDep,
    on_date: Annotated[date | None, Query()] = None,
) -> Page[LeaveRequestView]:
    items, total = leave.page_on_leave(on_date=on_date, limit=paging.limit, offset=paging.offset)
    return Page.of(
        [LeaveRequestView.from_model(item) for item in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/requests/{request_id}", response_model=LeaveRequestView)
def get_request(request_id: UUID, leave: LeaveDep) -> LeaveRequestView:
    try:
        return LeaveRequestView.from_model(leave.get_request(request_id))
    except LeaveError as exc:
        raise not_found(str(exc)) from exc


@router.post(
    "/requests/{request_id}/cancel",
    response_model=LeaveRequestView,
    dependencies=[Depends(require_permission(Permission.SELF_SERVICE))],
)
def cancel_request(
    request_id: UUID, payload: RequestAction, leave: LeaveDep, actor: ActorDep
) -> LeaveRequestView:
    try:
        request = leave.cancel(request_id, actor=actor, reason=payload.reason)
    except LeaveError as exc:
        raise conflict(exc) from exc
    return LeaveRequestView.from_model(request)


@router.post(
    "/approvals/{approval_id}/sync",
    response_model=LeaveRequestView,
    dependencies=[Depends(require_permission(Permission.PEOPLE_WRITE))],
)
def sync_from_approval(approval_id: UUID, leave: LeaveDep, actor: ActorDep) -> LeaveRequestView:
    """Sync a leave request with its approval's outcome (called after a decision)."""
    try:
        request = leave.apply_decision(approval_id, actor=actor)
    except LeaveError as exc:
        raise not_found(str(exc)) from exc
    return LeaveRequestView.from_model(request)
