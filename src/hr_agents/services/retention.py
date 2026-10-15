"""The wire from record-creating services to the retention ledger.

The ledger is what makes a purge possible: a record nobody tracked cannot be
found by the retention scan, so `execute_purge` reports nothing to do. Until
this module existed the only writer was the operator-facing endpoint, which
means a real install accumulated documents and employee records that no sweep
could ever see.

The connection is late-bound because of construction order: the services that
create records are built before the compliance engine they report to, and a
service holding a direct reference would turn that order into a hard constraint
that every future wiring change has to preserve.
"""

from __future__ import annotations

from collections.abc import Callable

from hr_agents.identity import ActorRef
from hr_agents.models import RecordEntity, SubjectKind

# The compliance service's own signature, as a type, so this module does not
# import it (which would close a cycle: compliance imports the models, the
# services import compliance).
TrackFn = Callable[..., object]


class RetentionLedger:
    """Tracks created records, once somebody has bound the ledger to a tracker.

    Unbound is a valid state and not an error: a bare service in a unit test has
    no compliance engine, and tracking is an effect the test did not ask for.
    ``bound`` exists so wiring tests can assert the composition root did its job
    rather than trusting it to.
    """

    def __init__(self) -> None:
        self._track: TrackFn | None = None
        self.tracked: list[tuple[RecordEntity, SubjectKind, str]] = []

    def bind(self, track: TrackFn) -> None:
        self._track = track

    @property
    def bound(self) -> bool:
        return self._track is not None

    def track(
        self,
        *,
        entity: RecordEntity,
        subject_kind: SubjectKind,
        subject_id: str,
        actor: ActorRef,
        label: str = "",
    ) -> None:
        """Register one created record.

        The list of what was tracked is kept even when unbound, because a test
        asserting "creating an employee tracks a record" is worth writing and
        does not need a whole compliance engine behind it.
        """
        self.tracked.append((entity, subject_kind, subject_id))
        if self._track is None:
            return
        self._track(
            entity=entity,
            subject_kind=subject_kind,
            subject_id=subject_id,
            actor=actor,
            label=label,
        )
