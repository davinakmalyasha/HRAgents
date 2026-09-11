"""Screening tools: consent, availability, escalation, candidate context.

Each tool writes through a callback supplied by the caller (the pipeline owns
persistence). Tools stay transport-agnostic and fully testable offline.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hr_agents.tools.registry import ToolDefinition

_SCREENING_AGENTS = frozenset({"screening_coordinator"})

ConsentRecorder = Callable[[str, bool], dict[str, Any]]
AvailabilityRecorder = Callable[[str, dict[str, Any]], dict[str, Any]]
EscalationRecorder = Callable[[str, str], dict[str, Any]]
ProfileLookup = Callable[[str], dict[str, Any] | None]


def make_capture_consent_tool(recorder: ConsentRecorder) -> ToolDefinition:
    """Record consent state for a candidate (never assumed — only recorded)."""

    def capture_consent(candidate_id: str, granted: bool) -> dict[str, object]:
        """Record whether the candidate granted consent for evaluation."""
        return recorder(candidate_id, granted)

    return ToolDefinition(
        name="capture_consent",
        description=(
            "Record the candidate's explicit consent decision for evaluation. "
            "Use only after the candidate clearly states their choice."
        ),
        allowed_agents=_SCREENING_AGENTS,
        handler=capture_consent,
        tags=frozenset({"screening", "write"}),
    )


def make_record_availability_tool(recorder: AvailabilityRecorder) -> ToolDefinition:
    """Record availability windows gathered from the candidate."""

    def record_availability(candidate_id: str, availability: dict[str, Any]) -> dict[str, object]:
        """Record availability: timezone, weekly windows, notice period."""
        return recorder(candidate_id, availability)

    return ToolDefinition(
        name="record_availability",
        description=(
            "Record the candidate's interview availability (timezone, weekly "
            "windows as {weekday, start_local, end_local}, notice period)."
        ),
        allowed_agents=_SCREENING_AGENTS,
        handler=record_availability,
        tags=frozenset({"screening", "write"}),
    )


def make_escalate_to_human_tool(recorder: EscalationRecorder) -> ToolDefinition:
    """Escalate the conversation to a human with a reason."""

    def escalate_to_human(candidate_id: str, reason: str) -> dict[str, object]:
        """Hand the conversation to a human reviewer with a reason."""
        return recorder(candidate_id, reason)

    return ToolDefinition(
        name="escalate_to_human",
        description=(
            "Hand this conversation to a human. Required for complaints, legal or "
            "salary questions, hostility, or anything you cannot ground in policy."
        ),
        allowed_agents=_SCREENING_AGENTS,
        handler=escalate_to_human,
        tags=frozenset({"screening", "write", "escalation"}),
    )


def make_get_candidate_profile_tool(lookup: ProfileLookup) -> ToolDefinition:
    """Read-only lookup of the candidate's structured facts."""

    def get_candidate_profile(candidate_id: str) -> dict[str, object]:
        """Fetch the candidate's structured profile facts for context."""
        profile = lookup(candidate_id)
        if profile is None:
            return {"error": f"candidate {candidate_id} not found"}
        return profile

    return ToolDefinition(
        name="get_candidate_profile",
        description=(
            "Fetch the candidate's structured profile (name, headline, missing "
            "fields) to personalize messages and detect information gaps."
        ),
        allowed_agents=_SCREENING_AGENTS,
        handler=get_candidate_profile,
        tags=frozenset({"screening", "read"}),
    )
