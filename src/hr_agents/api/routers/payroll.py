"""Payroll API router — prepare & verify only; never executes payments."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from hr_agents.api.deps import require_permission
from hr_agents.api.payroll_schemas import (
    InputsSet,
    RunAction,
    RunCreate,
    RunView,
)
from hr_agents.rbac import Permission
from hr_agents.services.payroll import PayrollError, PayrollService

router = APIRouter(
    prefix="/v1/payroll",
    tags=["payroll"],
    dependencies=[Depends(require_permission(Permission.PAYROLL_READ))],
)


def get_payroll(request: Request) -> PayrollService:
    return request.app.state.people.payroll


PayrollDep = Annotated[PayrollService, Depends(get_payroll)]


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


@router.post("/runs", status_code=status.HTTP_201_CREATED, response_model=RunView)
def create_run(payload: RunCreate, payroll: PayrollDep) -> RunView:
    try:
        run = payroll.create_run(
            period_year=payload.period_year,
            period_month=payload.period_month,
            created_by=payload.created_by,
            kind=payload.kind,
        )
    except PayrollError as exc:
        raise _conflict(exc) from exc
    return RunView.from_model(run)


@router.get("/runs", response_model=list[RunView])
def list_runs(payroll: PayrollDep) -> list[RunView]:
    return [RunView.from_model(run) for run in payroll.list_runs()]


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: UUID, payroll: PayrollDep) -> RunView:
    try:
        return RunView.from_model(payroll.get_run(run_id))
    except PayrollError as exc:
        raise _not_found(str(exc)) from exc


@router.put("/runs/{run_id}/inputs", response_model=RunView)
def set_inputs(run_id: UUID, payload: InputsSet, payroll: PayrollDep) -> RunView:
    try:
        run = payroll.set_inputs(
            run_id, inputs=[item.to_model() for item in payload.inputs], by=payload.by
        )
    except PayrollError as exc:
        raise _conflict(exc) from exc
    return RunView.from_model(run)


@router.post("/runs/{run_id}/compute", response_model=RunView)
def compute_run(run_id: UUID, payload: RunAction, payroll: PayrollDep) -> RunView:
    try:
        run = payroll.compute(run_id, by=payload.by)
    except PayrollError as exc:
        raise _conflict(exc) from exc
    return RunView.from_model(run)


@router.post("/runs/{run_id}/submit", response_model=RunView)
def submit_for_signoff(run_id: UUID, payload: RunAction, payroll: PayrollDep) -> RunView:
    try:
        run = payroll.submit_for_signoff(run_id, by=payload.by)
    except PayrollError as exc:
        raise _conflict(exc) from exc
    return RunView.from_model(run)


@router.post(
    "/approvals/{approval_id}/sync",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_APPROVE))],
)
def sync_decision(approval_id: UUID, payroll: PayrollDep) -> RunView:
    try:
        run = payroll.apply_decision(approval_id)
    except PayrollError as exc:
        raise _not_found(str(exc)) from exc
    return RunView.from_model(run)


@router.post(
    "/runs/{run_id}/export",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_APPROVE))],
)
def export_run(run_id: UUID, payload: RunAction, payroll: PayrollDep) -> RunView:
    try:
        run = payroll.mark_exported(run_id, by=payload.by)
    except PayrollError as exc:
        raise _conflict(exc) from exc
    return RunView.from_model(run)


@router.get("/runs/{run_id}/packet.xlsx")
def download_packet(run_id: UUID, payroll: PayrollDep) -> Response:
    try:
        content = payroll.build_review_packet_xlsx(run_id)
    except PayrollError as exc:
        raise _conflict(exc) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="payroll-{run_id}.xlsx"',
            "X-HRAgents-Notice": "review packet only; no payments executed",
        },
    )


@router.post("/runs/{run_id}/cancel", response_model=RunView)
def cancel_run(run_id: UUID, payload: RunAction, payroll: PayrollDep) -> RunView:
    if not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cancelling a run requires a reason",
        )
    try:
        run = payroll.cancel_run(run_id, by=payload.by, reason=payload.reason)
    except PayrollError as exc:
        raise _conflict(exc) from exc
    return RunView.from_model(run)
