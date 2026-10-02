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
from hr_agents.identity import ActorRef
from hr_agents.models import (
    CandidateCommunication,
    Channel,
    CommunicationKind,
    CommunicationStatus,
    FeedbackReport,
    HitlOverride,
    JobSpecification,
    PolicyDecision,
    PolicyEvaluation,
    ProposalStatus,
    SchedulingPayload,
    TechnicalEvaluation,
    TimeSlot,
)
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.ingestion import ApplicationStore
from hr_agents.services.policy import evaluate_policy
from hr_agents.services.recruiting import (
    CommunicationService,
    DocumentService,
    EvaluationRecord,
    EvaluationService,
    JobService,
    RecruitingError,
    SchedulingProposalRecord,
    SchedulingService,
    StoredDocument,
    normalize_message_id,
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

    def _record_for_candidate(self, candidate_id: UUID) -> EvaluationRecord | None:
        """One indexed read.

        The index was already there; the base class used to answer this by
        scanning every row it had loaded, which meant the whole pipeline was
        re-read for each candidate the rejection and scheduling paths touched.
        """
        with sync_session_scope(self._session_factory) as session:
            row = (
                session.execute(
                    select(t.Evaluation).where(t.Evaluation.candidate_id == candidate_id).limit(1)
                )
                .scalars()
                .first()
            )
            return None if row is None else self._to_record(row)

    def _record_for_application(self, application_id: UUID) -> EvaluationRecord | None:
        with sync_session_scope(self._session_factory) as session:
            row = (
                session.execute(
                    select(t.Evaluation)
                    .where(t.Evaluation.application_id == application_id)
                    .limit(1)
                )
                .scalars()
                .first()
            )
            return None if row is None else self._to_record(row)

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

    def _persist_feedback(
        self, candidate_id: UUID, report: FeedbackReport, *, actor: ActorRef
    ) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.FeedbackReportRecord, candidate_id)
            if row is None:
                session.add(
                    t.FeedbackReportRecord(
                        candidate_id=candidate_id,
                        language=report.language,
                        report=report.model_dump(mode="json"),
                        saved_by=actor.actor_id,
                    )
                )
            else:
                row.language = report.language
                row.report = report.model_dump(mode="json")
                row.saved_by = actor.actor_id
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
        approvals: ApprovalEngine | None = None,
    ) -> None:
        super().__init__(
            evaluations=evaluations,
            audit=audit,
            applications=applications,
            approvals=approvals,
        )
        self._session_factory = session_factory

    def _load_availability(self, interviewer_id: UUID) -> list[TimeSlot]:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.SchedulingAvailabilityRecord, interviewer_id)
            if row is None:
                return []
            return [TimeSlot.model_validate(slot) for slot in row.slots]

    def _persist_availability(
        self, interviewer_id: UUID, slots: list[TimeSlot], *, actor: ActorRef
    ) -> None:
        payload = [slot.model_dump(mode="json") for slot in slots]
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.SchedulingAvailabilityRecord, interviewer_id)
            if row is None:
                session.add(
                    t.SchedulingAvailabilityRecord(
                        interviewer_id=interviewer_id,
                        slots=payload,
                        updated_by=actor.actor_id,
                    )
                )
            else:
                row.slots = payload
                row.updated_by = actor.actor_id
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
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.ScheduleProposal, proposal.id)
            if row is None:
                row = t.ScheduleProposal(id=proposal.id, status=proposal.status.value, payload={})
                session.add(row)
            row.candidate_id = payload.candidate_id
            row.job_id = payload.job_id
            row.status = proposal.status.value
            row.payload = payload.model_dump(mode="json")
            row.requires_human_approval = proposal.requires_human_approval
            row.needs_human_reconciliation = proposal.needs_human_reconciliation
            row.supersedes_id = proposal.supersedes_id
            row.decided_by = proposal.decided_by
            row.decided_at = proposal.decided_at
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
            status=ProposalStatus(row.status),
            supersedes_id=row.supersedes_id,
            decided_by=row.decided_by,
            decided_at=None if row.decided_at is None else _aware(row.decided_at),
            created_by=row.created_by or "system",
            created_at=_aware(row.created_at),
        )


