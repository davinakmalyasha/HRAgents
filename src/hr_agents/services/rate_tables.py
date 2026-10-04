"""Rate table service — operator-owned statutory rates.

Ships structure, never numbers. HR enters values in the UI, marks them verified
with a source note, and only then may payroll math consume them. Any unverified
table is reported so the system can warn before a payroll run.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from hr_agents.identity import ActorRef
from hr_agents.models import (
    RateEntry,
    RateTable,
    RateTableKind,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import RateTableStore


class RateTableError(RuntimeError):
    """Raised for invalid rate table operations."""


class RateTableService:
    """Manage statutory rate tables with a verification gate."""

    def __init__(self, store: RateTableStore, *, audit: AuditChain | None = None) -> None:
        self._store = store
        self._audit = audit or AuditChain()

    def create(
        self,
        *,
        kind: RateTableKind,
        name: str,
        actor: ActorRef,
        jurisdiction: str = "ID",
    ) -> RateTable:
        table = RateTable(kind=kind, name=name, jurisdiction=jurisdiction)
        self._store.add(table)
        self._record(table, action="rate_table.created", actor=actor)
        return table

    def set_entries(
        self,
        table_id: UUID,
        *,
        entries: list[RateEntry],
        actor: ActorRef,
    ) -> RateTable:
        """Replace entries. Editing values invalidates verification."""
        table = self._require(table_id)
        updated = table.model_copy(
            update={
                "entries": entries,
                "verified": False,
                "verified_by": None,
                "verified_at": None,
                "updated_at": utc_now(),
            }
        )
        self._store.save(updated)
        self._record(
            updated,
            action="rate_table.entries_updated",
            actor=actor,
            extra={"entry_count": len(entries)},
        )
        return updated

    def verify(
        self,
        table_id: UUID,
        *,
        actor: ActorRef,
        source_note: str,
    ) -> RateTable:
        """Mark verified with a source. Required before payroll may consume it.

        Certification is the ``verified`` gate behind the statutory rates: one
        named human enters the numbers, records where they came from, and
        confirms them. So it insists on that person being a person -- which it did
        not, and which was the one gap left in this module.

        The route was already behind `RATES_VERIFY`, held by `FINANCE` and
        `HR_ADMIN`, so an HTTP caller could not reach this with an agent actor.
        But the gate belongs here: `RateTableService` is constructed in
        `PeopleServices` and reachable in-process by the worker, the scheduler and
        any tool, and the other twelve consequential operations in this codebase
        all check at the service layer for exactly that reason. A principal
        configured as ``agent:hr_bot`` with `RATES_VERIFY` could otherwise certify
        a BPJS or PPh21 table, and the audit entry would name an agent as the
        person who confirmed the figures.
        """
        actor.require_human("verifying a statutory rate table", RateTableError)
        table = self._require(table_id)
        if not table.entries:
            raise RateTableError("cannot verify an empty rate table")
        if not source_note.strip():
            raise RateTableError("verification requires a source note")
        verified = table.mark_verified(verified_by=actor.actor_id, source_note=source_note)
        self._store.save(verified)
        self._record(verified, action="rate_table.verified", actor=actor)
        return verified

    def get(self, table_id: UUID) -> RateTable:
        return self._require(table_id)

    def list_all(self) -> list[RateTable]:
        return self._store.list_all()

    def unverified(self) -> list[RateTable]:
        """Tables that must not silently drive payroll math."""
        return [table for table in self._store.list_all() if not table.usable]

    def require_usable(self, kind: RateTableKind, *, as_of: date | None = None) -> RateTable:
        """Fetch the verified table of a kind in force, or raise.

        "In force" means: verified, non-empty, effective on ``as_of`` (default
        today) or with no window at all, and — among those — the most recently
        effective. Ordering by name or by list position would silently pick an
        arbitrary table whenever an operator keeps more than one version.
        """
        moment = as_of or date.today()
        candidates = [
            table
            for table in self._store.list_all()
            if table.kind is kind and table.usable and self._in_force(table, moment)
        ]
        if not candidates:
            raise RateTableError(
                f"no verified {kind.value} rate table in force on {moment.isoformat()} "
                "— HR must enter and verify current rates before payroll computations run"
            )
        return max(candidates, key=self._recency)

    @staticmethod
    def _in_force(table: RateTable, moment: date) -> bool:
        if table.effective_from is not None and moment < table.effective_from:
            return False
        return not (table.effective_to is not None and moment > table.effective_to)

    @staticmethod
    def _recency(table: RateTable) -> tuple[date, str]:
        """Later effective_from wins; undated tables fall back to last-updated."""
        stamp = table.updated_at.isoformat() if table.updated_at else ""
        return (table.effective_from or date.min, stamp)

    # --- internals ------------------------------------------------------

    def _require(self, table_id: UUID) -> RateTable:
        table = self._store.get(table_id)
        if table is None:
            raise RateTableError(f"unknown rate table {table_id}")
        return table

    def _record(
        self,
        table: RateTable,
        *,
        action: str,
        actor: ActorRef,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "kind": table.kind.value,
            "name": table.name,
            "verified": table.verified,
        }
        if extra:
            payload.update(extra)
        self._audit.append(
            actor=actor.audit_actor(),
            action=action,
            subject_type="rate_table",
            subject_id=str(table.id),
            payload=payload,
        )
