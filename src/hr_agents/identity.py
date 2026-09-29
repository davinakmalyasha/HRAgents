"""Actor identity — the single meaning of "who did this".

Every service used to carry its own private copy of two questions: *what kind of
actor is this string* and *is this a named human*. There were eleven copies of
the first with three different answers and eight of the second with two, and
they disagreed with each other inside the same function.

The concrete cost was that the audit chain recorded agents as humans. Three
services classified ``agent:`` as ``ActorType.HUMAN`` because their copy of the
function had no agent branch at all, and every named-human gate in the codebase
accepted ``system``/``system:`` because they all checked only the agent prefix —
so a caller could decide an approval as ``system`` and it would land on the
chain as ``ActorType.SYSTEM``, having passed a check named "decisions require a
named human actor".

There is one table and one predicate now:

    classify_actor(actor_id)          -> ActorType
    require_named_human(actor, ...)   -> the cleaned actor, or raise

A named human is exactly ``classify_actor(actor) is ActorType.HUMAN``, which
rejects ``agent:``, ``system:``, ``system``, and the empty string in a single
expression. Adding a fifth actor kind to this module is the only edit needed to
audit it correctly everywhere.

This module decides nothing about *authority* — whether a principal may perform
an action is RBAC, at the router. It decides what the tamper-evident chain
records, and which callers are refused before they can act.
"""

from __future__ import annotations

from hr_agents.models import ActorType

AGENT_ACTOR_PREFIX = "agent:"
SYSTEM_ACTOR_PREFIX = "system:"
LEGACY_SYSTEM_ACTORS = frozenset({"system", "scheduler", "approval-engine"})


class ActorError(ValueError):
    """The actor string cannot be interpreted, or is not permitted to act."""


def classify_actor(actor_id: str) -> ActorType:
    """Map an actor id to the type recorded on the audit chain.

    Raises on an empty or whitespace-only id: ``AuditActor.actor_id`` has
    ``min_length=1``, so a blank actor can never be written to the chain. Letting
    one reach the classifier produced a state change followed by a failed audit
    append, which is the worst of both worlds.
    """
    cleaned = actor_id.strip()
    if not cleaned:
        raise ActorError("an actor id is required; it is recorded on the audit chain")
    if cleaned.startswith(AGENT_ACTOR_PREFIX):
        return ActorType.AGENT
    if cleaned.startswith(SYSTEM_ACTOR_PREFIX) or cleaned in LEGACY_SYSTEM_ACTORS:
        return ActorType.SYSTEM
    return ActorType.HUMAN


def require_named_human(
    actor: str,
    action: str,
    error: type[Exception] = ActorError,
    *,
    subject: str = "",
) -> str:
    """Refuse anything that is not a named human; return the cleaned actor.

    ``error`` lets each service raise its own exception type, so routers keep
    mapping failures to status codes without knowing this module exists.

    Empty and whitespace-only ids are refused too: a gate that accepts them lets
    a state change through and then fails the audit append that records it.
    """
    cleaned = actor.strip()
    detail = f" — {subject}" if subject else ""
    if not cleaned:
        raise error(f"{action} requires a named human actor; none was given{detail}")
    if classify_actor(cleaned) is not ActorType.HUMAN:
        raise error(
            f"{action} requires a named human actor, not a {cleaned.split(':', 1)[0]} "
            f"actor ({cleaned}){detail}"
        )
    return cleaned


def require_named_human_or_system(
    actor: str,
    action: str,
    error: type[Exception] = ActorError,
    *,
    subject: str = "",
) -> str:
    """Refuse agents only. For the scheduled jobs that may act as the system.

    Narrower than :func:`require_named_human` on purpose: it exists because a
    handful of operations (the retention sweep) legitimately run unattended. Every
    other consequential action must be attributable to a person.
    """
    cleaned = actor.strip()
    detail = f" — {subject}" if subject else ""
    if not cleaned:
        raise error(f"{action} requires an actor; none was given{detail}")
    if classify_actor(cleaned) is ActorType.AGENT:
        raise error(f"agents cannot {action}{detail}")
    return cleaned
