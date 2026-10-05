"""Postgres-backed payroll store.

Amounts go into ``Numeric(18,2)`` columns rather than a JSON document so a payslip
can be reconciled in SQL. That makes this adapter the one place the full field list
appears twice -- once here, once in ``db/payroll_tables.py`` -- and
``PayrollLine.check_invariants`` is the guard: a line whose totals do not match its
components cannot be written, so a column added here and forgotten there fails the
adapter tests rather than producing a payslip that quietly disagrees with itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.payroll_tables import PayrollLineRecord, PayrollRunRecord
from hr_agents.db.session import sync_session_scope
from hr_agents.models.payroll import (
    PayrollAnomaly,
    PayrollInput,
    PayrollLine,
    PayrollRun,
    PayrollRunKind,
    PayrollRunStatus,
)
from hr_agents.services.payroll import PayrollService

# The monetary columns, in the order `models.PayrollLine` declares them. Anything
# Money-typed is a Decimal on the way in and a Decimal on the way out; the rest are
# counts and identifiers.
_AMOUNT_FIELDS = (
    "base_salary",
    "allowances",
    "overtime_pay",
    "bonus",
    "gross",
    "bpjs_kesehatan_employee",
    "bpjs_jht_employee",
    "bpjs_jp_employee",
    "pph21",
    "other_deductions",
    "total_deductions",
    "net",
    "bpjs_kesehatan_employer",
    "bpjs_jht_employer",
    "bpjs_jp_employer",
    "bpjs_jkk_employer",
    "bpjs_jkm_employer",
    "employer_cost",
)


def _aware(moment: datetime) -> datetime:
    """Stamp a naive datetime as UTC; SQLite drops the tzinfo SQLite has no zone."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class DbPayrollService(PayrollService):
    """Durable payroll runs on the ``payroll_runs``/``payroll_lines`` tables."""

    def __init__(self, session_factory: sessionmaker[Session], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._session_factory = session_factory

    def _load_run(self, run_id: UUID) -> PayrollRun | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(PayrollRunRecord, run_id)
            return None if row is None else self._to_run(session, row)

    def _iter_runs(self) -> Iterator[PayrollRun]:
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    select(PayrollRunRecord).order_by(
                        PayrollRunRecord.period_year,
                        PayrollRunRecord.period_month,
                        PayrollRunRecord.created_at,
                    )
                )
                .scalars()
                .all()
            )
            # Materialised inside the session: a lazy iterator would read through a
            # closed session.
            return iter([self._to_run(session, row) for row in rows])

    def _save_run(self, run: PayrollRun) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(PayrollRunRecord, run.id)
            values = {
                "period_year": run.period_year,
                "period_month": run.period_month,
                "kind": run.kind.value,
                "status": run.status.value,
                "inputs": [item.model_dump(mode="json") for item in run.inputs],
                "anomalies": [item.model_dump(mode="json") for item in run.anomalies],
                "rate_table_ids": dict(run.rate_table_ids),
                "approval_id": run.approval_id,
                "signed_off_by": run.signed_off_by,
                "signed_off_at": _optional_aware(run.signed_off_at),
                "exported_at": _optional_aware(run.exported_at),
                "created_at": _aware(run.created_at),
                "updated_at": _aware(run.updated_at),
            }
            if row is None:
                row = PayrollRunRecord(id=run.id, **values)
                session.add(row)
            else:
                for column, value in values.items():
                    setattr(row, column, value)
            # Lines are replaced wholesale rather than merged. A recomputed run has a
            # different set of employees, so a merge would leave the lines of an
            # employee who is no longer in the run on the payslip.
            session.execute(delete(PayrollLineRecord).where(PayrollLineRecord.run_id == run.id))
            session.add_all(self._line_records(run))

    @staticmethod
    def _line_records(run: PayrollRun) -> list[PayrollLineRecord]:
        records: list[PayrollLineRecord] = []
        for line in run.lines:
            values: dict[str, object] = {
                "run_id": run.id,
                "employee_id": line.employee_id,
                "employee_name": line.employee_name,
                "thr_months": line.thr_months,
                "notes": list(line.notes),
            }
            for field in _AMOUNT_FIELDS:
                values[field] = Decimal(getattr(line, field))
            records.append(PayrollLineRecord(**values))
        return records

    def _to_run(self, session: Session, row: PayrollRunRecord) -> PayrollRun:
        line_rows = (
            session.execute(select(PayrollLineRecord).where(PayrollLineRecord.run_id == row.id))
            .scalars()
            .all()
        )
        return PayrollRun(
            id=row.id,
            period_year=row.period_year,
            period_month=row.period_month,
            kind=PayrollRunKind(row.kind),
            status=PayrollRunStatus(row.status),
            inputs=[PayrollInput.model_validate(item) for item in row.inputs],
            lines=[self._to_line(line_row) for line_row in line_rows],
            anomalies=[PayrollAnomaly.model_validate(item) for item in row.anomalies],
            rate_table_ids={str(key): str(value) for key, value in row.rate_table_ids.items()},
            approval_id=row.approval_id,
            signed_off_by=row.signed_off_by,
            signed_off_at=_aware(row.signed_off_at) if row.signed_off_at else None,
            exported_at=_aware(row.exported_at) if row.exported_at else None,
            created_at=_aware(row.created_at),
            updated_at=_aware(row.updated_at),
        )

    @staticmethod
    def _to_line(row: PayrollLineRecord) -> PayrollLine:
        values: dict[str, object] = {
            "employee_id": row.employee_id,
            "employee_name": row.employee_name,
            "thr_months": row.thr_months,
            "notes": list(row.notes),
        }
        for field in _AMOUNT_FIELDS:
            values[field] = Decimal(getattr(row, field))
        line = PayrollLine.model_validate(values)
        # Asserted on the way *out* of the database as well as in. A payslip whose
        # stored components no longer add up to its stored total is the exact
        # failure the invariants exist to catch, and a database round trip is
        # exactly when it would go unnoticed.
        line.check_invariants()
        return line


def _optional_aware(moment: datetime | None) -> datetime | None:
    return None if moment is None else _aware(moment)
