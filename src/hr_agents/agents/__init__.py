"""Agent layer: runtime, dependencies, guards, and specialists.

Design rule: agents extract and communicate only. They never score, rank,
reject, or advance anyone — the deterministic core owns decisions and humans
gate every consequential action (`docs/architecture/hitl-bounds.md`).
"""

from hr_agents.agents.code_portfolio import AGENT_NAME as CODE_PORTFOLIO_AGENT
from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.feedback_writer import AGENT_NAME as FEEDBACK_WRITER_AGENT
from hr_agents.agents.injection_guard import (
    GuardFinding,
    GuardReport,
    InjectionGuard,
)
from hr_agents.agents.policy_assistant import AGENT_NAME as POLICY_ASSISTANT_AGENT
from hr_agents.agents.resume_deconstructor import AGENT_NAME as RESUME_DECONSTRUCTOR_AGENT
from hr_agents.agents.runtime import AgentRuntime, AgentRuntimeError, RuntimeLimits
from hr_agents.agents.screening_coordinator import AGENT_NAME as SCREENING_COORDINATOR_AGENT

AGENT_NAMES: frozenset[str] = frozenset(
    {
        CODE_PORTFOLIO_AGENT,
        FEEDBACK_WRITER_AGENT,
        POLICY_ASSISTANT_AGENT,
        RESUME_DECONSTRUCTOR_AGENT,
        SCREENING_COORDINATOR_AGENT,
    }
)

__all__ = [
    "AGENT_NAMES",
    "AgentDeps",
    "AgentRuntime",
    "AgentRuntimeError",
    "GuardFinding",
    "GuardReport",
    "InjectionGuard",
    "RuntimeLimits",
]
