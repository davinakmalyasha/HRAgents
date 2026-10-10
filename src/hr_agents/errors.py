"""Domain refusals that carry their own code.

Thirty-eight domain error classes were flat ``RuntimeError``/``ValueError``
subclasses with no common ancestor, which is why the routers had to recognise a
failure by reading its English prose -- ``if "named human" in message``. Rewording
one exception message could then move a status code, and two comments in the
routers record that it already had.

`DomainError` gives the refusal a code and a status at the place that raises it,
so the routers stop guessing. It lives at the top level and imports nothing from
`hr_agents`: `identity` needs it, and anything under `services` imports `identity`,
so a definition under `services` would be a cycle.

Reparenting is additive: every domain class keeps its old base
(``DomainError, RuntimeError``), so an ``except RuntimeError`` anywhere in the
tree still catches it while ``except DomainError`` also works.
"""

from __future__ import annotations

from enum import StrEnum


class DomainCode(StrEnum):
    """Why a domain refused, in terms a client can switch on.

    These map onto `api.problem.ProblemCode` in one place, at the API edge. The
    duplication is the point: the service layer says what happened in its own
    vocabulary and never learns what HTTP is.
    """

    STATE_CONFLICT = "state_conflict"
    UNKNOWN_RECORD = "unknown_record"
    VALIDATION_FAILED = "validation_failed"
    NAMED_HUMAN_REQUIRED = "named_human_required"
    PERMISSION_REQUIRED = "permission_required"
    OWNERSHIP_REQUIRED = "ownership_required"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    TEMPLATE_UNAVAILABLE = "template_unavailable"
    RATE_TABLE_UNUSABLE = "rate_table_unusable"
    BLOCKING_ANOMALIES = "blocking_anomalies"
    APPROVAL_ALREADY_DECIDED = "approval_already_decided"


class DomainError(Exception):
    """A domain refusal carrying its own code and status.

    ``status`` lives here rather than at the router because the *meaning*
    decides it: refusing an agent is a 403 wherever it happens, and a router that
    has to re-derive that from the message is the thing being removed.
    """

    code: DomainCode = DomainCode.STATE_CONFLICT
    status: int = 409

    def __init__(
        self,
        message: str,
        *,
        code: DomainCode | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
