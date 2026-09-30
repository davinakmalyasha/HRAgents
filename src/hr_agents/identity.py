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

from dataclasses import dataclass

from hr_agents.models import ActorProvenance, ActorType, AuditActor
from hr_agents.rbac import Principal

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


@dataclass(frozen=True, slots=True)
class ActorRef:
    """The actor of one action, together with how that actor was established.

    Services take this instead of a bare ``by: str``. The string could say
    anything; an ``ActorRef`` cannot be constructed without the caller stating
    where the identity came from, and the answer is written to the audit chain.

    ``provenance`` is the whole point. "Rina" as a request field is a claim; an
    ``ActorRef`` built by ``from_principal`` is a verified fact, and the chain
    records the difference. A scheduled job and an agent tool are honest actors,
    but they are different claims from a person who logged in, and an auditor
    should be able to tell them apart without reading the action name.
    """

    actor_id: str
    actor_type: ActorType
    provenance: ActorProvenance
    role: str | None = None

    @classmethod
    def from_principal(cls, principal: Principal) -> ActorRef:
        """An authenticated request. The only provenance that names a role."""
        return cls(
            actor_id=principal.actor_id,
            actor_type=classify_actor(principal.actor_id),
            provenance=ActorProvenance.AUTHENTICATED,
            role=principal.role.value,
        )

    @classmethod
    def system(cls, job: str) -> ActorRef:
        """A scheduled job. Never a person, never carries a role."""
        return cls(
            actor_id=f"{SYSTEM_ACTOR_PREFIX}{job}",
            actor_type=ActorType.SYSTEM,
            provenance=ActorProvenance.SYSTEM_JOB,
        )

    @classmethod
    def agent(cls, name: str) -> ActorRef:
        """An in-process agent tool, e.g. consent capture during a chat turn."""
        cleaned = name.strip()
        if not cleaned:
            raise ActorError("an agent actor needs a name")
        return cls(
            actor_id=f"{AGENT_ACTOR_PREFIX}{cleaned.removeprefix(AGENT_ACTOR_PREFIX)}",
            actor_type=ActorType.AGENT,
            provenance=ActorProvenance.AGENT_TOOL,
        )

    @classmethod
    def legacy(cls, actor: str) -> ActorRef:
        """A bare string from code with no authenticated principal behind it.

        Legitimate for internal callers during the migration, but the weakest
        claim, and the chain says so. Prefer a more specific constructor.
        """
        return cls(
            actor_id=actor.strip(),
            actor_type=classify_actor(actor),
            provenance=ActorProvenance.LEGACY_STRING,
        )

    @classmethod
    def coerce(cls, value: ActorRef | str) -> ActorRef:
        """Accept either form so call sites migrate one at a time."""
        if isinstance(value, ActorRef):
            return value
        return cls.legacy(value)

    @property
    def is_human(self) -> bool:
        return self.actor_type is ActorType.HUMAN

    @property
    def is_attributable(self) -> bool:
        """True when the chain can name a person responsible for this action."""
        return self.is_human

    def audit_actor(self) -> AuditActor:
        """Build the chain entry's actor, carrying provenance and role."""
        return AuditActor(
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            provenance=self.provenance,
            role=self.role,
        )

    def require_human(
        self, action: str, error: type[Exception] = ActorError, *, subject: str = ""
    ) -> ActorRef:
        """Refuse a non-human actor using the single shared predicate."""
        require_named_human(self.actor_id, action, error, subject=subject)
        return self

    def require_human_or_system(
        self, action: str, error: type[Exception] = ActorError, *, subject: str = ""
    ) -> ActorRef:
        """Refuse agents only, for the scheduled jobs that may act as the system.

        Deliberately narrower than :meth:`require_human`. The retention sweep
        legitimately runs unattended, and a gate that demanded a person would
        leave expired records in place because nobody was watching. Every other
        consequential action must name a human.
        """
        require_named_human_or_system(self.actor_id, action, error, subject=subject)
        return self

    def __str__(self) -> str:
        return self.actor_id


def deciding_actor(decided_by: str | None) -> ActorRef:
    """The actor of an already-decided approval, for the services that sync it.

    A payroll run, a leave request and an erasure request all follow an approval
    to its outcome, and all read the approver's name back off the stored record
    rather than being handed a live principal. That is exactly why the provenance
    is ``legacy_string`` and not ``authenticated``: the person was verified when
    they decided, but nothing at this point can prove it a second time. Stamping
    ``authenticated`` on a value loaded from storage would assert something the
    caller never checked, and the chain would say so to the next reader.

    Persisting the deciding actor's provenance on the request closes the gap, and
    belongs with the rest of the provenance work.
    """
    return ActorRef.legacy(decided_by or "approval-engine")
