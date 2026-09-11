"""Agent layer: runtime, dependencies, guards, and specialists.

Design rule: agents extract and communicate only. They never score, rank,
reject, or advance anyone — the deterministic core owns decisions and humans
gate every consequential action (`docs/architecture/hitl-bounds.md`).
"""

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.injection_guard import (
    GuardFinding,
    GuardReport,
    InjectionGuard,
)
from hr_agents.agents.runtime import AgentRuntime, AgentRuntimeError, RuntimeLimits

__all__ = [
    "AgentDeps",
    "AgentRuntime",
    "AgentRuntimeError",
    "GuardFinding",
    "GuardReport",
    "InjectionGuard",
    "RuntimeLimits",
]
