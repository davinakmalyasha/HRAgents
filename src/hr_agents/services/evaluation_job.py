"""Queue handler that evaluates one application — the API-to-pipeline seam.

The API stores the submission; a worker runner claims the message; this handler
marks the application ``processing``, runs the deterministic pipeline, registers
the evaluation (which syncs the terminal status), and audits every transition.
Failures propagate so the ``Worker`` can retry or dead-letter the message.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from hr_agents.providers.queue import QueueMessage
from hr_agents.services.audit import AuditChain
from hr_agents.services.ingestion import ApplicationStatus, ApplicationStore
from hr_agents.services.pipeline import ApplicationPipeline
from hr_agents.services.recruiting import EvaluationService, JobService

EVALUATION_TOPIC = "evaluation.evaluate"


def evaluation_payload(
    *,
    application_id: UUID,
    job_id: UUID,
    resume_text: str,
    candidate_name: str = "",
) -> dict[str, Any]:
    """Build the message payload for one evaluation job."""
    return {
        "application_id": str(application_id),
        "job_id": str(job_id),
        "resume_text": resume_text,
        "candidate_name": candidate_name,
    }


class EvaluationJobHandler:
    """Runs the pipeline for one ``evaluation.evaluate`` message."""

    def __init__(
        self,
        *,
        pipeline: ApplicationPipeline,
        applications: ApplicationStore,
        evaluations: EvaluationService,
        jobs: JobService,
        audit: AuditChain,
    ) -> None:
        self._pipeline = pipeline
        self._applications = applications
        self._evaluations = evaluations
        self._jobs = jobs
        self._audit = audit

    async def __call__(self, message: QueueMessage) -> None:
        application_id = UUID(str(message.payload["application_id"]))
        job_id = UUID(str(message.payload["job_id"]))
        resume_text = str(message.payload["resume_text"])
        candidate_name = str(message.payload.get("candidate_name", ""))

        if self._applications.get(application_id) is None:
            raise ValueError(f"unknown application {application_id}")
        job = self._jobs.get(job_id)

        self._applications.set_status(
            application_id, ApplicationStatus.PROCESSING, event="worker.processing"
        )
        self._audit.append_system(
            action="worker.processing",
            subject_type="application",
            subject_id=str(application_id),
            payload={"topic": message.topic, "attempt": message.attempts},
        )

        try:
            result = await self._pipeline.process(
                application_id=str(application_id),
                resume_text=resume_text,
                job=job,
            )
        except Exception as exc:
            self._audit.append_system(
                action="worker.failed",
                subject_type="application",
                subject_id=str(application_id),
                payload={"error": type(exc).__name__, "attempt": message.attempts},
            )
            raise

        self._evaluations.register(
            application_id=application_id,
            evaluation=result.evaluation,
            candidate_name=candidate_name,
            job_title=job.title,
            policy=result.policy,
            source="pipeline",
        )
        self._audit.append_system(
            action="worker.completed",
            subject_type="application",
            subject_id=str(application_id),
            payload={
                "recommendation": result.recommendation.value,
                "flags": [flag.value for flag in result.flags],
            },
        )
