"""Run the scheduled job runner once (cron/systemd friendly).

Builds the same service containers as the API server, so the configured
storage backend applies (``HRAGENTS_STORE_BACKEND=postgres`` for production),
then runs every (or selected) job and prints the report. Exit code is nonzero
when any job fails.

The report is also written to ``HRAGENTS_SCHEDULER_REPORT`` (default
``/tmp/hragents-scheduler.json``) on every tick. That file is what makes a
compose ``while true`` loop observable: if a job starts failing, the timestamp
the ``hragents_scheduler_last_success_timestamp`` metric reports goes stale
instead of the failure being swallowed by the shell loop.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from hr_agents.api.metrics import record_scheduler_run
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
    parser.add_argument(
        "--report-path",
        default=None,
        help="where to write the JSON report (default: $HRAGENTS_SCHEDULER_REPORT)",
    )
    args = parser.parse_args(argv)

    app = create_app()
    scheduler = Scheduler(
        people=app.state.people,
        recruiting=app.state.recruiting,
        replies=app.state.messaging.replies,  # type: ignore[attr-defined]
    )
    try:
        report = scheduler.run(args.job, now=parse_at(args.at), purge=args.purge)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for job in report.jobs:
        record_scheduler_run(job.name, job.ok)

    payload = report.model_dump_json(indent=2)
    if args.json:
        print(payload)

    from hr_agents.api.metrics import SCHEDULER_REPORT_PATH

    target = Path(args.report_path) if args.report_path else SCHEDULER_REPORT_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    except OSError as exc:
        # A read-only /tmp must not take the department clock down with it.
        print(f"warning: could not write scheduler report to {target}: {exc}", file=sys.stderr)

    if not args.json:
        print(format_report(report))
    return 0 if all(job.ok for job in report.jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
