"""Attendance import — fingerprint/CSV exports into payroll inputs.

Pure parsing + aggregation. No database, no network, no LLM. The payroll
service resolves employee numbers and approved leave; this module turns text
into days so the rules stay testable without a database.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Mapping
from datetime import date, time
from io import StringIO
from uuid import UUID

from pydantic import Field

from hr_agents.models.common import StrictModel

STANDARD_HOURS_PER_DAY = 8.0
MAX_DATA_ROWS = 5000
EXPECTED_HEADER = ("employee_number", "date", "clock_in", "clock_out")


class AttendanceRowError(StrictModel):
    row: int
    employee_number: str | None = None
    code: str
    detail: str


class AttendanceDay(StrictModel):
    employee_number: str
    day: date
    clock_in: time
    clock_out: time
    worked_hours: float
    overtime_hours: float


class EmployeeAttendance(StrictModel):
    employee_number: str
    employee_id: UUID | None = None
    days_present: int
    overtime_hours: float
    absence_days: float
    on_leave_days: int = 0
    flags: list[str] = Field(default_factory=list)


class AttendancePreview(StrictModel):
    period_year: int
    period_month: int
    working_days: int
    file_hash: str
    rows: list[EmployeeAttendance]
    errors: list[AttendanceRowError]


class _RowError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _parse_clock(value: str) -> time:
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        raise _RowError("bad_time", f"clock value {value!r} is not HH:MM(24h)") from None


def parse_attendance_csv(
    text: str, *, period_year: int, period_month: int
) -> tuple[list[AttendanceDay], list[AttendanceRowError]]:
    """Parse fingerprint-style CSV rows. Never guesses; every refusal names the row."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return [], [AttendanceRowError(row=0, code="empty_file", detail="no rows in file")]
    reader = csv.reader(StringIO(normalized))
    try:
        header = next(reader)
    except StopIteration:
        return [], [AttendanceRowError(row=0, code="empty_file", detail="no rows in file")]
    cleaned = [cell.strip().lower() for cell in header]
    if tuple(cleaned) != EXPECTED_HEADER:
        return [], [
            AttendanceRowError(
                row=1,
                code="bad_header",
                detail=f"header must be {','.join(EXPECTED_HEADER)}",
            )
        ]
    days: list[AttendanceDay] = []
    errors: list[AttendanceRowError] = []
    seen: set[tuple[str, date]] = set()
    for index, record in enumerate(reader, start=2):
        if not record or all(not cell.strip() for cell in record):
            continue
        if len(record) != 4:
            errors.append(
                AttendanceRowError(row=index, code="bad_columns", detail="each row needs 4 columns")
            )
            continue
        if index - 1 > MAX_DATA_ROWS:
            errors.append(
                AttendanceRowError(
                    row=index,
                    code="too_many_rows",
                    detail=f"file exceeds {MAX_DATA_ROWS} rows",
                )
            )
            break
        number, day_raw, in_raw, out_raw = (cell.strip() for cell in record)
        try:
            if not number or len(number) > 40:
                raise _RowError("bad_employee", "employee_number is empty or too long")
            try:
                day = date.fromisoformat(day_raw.strip())
            except ValueError:
                raise _RowError("bad_date", f"date {day_raw!r} is not YYYY-MM-DD") from None
            if day.year != period_year or day.month != period_month:
                raise _RowError(
                    "outside_period",
                    f"{day.isoformat()} is not in {period_year}-{period_month:02d}",
                )
            start = _parse_clock(in_raw)
            end = _parse_clock(out_raw)
            start_minutes = start.hour * 60 + start.minute
            end_minutes = end.hour * 60 + end.minute
            if end_minutes <= start_minutes:
                raise _RowError("invalid_hours", "clock_out must be after clock_in on the same day")
            if (number, day) in seen:
                raise _RowError("duplicate_day", f"second row for {number} on {day.isoformat()}")
            seen.add((number, day))
            worked = round((end_minutes - start_minutes) / 60, 2)
            overtime = round(max(0.0, worked - STANDARD_HOURS_PER_DAY), 2)
            days.append(
                AttendanceDay(
                    employee_number=number,
                    day=day,
                    clock_in=start,
                    clock_out=end,
                    worked_hours=worked,
                    overtime_hours=overtime,
                )
            )
        except _RowError as exc:
            errors.append(
                AttendanceRowError(
                    row=index,
                    employee_number=number or None,
                    code=exc.code,
                    detail=exc.detail,
                )
            )
    return days, errors


def summarize_attendance(
    days: list[AttendanceDay],
    *,
    working_days: int,
    leave_days: Mapping[str, set[date]] | None = None,
) -> list[EmployeeAttendance]:
    """Aggregate parsed days per employee. Leave days excuse an absence, not a record."""
    leave_days = leave_days or {}
    by_employee: dict[str, list[AttendanceDay]] = {}
    for day in days:
        by_employee.setdefault(day.employee_number, []).append(day)
    rows: list[EmployeeAttendance] = []
    for number in sorted(by_employee):
        records = by_employee[number]
        present = {item.day for item in records}
        excused = {day for day in leave_days.get(number, set()) if day not in present}
        absence = max(0.0, float(working_days - len(present) - len(excused)))
        overtime = round(sum(item.overtime_hours for item in records), 2)
        flags: list[str] = []
        if overtime > 60.0:
            flags.append("overtime_excessive")
        if absence >= working_days and working_days > 0:
            flags.append("absence_full_period")
        rows.append(
            EmployeeAttendance(
                employee_number=number,
                days_present=len(present),
                overtime_hours=overtime,
                absence_days=absence,
                on_leave_days=len(excused),
                flags=flags,
            )
        )
    return rows


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
