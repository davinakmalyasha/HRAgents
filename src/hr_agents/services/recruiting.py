"""Recruitment API services — documents, jobs, evaluations, overrides, feedback, scheduling.

These are the deterministic surfaces behind the ingestion API:

- **Documents** are stored with their hash; content never reaches an LLM without
  a redaction pass (handled upstream when extraction runs).
- **Jobs** are operator-owned specifications; lifecycle transitions are guarded
  and audited.
- **Evaluations** are registered by the pipeline (never computed here). Human
  overrides are append-only, restricted to named reviewers in permitted roles,
  and audited with a receipt the caller can persist.
- **Feedback reports** are served from stored (agent-authored) reports when
  present, otherwise synthesized deterministically from the evaluation
  breakdown. Neither path includes protected attributes, raw scores in prose,
  or internal notes.
- **Scheduling proposals** intersect interviewer availability deterministically
  and route through the policy engine; auto-scheduling happens only inside
  policy bounds, everything else is marked for human approval.

All state lives in in-memory stores that define the behavioral contract;
Postgres adapters arrive in the integrations phase behind the same interfaces.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models import (
    ActorType,
    AuditActor,
    AuditEntry,
    FeedbackGrowthArea,
    FeedbackReport,
    FeedbackStrength,
    HitlOverride,
    JobSpecification,
    JobStatus,
    PolicyDecision,
    PolicyEvaluation,
    Recommendation,
    SchedulingChannel,
    SchedulingPayload,
    ScoreDimension,
    Seniority,
    StrictModel,
    TechnicalEvaluation,
    TimeSlot,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.ingestion import ApplicationStatus, ApplicationStore
from hr_agents.services.policy import evaluate_policy

# --- shared constants ---------------------------------------------------------

DOCUMENT_KINDS = frozenset({"cv", "portfolio", "questionnaire", "linkedin_export", "other"})
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MiB

OVERRIDE_REVIEWER_ROLES = frozenset({"engineering_lead", "recruiter_lead", "hr_partner"})

JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.DRAFT: frozenset({JobStatus.OPEN, JobStatus.CLOSED}),
    JobStatus.OPEN: frozenset({JobStatus.PAUSED, JobStatus.CLOSED}),
    JobStatus.PAUSED: frozenset({JobStatus.OPEN, JobStatus.CLOSED}),
    JobStatus.CLOSED: frozenset(),
}

MAX_PROPOSED_SLOTS = 3
AGENT_ACTOR_PREFIX = "agent:"

_DIMENSION_LABELS: dict[ScoreDimension, tuple[str, str]] = {
    ScoreDimension.TECHNICAL_DEPTH: ("technical depth", "kedalaman teknis"),
    ScoreDimension.STACK_ALIGNMENT: ("stack alignment", "kesesuaian teknologi"),
    ScoreDimension.SYSTEMS_LITERACY: ("systems literacy", "pemahaman sistem"),
    ScoreDimension.VERIFIABLE_CERTIFICATIONS: (
        "verifiable certifications",
        "sertifikasi yang dapat diverifikasi",
    ),
}

_STRENGTH_THRESHOLD = 0.60
_GROWTH_THRESHOLD = 0.70


class RecruitingError(RuntimeError):
    """Raised for invalid recruitment operations."""


class DocumentTooLargeError(RecruitingError):
    """Raised when an upload exceeds the configured size ceiling."""


# --- documents ----------------------------------------------------------------


@dataclass
class StoredDocument:
    """A stored source document (CV, portfolio, questionnaire, export)."""

    id: UUID
    kind: str
    filename: str | None
    sha256: str
    size_bytes: int
    content: bytes
    uploaded_by: str
    uploaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DocumentService:
    """Store uploaded documents with content hashing and size enforcement.

    Database adapters override the ``_load_document``/``_iter_documents``/
    ``_store_document`` primitives; validation and auditing stay here.
    """

    def __init__(self, *, audit: AuditChain | None = None) -> None:
        self._documents: dict[UUID, StoredDocument] = {}
        self._audit = audit or AuditChain()

    # persistence primitives (overridden by database adapters)

    def _load_document(self, document_id: UUID) -> StoredDocument | None:
        return self._documents.get(document_id)

    def _iter_documents(self) -> Iterator[StoredDocument]:
        return iter(self._documents.values())

    def _store_document(self, document: StoredDocument) -> None:
        self._documents[document.id] = document

    def upload(
        self,
        *,
        filename: str | None,
        kind: str,
        content: bytes,
        uploaded_by: str,
    ) -> StoredDocument:
        if kind not in DOCUMENT_KINDS:
            raise RecruitingError(
                f"unsupported document kind {kind!r}; expected one of "
                + ", ".join(sorted(DOCUMENT_KINDS))
            )
        if not content:
            raise RecruitingError("document is empty")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise DocumentTooLargeError(
                f"document is {len(content)} bytes; limit is {MAX_DOCUMENT_BYTES}"
            )

        document = StoredDocument(
            id=uuid4(),
            kind=kind,
            filename=filename,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content=content,
            uploaded_by=uploaded_by,
        )
        self._store_document(document)
        self._audit.append(
            actor=self._actor(uploaded_by),
            action="document.uploaded",
            subject_type="document",
            subject_id=str(document.id),
            payload={"kind": kind, "sha256": document.sha256, "size_bytes": document.size_bytes},
        )
        return document

    def get(self, document_id: UUID) -> StoredDocument:
        document = self._load_document(document_id)
        if document is None:
            raise RecruitingError(f"unknown document {document_id}")
        return document

    def list_all(self) -> list[StoredDocument]:
        return sorted(self._iter_documents(), key=lambda item: item.uploaded_at)

    @staticmethod
    def _actor(actor_id: str) -> AuditActor:
        if actor_id.startswith(AGENT_ACTOR_PREFIX):
            actor_type = ActorType.AGENT
        elif actor_id == "system" or actor_id.startswith("system:"):
            actor_type = ActorType.SYSTEM
        else:
            actor_type = ActorType.HUMAN
        return AuditActor(actor_type=actor_type, actor_id=actor_id)


# --- jobs ----------------------------------------------------------------------


class JobService:
    """Job specification CRUD with a guarded status lifecycle.

    Database adapters override ``_load_job``/``_iter_jobs``/``_persist_job``.
    """

    def __init__(self, *, audit: AuditChain | None = None) -> None:
        self._jobs: dict[UUID, JobSpecification] = {}
        self._audit = audit or AuditChain()

    # persistence primitives (overridden by database adapters)

    def _load_job(self, job_id: UUID) -> JobSpecification | None:
        return self._jobs.get(job_id)

    def _iter_jobs(self) -> Iterator[JobSpecification]:
        return iter(self._jobs.values())

    def _persist_job(self, job: JobSpecification) -> None:
        self._jobs[job.id] = job

    def create(
        self,
        *,
        title: str,
        created_by: str,
        seniority: Seniority | None = None,
        description: str = "",
        responsibilities: list[str] | None = None,
        must_have_skills: list[str] | None = None,
        nice_to_have_skills: list[str] | None = None,
        stack: list[str] | None = None,
        min_years_experience: int = 0,
        dimension_weights: dict[ScoreDimension, float] | None = None,
        status: JobStatus = JobStatus.DRAFT,
    ) -> JobSpecification:
        job = JobSpecification(
            title=title,
            seniority=seniority or Seniority.MID,
            description=description,
            responsibilities=responsibilities or [],
            must_have_skills=must_have_skills or [],
            nice_to_have_skills=nice_to_have_skills or [],
            stack=stack or [],
            min_years_experience=min_years_experience,
            dimension_weights=dimension_weights,
            status=status,
            created_by=created_by,
        )
        self._persist_job(job)
        self._audit.append(
            actor=self._actor(created_by),
            action="job.created",
            subject_type="job",
            subject_id=str(job.id),
            payload={"title": title, "status": status.value},
        )
        return job

    def get(self, job_id: UUID) -> JobSpecification:
        job = self._load_job(job_id)
        if job is None:
            raise RecruitingError(f"unknown job {job_id}")
        return job

    def list_all(self, *, status: JobStatus | None = None) -> list[JobSpecification]:
        jobs = sorted(self._iter_jobs(), key=lambda item: item.created_at)
        if status is not None:
            jobs = [job for job in jobs if job.status is status]
        return jobs

    def update(
        self,
        job_id: UUID,
        *,
        by: str,
        title: str | None = None,
        seniority: Seniority | None = None,
        description: str | None = None,
        responsibilities: list[str] | None = None,
        must_have_skills: list[str] | None = None,
        nice_to_have_skills: list[str] | None = None,
        stack: list[str] | None = None,
        min_years_experience: int | None = None,
        dimension_weights: dict[ScoreDimension, float] | None = None,
    ) -> JobSpecification:
        job = self.get(job_id)
        if job.status is JobStatus.CLOSED:
            raise RecruitingError("closed jobs are read-only")

        updates: dict[str, object] = {"updated_at": utc_now()}
        for name, value in {
            "title": title,
            "seniority": seniority,
            "description": description,
            "responsibilities": responsibilities,
            "must_have_skills": must_have_skills,
            "nice_to_have_skills": nice_to_have_skills,
            "stack": stack,
            "min_years_experience": min_years_experience,
            "dimension_weights": dimension_weights,
        }.items():
            if value is not None:
                updates[name] = value

        updated = job.model_copy(update=updates)
        self._persist_job(updated)
        self._audit.append(
            actor=self._actor(by),
            action="job.updated",
            subject_type="job",
            subject_id=str(updated.id),
            payload={"fields": sorted(name for name in updates if name != "updated_at")},
        )
        return updated

    def transition(self, job_id: UUID, *, target: JobStatus, by: str) -> JobSpecification:
        job = self.get(job_id)
        if target not in JOB_TRANSITIONS[job.status]:
            raise RecruitingError(f"cannot move job from {job.status.value} to {target.value}")
        updated = job.model_copy(update={"status": target, "updated_at": utc_now()})
        self._persist_job(updated)
        self._audit.append(
            actor=self._actor(by),
            action="job.status_changed",
            subject_type="job",
            subject_id=str(updated.id),
            payload={"from": job.status.value, "to": target.value},
        )
        return updated

    @staticmethod
    def _actor(actor_id: str) -> AuditActor:
        return DocumentService._actor(actor_id)


# --- evaluations & overrides ----------------------------------------------------


@dataclass
class EvaluationRecord:
    """One registered evaluation plus the context needed to serve it."""

    application_id: UUID
    candidate_id: UUID
    candidate_name: str
    job_id: UUID | None
    job_title: str
    evaluation: TechnicalEvaluation
    policy: PolicyEvaluation
    source: str = "pipeline"
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class OverrideOutcome:
    override: HitlOverride
    receipt: AuditEntry


class EvaluationService:
    """Registered evaluations, append-only human overrides, and feedback.

    Database adapters override the ``_load_*``/``_iter_*``/``_persist_*``/
    ``_append_override`` primitives.
    """

    def __init__(
        self,
        *,
        audit: AuditChain | None = None,
        applications: ApplicationStore | None = None,
    ) -> None:
        self._records: dict[UUID, EvaluationRecord] = {}  # evaluation id → record
        self._overrides: dict[UUID, list[HitlOverride]] = {}  # evaluation id → overrides
        self._feedback: dict[UUID, FeedbackReport] = {}  # candidate id → stored report
        self._audit = audit or AuditChain()
        self._applications = applications

    # persistence primitives (overridden by database adapters)

    def _load_record(self, evaluation_id: UUID) -> EvaluationRecord | None:
        return self._records.get(evaluation_id)

    def _iter_records(self) -> Iterator[EvaluationRecord]:
        return iter(self._records.values())

    def _persist_record(self, record: EvaluationRecord) -> None:
        self._records[record.evaluation.id] = record

    def _load_overrides(self, evaluation_id: UUID) -> list[HitlOverride]:
        return list(self._overrides.get(evaluation_id, []))

    def _append_override(self, override: HitlOverride) -> None:
        self._overrides.setdefault(UUID(override.evaluation_id), []).append(override)

    def _load_feedback(self, candidate_id: UUID) -> FeedbackReport | None:
        return self._feedback.get(candidate_id)

    def _persist_feedback(self, candidate_id: UUID, report: FeedbackReport, *, by: str) -> None:
        self._feedback[candidate_id] = report

    # registration

    def register(
        self,
        *,
        application_id: UUID,
        evaluation: TechnicalEvaluation,
        candidate_name: str,
        job_title: str,
        policy: PolicyEvaluation | None = None,
        source: str = "pipeline",
    ) -> EvaluationRecord:
        """Register a pipeline result. The pipeline owns computation; the API reads."""
        if self._load_record(evaluation.id) is not None:
            raise RecruitingError(f"evaluation {evaluation.id} is already registered")
        resolved_policy = policy or evaluate_policy(
            s_tech=evaluation.s_tech,
            sigma=evaluation.sigma,
            flags=evaluation.flags,
        )
        record = EvaluationRecord(
            application_id=application_id,
            candidate_id=evaluation.candidate_id,
            candidate_name=candidate_name,
            job_id=evaluation.job_id,
            job_title=job_title,
            evaluation=evaluation,
            policy=resolved_policy,
            source=source,
        )
        self._persist_record(record)

        if self._applications is not None:
            self._sync_application_for_evaluation(record)

        self._audit.append_system(
            action="evaluation.registered",
            subject_type="evaluation",
            subject_id=str(evaluation.id),
            payload={
                "application_id": str(application_id),
                "candidate_id": str(evaluation.candidate_id),
                "s_tech": round(evaluation.s_tech, 6),
                "sigma": round(evaluation.sigma, 6),
                "recommendation": evaluation.recommendation.value,
                "source": source,
            },
        )
        return record

    def get(self, evaluation_id: UUID) -> EvaluationRecord:
        record = self._load_record(evaluation_id)
        if record is None:
            raise RecruitingError(f"unknown evaluation {evaluation_id}")
        return record

    def get_by_application(self, application_id: UUID) -> EvaluationRecord:
        for record in self._iter_records():
            if record.application_id == application_id:
                return record
        raise RecruitingError(f"no evaluation for application {application_id}")

    def get_by_candidate(self, candidate_id: UUID) -> EvaluationRecord:
        for record in self._iter_records():
            if record.candidate_id == candidate_id:
                return record
        raise RecruitingError(f"no evaluation for candidate {candidate_id}")

    # overrides

    def record_override(
        self,
        evaluation_id: UUID,
        *,
        reviewer_id: str,
        reviewer_role: str,
        override_decision: PolicyDecision,
        reason_code: str,
        notes: str | None = None,
    ) -> OverrideOutcome:
        """Append a named human decision. Overrides are never edited or deleted."""
        record = self.get(evaluation_id)
        if not reviewer_id or reviewer_id.startswith(AGENT_ACTOR_PREFIX):
            raise RecruitingError("overrides require a named human reviewer")
        if reviewer_role not in OVERRIDE_REVIEWER_ROLES:
            raise RecruitingError(
                f"role {reviewer_role!r} cannot override; expected one of "
                + ", ".join(sorted(OVERRIDE_REVIEWER_ROLES))
            )
        if not reason_code.strip():
            raise RecruitingError("an override requires a reason code")

        override = HitlOverride(
            evaluation_id=str(evaluation_id),
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
            override_decision=override_decision,
            reason_code=reason_code,
            notes=notes,
        )
        self._append_override(override)

        if self._applications is not None:
            self._apply_override_status(record, override_decision)

        receipt = self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=reviewer_id),
            action="evaluation.override_recorded",
            subject_type="evaluation",
            subject_id=str(evaluation_id),
            payload={
                "reviewer_role": reviewer_role,
                "override_decision": override_decision.value,
                "reason_code": reason_code,
                "notes_present": bool(notes),
            },
        )
        return OverrideOutcome(override=override, receipt=receipt)

    def list_overrides(self, evaluation_id: UUID) -> list[HitlOverride]:
        self.get(evaluation_id)
        return self._load_overrides(evaluation_id)

    # feedback

    def save_feedback(self, candidate_id: UUID, report: FeedbackReport, *, by: str) -> None:
        """Store an agent-authored report; it takes precedence over synthesis."""
        self._persist_feedback(candidate_id, report, by=by)
        self._audit.append(
            actor=DocumentService._actor(by),
            action="feedback.saved",
            subject_type="candidate",
            subject_id=str(candidate_id),
            payload={"language": report.language},
        )

    def feedback_for(self, candidate_id: UUID, *, language: str = "en") -> FeedbackReport:
        """Return the stored report, else synthesize deterministically."""
        stored = self._load_feedback(candidate_id)
        if stored is not None:
            return stored
        record = self.get_by_candidate(candidate_id)
        return synthesize_feedback(
            record.evaluation,
            candidate_name=record.candidate_name,
            job_title=record.job_title,
            language=language,
        )

    # internals

    def _sync_application_for_evaluation(self, record: EvaluationRecord) -> None:
        assert self._applications is not None
        application = self._applications.get(record.application_id)
        if application is None:
            return
        application.s_tech = record.evaluation.s_tech
        application.sigma = record.evaluation.sigma
        application.recommendation = record.evaluation.recommendation
        status_map = {
            Recommendation.REJECT: ApplicationStatus.REJECTED,
            Recommendation.AUTO_SCHEDULE: ApplicationStatus.EVALUATED,
        }
        target = status_map.get(record.evaluation.recommendation, ApplicationStatus.GATED)
        application.status = target
        application.note(f"application.evaluated.{target.value}")
        application.refresh_priority(risk_flag_count=len(record.evaluation.flags))
        self._applications.save(application)

    def _apply_override_status(self, record: EvaluationRecord, decision: PolicyDecision) -> None:
        assert self._applications is not None
        application = self._applications.get(record.application_id)
        if application is None:
            return
        target = {
            PolicyDecision.AUTO_SCHEDULE: ApplicationStatus.SCHEDULED,
            PolicyDecision.REJECT_AUTO: ApplicationStatus.REJECTED,
        }.get(decision, ApplicationStatus.GATED)
        application.status = target
        application.note(f"evaluation.override.{decision.value}")
        self._applications.save(application)


def synthesize_feedback(
    evaluation: TechnicalEvaluation,
    *,
    candidate_name: str,
    job_title: str,
    language: str = "en",
) -> FeedbackReport:
    """Build a deterministic, evidence-grounded report from the breakdown.

    No scores appear in prose, no protected attributes are used, and growth
    areas are phrased as missing evidence — never ability judgments.
    """
    lang = "id" if language == "id" else "en"
    scores = {item.dimension: item.score for item in evaluation.breakdown}
    top = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
    strengths = [
        FeedbackStrength(
            dimension=dimension,
            text=_strength_text(dimension, lang),
        )
        for dimension, score in top
        if score >= _STRENGTH_THRESHOLD
    ][:2]
    growth = [
        FeedbackGrowthArea(dimension=dimension, text=_growth_text(dimension, lang))
        for dimension, score in sorted(scores.items(), key=lambda item: (item[1], item[0].value))
        if score < _GROWTH_THRESHOLD
    ][:2]

    if lang == "id":
        summary = (
            f"Laporan ini merangkum evaluasi terstruktur untuk lamaran Anda pada posisi "
            f"{job_title}. Laporan disusun dari bukti yang ditinjau dan tetap berguna "
            "terlepas dari hasil prosesnya."
        )
        process_note = (
            "Dibuat otomatis dari evaluasi terstruktur berbasis bukti; atribut pribadi "
            "yang dilindungi tidak digunakan dalam penilaian."
        )
        correction_notice = (
            "Jika ada informasi yang tidak akurat, hubungi HR untuk meminta perbaikan."
        )
    else:
        summary = (
            f"This report summarises the structured evaluation of your application for "
            f"{job_title}. It is written from the evidence reviewed and is intended to be "
            "useful whether or not the process continues."
        )
        process_note = (
            "Generated automatically from the evidence-based structured evaluation; "
            "protected personal attributes are not part of scoring."
        )
        correction_notice = (
            "If any information here is inaccurate, contact HR to request a correction."
        )

    return FeedbackReport(
        candidate_name=candidate_name,
        job_title=job_title,
        language=lang,  # type: ignore[arg-type]
        summary=summary,
        strengths=strengths,
        growth_areas=growth,
        process_note=process_note,
        correction_notice=correction_notice,
    )


def _strength_text(dimension: ScoreDimension, language: str) -> str:
    en, id_ = _DIMENSION_LABELS[dimension]
    if language == "id":
        return f"Terdapat bukti {id_} yang selaras dengan kebutuhan posisi."
    return f"Evidence of {en} aligned with the role requirements."


def _growth_text(dimension: ScoreDimension, language: str) -> str:
    en, id_ = _DIMENSION_LABELS[dimension]
    if language == "id":
        return (
            f"Penekanan diberikan pada {id_}; bukti yang lebih konkret (proyek, artefak, "
            "atau referensi) akan memperkuat lamaran berikutnya."
        )
    return (
        f"Weight was given to {en}; more concrete evidence (projects, artefacts, or "
        "references) would strengthen future applications."
    )


# --- scheduling -----------------------------------------------------------------


class SchedulingProposalRecord(StrictModel):
    """A stored proposal with its approval requirement and provenance."""

    id: UUID = Field(default_factory=uuid4)
    payload: SchedulingPayload
    requires_human_approval: bool
    needs_human_reconciliation: bool = False
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SchedulingService:
    """Interviewer availability registry and deterministic slot proposals.

    Database adapters override the ``_load_*``/``_iter_*``/``_persist_*``
    primitives.
    """

    def __init__(
        self,
        *,
        evaluations: EvaluationService,
        audit: AuditChain | None = None,
        applications: ApplicationStore | None = None,
    ) -> None:
        self._evaluations = evaluations
        self._availability: dict[UUID, list[TimeSlot]] = {}
        self._proposals: dict[UUID, SchedulingProposalRecord] = {}
        self._audit = audit or AuditChain()
        self._applications = applications

    # persistence primitives (overridden by database adapters)

    def _load_availability(self, interviewer_id: UUID) -> list[TimeSlot]:
        return list(self._availability.get(interviewer_id, []))

    def _persist_availability(
        self, interviewer_id: UUID, slots: list[TimeSlot], *, by: str
    ) -> None:
        self._availability[interviewer_id] = list(slots)

    def _load_proposal(self, proposal_id: UUID) -> SchedulingProposalRecord | None:
        return self._proposals.get(proposal_id)

    def _iter_proposals(self) -> Iterator[SchedulingProposalRecord]:
        return iter(self._proposals.values())

    def _persist_proposal(self, proposal: SchedulingProposalRecord) -> None:
        self._proposals[proposal.id] = proposal

    def set_availability(
        self, interviewer_id: UUID, *, slots: list[TimeSlot], by: str
    ) -> list[TimeSlot]:
        """Replace an interviewer's free slots (calendar provider feeds this later)."""
        ordered = sorted(slots, key=lambda slot: slot.start_utc)
        self._persist_availability(interviewer_id, ordered, by=by)
        self._audit.append(
            actor=DocumentService._actor(by),
            action="scheduling.availability_set",
            subject_type="interviewer",
            subject_id=str(interviewer_id),
            payload={"slot_count": len(ordered)},
        )
        return ordered

    def get_availability(self, interviewer_id: UUID) -> list[TimeSlot]:
        return self._load_availability(interviewer_id)

    def propose(
        self,
        *,
        candidate_id: UUID,
        job_id: UUID,
        interviewer_ids: list[UUID],
        created_by: str = "system",
        requested_channels: list[SchedulingChannel] | None = None,
        notes: str | None = None,
    ) -> SchedulingProposalRecord:
        """Build a proposal; auto-scheduling only when policy permits."""
        if not interviewer_ids:
            raise RecruitingError("at least one interviewer is required")
        record = self._evaluations.get_by_candidate(candidate_id)

        common = self._common_slots(interviewer_ids)
        availability_present = any(self._load_availability(iid) for iid in interviewer_ids)
        if not availability_present:
            raise RecruitingError("no interviewer availability recorded for this request")

        needs_reconciliation = not common
        if common:
            slots = sorted(common, key=lambda slot: slot.start_utc)[:MAX_PROPOSED_SLOTS]
        else:
            slots = self._union_slots(interviewer_ids)[: MAX_PROPOSED_SLOTS + 2]

        policy = evaluate_policy(
            s_tech=record.evaluation.s_tech,
            sigma=record.evaluation.sigma,
            flags=record.evaluation.flags,
            mutual_slots=len(common),
        )
        auto = policy.decision is PolicyDecision.AUTO_SCHEDULE
        channels = requested_channels or [SchedulingChannel.EMAIL]

        payload = SchedulingPayload(
            candidate_id=candidate_id,
            job_id=job_id,
            interviewer_ids=interviewer_ids,
            slots=slots,
            channel=channels[0],
            auto_scheduled=auto,
            policy=policy,
            notes=notes,
        )
        proposal = SchedulingProposalRecord(
            payload=payload,
            requires_human_approval=not auto,
            needs_human_reconciliation=needs_reconciliation,
            created_by=created_by,
        )
        self._persist_proposal(proposal)

        if auto and self._applications is not None:
            for application in self._applications.find_by_candidate(candidate_id):
                application.status = ApplicationStatus.SCHEDULED
                application.note("scheduling.proposal_auto_scheduled")
                self._applications.save(application)

        self._audit.append(
            actor=DocumentService._actor(created_by),
            action="scheduling.proposal_created",
            subject_type="scheduling_proposal",
            subject_id=str(proposal.id),
            payload={
                "candidate_id": str(candidate_id),
                "job_id": str(job_id),
                "auto_scheduled": auto,
                "decision": policy.decision.value,
                "mutual_slots": len(common),
                "proposed_slots": len(slots),
            },
        )
        return proposal

    def get(self, proposal_id: UUID) -> SchedulingProposalRecord:
        proposal = self._load_proposal(proposal_id)
        if proposal is None:
            raise RecruitingError(f"unknown scheduling proposal {proposal_id}")
        return proposal

    def list_all(self) -> list[SchedulingProposalRecord]:
        return sorted(self._iter_proposals(), key=lambda item: item.created_at)

    # internals

    def _common_slots(self, interviewer_ids: list[UUID]) -> list[TimeSlot]:
        lists = [self._load_availability(iid) for iid in interviewer_ids]
        if any(not slots for slots in lists):
            return []
        keys = {(slot.start_utc, slot.end_utc) for slot in lists[0]}
        for slots in lists[1:]:
            keys &= {(slot.start_utc, slot.end_utc) for slot in slots}
        return [slot for slot in lists[0] if (slot.start_utc, slot.end_utc) in keys]

    def _union_slots(self, interviewer_ids: list[UUID]) -> list[TimeSlot]:
        seen: set[tuple[datetime, datetime]] = set()
        union: list[TimeSlot] = []
        for interviewer_id in interviewer_ids:
            for slot in self._load_availability(interviewer_id):
                key = (slot.start_utc, slot.end_utc)
                if key in seen:
                    continue
                seen.add(key)
                union.append(slot)
        return sorted(union, key=lambda slot: slot.start_utc)


