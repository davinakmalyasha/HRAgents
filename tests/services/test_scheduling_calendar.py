"""Free/busy arithmetic: the operator's window minus the calendar's answer."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from hr_agents.models import TimeSlot
from hr_agents.services.scheduling_calendar import free_slots

MONDAY = date(2026, 11, 2)
BEFORE = datetime(2026, 10, 31, 0, 0, tzinfo=UTC)


def utc(day: date, hour: int, minute: int = 0) -> datetime:
    """A Jakarta wall-clock moment as UTC (UTC+7, no DST)."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - timedelta(hours=7)


def test_a_busy_block_is_subtracted_from_the_work_window() -> None:
    busy = [TimeSlot(start_utc=utc(MONDAY, 10), end_utc=utc(MONDAY, 11))]

    slots = free_slots(busy, start_date=MONDAY, days=1, now=BEFORE)

    assert [(slot.start_utc, slot.end_utc) for slot in slots] == [
        (utc(MONDAY, 9), utc(MONDAY, 10)),
        (utc(MONDAY, 11), utc(MONDAY, 17)),
    ]


def test_overlapping_busy_blocks_do_not_create_a_slot_between_them() -> None:
    busy = [
        TimeSlot(start_utc=utc(MONDAY, 10), end_utc=utc(MONDAY, 12)),
        TimeSlot(start_utc=utc(MONDAY, 11), end_utc=utc(MONDAY, 13)),
    ]

    slots = free_slots(busy, start_date=MONDAY, days=1, now=BEFORE)

    assert [(slot.start_utc, slot.end_utc) for slot in slots] == [
        (utc(MONDAY, 9), utc(MONDAY, 10)),
        (utc(MONDAY, 13), utc(MONDAY, 17)),
    ]


def test_a_block_covering_the_whole_window_leaves_nothing() -> None:
    busy = [TimeSlot(start_utc=utc(MONDAY, 8), end_utc=utc(MONDAY, 18))]

    assert free_slots(busy, start_date=MONDAY, days=1, now=BEFORE) == []


def test_weekends_are_not_offered() -> None:
    saturday = date(2026, 11, 7)

    slots = free_slots([], start_date=saturday, days=2, now=BEFORE)

    assert slots == []


def test_time_already_past_is_not_availability() -> None:
    # 11:30 Jakarta on the day itself: only the afternoon remains.
    now = utc(MONDAY, 11, 30)

    slots = free_slots([], start_date=MONDAY, days=1, now=now)

    assert [(slot.start_utc, slot.end_utc) for slot in slots] == [(now, utc(MONDAY, 17))]


def test_a_busy_block_outside_the_window_changes_nothing() -> None:
    busy = [TimeSlot(start_utc=utc(MONDAY, 6), end_utc=utc(MONDAY, 8))]

    slots = free_slots(busy, start_date=MONDAY, days=1, now=BEFORE)

    assert [(slot.start_utc, slot.end_utc) for slot in slots] == [(utc(MONDAY, 9), utc(MONDAY, 17))]


def test_the_window_is_configurable() -> None:
    slots = free_slots(
        [],
        start_date=MONDAY,
        days=1,
        work_start_hour=13,
        work_end_hour=15,
        now=BEFORE,
    )

    assert [(slot.start_utc, slot.end_utc) for slot in slots] == [
        (utc(MONDAY, 13), utc(MONDAY, 15))
    ]


def test_days_after_the_first_are_included() -> None:
    slots = free_slots([], start_date=MONDAY, days=2, now=BEFORE)

    assert [slot.start_utc for slot in slots] == [utc(MONDAY, 9), utc(date(2026, 11, 3), 9)]


def test_an_inverted_window_is_refused() -> None:
    with pytest.raises(ValueError, match="work_start_hour"):
        free_slots([], start_date=MONDAY, days=1, work_start_hour=17, work_end_hour=9)


def test_days_must_be_positive() -> None:
    with pytest.raises(ValueError, match="days"):
        free_slots([], start_date=MONDAY, days=0)
