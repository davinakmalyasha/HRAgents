"""Rate table service — operator-owned statutory rates.

Ships structure, never numbers. HR enters values in the UI, marks them verified
with a source note, and only then may payroll math consume them. Any unverified
table is reported so the system can warn before a payroll run.
"""

from __future__ import annotations

from uuid import UUID

from hr_agents.models import (
    ActorType,
    AuditActor,
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
        created_by: str,
        jurisdiction: str = "ID",
    ) -> RateTable:
        table = RateTable(kind=kind, name=name, jurisdiction=jurisdiction)
        self._store.add(table)
        self._record(table, action="rate_table.created", actor_id=created_by)
        return table

    def set_entries(
        self,
        table_id: UUID,
        *,
        entries: list[RateEntry],
        updated_by: str,
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
            actor_id=updated_by,
            extra={"entry_count": len(entries)},
        )
        return updated

    def verify(
        self,
        table_id: UUID,
        *,
        verified_by: str,
        source_note: str,
    ) -> RateTable:
        """Mark verified with a source. Required before payroll may consume it."""
        table = self._require(table_id)
        if not table.entries:
            raise RateTableError("cannot verify an empty rate table")
        if not source_note.strip():
            raise RateTableError("verification requires a source note")
        verified = table.mark_verified(verified_by=verified_by, source_note=source_note)
        self._store.save(verified)
        self._record(verified, action="rate_table.verified", actor_id=verified_by)
        return verified

    def get(self, table_id: UUID) -> RateTable:
        return self._require(table_id)

    def list_all(self) -> list[RateTable]:
        return self._store.list_all()

    def unverified(self) -> list[RateTable]:
        """Tables that must not silently drive payroll math."""
        return [table for table in self._store.list_all() if not table.usable]

    def require_usable(self, kind: RateTableKind) -> RateTable:
        """Fetch the verified table of a kind, or raise — payroll calls this."""
        candidates = [
            table for table in self._store.list_all() if table.kind is kind and table.usable
        ]
        if not candidates:
            raise RateTableError(
                f"no verified {kind.value} rate table — HR must enter and verify "
                "current rates before payroll computations run"
            )
        return candidates[-1]

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
        actor_id: str,
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
            actor=AuditActor(
                actor_type=ActorType.SYSTEM if actor_id == "system" else ActorType.HUMAN,
                actor_id=actor_id,
            ),
            action=action,
            subject_type="rate_table",
            subject_id=str(table.id),
            payload=payload,
        )
