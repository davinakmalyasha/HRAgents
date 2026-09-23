"""Run the scheduled job runner once (cron/systemd friendly).

Builds the same service containers as the API server, so the configured
storage backend applies (``HRAGENTS_STORE_BACKEND=postgres`` for production),
then runs every (or selected) job and prints the report. Exit code is nonzero
when any job fails.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from hr_agents.main import create_app
from hr_agents.services.scheduler import JOB_NAMES, Scheduler, format_report


def parse_at(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--job",
        action="append",
        choices=sorted(JOB_NAMES),
        default=None,
        help="run only this job (repeatable; default: all)",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="let the retention sweep actually purge expired records",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--at", default=None, help="ISO datetime clock override (backfill/testing)")
    args = parser.parse_args(argv)

    app = create_app()
    scheduler = Scheduler(people=app.state.people, recruiting=app.state.recruiting)
    try:
        report = scheduler.run(args.job, now=parse_at(args.at), purge=args.purge)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(format_report(report))
    return 0 if all(job.ok for job in report.jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
