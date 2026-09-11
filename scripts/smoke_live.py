"""Single live-model smoke test: one resume through the deconstructor.

Prints the raw outcome to diagnose structured-output behavior. Uses the
configured provider from the environment; one model call (plus possible retries).

    uv run python scripts/smoke_live.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals"))

from hr_agents.agents import AgentDeps, AgentRuntime  # noqa: E402
from hr_agents.agents.resume_deconstructor import ResumeDeconstructor  # noqa: E402
from hr_agents.knowledge import KnowledgeRetriever  # noqa: E402
from hr_agents.services.audit import AuditChain  # noqa: E402
from hr_agents.skills import SkillRegistry, load_library  # noqa: E402
from hr_agents.tools import (  # noqa: E402
    ToolRegistry,
    make_canonicalize_skill_tool,
    make_search_knowledge_tool,
)

SAMPLE = """\
# Budi Santoso
Backend Engineer, Jakarta. budi@example.com

## Experience
- 2020-2024 Senior Engineer, Nusantara Systems: Python, FastAPI, PostgreSQL.
- 2024-present Lead Engineer, Merdeka AI: Python, PydanticAI, Kafka.

## Skills
Python, FastAPI, PostgreSQL, Docker
"""


async def main() -> int:
    runtime = AgentRuntime.from_env()
    print(f"provider: {runtime.provider_id}")
    print(f"model type: {type(runtime.model).__name__}")

    skills = SkillRegistry(load_library(REPO_ROOT / "skills"))
    retriever = await KnowledgeRetriever.build(skills.knowledge())
    tools = ToolRegistry(audit=AuditChain())
    tools.register(make_search_knowledge_tool(retriever, namespaces=["recruiting.evaluation"]))
    tools.register(make_canonicalize_skill_tool())
    deps = AgentDeps(tools=tools)

    agent = ResumeDeconstructor(runtime, skills=skills)
    try:
        result = await agent.deconstruct(SAMPLE, deps=deps, source_name="smoke.md")
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}")
        print(str(exc)[:2000])
        return 1

    profile = result.profile
    print("\nSUCCESS")
    print(f"name: {profile.full_name}")
    print(f"emails: {profile.emails}")
    print(f"experience entries: {len(profile.experience)}")
    print(f"skills: {[s.name for s in profile.skills][:8]}")
    print(f"guard: severity={result.guard.risk_severity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
