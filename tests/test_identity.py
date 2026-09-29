"""Actor identity — the negative tests come first.

The whole point of this module is that a handful of specific strings must never
pass as a named human. Those are pinned here directly, because a refactor that
loosened the predicate would be invisible everywhere else: each service delegates
to it, so a weakened check shows up only as a service that stops raising.
"""

from __future__ import annotations

import pytest

from hr_agents.identity import (
    AGENT_ACTOR_PREFIX,
    ActorError,
    classify_actor,
    require_named_human,
    require_named_human_or_system,
)
from hr_agents.models import ActorType

# Every string that has ever been accepted by a named-human gate it should not
# have been. Three of the eight old implementations passed "" (state mutated,
# then the audit append raised); all eight passed "system", which the chain then
# recorded as ActorType.SYSTEM under a check reading "requires a named human".
NON_HUMAN_ACTORS = [
    "agent:screening_coordinator",
    "agent:records",
    "agent:",
    "system",
    "system:",
    "system:retention",
    "scheduler",
    "approval-engine",
    "",
    "   ",
    "\t\n",
]


class ServiceError(RuntimeError):
    """Stands in for the per-service error type the callers pass in."""


# --- classification -----------------------------------------------------------


def test_classifies_agents() -> None:
    assert classify_actor("agent:screening_coordinator") is ActorType.AGENT
    assert classify_actor(AGENT_ACTOR_PREFIX) is ActorType.AGENT


def test_classifies_system_actors() -> None:
    for actor in ("system", "system:", "system:retention", "scheduler", "approval-engine"):
        assert classify_actor(actor) is ActorType.SYSTEM, actor


def test_classifies_people_as_humans() -> None:
    for actor in ("Rina", "dpo-nadia", "Sinta Prabowo", " hr-admin "):
        assert classify_actor(actor) is ActorType.HUMAN, actor


def test_a_blank_actor_cannot_be_classified() -> None:
    """AuditActor.actor_id has min_length=1, so a blank can never be recorded."""
    for actor in ("", "   ", "\t\n"):
        with pytest.raises(ActorError, match="actor id is required"):
            classify_actor(actor)


# --- the named-human gate -----------------------------------------------------


@pytest.mark.parametrize("actor", NON_HUMAN_ACTORS)
def test_no_non_human_actor_passes_the_named_human_gate(actor: str) -> None:
    with pytest.raises(ServiceError):
        require_named_human(actor, "a decision", ServiceError)


@pytest.mark.parametrize("actor", NON_HUMAN_ACTORS)
def test_the_same_rejection_carries_the_service_error_type(actor: str) -> None:
    """Routers map each service's own error to a status code, so the type matters."""

    class DomainError(RuntimeError):
        pass

    with pytest.raises(DomainError):
        require_named_human(actor, "a decision", DomainError)


def test_a_named_human_is_returned_stripped() -> None:
    assert require_named_human("  Rina  ", "a decision", ServiceError) == "Rina"


def test_the_rejection_names_the_actor_and_the_action() -> None:
    with pytest.raises(ServiceError) as excinfo:
        require_named_human("agent:x", "decide an approval", ServiceError)
    message = str(excinfo.value)
    assert "decide an approval" in message
    assert "agent:x" in message
    assert "named human" in message


def test_the_rejection_distinguishes_a_missing_actor_from_a_forbidden_one() -> None:
    """An empty string is a caller bug; "system" is an authority problem."""
    with pytest.raises(ServiceError, match="none was given"):
        require_named_human("", "a decision", ServiceError)
    with pytest.raises(ServiceError, match="not a system actor"):
        require_named_human("system:retention", "a decision", ServiceError)


def test_a_subject_is_included_when_supplied() -> None:
    with pytest.raises(ServiceError, match="payroll run 17"):
        require_named_human("agent:x", "export", ServiceError, subject="payroll run 17")


# --- the system-actor gate ----------------------------------------------------


def test_scheduled_jobs_may_act_as_the_system() -> None:
    for actor in ("system", "system:retention", "scheduler"):
        assert require_named_human_or_system(actor, "purge", ServiceError) == actor


@pytest.mark.parametrize("actor", ["agent:records", "agent:", "", "  "])
def test_agents_and_blanks_cannot_use_the_system_gate(actor: str) -> None:
    with pytest.raises(ServiceError):
        require_named_human_or_system(actor, "purge", ServiceError)


# --- the regression this module exists for -------------------------------------


def test_a_system_actor_no_longer_reaches_the_chain_as_a_human() -> None:
    """The exact hole: approvals.decide accepted "system", then recorded SYSTEM.

    Gate and classifier disagreed 180 lines apart inside one service. Now a
    single predicate decides both, so they cannot.
    """
    with pytest.raises(ServiceError):
        require_named_human("system", "decide an approval", ServiceError)
    # And the classifier agrees with the gate, rather than the two being separate
    # private copies of the same question.
    assert classify_actor("system") is ActorType.SYSTEM
