"""Seam test: API submission → queue → worker → registered evaluation → queue view.

Exercises the real store, evaluation service, audit chain, queue backend, worker,
and deterministic pipeline (offline test model) together. The only simulated
step is publication of the evaluation message — exactly what a worker runner
does in production.
"""

from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from hr_agents.agents import AgentRuntime
from hr_agents.agents.resume_deconstructor import ResumeDeconstructor
from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.main import create_app
from hr_agents.providers.queue.memory import MemoryQueueBackend
from hr_agents.services.audit import AuditChain
from hr_agents.services.evaluation_job import (
    EVALUATION_TOPIC,
    EvaluationJobHandler,
    evaluation_payload,
)
from hr_agents.services.pipeline import ApplicationPipeline, InMemoryStorage
from hr_agents.services.worker import Worker, WorkerConfig
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import (
    ToolRegistry,
    make_canonicalize_skill_tool,
    make_search_knowledge_tool,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

RESUME = """\
# Budi Santoso
Backend Engineer with 6 years. budi@example.com

## Experience
- 2019-2025 Senior Engineer, Nusantara Systems: Python, FastAPI, PostgreSQL.
"""


def _payload(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "source_channel": "api",
        "consent": {"granted": True, "policy_version": "1.0"},
        "candidate": {
            "full_name": "Budi Santoso",
            "emails": ["budi@example.com"],
        },
    }


async def _build_pipeline(audit: AuditChain) -> ApplicationPipeline:
    skills = SkillRegistry(load_library(REPO_ROOT / "skills"))
    retriever = await KnowledgeRetriever.build(skills.knowledge())
    tools = ToolRegistry(audit=audit)
    tools.register(make_search_knowledge_tool(retriever, namespaces=["recruiting.evaluation"]))
    tools.register(make_canonicalize_skill_tool())
    runtime = AgentRuntime(TestModel(call_tools=[]))
    deconstructor = ResumeDeconstructor(runtime, skills=skills)
    return ApplicationPipeline(
        deconstructor=deconstructor,
        storage=InMemoryStorage(tools),
        audit=audit,
    )


async def test_submit_then_evaluate_seam() -> None:
    app = create_app()
    with TestClient(app) as client:
        job = app.state.recruiting.jobs.create(
            title="Backend Engineer",
            created_by="hr-admin",
            must_have_skills=["Python", "PostgreSQL"],
            stack=["FastAPI"],
        )
        response = client.post("/v1/applications", json=_payload(str(job.id)))
        assert response.status_code == 202
        application_id = UUID(response.json()["application_id"])

        queue = MemoryQueueBackend()
        await queue.publish(
            EVALUATION_TOPIC,
            evaluation_payload(
                application_id=application_id,
                job_id=job.id,
                resume_text=RESUME,
                candidate_name="Budi Santoso",
            ),
        )

        handler = EvaluationJobHandler(
            pipeline=await _build_pipeline(app.state.audit),
            applications=app.state.store,
            evaluations=app.state.recruiting.evaluations,
            jobs=app.state.recruiting.jobs,
            audit=app.state.audit,
        )
        worker = Worker(queue, handler, config=WorkerConfig(topic=EVALUATION_TOPIC))
        assert await worker.run_once() == 1

        status_body = client.get(f"/v1/applications/{application_id}").json()
        assert status_body["status"] in {"evaluated", "gated", "rejected"}
        assert status_body["s_tech"] is not None
        events = [item["event"] for item in status_body["timeline"]]
        assert "worker.processing" in events

        queue_body = client.get("/v1/queue", params={"job_id": str(job.id)}).json()
        entry = next(
            item for item in queue_body["items"] if item["application_id"] == str(application_id)
        )
        assert entry["status"] == status_body["status"]

        evaluation_response = client.get(f"/v1/applications/{application_id}/evaluation")
        assert evaluation_response.status_code == 200
        assert evaluation_response.json()["application_id"] == str(application_id)

        stats = await queue.stats(EVALUATION_TOPIC)
        assert stats.pending == 0
        assert stats.inflight == 0
        assert app.state.audit.verify() == -1
