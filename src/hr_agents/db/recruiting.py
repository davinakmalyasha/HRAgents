"""Postgres-backed recruitment services.

Each adapter overrides only the persistence primitives of its service class, so
validation, auditing, and lifecycle rules stay in one place.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.session import sync_session_scope
from hr_agents.models import (
    FeedbackReport,
    HitlOverride,
    JobSpecification,
    PolicyDecision,
    PolicyEvaluation,
    SchedulingPayload,
    TechnicalEvaluation,
    TimeSlot,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.ingestion import ApplicationStore
from hr_agents.services.policy import evaluate_policy
from hr_agents.services.recruiting import (
    DocumentService,
    EvaluationRecord,
    EvaluationService,
    JobService,
    RecruitingError,
    SchedulingProposalRecord,
    SchedulingService,
    StoredDocument,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class DbDocumentService(DocumentService):
    """Stored documents in ``candidate_documents`` (content included)."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        audit: AuditChain | None = None,
    ) -> None:
        super().__init__(audit=audit)
        self._session_factory = session_factory

    def _load_document(self, document_id: UUID) -> StoredDocument | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.CandidateDocumentRecord, document_id)
            return None if row is None else self._to_document(row)

    def _iter_documents(self) -> Iterator[StoredDocument]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(t.CandidateDocumentRecord)).scalars().all()
            return iter([self._to_document(row) for row in rows])

    def _store_document(self, document: StoredDocument) -> None:
        with sync_session_scope(self._session_factory) as session:
            session.add(
                t.CandidateDocumentRecord(
                    id=document.id,
                    kind=document.kind,
                    filename=document.filename,
                    sha256=document.sha256,
                    size_bytes=document.size_bytes,
                    content=document.content,
                    uploaded_by=document.uploaded_by,
                    uploaded_at=document.uploaded_at,
                )
            )
            session.flush()

    @staticmethod
    def _to_document(row: t.CandidateDocumentRecord) -> StoredDocument:
        return StoredDocument(
            id=row.id,
            kind=row.kind,
            filename=row.filename,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            content=bytes(row.content),
            uploaded_by=row.uploaded_by,
            uploaded_at=_aware(row.uploaded_at),
        )


class DbJobService(JobService):
    """Job specifications in the ``jobs`` table (full spec in a JSON document)."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        audit: AuditChain | None = None,
    ) -> None:
        super().__init__(audit=audit)
        self._session_factory = session_factory

    def _load_job(self, job_id: UUID) -> JobSpecification | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.Job, job_id)
            return None if row is None else JobSpecification.model_validate(row.spec)

    def _iter_jobs(self) -> Iterator[JobSpecification]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(t.Job)).scalars().all()
            return iter([JobSpecification.model_validate(row.spec) for row in rows])

    def _persist_job(self, job: JobSpecification) -> None:
        spec = job.model_dump(mode="json")
        weights = (
            {dimension.value: weight for dimension, weight in job.dimension_weights.items()}
            if job.dimension_weights is not None
            else None
        )
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.Job, job.id)
            if row is None:
                session.add(
                    t.Job(
                        id=job.id,
                        title=job.title,
                        seniority=job.seniority.value,
                        status=job.status.value,
                        spec=spec,
                        dimension_weights=weights,
                        created_at=job.created_at,
                        updated_at=job.updated_at,
                    )
                )
            else:
                row.title = job.title
                row.seniority = job.seniority.value
                row.status = job.status.value
                row.spec = spec
                row.dimension_weights = weights
                row.updated_at = job.updated_at
            session.flush()


class DbEvaluationService(EvaluationService):
    """Evaluations, overrides, and feedback in their dedicated tables."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        audit: AuditChain | None = None,
        applications: ApplicationStore | None = None,
    ) -> None:
        super().__init__(audit=audit, applications=applications)
        self._session_factory = session_factory

    # records

    def _load_record(self, evaluation_id: UUID) -> EvaluationRecord | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.Evaluation, evaluation_id)
            return None if row is None else self._to_record(row)

    def _iter_records(self) -> Iterator[EvaluationRecord]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(t.Evaluation)).scalars().all()
            return iter([self._to_record(row) for row in rows])

    def _persist_record(self, record: EvaluationRecord) -> None:
        evaluation = record.evaluation
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.Evaluation, evaluation.id)
            if row is None:
                row = t.Evaluation(id=evaluation.id, document={})
                session.add(row)
            row.candidate_id = evaluation.candidate_id
            row.application_id = record.application_id
            row.job_id = evaluation.job_id
            row.candidate_name = record.candidate_name
            row.job_title = record.job_title
            row.s_tech = evaluation.s_tech
            row.sigma = evaluation.sigma
            row.recommendation = evaluation.recommendation.value
            row.policy_version = evaluation.policy_version
            row.source = record.source
            row.document = evaluation.model_dump(mode="json")
            row.policy = record.policy.model_dump(mode="json")
            row.created_at = record.registered_at
            session.flush()

    # overrides

    def _load_overrides(self, evaluation_id: UUID) -> list[HitlOverride]:
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    select(t.EvaluationOverrideRecord)
                    .where(t.EvaluationOverrideRecord.evaluation_id == evaluation_id)
                    .order_by(t.EvaluationOverrideRecord.created_at)
                )
                .scalars()
                .all()
            )
            return [self._to_override(row) for row in rows]

    def _append_override(self, override: HitlOverride) -> None:
        with sync_session_scope(self._session_factory) as session:
            session.add(
                t.EvaluationOverrideRecord(
                    id=override.id,
                    evaluation_id=UUID(override.evaluation_id),
                    reviewer_id=override.reviewer_id,
                    reviewer_role=override.reviewer_role,
                    override_decision=override.override_decision.value,
                    reason_code=override.reason_code,
                    notes=override.notes,
                    created_at=override.decided_at,
                )
            )
            session.flush()

    # feedback

    def _load_feedback(self, candidate_id: UUID) -> FeedbackReport | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.FeedbackReportRecord, candidate_id)
            return None if row is None else FeedbackReport.model_validate(row.report)

    def _persist_feedback(self, candidate_id: UUID, report: FeedbackReport, *, by: str) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.FeedbackReportRecord, candidate_id)
            if row is None:
                session.add(
                    t.FeedbackReportRecord(
                        candidate_id=candidate_id,
                        language=report.language,
                        report=report.model_dump(mode="json"),
                        saved_by=by,
                    )
                )
            else:
                row.language = report.language
                row.report = report.model_dump(mode="json")
                row.saved_by = by
            session.flush()

    # mapping

    @staticmethod
    def _to_record(row: t.Evaluation) -> EvaluationRecord:
        if row.application_id is None:
            raise RecruitingError(f"evaluation {row.id} has no application_id")
        evaluation = TechnicalEvaluation.model_validate(row.document)
        if row.policy is not None:
            policy = PolicyEvaluation.model_validate(row.policy)
        else:
            policy = evaluate_policy(
                s_tech=evaluation.s_tech,
                sigma=evaluation.sigma,
                flags=evaluation.flags,
            )
        return EvaluationRecord(
            application_id=row.application_id,
            candidate_id=row.candidate_id,
            candidate_name=row.candidate_name or "",
            job_id=row.job_id,
            job_title=row.job_title or "",
            evaluation=evaluation,
            policy=policy,
            source=row.source or "pipeline",
            registered_at=_aware(row.created_at),
        )

    @staticmethod
    def _to_override(row: t.EvaluationOverrideRecord) -> HitlOverride:
        return HitlOverride(
            id=row.id,
            evaluation_id=str(row.evaluation_id),
            reviewer_id=row.reviewer_id,
            reviewer_role=row.reviewer_role,
            override_decision=PolicyDecision(row.override_decision),
            reason_code=row.reason_code,
            notes=row.notes,
            decided_at=_aware(row.created_at),
        )


