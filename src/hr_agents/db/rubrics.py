"""Postgres-backed rubric versions.

Overrides only the persistence primitives; the verification and activation
rules stay in ``services.rubrics``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.mapping import add_model, get_model, list_models, model_from_row, save_model
from hr_agents.db.session import sync_session_scope
from hr_agents.models import JobFamily, RubricVersion
from hr_agents.services.rubrics import RubricStore


class DbRubricStore(RubricStore):
    """Rubric versions in ``rubric_versions``."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add(self, record: RubricVersion) -> None:
        add_model(self._session_factory, record, t.RubricVersionRecord)

    def save(self, record: RubricVersion) -> None:
        save_model(self._session_factory, record, t.RubricVersionRecord)

    def get(self, version_id: UUID) -> RubricVersion | None:
        return get_model(self._session_factory, RubricVersion, t.RubricVersionRecord, version_id)

    def list_all(self) -> list[RubricVersion]:
        records = list_models(self._session_factory, RubricVersion, t.RubricVersionRecord)
        return sorted(records, key=lambda item: (item.family.value, item.revision))

    def list_for(self, family: JobFamily) -> list[RubricVersion]:
        row = t.RubricVersionRecord
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    select(row).where(row.family == family.value).order_by(row.revision)
                )
                .scalars()
                .all()
            )
            return [model_from_row(RubricVersion, item) for item in rows]

    def active_for(self, family: JobFamily) -> RubricVersion | None:
        row = t.RubricVersionRecord
        with sync_session_scope(self._session_factory) as session:
            record = (
                session.execute(
                    select(row).where(row.family == family.value, row.active.is_(True)).limit(1)
                )
                .scalars()
                .first()
            )
            return None if record is None else model_from_row(RubricVersion, record)
