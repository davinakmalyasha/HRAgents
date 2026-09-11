"""Run evaluation suites against the configured model.

Offline (default): deterministic `test` model — works with no API keys.
Live: configure a real LLM provider, then pass ``--live``.

    HRAGENTS_PROVIDER_LLM=llm.anthropic
    HRAGENTS_PROVIDER_LLM_CONFIG={"api_key":"sk-ant-...","model":"claude-sonnet-4-5"}

    uv run python scripts/run_evals.py --live
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals"))

from resume_extraction import ResumeCase, build_dataset  # noqa: E402

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

SKILLS_ROOT = REPO_ROOT / "skills"

# Assertions that require a real language model to pass (the offline `test`
# model generates schema-valid but semantically random data).
SEMANTIC_ASSERTIONS = frozenset(
    {
        "expected_skill_present_or_extractable",
        "experience_has_evidence_or_is_offline",
    }
)


def _failed_assertions(report) -> dict[str, list[str]]:  # type: ignore[no-untyped-def]
    """Map case name → failed assertion names."""
    failed: dict[str, list[str]] = {}
    for case in report.cases:
        names: list[str] = []
        assertions = case.assertions
        for key, item in assertions.items() if isinstance(assertions, dict) else []:
            value = getattr(item, "value", item)
            if value is not True:
                names.append(str(key))
        if names:
            failed[case.name] = names
    return failed


async def main(live: bool) -> int:
    runtime = AgentRuntime.from_env() if live else AgentRuntime.offline()
    mode = "LIVE" if live else "offline (test model)"
    print(f"Runtime provider: {runtime.provider_id}  [{mode}]")

    if live and runtime.provider_id == "llm.test":
        print(
            "\nNo LLM provider configured. Set these environment variables "
            "(or put them in .env):\n"
            "  HRAGENTS_PROVIDER_LLM=llm.anthropic\n"
            '  HRAGENTS_PROVIDER_LLM_CONFIG={"api_key":"sk-ant-...",'
            '"model":"claude-sonnet-4-5"}\n'
            "\nOr use llm.openai_compatible for OpenAI/OpenRouter/Groq/vLLM, "
            "or llm.ollama for local models.",
            file=sys.stderr,
        )
        return 2

    skills = SkillRegistry(load_library(SKILLS_ROOT))
    retriever = await KnowledgeRetriever.build(skills.knowledge())
    tools = ToolRegistry(audit=AuditChain())
    tools.register(make_search_knowledge_tool(retriever, namespaces=["recruiting.evaluation"]))
    tools.register(make_canonicalize_skill_tool())
    deps = AgentDeps(tools=tools)

    deconstructor = ResumeDeconstructor(runtime, skills=skills)
    dataset = build_dataset()

    async def task(case: ResumeCase):
        return await deconstructor.deconstruct(case.text, deps=deps, source_name=case.source_name)

    report = await dataset.evaluate(task, max_concurrency=2, progress=True)
    report.print(include_input=False, include_output=False)

    failed = _failed_assertions(report)

    # Task errors (exceptions: provider outages, schema failures) are failures.
    if report.failures:
        print("\nCases that raised errors:")
        for failure in report.failures:
            print(f"  - {failure.name}: {type(failure.exception).__name__}")
            if failure.exception is not None:
                print(f"      {failure.exception}")

    if live:
        blocking = failed
    else:
        # Offline: enforce structural/safety assertions only.
        blocking = {
            case: [name for name in names if name not in SEMANTIC_ASSERTIONS]
            for case, names in failed.items()
        }
        blocking = {case: names for case, names in blocking.items() if names}

    if report.failures or blocking:
        if blocking:
            print("\nFailing assertions:")
            for case, names in blocking.items():
                print(f"  - {case}: {', '.join(names)}")
        return 1

    if live:
        print("\nAll evaluation cases passed (live model).")
    else:
        print(
            "\nStructural and safety assertions passed (offline model). "
            "Semantic checks (skill extraction, evidence coverage) require a real "
            "LLM — run with --live."
        )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="use the configured real LLM provider instead of the offline test model",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.live)))