# --- container -------------------------------------------------------------------


@dataclass
class RecruitingServices:
    """All recruitment-side services sharing one audit chain."""

    audit: AuditChain = field(default_factory=AuditChain)
    applications: ApplicationStore | None = None

    documents: DocumentService = field(init=False)
    jobs: JobService = field(init=False)
    evaluations: EvaluationService = field(init=False)
    scheduling: SchedulingService = field(init=False)

    def __post_init__(self) -> None:
        self.documents = DocumentService(audit=self.audit)
        self.jobs = JobService(audit=self.audit)
        self.evaluations = EvaluationService(audit=self.audit, applications=self.applications)
        self.scheduling = SchedulingService(
            evaluations=self.evaluations, audit=self.audit, applications=self.applications
        )


__all__ = [
    "DOCUMENT_KINDS",
    "JOB_TRANSITIONS",
    "MAX_DOCUMENT_BYTES",
    "OVERRIDE_REVIEWER_ROLES",
    "DocumentService",
    "DocumentTooLargeError",
    "EvaluationRecord",
    "EvaluationService",
    "JobService",
    "OverrideOutcome",
    "RecruitingError",
    "RecruitingServices",
    "SchedulingProposalRecord",
    "SchedulingService",
    "StoredDocument",
    "synthesize_feedback",
]
