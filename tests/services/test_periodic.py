"""Periodic loops stop between ticks, so the running unit can drain."""

from __future__ import annotations

import threading

from hr_agents.services.periodic import run_periodic


def test_ticks_repeat_until_the_event_is_set() -> None:
    stop = threading.Event()
    calls: list[int] = []

    def tick() -> None:
        calls.append(len(calls) + 1)
        if len(calls) == 3:
            stop.set()

    assert run_periodic(tick, interval_seconds=0, stop=stop) == 0
    assert calls == [1, 2, 3]


def test_a_failed_tick_is_counted_and_the_next_one_still_runs() -> None:
    stop = threading.Event()
    calls: list[int] = []

    def tick() -> None:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("the first run failed")
        stop.set()

    assert run_periodic(tick, interval_seconds=0, stop=stop) == 1
    assert calls == [1, 2]


def test_a_pre_set_stop_runs_nothing() -> None:
    stop = threading.Event()
    stop.set()
    calls: list[int] = []

    assert run_periodic(lambda: calls.append(1), interval_seconds=0, stop=stop) == 0
    assert calls == []
