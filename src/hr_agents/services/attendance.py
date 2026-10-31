"""Attendance import — fingerprint/CSV exports into payroll inputs.

Pure parsing + aggregation. No database, no network, no LLM. The payroll
service resolves employee numbers and approved leave; this module turns text
into days so the rules stay testable without a database.

Two assumptions are stated rather than hidden, because both decide how many
hours are paid:

- **A day is standard when it is shorter than ``standard_hours_per_day``** (8 by
  default). Every hour past it is overtime. The preview reports the value it
  used, and the operator can pass their own; the *price* of an overtime hour
  still comes from the verified overtime rate table, never from here.
- **One row is one calendar day.** A shift that ends after midnight cannot be
  represented: clock-out earlier than clock-in is refused rather than guessed,
  which fails the commit closed. Split an overnight shift at midnight, or use
  the payroll inputs directly.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from io import BytesIO, StringIO
from uuid import UUID

from openpyxl import load_workbook
from pydantic import Field

from hr_agents.models.common import StrictModel

STANDARD_HOURS_PER_DAY = 8.0
"""The default daily threshold; a scheduling assumption, not a statutory rate."""

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
    standard_hours_per_day: float = STANDARD_HOURS_PER_DAY


class _RowError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ColumnMapping(StrictModel):
    """Which spreadsheet column carries each required field.

    Fingerprint exports are named by whoever installed the machine, so the
    canonical header cannot be assumed. The mapping is matched case-insensitively
    after trimming, and a name that is not in the sheet is a header error — never
    a silent zero.
    """

    employee_number: str = Field(default="employee_number", min_length=1, max_length=120)
    date: str = Field(default="date", min_length=1, max_length=120)
    clock_in: str = Field(default="clock_in", min_length=1, max_length=120)
    clock_out: str = Field(default="clock_out", min_length=1, max_length=120)

    def pairs(self) -> tuple[tuple[str, str], ...]:
        """``(canonical field, column name)`` in the order the error names them."""
        return (
            ("employee_number", self.employee_number),
            ("date", self.date),
            ("clock_in", self.clock_in),
            ("clock_out", self.clock_out),
        )


def _parse_clock(value: str) -> time:
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        raise _RowError("bad_time", f"clock value {value!r} is not HH:MM(24h)") from None


def _cell_text(value: object) -> str:
    """One spreadsheet cell as text, without guessing a format it does not have."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        # Excel stores whole numbers as floats; "1001.0" is not an employee number.
        return str(int(value))
    return str(value).strip()


def _cell_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _cell_text(value)
    for parse in (date.fromisoformat, lambda item: date.fromisoformat(item.replace("/", "-"))):
        try:
            return parse(text)
        except ValueError:
            continue
    raise _RowError("bad_date", f"date {text!r} is not YYYY-MM-DD")


