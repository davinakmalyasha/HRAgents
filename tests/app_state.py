"""Deterministic app-state stubs for tests that need a specific service.

`tests/api/test_chat_api.py` needed a chat service that answers without a model,
and `tests/test_audit_provenance.py` needed the same one to reach `/v1/chat` when
sweeping for degraded audit actors. Two copies of a stub is how they drift, so it
lives here.

Nothing here mocks the thing under test. `ChatService` is real: the front door
routes, the tool registry is real, and the audit chain is the application's own.
Only the LLM responder is replaced, because `AGENTS.md` forbids real model calls
and the offline `test` model is not what these assertions are about.
"""

from __future__ import annotations

from fastapi import FastAPI

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.policy_assistant import PolicyAnswer, PolicyResult
from hr_agents.services.chat import ChatService
from hr_agents.services.front_door import FrontDoor
from hr_agents.services.workspace_requests import HandoffService
from hr_agents.tools import ToolRegistry
from hr_agents.workspaces import default_registry


class FixedResponder:
    """Answers every question with a citation and high confidence."""

    async def ask(self, question: str, *, deps: AgentDeps) -> PolicyResult:
        return PolicyResult(
            answer=PolicyAnswer(
                answer=f"Grounded answer for: {question}",
                citations=["policy.md#1"],
                confidence=0.9,
            )
        )


def install_fixed_chat(app: FastAPI) -> None:
    audit = app.state.audit
    app.state.chat = ChatService(
        front_door=FrontDoor(),
        responder=FixedResponder(),
        audit=audit,
        tools=ToolRegistry(audit=audit),
    )


def install_handoffs(app: FastAPI) -> None:
    app.state.handoffs = HandoffService(registry=default_registry(), audit=app.state.audit)
