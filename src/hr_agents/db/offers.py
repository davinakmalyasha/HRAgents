"""Postgres-backed offer service.

Overrides only the persistence primitives; validation, approval linkage, and
lifecycle rules stay in ``hr_agents.services.offers``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from collections.abc import Sequence

from hr_agents.db import offers_tables as ot
from hr_agents.db.session import sync_session_scope
from hr_agents.models import Offer, OfferRevision, OfferStatus, OfferTerms
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.ingestion import ApplicationStore
from hr_agents.services.offers import OfferService
from hr_agents.services.recruiting import CommunicationService, EvaluationService


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class DbOfferService(OfferService):
    """Offers and their append-only revisions in Postgres."""

    def __init__(
        self,
        *,
        evaluations: EvaluationService,
        communications: CommunicationService,
        session_factory: sessionmaker[Session],
        audit: AuditChain | None = None,
        approvals: ApprovalEngine | None = None,
        applications: ApplicationStore | None = None,
    ) -> None:
        super().__init__(
            evaluations=evaluations,
            communications=communications,
            audit=audit,
            approvals=approvals,
            applications=applications,
        )
        self._session_factory = session_factory

    def _load(self, offer_id: UUID) -> Offer | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(ot.OfferRecord, offer_id)
            if row is None:
                return None
            revisions = self._revisions_for(session, offer_id)
            return self._to_offer(row, revisions)

    def _iter(self) -> list[Offer]:
        """Every offer, with its revisions, in two statements.

        This issued one revision query per offer, so reading 100 offers cost 201
        statements and the expiry sweep paid it on every run. Revisions are small
        and always needed alongside the offer, so they are fetched once and
        grouped in memory.
        """
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(ot.OfferRecord)).scalars().all()
            revisions = self._revisions_by_offer(session, [row.id for row in rows])
            return [self._to_offer(row, revisions.get(row.id, [])) for row in rows]

    def _persist(self, offer: Offer) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(ot.OfferRecord, offer.id)
            if row is None:
                row = ot.OfferRecord(
                    id=offer.id,
                    status=offer.status.value,
                    terms={},
                    created_by=offer.created_by,
                )
                session.add(row)
            row.application_id = offer.application_id
            row.candidate_id = offer.candidate_id
            row.job_id = offer.job_id
            row.status = offer.status.value
            row.terms = offer.terms.model_dump(mode="json")
            row.created_at = offer.created_at
            row.updated_at = offer.updated_at
            row.decided_by = offer.decided_by
            row.decided_at = offer.decided_at
            row.queued_at = offer.queued_at
            row.accepted_at = offer.accepted_at
            row.declined_at = offer.declined_at
            row.decline_reason = offer.decline_reason
            existing = {
                revision_id
                for (revision_id,) in session.execute(
                    select(ot.OfferRevisionRecord.id).where(
                        ot.OfferRevisionRecord.offer_id == offer.id
                    )
                )
            }
            for revision in offer.revisions:
                if revision.id in existing:
                    continue
                session.add(
                    ot.OfferRevisionRecord(
                        id=revision.id,
                        offer_id=offer.id,
                        revision_index=revision.revision_index,
                        terms=revision.terms.model_dump(mode="json"),
                        changed_by=revision.changed_by,
                        changed_at=revision.changed_at,
                        note=revision.note,
                    )
                )
            session.flush()

    @staticmethod
    def _revisions_by_offer(
        session: Session, offer_ids: Sequence[UUID]
    ) -> dict[UUID, list[ot.OfferRevisionRecord]]:
        """Revisions for many offers at once, keyed by offer.

        Ordered the same way ``_revisions_for`` orders a single offer's, so the
        two paths cannot return a different revision history for the same offer.
        """
        if not offer_ids:
            return {}
        rows = (
            session.execute(
                select(ot.OfferRevisionRecord)
                .where(ot.OfferRevisionRecord.offer_id.in_(offer_ids))
                .order_by(ot.OfferRevisionRecord.offer_id, ot.OfferRevisionRecord.revision_index)
            )
            .scalars()
            .all()
        )
        grouped: dict[UUID, list[ot.OfferRevisionRecord]] = {}
        for row in rows:
            grouped.setdefault(row.offer_id, []).append(row)
        return grouped

    @staticmethod
    def _revisions_for(session: Session, offer_id: UUID) -> list[ot.OfferRevisionRecord]:
        return list(
            session.execute(
                select(ot.OfferRevisionRecord)
                .where(ot.OfferRevisionRecord.offer_id == offer_id)
                .order_by(ot.OfferRevisionRecord.revision_index)
            )
            .scalars()
            .all()
        )

    @staticmethod
    def _to_offer(row: ot.OfferRecord, revisions: list[ot.OfferRevisionRecord]) -> Offer:
        return Offer(
            id=row.id,
            application_id=row.application_id,
            candidate_id=row.candidate_id,
            job_id=row.job_id,
            status=OfferStatus(row.status),
            terms=OfferTerms.model_validate(row.terms),
            revisions=[
                OfferRevision(
                    id=revision.id,
                    offer_id=revision.offer_id,
                    revision_index=revision.revision_index,
                    terms=OfferTerms.model_validate(revision.terms),
                    changed_by=revision.changed_by,
                    changed_at=_aware(revision.changed_at),
                    note=revision.note,
                )
                for revision in revisions
            ],
            created_by=row.created_by,
            created_at=_aware(row.created_at),
            updated_at=_aware(row.updated_at),
            decided_by=row.decided_by,
            decided_at=None if row.decided_at is None else _aware(row.decided_at),
            queued_at=None if row.queued_at is None else _aware(row.queued_at),
            accepted_at=None if row.accepted_at is None else _aware(row.accepted_at),
            declined_at=None if row.declined_at is None else _aware(row.declined_at),
            decline_reason=row.decline_reason,
        )
