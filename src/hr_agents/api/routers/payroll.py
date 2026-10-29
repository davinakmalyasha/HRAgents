"""Payroll API router — prepare & verify only; never executes payments."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from hr_agents.api.deps import ActorDep, PaginationDep, require_permission
from hr_agents.api.payroll_schemas import (
    AttendanceCommit,
    AttendancePreviewView,
    InputsSet,
    RunAction,
    RunCreate,
    RunView,
)
from hr_agents.api.problem import conflict, not_found
from hr_agents.api.schemas import Page
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


@router.post(
    "/runs",
    status_code=status.HTTP_201_CREATED,
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
)
def create_run(payload: RunCreate, payroll: PayrollDep, actor: ActorDep) -> RunView:
    try:
        run = payroll.create_run(
            period_year=payload.period_year,
            period_month=payload.period_month,
            actor=actor,
            kind=payload.kind,
        )
    except PayrollError as exc:
        raise conflict(exc) from exc
    return RunView.from_model(run)


@router.get("/runs", response_model=Page[RunView])
def list_runs(payroll: PayrollDep, paging: PaginationDep) -> Page[RunView]:
    runs, total = payroll.page_runs(limit=paging.limit, offset=paging.offset)
    return Page.of(
        [RunView.from_model(run) for run in runs],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: UUID, payroll: PayrollDep) -> RunView:
    try:
        return RunView.from_model(payroll.get_run(run_id))
    except PayrollError as exc:
        raise not_found(str(exc)) from exc


@router.put(
    "/runs/{run_id}/inputs",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
)
def set_inputs(run_id: UUID, payload: InputsSet, payroll: PayrollDep, actor: ActorDep) -> RunView:
    try:
        run = payroll.set_inputs(
            run_id, inputs=[item.to_model() for item in payload.inputs], actor=actor
        )
    except PayrollError as exc:
        raise conflict(exc) from exc
    return RunView.from_model(run)


@router.post(
    "/runs/{run_id}/attendance:preview",
    response_model=AttendancePreviewView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
    summary="Preview fingerprint CSV aggregation without writing",
)
def preview_attendance(
    run_id: UUID, payload: AttendanceCommit, payroll: PayrollDep, actor: ActorDep
) -> AttendancePreviewView:
    try:
        run = payroll.get_run(run_id)
        preview = payroll.preview_attendance(
            payload.csv_text,
            period_year=run.period_year,
            period_month=run.period_month,
        )
    except PayrollError as exc:
        raise not_found(str(exc)) from exc
    from hr_agents.api.payroll_schemas import AttendanceErrorView, AttendanceRowView

    return AttendancePreviewView(
        period_year=preview.period_year,
        period_month=preview.period_month,
        working_days=preview.working_days,
        file_hash=preview.file_hash,
        rows=[
            AttendanceRowView(
                employee_number=row.employee_number,
                employee_id=row.employee_id,
                days_present=row.days_present,
                overtime_hours=row.overtime_hours,
                absence_days=row.absence_days,
                on_leave_days=row.on_leave_days,
                flags=row.flags,
            )
            for row in preview.rows
        ],
        errors=[
            AttendanceErrorView(
                row=error.row,
                employee_number=error.employee_number,
                code=error.code,
                detail=error.detail,
            )
            for error in preview.errors
        ],
    )


@router.post(
    "/runs/{run_id}/attendance:commit",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
    summary="Fill overtime/absence on an editable run from fingerprint CSV",
)
def commit_attendance(
    run_id: UUID, payload: AttendanceCommit, payroll: PayrollDep, actor: ActorDep
) -> RunView:
    try:
        run = payroll.apply_attendance(run_id, payload.csv_text, actor=actor)
    except PayrollError as exc:
        raise conflict(exc) from exc
    return RunView.from_model(run)


@router.post(
    "/runs/{run_id}/compute",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
)
def compute_run(run_id: UUID, payload: RunAction, payroll: PayrollDep, actor: ActorDep) -> RunView:
    try:
        run = payroll.compute(run_id, actor=actor)
    except PayrollError as exc:
        raise conflict(exc) from exc
    return RunView.from_model(run)


@router.post(
    "/runs/{run_id}/supersede",
    status_code=status.HTTP_201_CREATED,
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
    summary="Start a new run that replaces a reviewed one; the reviewed run is not rewritten",
)
def supersede_run(
    run_id: UUID, payload: RunAction, payroll: PayrollDep, actor: ActorDep
) -> RunView:
    if not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="superseding a run requires a reason",
        )
    try:
        run = payroll.supersede_run(run_id, actor=actor, reason=payload.reason)
    except PayrollError as exc:
        raise conflict(exc) from exc
    return RunView.from_model(run)


@router.post(
    "/runs/{run_id}/submit",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
)
def submit_for_signoff(
    run_id: UUID, payload: RunAction, payroll: PayrollDep, actor: ActorDep
) -> RunView:
    try:
        run = payroll.submit_for_signoff(run_id, actor=actor)
    except PayrollError as exc:
        raise conflict(exc) from exc
    return RunView.from_model(run)


@router.post(
    "/approvals/{approval_id}/sync",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_APPROVE))],
)
def sync_decision(approval_id: UUID, payroll: PayrollDep, actor: ActorDep) -> RunView:
    """Land a decided approval's outcome on the payroll run."""
    try:
        run = payroll.apply_decision(approval_id, actor=actor)
    except PayrollError as exc:
        raise not_found(str(exc)) from exc
    return RunView.from_model(run)


@router.post(
    "/runs/{run_id}/export",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_APPROVE))],
)
def export_run(run_id: UUID, payload: RunAction, payroll: PayrollDep, actor: ActorDep) -> RunView:
    try:
        run = payroll.mark_exported(run_id, actor=actor)
    except PayrollError as exc:
        raise conflict(exc) from exc
    return RunView.from_model(run)


@router.get("/runs/{run_id}/packet.xlsx")
def download_packet(run_id: UUID, payroll: PayrollDep) -> Response:
    try:
        content = payroll.build_review_packet_xlsx(run_id)
    except PayrollError as exc:
        raise conflict(exc) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="payroll-{run_id}.xlsx"',
            "X-HRAgents-Notice": "review packet only; no payments executed",
        },
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunView,
    dependencies=[Depends(require_permission(Permission.PAYROLL_WRITE))],
)
def cancel_run(run_id: UUID, payload: RunAction, payroll: PayrollDep, actor: ActorDep) -> RunView:
    if not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cancelling a run requires a reason",
        )
    try:
        run = payroll.cancel_run(run_id, actor=actor, reason=payload.reason)
    except PayrollError as exc:
        raise conflict(exc) from exc
    return RunView.from_model(run)
