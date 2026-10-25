"""The one shape a service uses to write an audit entry.

Every service used to open-code the same four steps: coerce the actor, name the
subject, merge the entity payload, call `AuditChain.append`. The risk in that
duplication is not stylistic — a service that forgot the coercion wrote a
weaker provenance claim, and one that forgot the subject type made the entry
unfindable by subject. `record` makes those mistakes impossible to make one
service at a time.

The *content* of a payload is still the service's; this only owns the envelope.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hr_agents.identity import ActorRef
from hr_agents.models import AuditEntry
from hr_agents.services.audit import AuditChain


def record_audit(
    audit: AuditChain,
    *,
    actor: ActorRef | str,
    action: str,
    subject_type: str,
    subject_id: str,
    payload: Mapping[str, Any] | None = None,
) -> AuditEntry:
    """Append one entry with a coerced actor and a named subject."""
    return audit.append(
        actor=ActorRef.coerce(actor).audit_actor(),
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=dict(payload or {}),
    )