class DbSchedulingService(SchedulingService):
    """Availability and proposals in ``scheduling_availability``/``schedule_proposals``."""

    def __init__(
        self,
        *,
        evaluations: EvaluationService,
        session_factory: sessionmaker[Session],
        audit: AuditChain | None = None,
        applications: ApplicationStore | None = None,
    ) -> None:
        super().__init__(evaluations=evaluations, audit=audit, applications=applications)
        self._session_factory = session_factory

    def _load_availability(self, interviewer_id: UUID) -> list[TimeSlot]:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.SchedulingAvailabilityRecord, interviewer_id)
            if row is None:
                return []
            return [TimeSlot.model_validate(slot) for slot in row.slots]

    def _persist_availability(
        self, interviewer_id: UUID, slots: list[TimeSlot], *, by: str
    ) -> None:
        payload = [slot.model_dump(mode="json") for slot in slots]
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.SchedulingAvailabilityRecord, interviewer_id)
            if row is None:
                session.add(
                    t.SchedulingAvailabilityRecord(
                        interviewer_id=interviewer_id,
                        slots=payload,
                        updated_by=by,
                    )
                )
            else:
                row.slots = payload
                row.updated_by = by
            session.flush()

    def _load_proposal(self, proposal_id: UUID) -> SchedulingProposalRecord | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.ScheduleProposal, proposal_id)
            return None if row is None else self._to_proposal(row)

    def _iter_proposals(self) -> Iterator[SchedulingProposalRecord]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(t.ScheduleProposal)).scalars().all()
            return iter([self._to_proposal(row) for row in rows])

    def _persist_proposal(self, proposal: SchedulingProposalRecord) -> None:
        payload = proposal.payload
        status = (
            "auto_scheduled"
            if payload.auto_scheduled
            else ("pending_approval" if proposal.requires_human_approval else "proposed")
        )
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.ScheduleProposal, proposal.id)
            if row is None:
                row = t.ScheduleProposal(id=proposal.id, payload={})
                session.add(row)
            row.candidate_id = payload.candidate_id
            row.job_id = payload.job_id
            row.status = status
            row.payload = payload.model_dump(mode="json")
            row.requires_human_approval = proposal.requires_human_approval
            row.needs_human_reconciliation = proposal.needs_human_reconciliation
            row.created_by = proposal.created_by
            row.created_at = proposal.created_at
            session.flush()

    @staticmethod
    def _to_proposal(row: t.ScheduleProposal) -> SchedulingProposalRecord:
        return SchedulingProposalRecord(
            id=row.id,
            payload=SchedulingPayload.model_validate(row.payload),
            requires_human_approval=bool(row.requires_human_approval),
            needs_human_reconciliation=bool(row.needs_human_reconciliation),
            created_by=row.created_by or "system",
            created_at=_aware(row.created_at),
        )
