"""Queue resolution and metrics.

The resolver is the only thing standing between "the API published work" and
"nothing ever evaluates it", so each branch is pinned: unreachable redis falls
through to postgres, a process-local queue is refused unless it is asked for by
name, and the metrics expose the canaries that would have caught the missing
worker on day one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from hr_agents.api.metrics import (
    queued_application_counts,
    record_http_request,
    record_scheduler_run,
    render,
    scheduler_last_success,
    stuck_queued_count,
)
from hr_agents.providers.base import (
    BuildFn,
    Capability,
    HealthFn,
    ProviderConfig,
    ProviderHealth,
    ProviderSpec,
)
from hr_agents.providers.queue import MemoryQueueBackend
from hr_agents.providers.registry import ProviderRegistry
from hr_agents.queue import QueueUnavailableError, resolve_queue_backend
from hr_agents.services.ingestion import ApplicationStore, SubmissionInput

NOW = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)


class _Config(ProviderConfig):
    pass


def _spec(provider_id: str, build: BuildFn, health: HealthFn) -> ProviderSpec:
    return ProviderSpec(
        id=provider_id,
        capability=Capability.QUEUE,
        display_name=provider_id,
        config_model=_Config,
        build=build,
        health_check=health,
    )


def _registry(*specs: ProviderSpec) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register_all(specs)
    return registry


# --- resolution ---------------------------------------------------------------


async def test_an_explicitly_requested_memory_queue_is_honoured() -> None:
    registry = _registry(
        _spec("queue.memory", lambda _c: MemoryQueueBackend(), lambda _c: ProviderHealth.ok())
    )

    backend = await resolve_queue_backend(registry=registry, prefer="queue.memory")

    assert isinstance(backend, MemoryQueueBackend)


async def test_an_unreachable_candidate_falls_through_to_the_next() -> None:
    """redis is first in the chain; when it cannot be reached, postgres takes over."""
    registry = _registry(
        _spec(
            "queue.redis",
            lambda _c: MemoryQueueBackend(),
            lambda _c: ProviderHealth.unavailable("connection refused"),
        ),
        _spec("queue.postgres", lambda _c: MemoryQueueBackend(), lambda _c: ProviderHealth.ok()),
    )

    backend = await resolve_queue_backend(registry=registry)

    assert isinstance(backend, MemoryQueueBackend)


async def test_a_process_local_queue_is_refused_when_only_implicit() -> None:
    """Otherwise the API process accepts work no separate worker can claim."""
    registry = _registry(
        _spec("queue.memory", lambda _c: MemoryQueueBackend(), lambda _c: ProviderHealth.ok())
    )

    with pytest.raises(QueueUnavailableError, match="cannot span api\\+worker"):
        await resolve_queue_backend(registry=registry)


async def test_a_provider_that_fails_to_build_is_skipped() -> None:
    def explode(_config: ProviderConfig) -> object:
        raise RuntimeError("no driver installed")

    registry = _registry(
        _spec("queue.redis", explode, lambda _c: ProviderHealth.ok()),
        _spec("queue.postgres", lambda _c: MemoryQueueBackend(), lambda _c: ProviderHealth.ok()),
    )

    backend = await resolve_queue_backend(registry=registry)

    assert isinstance(backend, MemoryQueueBackend)


async def test_no_usable_queue_raises_and_names_what_it_tried() -> None:
    registry = _registry(
        _spec(
            "queue.redis",
            lambda _c: MemoryQueueBackend(),
            lambda _c: ProviderHealth.unavailable("timeout"),
        )
    )

    with pytest.raises(QueueUnavailableError) as excinfo:
        await resolve_queue_backend(registry=registry)

    message = str(excinfo.value)
    assert "queue.redis" in message
    assert "timeout" in message
    assert "queue.postgres" in message, "the operator must be told the fallback to set"


# --- metrics ------------------------------------------------------------------


def test_stuck_queued_counts_the_applications_nothing_will_evaluate() -> None:
    store = ApplicationStore()
    for _ in range(3):
        store.submit(SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True))

    assert stuck_queued_count(store) == 3
    assert queued_application_counts(store) == {"queued": 3}


def test_metrics_never_raise_on_a_broken_store() -> None:
    class Broken:
        def iter_all(self) -> Iterator[object]:
            raise RuntimeError("connection lost")

    assert queued_application_counts(Broken()) == {}
    assert stuck_queued_count(Broken()) == 0


def test_http_and_scheduler_counters_appear_in_the_payload() -> None:
    record_http_request("/v1/applications", 202, 0.012)
    record_http_request("/v1/applications", 202, 0.008)
    record_scheduler_run("retention", ok=True)
    record_scheduler_run("retention", ok=False)

    queued = ApplicationStore()
    for _ in range(2):
        queued.submit(SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True))

    class FakeState:
        store = queued
        audit = None

    class FakeApp:
        state = FakeState()

    payload = render(FakeApp())

    def series(name: str) -> float:
        """Read a counter/gauge. Counters are process-global, so the value is
        order-dependent — only the presence of a series is a hard assertion."""
        for line in payload.splitlines():
            if line.startswith(name):
                return float(line.rsplit(" ", 1)[1])
        raise AssertionError(f"{name} missing from:\n{payload}")

    assert "hragents_build_info" in payload
    assert series('hragents_http_requests_total{route="/v1/applications",status="202"}') >= 2
    assert "hragents_http_request_duration_seconds_sum" in payload
    assert series('hragents_scheduler_runs_total{job="retention",result="ok"}') >= 1
    assert series('hragents_scheduler_runs_total{job="retention",result="failed"}') >= 1
    assert series("hragents_applications_stuck_queued") == 2
    assert series('hragents_applications_by_status{status="queued"}') == 2


def test_scheduler_last_success_reads_the_loop_report(tmp_path: Path) -> None:
    """A `while true` loop swallows failures, so its report file is the canary."""
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "started_at": "2026-03-10T09:00:00Z",
                "jobs": [
                    {"name": "retention", "ok": True},
                    {"name": "audit_verify", "ok": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    import hr_agents.api.metrics as metrics_module

    original = metrics_module.SCHEDULER_REPORT_PATH
    metrics_module.SCHEDULER_REPORT_PATH = report
    try:
        last = scheduler_last_success()
    finally:
        metrics_module.SCHEDULER_REPORT_PATH = original

    assert list(last) == ["retention"]
    assert last["retention"] == datetime(2026, 3, 10, 9, 0, tzinfo=UTC).timestamp()


def test_scheduler_last_success_tolerates_a_missing_or_broken_report(
    tmp_path: Path,
) -> None:
    import hr_agents.api.metrics as metrics_module

    original = metrics_module.SCHEDULER_REPORT_PATH
    try:
        metrics_module.SCHEDULER_REPORT_PATH = tmp_path / "absent.json"
        assert scheduler_last_success() == {}

        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        metrics_module.SCHEDULER_REPORT_PATH = broken
        assert scheduler_last_success() == {}
    finally:
        metrics_module.SCHEDULER_REPORT_PATH = original