def _cell_time(value: object) -> time:
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, float) and 0 <= value < 1:
        # An Excel time cell is a fraction of a day when no format is applied.
        minutes = round(value * 24 * 60)
        return time(hour=(minutes // 60) % 24, minute=minutes % 60)
    return _parse_clock(_cell_text(value))


def _resolve_columns(
    header: Sequence[str], mapping: ColumnMapping, *, header_row: int
) -> tuple[dict[str, int], AttendanceRowError | None]:
    normalized = [_cell_text(cell).casefold() for cell in header]
    indices: dict[str, int] = {}
    missing: list[str] = []
    for field, name in mapping.pairs():
        try:
            indices[field] = normalized.index(name.strip().casefold())
        except ValueError:
            missing.append(name)
    if missing:
        return indices, AttendanceRowError(
            row=header_row,
            code="bad_header",
            detail="header is missing column(s): " + ", ".join(missing),
        )
    return indices, None


def _parse_record(
    record: Sequence[object],
    *,
    row: int,
    indices: Mapping[str, int],
    period_year: int,
    period_month: int,
    standard_hours_per_day: float,
    seen: set[tuple[str, date]],
) -> AttendanceDay:
    number = _cell_text(record[indices["employee_number"]])
    if not number or len(number) > 40:
        raise _RowError("bad_employee", "employee_number is empty or too long")
    day = _cell_date(record[indices["date"]])
    if day.year != period_year or day.month != period_month:
        raise _RowError(
            "outside_period",
            f"{day.isoformat()} is not in {period_year}-{period_month:02d}",
        )
    start = _cell_time(record[indices["clock_in"]])
    end = _cell_time(record[indices["clock_out"]])
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    if end_minutes <= start_minutes:
        raise _RowError("invalid_hours", "clock_out must be after clock_in on the same day")
    if (number, day) in seen:
        raise _RowError("duplicate_day", f"second row for {number} on {day.isoformat()}")
    seen.add((number, day))
    worked = round((end_minutes - start_minutes) / 60, 2)
    overtime = round(max(0.0, worked - standard_hours_per_day), 2)
    return AttendanceDay(
        employee_number=number,
        day=day,
        clock_in=start,
        clock_out=end,
        worked_hours=worked,
        overtime_hours=overtime,
    )


def parse_attendance_csv(
    text: str,
    *,
    period_year: int,
    period_month: int,
    standard_hours_per_day: float = STANDARD_HOURS_PER_DAY,
    mapping: ColumnMapping | None = None,
) -> tuple[list[AttendanceDay], list[AttendanceRowError]]:
    """Parse fingerprint-style CSV rows. Never guesses; every refusal names the row."""
    if standard_hours_per_day <= 0:
        raise ValueError("standard_hours_per_day must be positive")
    columns = mapping or ColumnMapping()
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return [], [AttendanceRowError(row=0, code="empty_file", detail="no rows in file")]
    reader = csv.reader(StringIO(normalized))
    try:
        header = next(reader)
    except StopIteration:
        return [], [AttendanceRowError(row=0, code="empty_file", detail="no rows in file")]
    indices, header_error = _resolve_columns(header, columns, header_row=1)
    if header_error is not None:
        return [], [header_error]
    days: list[AttendanceDay] = []
    errors: list[AttendanceRowError] = []
    seen: set[tuple[str, date]] = set()
    for index, record in enumerate(reader, start=2):
        if not record or all(not cell.strip() for cell in record):
            continue
        if len(record) <= max(indices.values()):
            errors.append(
                AttendanceRowError(row=index, code="bad_columns", detail="row is missing a column")
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
        number = _cell_text(record[indices["employee_number"]])
        try:
            days.append(
                _parse_record(
                    record,
                    row=index,
                    indices=indices,
                    period_year=period_year,
                    period_month=period_month,
                    standard_hours_per_day=standard_hours_per_day,
                    seen=seen,
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


def parse_attendance_xlsx(
    content: bytes,
    *,
    period_year: int,
    period_month: int,
    standard_hours_per_day: float = STANDARD_HOURS_PER_DAY,
    mapping: ColumnMapping | None = None,
    sheet: str | None = None,
    header_row: int = 1,
) -> tuple[list[AttendanceDay], list[AttendanceRowError]]:
    """Parse an XLSX export (or CSV saved as a workbook) through the CSV rule set.

    Real fingerprint exports carry dates and times as spreadsheet *values*, not
    strings, so the cells are coerced rather than compared as text. Everything
    after that — the period check, duplicate days, clock order, the row cap — is
    the same code the CSV path runs, so the two formats cannot drift apart.
    """
    if standard_hours_per_day <= 0:
        raise ValueError("standard_hours_per_day must be positive")
    if header_row < 1:
        raise ValueError("header_row is 1-based")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several unrelated types
        return [], [
            AttendanceRowError(row=0, code="bad_file", detail=f"not a readable workbook: {exc}")
        ]
    try:
        if sheet is not None:
            if sheet not in workbook.sheetnames:
                return [], [
                    AttendanceRowError(
                        row=0,
                        code="bad_sheet",
                        detail=f"sheet {sheet!r} is not in {', '.join(workbook.sheetnames)}",
                    )
                ]
            worksheet = workbook[sheet]
        else:
            worksheet = workbook.worksheets[0]
        rows = worksheet.iter_rows(values_only=True)
        header: Sequence[object] | None = None
        for _ in range(header_row):
            header = next(rows, None)
        if header is None:
            return [], [AttendanceRowError(row=0, code="empty_file", detail="no rows in file")]
        columns = mapping or ColumnMapping()
        indices, header_error = _resolve_columns(
            [_cell_text(cell) for cell in header], columns, header_row=header_row
        )
        if header_error is not None:
            return [], [header_error]
        days: list[AttendanceDay] = []
        errors: list[AttendanceRowError] = []
        seen: set[tuple[str, date]] = set()
        for index, record in enumerate(rows, start=header_row + 1):
            values = list(record)
            if not values or all(_cell_text(cell) == "" for cell in values):
                continue
            if index - header_row > MAX_DATA_ROWS:
                errors.append(
                    AttendanceRowError(
                        row=index,
                        code="too_many_rows",
                        detail=f"file exceeds {MAX_DATA_ROWS} rows",
                    )
                )
                break
            if len(values) <= max(indices.values()):
                errors.append(
                    AttendanceRowError(
                        row=index, code="bad_columns", detail="row is missing a column"
                    )
                )
                continue
            number = _cell_text(values[indices["employee_number"]])
            try:
                days.append(
                    _parse_record(
                        values,
                        row=index,
                        indices=indices,
                        period_year=period_year,
                        period_month=period_month,
                        standard_hours_per_day=standard_hours_per_day,
                        seen=seen,
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
    finally:
        workbook.close()


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
