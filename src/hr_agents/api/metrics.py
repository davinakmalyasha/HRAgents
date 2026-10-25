"""Operational metrics in Prometheus text format.

Hand-rolled rather than pulled from a client library: the surface below is a
dozen numbers, and the whole point is that a self-hoster can read them with
``curl`` and no extra stack.

The two that matter most are canaries for the failure mode that is invisible in
the UI — an application accepted into the queue that nothing ever evaluates:

    hragents_applications_stuck_queued   applications sitting in ``queued``
    hragents_scheduler_last_success_ts  last successful scheduler run, per job

A non-zero stuck count means no worker is draining the queue. A stale
last-success timestamp means a scheduled job has been failing silently inside a
``while true`` compose loop.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# The scheduler and messaging loops write their JSON report here on every tick.
# Reading its ``started_at`` is how a silent loop failure becomes visible.
SCHEDULER_REPORT_PATH = Path(
    os.environ.get("HRAGENTS_SCHEDULER_REPORT", "/tmp/hragents-scheduler.json")
)

_HTTP_REQUESTS: defaultdict[str, int] = defaultdict(int)
_HTTP_DURATION_SUM: defaultdict[str, float] = defaultdict(float)
_HTTP_DURATION_COUNT: defaultdict[str, int] = defaultdict(int)
_SCHEDULER_RUNS: defaultdict[str, int] = defaultdict(int)


def record_http_request(route: str, status_code: int, duration_seconds: float) -> None:
    """Called by the request-timing middleware."""
    _HTTP_REQUESTS[f'route="{route}",status="{status_code}"'] += 1
    _HTTP_DURATION_SUM[route] += duration_seconds
    _HTTP_DURATION_COUNT[route] += 1


def record_scheduler_run(job: str, ok: bool) -> None:
    """Called by the scheduler after every job."""
    _SCHEDULER_RUNS[f'job="{job}",result="{"ok" if ok else "failed"}"'] += 1


def queued_application_counts(store: Any) -> dict[str, int]:
    """Application counts by status, straight from the store."""
    counts: dict[str, int] = defaultdict(int)
    try:
        for record in store.iter_all():
            counts[record.status.value] += 1
    except Exception:  # metrics must never raise
        return {}
    return dict(counts)


def stuck_queued_count(store: Any) -> int:
    """Applications accepted but never evaluated — the missing-worker canary."""
    return queued_application_counts(store).get("queued", 0)


def scheduler_last_success() -> dict[str, float]:
    """Per-job age of the last successful run, read from the loop's JSON report."""
    try:
        report = json.loads(SCHEDULER_REPORT_PATH.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    started = report.get("started_at")
    if not isinstance(started, str):
        return {}

    def to_epoch(value: str) -> float:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.timestamp()

    try:
        completed = to_epoch(started)
    except ValueError:
        return {}
    last: dict[str, float] = {}
    for job in report.get("jobs", []):
        name = job.get("name")
        if isinstance(name, str) and job.get("ok"):
            last[name] = completed
    return last


def _lines() -> list[str]:
    lines: list[str] = [
        "# HELP hragents_build_info Build metadata.",
        "# TYPE hragents_build_info gauge",
        "# TYPE hragents_http_requests_total counter",
        "# TYPE hragents_http_request_duration_seconds_sum counter",
        "# TYPE hragents_http_request_duration_seconds_count counter",
        "# TYPE hragents_scheduler_runs_total counter",
        "# TYPE hragents_applications_by_status gauge",
        "# TYPE hragents_applications_stuck_queued gauge",
        "# TYPE hragents_scheduler_last_success_timestamp gauge",
        "# TYPE hragents_audit_chain_entries gauge",
    ]

    for series, value in sorted(_HTTP_REQUESTS.items()):
        lines.append(f"hragents_http_requests_total{{{series}}} {value}")
    for route in sorted(_HTTP_DURATION_SUM):
        lines.append(
            f'hragents_http_request_duration_seconds_sum{{route="{route}"}} '
            f"{_HTTP_DURATION_SUM[route]:.6f}"
        )
        lines.append(
            f'hragents_http_request_duration_seconds_count{{route="{route}"}} '
            f"{_HTTP_DURATION_COUNT[route]}"
        )
    for series, value in sorted(_SCHEDULER_RUNS.items()):
        lines.append(f"hragents_scheduler_runs_total{{{series}}} {value}")
    for job, epoch in sorted(scheduler_last_success().items()):
        lines.append(f'hragents_scheduler_last_success_timestamp{{job="{job}"}} {epoch}')
    return lines


def render(app: Any) -> str:
    """Full metrics payload for one application instance."""
    lines = _lines()
    from hr_agents import __version__

    lines.append(f'hragents_build_info{{version="{__version__}"}} 1')

    store = getattr(app.state, "store", None)
    if store is not None:
        by_status = queued_application_counts(store)
        for status_value, count in sorted(by_status.items()):
            lines.append(f'hragents_applications_by_status{{status="{status_value}"}} {count}')
        # Reuse the counts just computed. `stuck_queued_count` re-derives them,
        # which walked the whole applications store a second time on every scrape.
        lines.append(f"hragents_applications_stuck_queued {by_status.get('queued', 0)}")

    audit = getattr(app.state, "audit", None)
    if audit is not None:
        with suppress(Exception):
            lines.append(f"hragents_audit_chain_entries {audit.entry_count()}")

    usage = getattr(app.state, "llm_usage", None)
    if usage is not None:
        with suppress(Exception):
            summary = usage.summary(since=datetime.now(UTC) - timedelta(days=30))
            if summary.by_model:
                lines.append("# TYPE hragents_llm_tokens gauge")
                lines.append("# TYPE hragents_llm_requests gauge")
                for item in summary.by_model:
                    labels = (
                        f'provider="{_label(item.provider_id)}",'
                        f'model="{_label(item.model or "unknown")}"'
                    )
                    lines.append(
                        f'hragents_llm_tokens{{{labels},kind="input"}} {item.input_tokens}'
                    )
                    lines.append(
                        f'hragents_llm_tokens{{{labels},kind="output"}} {item.output_tokens}'
                    )
                    lines.append(
                        f'hragents_llm_tokens{{{labels},kind="cache_read"}} '
                        f"{item.cache_read_tokens}"
                    )
                    lines.append(f"hragents_llm_requests{{{labels}}} {item.requests}")

    return "\n".join(lines) + "\n"


def _label(value: str) -> str:
    """Prometheus label escaping: backslash, quote and newline only."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


async def queue_metrics(app: Any) -> list[str]:
    """Queue depth and dead letters, from whichever backend is mounted.

    The API accepts submissions and a worker drains them; a growing dead-letter
    count means submissions are being accepted and then failing forever. The
    backend is resolved in the lifespan, so a scrape before startup has no queue
    section rather than a misleading zero.
    """
    queue = getattr(app.state, "queue", None)
    if queue is None:
        return []
    from hr_agents.services.evaluation_job import EVALUATION_TOPIC

    try:
        stats = await queue.stats(EVALUATION_TOPIC)
    except Exception:  # metrics must never raise
        return []
    return [
        "# TYPE hragents_queue_pending gauge",
        "# TYPE hragents_queue_inflight gauge",
        "# TYPE hragents_queue_dead gauge",
        f'hragents_queue_pending{{topic="{stats.topic}"}} {stats.pending}',
        f'hragents_queue_inflight{{topic="{stats.topic}"}} {stats.inflight}',
        f'hragents_queue_dead{{topic="{stats.topic}"}} {stats.dead}',
    ]


async def render_async(app: Any) -> str:
    """The full payload, including the gauges that need an async read.

    ``render`` stayed synchronous for the store/audit gauges; queue stats are
    async in every backend, so the endpoint awaits this wrapper instead.
    """
    lines = render(app).rstrip("\n").splitlines()
    lines.extend(await queue_metrics(app))
    return "\n".join(lines) + "\n"
