"""Run the evaluation worker: claim queued applications and run the pipeline.

The API publishes ``evaluation.evaluate`` messages; this process is what makes
them real. It builds the same service containers as the API server, resolves the
same queue backend, and constructs all five agents, so a running worker means
"submitted applications actually get evaluated".

Loops until SIGTERM, draining in-flight work before exit (``--once`` runs a
single poll for cron, CI, and smoke checks).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
from dataclasses import dataclass, field

from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agentset import build_agent_set
from hr_agents.config import get_settings
from hr_agents.logging import configure_logging, get_logger
from hr_agents.main import create_app
from hr_agents.providers.queue import QueueBackend
from hr_agents.queue import resolve_queue_backend
from hr_agents.services.evaluation_job import EVALUATION_TOPIC, EvaluationJobHandler
from hr_agents.services.pipeline import (
    ApplicationPipeline,
    InMemoryStorage,
    PipelineConfig,
)
from hr_agents.services.worker import Worker, WorkerConfig

logger = get_logger(__name__)


@dataclass(slots=True)
class WorkerSettings:
    topic: str = EVALUATION_TOPIC
    poll_interval: float = 2.0
    batch_size: int = 1
    max_attempts: int = 3
    lease_seconds: float = 300.0
    scoring_runs: int | None = None
    once: bool = False
    idle_exit_after: float | None = None
    errors: list[str] = field(default_factory=list)


def build_pipeline(app, agent_set, config: PipelineConfig) -> ApplicationPipeline:
    """Wire the extraction pipeline with every agent the evaluation path needs."""
    storage = InMemoryStorage(agent_set.tools)
    return ApplicationPipeline(
        deconstructor=agent_set.resume,
        storage=storage,
        audit=app.state.audit,
        config=config,
    )


def build_worker(app, agent_set, queue: QueueBackend, settings: WorkerSettings) -> Worker:
    """Compose the queue handler and the bounded-attempt worker around it."""
    config = PipelineConfig(
        scoring_runs=settings.scoring_runs if settings.scoring_runs is not None else 3
    )
    pipeline = build_pipeline(app, agent_set, config)
    handler = EvaluationJobHandler(
        pipeline=pipeline,
        applications=app.state.store,
        evaluations=app.state.recruiting.evaluations,
        jobs=app.state.recruiting.jobs,
        audit=app.state.audit,
    )
    return Worker(
        queue,
        handler,
        config=WorkerConfig(
            topic=settings.topic,
            max_attempts=settings.max_attempts,
            lease_seconds=settings.lease_seconds,
            batch_size=settings.batch_size,
        ),
    )


async def run_worker(settings: WorkerSettings) -> int:
    """Poll the queue until stopped. Returns a process exit code."""
    app = create_app()
    configure_logging(get_settings().log_level)

    queue = await resolve_queue_backend()
    agent_set = await build_agent_set(audit=app.state.audit, runtime=AgentRuntime.from_env())
    worker = build_worker(app, agent_set, queue, settings)

    logger.info(
        "worker_started",
        topic=settings.topic,
        backend=type(queue).__name__,
        poll_interval=settings.poll_interval,
        scoring_runs=settings.scoring_runs or get_settings().scoring_runs,
        agents=list(agent_set.agent_names),
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):  # not on Windows loops
            loop.add_signal_handler(sig, stop.set)

    idle_polls = 0
    while not stop.is_set():
        try:
            handled = await worker.run_once()
        except Exception as exc:
            logger.error("worker_poll_failed", error=type(exc).__name__, detail=str(exc))
            settings.errors.append(f"poll failed: {type(exc).__name__}: {exc}")
            handled = 0

        if handled:
            idle_polls = 0
            logger.info(
                "worker_batch_done",
                processed=worker.stats.processed,
                failed=worker.stats.failed,
                requeued=worker.stats.requeued,
                dead_lettered=worker.stats.dead_lettered,
            )
        else:
            idle_polls += 1

        if settings.once:
            break
        if settings.idle_exit_after is not None and idle_polls * settings.poll_interval >= (
            settings.idle_exit_after
        ):
            logger.info("worker_idle_exit", after_seconds=settings.idle_exit_after)
            break

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval)

    logger.info(
        "worker_stopped",
        processed=worker.stats.processed,
        failed=worker.stats.failed,
        requeued=worker.stats.requeued,
        dead_lettered=worker.stats.dead_lettered,
        errors=len(worker.stats.errors),
    )
    for error in worker.stats.errors:
        logger.error("worker_message_error", detail=error)
    return 1 if settings.errors or worker.stats.dead_lettered else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default=EVALUATION_TOPIC, help="queue topic to claim")
    parser.add_argument(
        "--poll-interval", type=float, default=2.0, help="seconds to wait when idle"
    )
    parser.add_argument("--batch-size", type=int, default=1, help="messages per claim")
    parser.add_argument(
        "--max-attempts", type=int, default=3, help="attempts before dead-lettering"
    )
    parser.add_argument(
        "--lease-seconds",
        type=float,
        default=300.0,
        help="claim lease; must exceed the p95 extraction time",
    )
    parser.add_argument(
        "--scoring-runs",
        type=int,
        default=None,
        help=(
            "independent extraction runs per application (k for sigma); "
            "defaults to HRAGENTS_SCORING_RUNS, or 3"
        ),
    )
    parser.add_argument(
        "--once", action="store_true", help="poll a single batch then exit (cron, smoke)"
    )
    parser.add_argument(
        "--idle-exit-seconds",
        type=float,
        default=None,
        help="exit after this long with no work (default: run forever)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = WorkerSettings(
        topic=args.topic,
        poll_interval=args.poll_interval,
        batch_size=args.batch_size,
        max_attempts=args.max_attempts,
        lease_seconds=args.lease_seconds,
        scoring_runs=args.scoring_runs,
        once=args.once,
        idle_exit_after=args.idle_exit_seconds,
    )
    try:
        return asyncio.run(run_worker(settings))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
