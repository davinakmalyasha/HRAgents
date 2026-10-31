"""Probe the configured calendar provider: refresh a token, read free/busy.

This is the operator's end-to-end check while no interviewer directory maps a
person to a calendar id (see `integrations/google_calendar.py`). Exit codes:
0 answered, 2 not configured, 1 the provider refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

from hr_agents.integrations.google_calendar import GoogleCalendarError
from hr_agents.providers.base import Capability
from hr_agents.providers.registry import default_registry
from hr_agents.providers.settings import resolve_provider_settings

GOOGLE_CALENDAR_PROVIDER_ID = "calendar.google"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=1, help="window length (default: 1)")
    args = parser.parse_args(argv)

    resolved = resolve_provider_settings().get(Capability.CALENDAR)
    if resolved is None or resolved.provider_id != GOOGLE_CALENDAR_PROVIDER_ID:
        print(
            "calendar.google is not configured; set HRAGENTS_PROVIDER_CALENDAR and its config",
            file=sys.stderr,
        )
        return 2
    spec = default_registry().get(GOOGLE_CALENDAR_PROVIDER_ID)
    if spec.build is None:
        print("the calendar.google provider has no builder", file=sys.stderr)
        return 2
    try:
        adapter = spec.build(spec.make_config(resolved.config))
        start = datetime.now(UTC)
        slots = adapter.busy(start=start, end=start + timedelta(days=args.days))
    except GoogleCalendarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "provider": GOOGLE_CALENDAR_PROVIDER_ID,
                "calendar_id": resolved.config.get("calendar_id", "primary"),
                "window_days": args.days,
                "busy": [
                    {"start": slot.start_utc.isoformat(), "end": slot.end_utc.isoformat()}
                    for slot in slots
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
