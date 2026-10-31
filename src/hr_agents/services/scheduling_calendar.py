"""Turn a calendar's busy intervals into interviewer availability.

Pure and deterministic: the work window is the operator's policy, the busy list
is the provider's answer, and the result is the free time between them. No
network and no clock beyond the one passed in, so the arithmetic is testable
without Google.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hr_agents.models import TimeSlot, utc_now

WORK_START_HOUR = 9
WORK_END_HOUR = 17
SYNC_DAYS = 14


def free_slots(
    busy: Sequence[TimeSlot],
    *,
    start_date: date,
    days: int = SYNC_DAYS,
    work_start_hour: int = WORK_START_HOUR,
    work_end_hour: int = WORK_END_HOUR,
    timezone: str = "Asia/Jakarta",
    now: datetime | None = None,
) -> list[TimeSlot]:
    """Free intervals on weekdays inside ``[work_start_hour, work_end_hour)``.

    Weekends are excluded because the operator's work week is a scheduling
    policy, not something the calendar can infer. Time already past is dropped:
    offering this morning to a candidate is not availability. Busy blocks are
    subtracted even when they overlap each other, and a block that covers the
    whole window simply produces no slots for that day.
    """
    if work_start_hour >= work_end_hour:
        raise ValueError("work_start_hour must be before work_end_hour")
    if days < 1:
        raise ValueError("days must be at least 1")
    tz = ZoneInfo(timezone)
    current = now or utc_now()
    ordered = sorted(busy, key=lambda slot: slot.start_utc)
    slots: list[TimeSlot] = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        window_start = datetime.combine(day, time(hour=work_start_hour), tzinfo=tz)
        window_end = datetime.combine(day, time(hour=work_end_hour), tzinfo=tz)
        if window_start < current.astimezone(tz):
            window_start = current.astimezone(tz)
        if window_end <= window_start:
            continue
        cursor = window_start
        for block in ordered:
            block_start = block.start_utc.astimezone(tz)
            block_end = block.end_utc.astimezone(tz)
            if block_end <= cursor:
                continue
            if block_start >= window_end:
                break
            if block_start > cursor:
                slots.append(
                    TimeSlot(
                        start_utc=cursor.astimezone(UTC),
                        end_utc=block_start.astimezone(UTC),
                    )
                )
            if block_end > cursor:
                cursor = block_end
        if cursor < window_end:
            slots.append(
                TimeSlot(start_utc=cursor.astimezone(UTC), end_utc=window_end.astimezone(UTC))
            )
    return slots
