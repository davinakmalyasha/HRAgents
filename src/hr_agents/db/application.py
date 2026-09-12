"""Postgres-backed application store.

Overrides only the persistence primitives of ``ApplicationStore``; idempotency
and lifecycle semantics stay in the service class.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.session import sync_session_scope
from hr_agents.db.tables import Application, Candidate
from hr_agents.models import ConsentRecord, Recommendation
from hr_agents.services.ingestion import (
    ApplicationRecord,
    ApplicationStatus,
    ApplicationStore,
    SubmissionInput,
)


class DbApplicationStore(ApplicationStore):
    """Durable application store on the ``candidates``/``applications`` tables."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    # primitives

    def _load(self, application_id: UUID) -> ApplicationRecord | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(Application, application_id)
            return None if row is None else self._to_record(row)

    def _iter(self) -> Iterator[ApplicationRecord]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(Application)).scalars().all()
            return iter([self._to_record(row) for row in rows])

    def _find_by_key(self, idempotency_key: str) -> tuple[str, UUID] | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(Application).where(Application.idempotency_key == idempotency_key)
            ).scalar_one_or_none()
            if row is None:
                return None
            return row.payload_hash or "", row.id

    def _persist_new(
        self, record: ApplicationRecord, payload_hash: str, submission: SubmissionInput
    ) -> None:
        primary_email = submission.candidate_emails[0] if submission.candidate_emails else None
        with sync_session_scope(self._session_factory) as session:
            session.add(
                Candidate(
                    id=record.candidate_id,
                    full_name=submission.candidate_name or "Unknown candidate",
                    primary_email=primary_email,
                    consent=record.consent.model_dump(mode="json"),
                    profile={},
                    field_confidence={},
                )
            )
            session.add(
                Application(
                    id=record.id,
                    candidate_id=record.candidate_id,
                    job_id=record.job_id,
                    status=record.status.value,
                    source_channel=record.source_channel,
                    idempotency_key=record.idempotency_key,
                    payload_hash=payload_hash,
                    consent=record.consent.model_dump(mode="json"),
                    timeline=self._dump_timeline(record),
                    received_at=record.received_at,
                    priority_score=record.priority_score,
                )
            )
            session.flush()

    def _persist(self, record: ApplicationRecord) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(Application, record.id)
            if row is None:
                raise KeyError(f"unknown application {record.id}")
            row.status = record.status.value
            row.s_tech = record.s_tech
            row.sigma = record.sigma
            row.recommendation = record.recommendation.value if record.recommendation else None
            row.timeline = self._dump_timeline(record)
            row.priority_score = record.priority_score
            row.priority_updated_at = datetime.now(UTC)
            session.flush()

    # mapping

    @staticmethod
    def _dump_timeline(record: ApplicationRecord) -> list[list[str]]:
        return [[moment.isoformat(), event] for moment, event in record.timeline]

    @staticmethod
    def _to_record(row: Application) -> ApplicationRecord:
        consent = (
            ConsentRecord.model_validate(row.consent)
            if row.consent is not None
            else ConsentRecord(granted=False)
        )
        received_at = row.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        timeline: list[tuple[datetime, str]] = []
        for item in row.timeline or []:
            moment = datetime.fromisoformat(item[0])
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            timeline.append((moment, item[1]))
        return ApplicationRecord(
            id=row.id,
            candidate_id=row.candidate_id,
            job_id=row.job_id,
            source_channel=row.source_channel,
            status=ApplicationStatus(row.status),
            received_at=received_at,
            consent=consent,
            idempotency_key=row.idempotency_key,
            s_tech=row.s_tech,
            sigma=row.sigma,
            recommendation=(
                Recommendation(row.recommendation) if row.recommendation is not None else None
            ),
            priority_score=row.priority_score or 0.0,
            timeline=timeline,
        )
