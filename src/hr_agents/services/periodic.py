"""Run one unit of work on a period, and stop between ticks rather than inside one.

Docker sends SIGTERM and then SIGKILL after the grace period. A shell
``while true`` loop does not forward that signal to its Python child, so the
child was killed mid-run and its queue lease had to expire before the work was
retried. Running the loop in Python means the signal becomes an event: the
current tick finishes (a pipeline run, a purge sweep, one messaging pass) and
the next one never starts.
"""

from __future__ import annotations

import contextlib
import signal
import threading
from collections.abc import Callable

from hr_agents.logging import get_logger

logger = get_logger(__name__)


def run_periodic(
    tick: Callable[[], object],
    *,
    interval_seconds: float,
    stop: threading.Event | None = None,
) -> int:
    """Call ``tick`` until SIGINT/SIGTERM, waiting ``interval_seconds`` between runs.

    ``stop`` is injectable so a test does not have to raise signals. A tick that
    raises is logged and the loop continues, matching the shell's
    ``python ... || echo failed`` behaviour; the return code is nonzero when any
    tick failed.
    """
    event = stop if stop is not None else threading.Event()

    def _request_stop(signum: int, _frame: object) -> None:
        logger.info("periodic_stop_requested", signal=signum)
        event.set()

    if stop is None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(ValueError, OSError, AttributeError):
                signal.signal(sig, _request_stop)

    failures = 0
    while not event.is_set():
        try:
            tick()
        except Exception as exc:  # one bad run must not take the department clock down
            failures += 1
            logger.error("periodic_tick_failed", error=type(exc).__name__, exc_info=True)
        if event.is_set():
            break
        event.wait(timeout=max(interval_seconds, 0.0))
    return 1 if failures else 0
