"""Leave API router — policies, balances, requests, calendar."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from hr_agents.api.deps import require_api_key
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
from hr_agents.models import LeaveType
from hr_agents.services.leave import LeaveError, LeaveService

router = APIRouter(prefix="/v1/leave", tags=["leave"], dependencies=[Depends(require_api_key)])


def get_leave(request: Request) -> LeaveService:
    return request.app.state.leave


LeaveDep = Annotated[LeaveService, Depends(get_leave)]


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# --- policies ----------------------------------------------------------------


@router.put("/policies", response_model=PolicyView)
async def set_policy(payload: PolicySet, leave: LeaveDep) -> PolicyView:
    try:
        policy = leave.set_policy(payload.to_policy(), by=payload.by)
    except (ValueError, LeaveError) as exc:
        raise _conflict(exc) from exc
    return PolicyView.from_model(policy)


@router.get("/policies", response_model=list[PolicyView])
async def list_policies(leave: LeaveDep) -> list[PolicyView]:
    return [PolicyView.from_model(policy) for policy in leave.list_policies()]


@router.put("/calendar/holidays", response_model=dict)
async def set_holidays(payload: HolidaySet, leave: LeaveDep) -> dict[str, int]:
    count = leave.set_holidays(payload.holidays, by=payload.by)
    return {"holidays_set": count}


# --- balances ----------------------------------------------------------------


@router.get("/balances/{employee_id}", response_model=list[BalanceView])
async def employee_balances(
    employee_id: UUID,
    leave: LeaveDep,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
) -> list[BalanceView]:
    try:
        balances = leave.all_balances(employee_id, year=year)
    except LeaveError as exc:
        raise _not_found(str(exc)) from exc
    return [BalanceView.from_model(balance) for balance in balances]


@router.get("/balances/{employee_id}/{leave_type}", response_model=BalanceView)
async def employee_balance(
    employee_id: UUID,
    leave_type: LeaveType,
    leave: LeaveDep,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
) -> BalanceView:
    try:
        balance = leave.balance(employee_id, leave_type, year=year)
    except LeaveError as exc:
        raise _not_found(str(exc)) from exc
    return BalanceView.from_model(balance)


@router.post("/balances/{employee_id}/{leave_type}/adjust", response_model=BalanceView)
async def adjust_balance(
    employee_id: UUID,
    leave_type: LeaveType,
    payload: BalanceAdjust,
    leave: LeaveDep,
) -> BalanceView:
    try:
        balance = leave.adjust_balance(
            employee_id,
            leave_type,
            days=payload.days,
            year=payload.year,
            by=payload.by,
            reason=payload.reason,
        )
    except LeaveError as exc:
        raise _conflict(exc) from exc
    return BalanceView.from_model(balance)


# --- requests ----------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=LeaveRequestView)
async def submit_request(payload: LeaveRequestCreate, leave: LeaveDep) -> LeaveRequestView:
    try:
        request = leave.request(**payload.model_dump())
    except LeaveError as exc:
        raise _conflict(exc) from exc
    return LeaveRequestView.from_model(request)


@router.get("", response_model=list[LeaveRequestView])
async def list_requests(
    leave: LeaveDep,
    employee_id: Annotated[UUID | None, Query()] = None,
    pending_only: Annotated[bool, Query()] = False,
) -> list[LeaveRequestView]:
    if pending_only:
        requests = leave.pending_requests()
    elif employee_id is not None:
        requests = leave.requests_for(employee_id)
    else:
        requests = leave.pending_requests()
    return [LeaveRequestView.from_model(request) for request in requests]


@router.get("/calendar", response_model=list[LeaveRequestView])
async def calendar(
    leave: LeaveDep,
    on_date: Annotated[date | None, Query()] = None,
) -> list[LeaveRequestView]:
    return [LeaveRequestView.from_model(item) for item in leave.on_leave(on_date=on_date)]


@router.get("/requests/{request_id}", response_model=LeaveRequestView)
async def get_request(request_id: UUID, leave: LeaveDep) -> LeaveRequestView:
    try:
        return LeaveRequestView.from_model(leave.get_request(request_id))
    except LeaveError as exc:
        raise _not_found(str(exc)) from exc


@router.post("/requests/{request_id}/cancel", response_model=LeaveRequestView)
async def cancel_request(
    request_id: UUID, payload: RequestAction, leave: LeaveDep
) -> LeaveRequestView:
    try:
        request = leave.cancel(request_id, by=payload.by)
    except LeaveError as exc:
        raise _conflict(exc) from exc
    return LeaveRequestView.from_model(request)


@router.post("/approvals/{approval_id}/sync", response_model=LeaveRequestView)
async def sync_from_approval(approval_id: UUID, leave: LeaveDep) -> LeaveRequestView:
    """Sync a leave request with its approval's outcome (called after a decision)."""
    try:
        request = leave.apply_decision(approval_id)
    except LeaveError as exc:
        raise _not_found(str(exc)) from exc
    return LeaveRequestView.from_model(request)