class DbCommunicationService(CommunicationService):
    """Queued candidate communications in ``candidate_communications``."""

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

    def _load(self, communication_id: UUID) -> CandidateCommunication | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.CandidateCommunicationRecord, communication_id)
            return None if row is None else self._to_communication(row)

    def _iter(self) -> Iterator[CandidateCommunication]:
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(select(t.CandidateCommunicationRecord)).scalars().all()
            return iter([self._to_communication(row) for row in rows])

    def _find(
        self,
        *,
        candidate_id: UUID | None = None,
        status: CommunicationStatus | None = None,
        channel: Channel | None = None,
        provider_message_id: str | None = None,
    ) -> list[CandidateCommunication]:
        """Filter in SQL, not in Python: the outbox table grows with every hire."""
        query = select(t.CandidateCommunicationRecord)
        if candidate_id is not None:
            query = query.where(t.CandidateCommunicationRecord.candidate_id == candidate_id)
        if status is not None:
            query = query.where(t.CandidateCommunicationRecord.status == status.value)
        if channel is not None:
            query = query.where(t.CandidateCommunicationRecord.channel == channel.value)
        if provider_message_id is not None:
            # Correlation compares canonicalized ids (case-insensitive, brackets
            # stripped) so a reply that echoes "<id@host>" still finds the row.
            query = query.where(
                t.CandidateCommunicationRecord.provider_message_id_normalized
                == normalize_message_id(provider_message_id)
            )
        with sync_session_scope(self._session_factory) as session:
            rows = session.execute(query).scalars().all()
            return [self._to_communication(row) for row in rows]

    def _persist(self, item: CandidateCommunication) -> None:
        with sync_session_scope(self._session_factory) as session:
            row = session.get(t.CandidateCommunicationRecord, item.id)
            if row is None:
                row = t.CandidateCommunicationRecord(
                    id=item.id, kind=item.kind.value, channel=item.channel.value
                )
                session.add(row)
            row.candidate_id = item.candidate_id
            row.application_id = item.application_id
            row.evaluation_id = item.evaluation_id
            row.kind = item.kind.value
            row.channel = item.channel.value
            row.language = item.language
            row.subject = item.subject
            row.body = item.body
            row.status = item.status.value
            row.approved_by = item.approved_by
            row.approved_at = item.approved_at
            row.sent_by = item.sent_by
            row.sent_at = item.sent_at
            row.recipient = item.recipient
            row.recipient_phone = item.recipient_phone
            row.provider = item.provider
            row.provider_message_id = item.provider_message_id
            row.provider_message_id_normalized = (
                None
                if item.provider_message_id is None
                else normalize_message_id(item.provider_message_id)
            )
            row.send_attempts = item.send_attempts
            row.last_error = item.last_error
            row.created_at = item.created_at
            session.flush()

    @staticmethod
    def _to_communication(row: t.CandidateCommunicationRecord) -> CandidateCommunication:
        return CandidateCommunication(
            id=row.id,
            candidate_id=row.candidate_id,
            application_id=row.application_id,
            evaluation_id=row.evaluation_id,
            kind=CommunicationKind(row.kind),
            channel=Channel(row.channel),
            language=row.language,  # type: ignore[arg-type]
            subject=row.subject,
            body=row.body,
            status=CommunicationStatus(row.status),
            approved_by=row.approved_by,
            approved_at=_aware(row.approved_at),
            sent_by=row.sent_by,
            sent_at=None if row.sent_at is None else _aware(row.sent_at),
            recipient=row.recipient,
            recipient_phone=row.recipient_phone,
            provider=row.provider,
            provider_message_id=row.provider_message_id,
            send_attempts=row.send_attempts,
            last_error=row.last_error,
            created_at=_aware(row.created_at),
        )
