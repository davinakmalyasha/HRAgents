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
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from pydantic import EmailStr, Field

from hr_agents.identity import ActorRef
from hr_agents.models import (
    TERMINAL_PROPOSAL_STATUSES,
    ActorType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    AuditActor,
    AuditEntry,
    CandidateCommunication,
    Channel,
    CommunicationKind,
    CommunicationPreview,
    CommunicationStatus,
    FeedbackGrowthArea,
    FeedbackReport,
    FeedbackStrength,
    HitlOverride,
    JobSpecification,
    JobStatus,
    PolicyDecision,
    PolicyEvaluation,
    ProposalStatus,
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
from hr_agents.services.approvals import ApprovalError
from hr_agents.services.audit import AuditChain
from hr_agents.services.ingestion import ApplicationStatus, ApplicationStore
from hr_agents.services.offers import OfferService
from hr_agents.services.policy import evaluate_policy

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from hr_agents.services.approvals import ApprovalEngine

# --- shared constants ---------------------------------------------------------

DOCUMENT_KINDS = frozenset({"cv", "portfolio", "questionnaire", "linkedin_export", "other"})
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MiB

OVERRIDE_REVIEWER_ROLES: frozenset[ApproverRole] = frozenset(
    {
        ApproverRole.HR_ADMIN,
        ApproverRole.RECRUITER_LEAD,
        ApproverRole.ENGINEERING_LEAD,
    }
)
"""Who may sign off on a gated rejection.

These were three free-text strings -- ``engineering_lead``,
``recruiter_lead``, ``hr_partner``. Two are real ``ApproverRole`` members; the
third never existed in any table, including ``APPROVER_ROLE_HOLDERS``, so it
could be typed by anyone and meant nothing. Typed now, so an unrecognised role is
a 422 at the boundary rather than a string that matches no one.

The *reviewer identity* is no longer part of this decision at all: it comes from
the API key. What is left is which authority the sign-off is being made under.
"""

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
        actor: ActorRef,
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
            uploaded_by=actor.actor_id,
        )
        self._store_document(document)
        self._audit.append(
            actor=self._actor(actor),
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
    def _actor(actor: ActorRef | str) -> AuditActor:
        """Build the chain entry's actor, carrying provenance through to the record.

        An ``ActorRef`` arrives from the authenticated request; a bare string is
        still accepted for internal and agent callers, and is recorded as the
        weaker ``legacy_string`` claim rather than being silently upgraded.
        """
        return ActorRef.coerce(actor).audit_actor()


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
        actor: ActorRef,
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
            created_by=actor.actor_id,
        )
        self._persist_job(job)
        self._audit.append(
            actor=self._actor(actor),
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
        actor: ActorRef,
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
            actor=self._actor(actor),
            action="job.updated",
            subject_type="job",
            subject_id=str(updated.id),
            payload={"fields": sorted(name for name in updates if name != "updated_at")},
        )
        return updated

    def transition(self, job_id: UUID, *, target: JobStatus, actor: ActorRef) -> JobSpecification:
        job = self.get(job_id)
        if target not in JOB_TRANSITIONS[job.status]:
            raise RecruitingError(f"cannot move job from {job.status.value} to {target.value}")
        updated = job.model_copy(update={"status": target, "updated_at": utc_now()})
        self._persist_job(updated)
        self._audit.append(
            actor=self._actor(actor),
            action="job.status_changed",
            subject_type="job",
            subject_id=str(updated.id),
            payload={"from": job.status.value, "to": target.value},
        )
        return updated

    @staticmethod
    def _actor(actor: ActorRef | str) -> AuditActor:
        return DocumentService._actor(actor)


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
        self._by_candidate: dict[UUID, EvaluationRecord] = {}  # candidate id → record
        self._by_application: dict[UUID, EvaluationRecord] = {}  # application id → record
        self._overrides: dict[UUID, list[HitlOverride]] = {}  # evaluation id → overrides
        self._feedback: dict[UUID, FeedbackReport] = {}  # candidate id → stored report
        self._audit = audit or AuditChain()
        self._applications = applications

    # persistence primitives (overridden by database adapters)

    def _load_record(self, evaluation_id: UUID) -> EvaluationRecord | None:
        return self._records.get(evaluation_id)

    def _iter_records(self) -> Iterator[EvaluationRecord]:
        return iter(self._records.values())

    def _record_for_candidate(self, candidate_id: UUID) -> EvaluationRecord | None:
        return self._by_candidate.get(candidate_id)

    def _record_for_application(self, application_id: UUID) -> EvaluationRecord | None:
        return self._by_application.get(application_id)

    def _persist_record(self, record: EvaluationRecord) -> None:
        evaluation_id = record.evaluation.id
        # Registration refuses a duplicate, but drop any stale mapping first so
        # the secondary indexes cannot outlive the record they point at.
        for index in (self._by_candidate, self._by_application):
            for key, existing in list(index.items()):
                if existing.evaluation.id == evaluation_id:
                    del index[key]
        self._records[evaluation_id] = record
        self._by_candidate[record.candidate_id] = record
        self._by_application[record.application_id] = record

    def _load_overrides(self, evaluation_id: UUID) -> list[HitlOverride]:
        return list(self._overrides.get(evaluation_id, []))

    def _append_override(self, override: HitlOverride) -> None:
        self._overrides.setdefault(UUID(override.evaluation_id), []).append(override)

    def _load_feedback(self, candidate_id: UUID) -> FeedbackReport | None:
        return self._feedback.get(candidate_id)

    def _persist_feedback(
        self, candidate_id: UUID, report: FeedbackReport, *, actor: ActorRef
    ) -> None:
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
        """The evaluation for an application.

        Five call sites reach this, several of them from inside loops over
        candidates, so a scan of every evaluation was a cost paid per candidate.
        """
        record = self._record_for_application(application_id)
        if record is None:
            raise RecruitingError(f"no evaluation for application {application_id}")
        return record

    def get_by_candidate(self, candidate_id: UUID) -> EvaluationRecord:
        """The evaluation for a candidate.

        Same reason as ``get_by_application``: the rejection, offer and scheduling
        paths all start here, so a linear scan made every candidate interaction
        cost the size of the pipeline.
        """
        record = self._record_for_candidate(candidate_id)
        if record is None:
            raise RecruitingError(f"no evaluation for candidate {candidate_id}")
        return record

    # overrides

    def record_override(
        self,
        evaluation_id: UUID,
        *,
        actor: ActorRef,
        reviewer_role: ApproverRole,
        override_decision: PolicyDecision,
        reason_code: str,
        notes: str | None = None,
    ) -> OverrideOutcome:
        """Append a named human decision. Overrides are never edited or deleted.

        The reviewer is whoever authenticated. This used to take ``reviewer_id``
        from the request body, which meant one recruiter could reverse a gated
        rejection and sign the chain with a colleague's name -- or the chief
        executive's. The record named a person who was never asked and never
        authenticated, on the one endpoint whose entire purpose is a named-human
        sign-off.

        ``reviewer_role`` stays a claim, because a principal's role cannot supply
        it: ``RoleId`` has no lead roles, so deriving one would mean inventing
        the whole approval-authority model. Instead the claim is permitted-set
        checked and the authenticated role is written beside it, so a body that
        says "engineering_lead" from a recruiter principal is visible rather than
        silent.
        """
        record = self.get(evaluation_id)
        actor.require_human("record a human override", RecruitingError)
        if reviewer_role not in OVERRIDE_REVIEWER_ROLES:
            raise RecruitingError(
                f"role {reviewer_role.value!r} cannot override; expected one of "
                + ", ".join(sorted(role.value for role in OVERRIDE_REVIEWER_ROLES))
            )
        if not reason_code.strip():
            raise RecruitingError("an override requires a reason code")

        override = HitlOverride(
            evaluation_id=str(evaluation_id),
            reviewer_id=actor.actor_id,
            reviewer_role=reviewer_role.value,
            override_decision=override_decision,
            reason_code=reason_code,
            notes=notes,
        )
        self._append_override(override)

        if self._applications is not None:
            self._apply_override_status(record, override_decision)

        receipt = self._audit.append(
            actor=actor.audit_actor(),
            action="evaluation.override_recorded",
            subject_type="evaluation",
            subject_id=str(evaluation_id),
            payload={
                "reviewer_role": reviewer_role.value,
                "authenticated_role": actor.role,
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

    def save_feedback(self, candidate_id: UUID, report: FeedbackReport, *, actor: ActorRef) -> None:
        """Store an agent-authored report; it takes precedence over synthesis."""
        self._persist_feedback(candidate_id, report, actor=actor)
        self._audit.append(
            actor=DocumentService._actor(actor),
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


# --- candidate communications ---------------------------------------------------

REJECTION_DECISIONS = frozenset({PolicyDecision.HITL_SOFT_REJECTION, PolicyDecision.REJECT_AUTO})

_ACTIVE_COMMUNICATION_STATUSES = frozenset({CommunicationStatus.QUEUED, CommunicationStatus.SENT})

_REJECTION_SECTIONS: dict[str, tuple[str, str]] = {
    "en": ("What stood out", "Where to strengthen"),
    "id": ("Yang menonjol", "Yang bisa diperkuat"),
}

_REJECTION_SUBJECTS: dict[str, str] = {
    "en": "Your application for {job_title}",
    "id": "Lamaran Anda untuk {job_title}",
}


def compose_rejection_body(report: FeedbackReport) -> str:
    """Deterministic candidate message from the grounded feedback report.

    No scores, no protected attributes, and no internal notes appear in prose.
    """
    strengths_header, growth_header = _REJECTION_SECTIONS[report.language]
    lines = [report.summary, ""]
    if report.strengths:
        lines.append(f"{strengths_header}:")
        lines.extend(f"- {item.text}" for item in report.strengths)
        lines.append("")
    if report.growth_areas:
        lines.append(f"{growth_header}:")
        lines.extend(f"- {item.text}" for item in report.growth_areas)
        lines.append("")
    lines.append(report.correction_notice)
    return "\n".join(lines).strip()


def normalize_message_id(message_id: str) -> str:
    """Canonical form of an RFC 5322 message id for correlation, never for trust."""
    return message_id.strip().strip("<>").strip().casefold()


class CommunicationService:
    """Candidate communication outbox — queued behind named humans.

    The rejection body is composed deterministically from the same grounded
    feedback report the candidate can request; offers are human-authored. Both
    kinds require an approval by a named human and a recorded decision where
    one applies. Dispatch itself happens outside the decision path: a human
    records it with ``mark_sent``, or a configured transport records it with
    ``record_dispatch`` — in both cases only a message a human already queued
    is ever carried, and the evidence lands in the audit chain.

    Database adapters override the ``_load``/``_iter``/``_persist`` primitives.
    """

    def __init__(
        self,
        *,
        evaluations: EvaluationService,
        audit: AuditChain | None = None,
        applications: ApplicationStore | None = None,
    ) -> None:
        self._evaluations = evaluations
        self._items: dict[UUID, CandidateCommunication] = {}
        self._audit = audit or AuditChain()
        self._applications = applications

    # persistence primitives (overridden by database adapters)

    def _load(self, communication_id: UUID) -> CandidateCommunication | None:
        return self._items.get(communication_id)

    def _iter(self) -> Iterator[CandidateCommunication]:
        return iter(self._items.values())

    def _persist(self, item: CandidateCommunication) -> None:
        self._items[item.id] = item

    # queueing

    def _rejection_blockers(
        self,
        candidate_id: UUID,
        record: EvaluationRecord | None,
    ) -> list[str]:
        """Every reason this rejection could not be queued, in gate order."""
        blockers: list[str] = []
        if record is None:
            return ["no evaluation"]
        try:
            self._require_rejection_proof(record)
        except RecruitingError as exc:
            blockers.append(str(exc))
        try:
            self._require_no_active(candidate_id, CommunicationKind.REJECTION)
        except RecruitingError as exc:
            blockers.append(str(exc))
        return blockers

    def preview_rejection(
        self,
        candidate_id: UUID,
        *,
        actor: ActorRef,
        language: str = "en",
        to_email: EmailStr | None = None,
        to_phone: str | None = None,
        channel: Channel = Channel.EMAIL,
    ) -> CommunicationPreview:
        """Render the rejection a human is about to queue, and why it might not work.

        Read-only: no message is stored, no audit entry is written, and no
        approval is implied. ``can_queue`` is exactly the condition the queue
        endpoint will apply, because both read the same blockers. The actor
        still has to be a named human at queue time.
        """
        del actor  # the named-human gate belongs to queueing, not to a preview
        try:
            record: EvaluationRecord | None = self._evaluations.get_by_candidate(candidate_id)
        except RecruitingError:
            record = None
        blockers = self._rejection_blockers(candidate_id, record)
        normalized: Literal["en", "id"] = "id" if language == "id" else "en"
        if record is None or blockers:
            return CommunicationPreview(
                kind=CommunicationKind.REJECTION,
                can_queue=False,
                blockers=blockers or ["no evaluation"],
                candidate_id=candidate_id,
                language=normalized,
                recipient=to_email,
                recipient_phone=to_phone,
                channel=channel,
            )
        report = synthesize_feedback(
            record.evaluation,
            candidate_name=record.candidate_name,
            job_title=record.job_title,
            language=normalized,
        )
        return CommunicationPreview(
            kind=CommunicationKind.REJECTION,
            can_queue=True,
            candidate_id=candidate_id,
            application_id=record.application_id,
            evaluation_id=record.evaluation.id,
            language=report.language,
            subject=_REJECTION_SUBJECTS[report.language].format(job_title=record.job_title),
            body=compose_rejection_body(report),
            recipient=to_email,
            recipient_phone=to_phone,
            channel=channel,
        )

    def queue_rejection(
        self,
        candidate_id: UUID,
        *,
        actor: ActorRef,
        channel: Channel = Channel.EMAIL,
        language: str = "en",
        to_email: EmailStr | None = None,
        to_phone: str | None = None,
    ) -> CandidateCommunication:
        """Queue the rejection message; only for a documented rejection."""
        actor.require_human("a candidate communication", RecruitingError)
        record = self._evaluations.get_by_candidate(candidate_id)
        self._require_rejection_proof(record)
        self._require_no_active(candidate_id, CommunicationKind.REJECTION)
        report = synthesize_feedback(
            record.evaluation,
            candidate_name=record.candidate_name,
            job_title=record.job_title,
            language=language,
        )
        item = CandidateCommunication(
            candidate_id=candidate_id,
            application_id=record.application_id,
            evaluation_id=record.evaluation.id,
            kind=CommunicationKind.REJECTION,
            channel=channel,
            language=report.language,
            subject=_REJECTION_SUBJECTS[report.language].format(job_title=record.job_title),
            body=compose_rejection_body(report),
            approved_by=actor.actor_id,
            recipient=to_email,
            recipient_phone=to_phone,
        )
        return self._queue(item, actor=actor)

    def queue_offer(
        self,
        candidate_id: UUID,
        *,
        actor: ActorRef,
        body: str,
        subject: str | None = None,
        channel: Channel = Channel.EMAIL,
        language: str = "en",
        to_email: EmailStr | None = None,
        to_phone: str | None = None,
    ) -> CandidateCommunication:
        """Queue a human-authored offer; the named human is the gate."""
        actor.require_human("a candidate communication", RecruitingError)
        if not body.strip():
            raise RecruitingError("an offer message body is required")
        record = self._evaluations.get_by_candidate(candidate_id)
        self._require_no_active(candidate_id, CommunicationKind.OFFER)
        item = CandidateCommunication(
            candidate_id=candidate_id,
            application_id=record.application_id,
            evaluation_id=record.evaluation.id,
            kind=CommunicationKind.OFFER,
            channel=channel,
            language=language,  # type: ignore[arg-type]
            subject=subject,
            body=body,
            approved_by=actor.actor_id,
            recipient=to_email,
            recipient_phone=to_phone,
        )
        return self._queue(item, actor=actor)

    def mark_sent(self, communication_id: UUID, *, actor: ActorRef) -> CandidateCommunication:
        """Record human dispatch evidence for a queued message."""
        actor.require_human("a candidate communication", RecruitingError)
        item = self.get(communication_id)
        if item.status is not CommunicationStatus.QUEUED:
            raise RecruitingError(
                f"communication is {item.status.value}; only a queued message can be marked sent"
            )
        updated = item.model_copy(
            update={
                "status": CommunicationStatus.SENT,
                "sent_by": actor.actor_id,
                "sent_at": utc_now(),
            }
        )
        self._persist(updated)
        self._audit.append(
            actor=DocumentService._actor(actor),
            action="communication.sent",
            subject_type="candidate_communication",
            subject_id=str(updated.id),
            payload={
                "candidate_id": str(updated.candidate_id),
                "kind": updated.kind.value,
                "channel": updated.channel.value,
                "approved_by": updated.approved_by,
            },
        )
        return updated

    def record_dispatch(
        self,
        communication_id: UUID,
        *,
        provider: str,
        recipient: EmailStr,
        message_id: str | None = None,
        sent_at: datetime | None = None,
    ) -> CandidateCommunication:
        """Record transport dispatch evidence for a message a human queued.

        The transport carries the message; the named human who queued it is
        what the audit entry points back to, so the approval trail stays intact.
        """
        item = self._require_queued(communication_id)
        updated = item.model_copy(
            update={
                "status": CommunicationStatus.SENT,
                "sent_by": f"transport:{provider}"[:200],
                "sent_at": sent_at or utc_now(),
                "provider": provider,
                "provider_message_id": message_id,
                "recipient": recipient,
                "send_attempts": item.send_attempts + 1,
                "last_error": None,
            }
        )
        self._persist(updated)
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.SYSTEM, actor_id=f"transport:{provider}"),
            action="communication.dispatched",
            subject_type="candidate_communication",
            subject_id=str(updated.id),
            payload={
                "candidate_id": str(updated.candidate_id),
                "kind": updated.kind.value,
                "provider": provider,
                "approved_by": item.approved_by,
                "recipient": str(recipient),
                "message_id": message_id,
            },
        )
        return updated

    def record_dispatch_failure(
        self,
        communication_id: UUID,
        *,
        provider: str,
        error: str,
    ) -> CandidateCommunication:
        """Record a failed transport attempt; the message stays queued."""
        item = self._require_queued(communication_id)
        updated = item.model_copy(
            update={
                "send_attempts": item.send_attempts + 1,
                "last_error": error[:500],
            }
        )
        self._persist(updated)
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.SYSTEM, actor_id=f"transport:{provider}"),
            action="communication.dispatch_failed",
            subject_type="candidate_communication",
            subject_id=str(updated.id),
            payload={
                "candidate_id": str(updated.candidate_id),
                "kind": updated.kind.value,
                "provider": provider,
                "attempts": updated.send_attempts,
                "error": updated.last_error,
            },
        )
        return updated

    def list_queued(self, *, channel: Channel | None = None) -> list[CandidateCommunication]:
        """Queued messages, oldest first, optionally narrowed to one channel."""
        return sorted(
            self._find(status=CommunicationStatus.QUEUED, channel=channel),
            key=lambda item: item.created_at,
        )

    def prepare_manual_dispatch(
        self,
        communication_id: UUID,
        *,
        actor: ActorRef,
        provider: str,
        recipient_phone: str | None = None,
    ) -> CandidateCommunication:
        """Audit a manual-link dispatch (wa.me) without marking anything as sent.

        The system can only hand the recruiter a link; the send itself still
        happens in their own app and is recorded with ``mark_sent``.
        """
        actor.require_human("a candidate communication", RecruitingError)
        item = self._require_queued(communication_id)
        if item.channel is not Channel.WHATSAPP:
            raise RecruitingError(
                f"manual links apply to WhatsApp messages, not {item.channel.value}"
            )
        phone = (recipient_phone or item.recipient_phone or "").strip()
        if not phone:
            raise RecruitingError("a recipient phone number is required for a manual link")
        updated = item.model_copy(update={"recipient_phone": phone[:32]})
        self._persist(updated)
        self._audit.append(
            actor=DocumentService._actor(actor),
            action="communication.dispatch_link_issued",
            subject_type="candidate_communication",
            subject_id=str(updated.id),
            payload={
                "candidate_id": str(updated.candidate_id),
                "kind": updated.kind.value,
                "provider": provider,
                "phone": phone[:32],
                "approved_by": updated.approved_by,
            },
        )
        return updated

    def list_sent(self) -> list[CandidateCommunication]:
        """Dispatched messages, oldest first (for SLA checks and reporting)."""
        return sorted(
            self._find(status=CommunicationStatus.SENT),
            key=lambda item: item.created_at,
        )

    def find_by_provider_message_id(self, message_id: str) -> CandidateCommunication | None:
        """Locate a dispatched message by its provider message id (for reply threading)."""
        target = normalize_message_id(message_id)
        for item in self._find():
            if not item.provider_message_id:
                continue
            if normalize_message_id(item.provider_message_id) == target:
                return item
        return None

    def get(self, communication_id: UUID) -> CandidateCommunication:
        item = self._load(communication_id)
        if item is None:
            raise RecruitingError(f"unknown communication {communication_id}")
        return item

    def _find(
        self,
        *,
        candidate_id: UUID | None = None,
        status: CommunicationStatus | None = None,
        channel: Channel | None = None,
        provider_message_id: str | None = None,
    ) -> list[CandidateCommunication]:
        """Filtered read. Database adapters push these predicates into SQL.

        Keeping every filter here means the in-memory store and the Postgres
        adapter answer the same questions, and the adapter never degrades into
        loading the whole table to filter it in Python.
        """
        target = normalize_message_id(provider_message_id) if provider_message_id else None
        matches: list[CandidateCommunication] = []
        for item in self._iter():
            if candidate_id is not None and item.candidate_id != candidate_id:
                continue
            if status is not None and item.status is not status:
                continue
            if channel is not None and item.channel is not channel:
                continue
            if target is not None and (
                not item.provider_message_id
                or normalize_message_id(item.provider_message_id) != target
            ):
                continue
            matches.append(item)
        return matches

    def list_for(self, candidate_id: UUID) -> list[CandidateCommunication]:
        return sorted(
            self._find(candidate_id=candidate_id),
            key=lambda item: item.created_at,
        )

    # internals

    def _queue(self, item: CandidateCommunication, *, actor: ActorRef) -> CandidateCommunication:
        self._persist(item)
        self._audit.append(
            actor=DocumentService._actor(actor),
            action="communication.queued",
            subject_type="candidate_communication",
            subject_id=str(item.id),
            payload={
                "candidate_id": str(item.candidate_id),
                "kind": item.kind.value,
                "channel": item.channel.value,
                "language": item.language,
                "subject_present": item.subject is not None,
            },
        )
        return item

    def _require_no_active(self, candidate_id: UUID, kind: CommunicationKind) -> None:
        for item in self._iter():
            if (
                item.candidate_id == candidate_id
                and item.kind is kind
                and item.status in _ACTIVE_COMMUNICATION_STATUSES
            ):
                raise RecruitingError(
                    f"an active {kind.value} message already exists for this candidate"
                )

    def _require_rejection_proof(self, record: EvaluationRecord) -> None:
        if record.policy.decision is PolicyDecision.REJECT_AUTO:
            return
        overrides = self._evaluations.list_overrides(record.evaluation.id)
        if overrides:
            latest = max(overrides, key=lambda item: item.decided_at)
            if latest.override_decision in REJECTION_DECISIONS:
                return
        raise RecruitingError(
            "rejection communication requires a recorded rejection decision "
            "(a human override or a documented automatic rejection)"
        )

    def _require_queued(self, communication_id: UUID) -> CandidateCommunication:
        item = self.get(communication_id)
        if item.status is not CommunicationStatus.QUEUED:
            raise RecruitingError(
                f"communication is {item.status.value}; only a queued message can be dispatched"
            )
        return item


# --- scheduling -----------------------------------------------------------------


class SchedulingProposalRecord(StrictModel):
    """A stored proposal with its approval requirement and provenance."""

    id: UUID = Field(default_factory=uuid4)
    payload: SchedulingPayload
    requires_human_approval: bool
    needs_human_reconciliation: bool = False
    status: ProposalStatus = ProposalStatus.PROPOSED
    supersedes_id: UUID | None = None
    decided_by: str | None = Field(default=None, max_length=200)
    decided_at: datetime | None = None
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SchedulingService:
    """Interviewer availability registry and deterministic slot proposals.

    Proposals that policy cannot auto-schedule create a pending
    ``ApprovalSubject.SCHEDULING`` request through the shared approval engine,
    so confirmations surface in the attention queues; ``decide`` is the single
    writer that confirms, cancels, or supersedes a proposal. Database adapters
    override the ``_load_*``/``_iter_*``/``_persist_*`` primitives.
    """

    def __init__(
        self,
        *,
        evaluations: EvaluationService,
        audit: AuditChain | None = None,
        applications: ApplicationStore | None = None,
        approvals: ApprovalEngine | None = None,
    ) -> None:
        self._evaluations = evaluations
        self._availability: dict[UUID, list[TimeSlot]] = {}
        self._proposals: dict[UUID, SchedulingProposalRecord] = {}
        self._audit = audit or AuditChain()
        self._applications = applications
        self._approvals = approvals

    # persistence primitives (overridden by database adapters)

    def _load_availability(self, interviewer_id: UUID) -> list[TimeSlot]:
        return list(self._availability.get(interviewer_id, []))

    def _persist_availability(
        self, interviewer_id: UUID, slots: list[TimeSlot], *, actor: ActorRef
    ) -> None:
        self._availability[interviewer_id] = list(slots)

    def _load_proposal(self, proposal_id: UUID) -> SchedulingProposalRecord | None:
        return self._proposals.get(proposal_id)

    def _iter_proposals(self) -> Iterator[SchedulingProposalRecord]:
        return iter(self._proposals.values())

    def _persist_proposal(self, proposal: SchedulingProposalRecord) -> None:
        self._proposals[proposal.id] = proposal

    def set_availability(
        self, interviewer_id: UUID, *, slots: list[TimeSlot], actor: ActorRef
    ) -> list[TimeSlot]:
        """Replace an interviewer's free slots (calendar provider feeds this later)."""
        ordered = sorted(slots, key=lambda slot: slot.start_utc)
        self._persist_availability(interviewer_id, ordered, actor=actor)
        self._audit.append(
            actor=DocumentService._actor(actor),
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
        actor: ActorRef | None = None,
        requested_channels: list[SchedulingChannel] | None = None,
        notes: str | None = None,
    ) -> SchedulingProposalRecord:
        """Build a proposal; auto-scheduling only when policy permits."""
        if not interviewer_ids:
            raise RecruitingError("at least one interviewer is required")
        # An automatic policy pass has no person behind it. Record that honestly
        # rather than attributing the proposal to a system that then reads like
        # a human on the chain.
        actor = actor or ActorRef.system("scheduler")
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
            status=ProposalStatus.AUTO_SCHEDULED if auto else ProposalStatus.PENDING_APPROVAL,
            created_by=actor.actor_id,
        )
        self._persist_proposal(proposal)

        if not auto and self._approvals is not None:
            self._approvals.create(
                subject=ApprovalSubject.SCHEDULING,
                subject_id=str(proposal.id),
                title=f"Confirm interview slots for candidate {str(candidate_id)[:8]}",
                summary=(
                    f"{len(slots)} slot(s) proposed; policy decision "
                    f"{policy.decision.value} requires a named human confirmation."
                ),
                assignee_role=ApproverRole.RECRUITER_LEAD,
                actor=actor,
                payload={
                    "proposal_id": str(proposal.id),
                    "candidate_id": str(candidate_id),
                    "job_id": str(job_id),
                    "proposed_slots": len(slots),
                    "needs_human_reconciliation": needs_reconciliation,
                },
            )

        if auto and self._applications is not None:
            for application in self._applications.find_by_candidate(candidate_id):
                application.status = ApplicationStatus.SCHEDULED
                application.note("scheduling.proposal_auto_scheduled")
                self._applications.save(application)

        self._audit.append(
            actor=DocumentService._actor(actor),
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

    # decisions

    def decide(
        self,
        proposal_id: UUID,
        *,
        decision: str,
        actor: ActorRef,
        reason: str = "",
    ) -> tuple[SchedulingProposalRecord, SchedulingProposalRecord | None]:
        """Confirm, cancel, or supersede a proposal as a named human.

        Returns ``(proposal, replacement)``; ``replacement`` is the new
        superseding proposal only for ``reschedule``. Confirmations decide the
        linked scheduling approval (when one exists) through the shared engine.
        """
        if decision not in {"confirm", "cancel", "reschedule"}:
            raise RecruitingError(f"unknown decision {decision!r}")
        # The agent check below used to be a hand-rolled `startswith("agent:")`
        # test, which was why it accepted the empty string. One shared gate now.
        actor.require_human("a scheduling decision", RecruitingError)

        proposal = self.get(proposal_id)
        if proposal.status in TERMINAL_PROPOSAL_STATUSES:
            raise RecruitingError(
                f"proposal is {proposal.status.value}; it cannot be decided again"
            )
        if decision == "confirm" and proposal.status is ProposalStatus.CONFIRMED:
            return proposal, None

        if decision in {"cancel", "reschedule"} and not reason.strip():
            raise RecruitingError("a reason is required to cancel or reschedule a proposal")

        approval = self._find_linked_approval(proposal.id)

        if decision == "confirm":
            self._decide_linked_approval(approval, actor=actor, reason=reason)
            updated = self._mark(proposal, ProposalStatus.CONFIRMED, actor=actor)
            self._sync_application_scheduled(proposal)
            self._audit.append(
                actor=DocumentService._actor(actor),
                action="scheduling.proposal_confirmed",
                subject_type="scheduling_proposal",
                subject_id=str(updated.id),
                payload={
                    "candidate_id": str(proposal.payload.candidate_id),
                    "job_id": str(proposal.payload.job_id),
                    "approval": approval.status.value if approval is not None else "none",
                    "reason_present": bool(reason.strip()),
                },
            )
            return updated, None

        if decision == "cancel":
            self._withdraw_linked_approval(approval, actor=actor, reason=reason)
            updated = self._mark(proposal, ProposalStatus.CANCELLED, actor=actor)
            self._audit.append(
                actor=DocumentService._actor(actor),
                action="scheduling.proposal_cancelled",
                subject_type="scheduling_proposal",
                subject_id=str(updated.id),
                payload={
                    "candidate_id": str(proposal.payload.candidate_id),
                    "reason": reason.strip(),
                },
            )
            return updated, None

        # reschedule: build the replacement first so a failure leaves the old intact
        replacement = self.propose(
            candidate_id=proposal.payload.candidate_id,
            job_id=proposal.payload.job_id,
            interviewer_ids=proposal.payload.interviewer_ids,
            actor=actor,
            requested_channels=[proposal.payload.channel],
            notes=proposal.payload.notes,
        )
        self._withdraw_linked_approval(approval, actor=actor, reason=reason)
        superseded = self._mark(proposal, ProposalStatus.SUPERSEDED, actor=actor)
        replacement = replacement.model_copy(update={"supersedes_id": proposal.id})
        self._persist_proposal(replacement)
        self._audit.append(
            actor=DocumentService._actor(actor),
            action="scheduling.proposal_superseded",
            subject_type="scheduling_proposal",
            subject_id=str(proposal.id),
            payload={
                "candidate_id": str(proposal.payload.candidate_id),
                "superseded_by": str(replacement.id),
                "reason": reason.strip(),
            },
        )
        return superseded, replacement

    # internals

    def _mark(
        self, proposal: SchedulingProposalRecord, status: ProposalStatus, *, actor: ActorRef
    ) -> SchedulingProposalRecord:
        updated = proposal.model_copy(
            update={
                "status": status,
                "decided_by": actor.actor_id,
                "decided_at": datetime.now(UTC),
            }
        )
        self._persist_proposal(updated)
        return updated

    def _find_linked_approval(self, proposal_id: UUID) -> ApprovalRequest | None:
        if self._approvals is None:
            return None
        return self._approvals.find_by_subject(ApprovalSubject.SCHEDULING, str(proposal_id))

    def _decide_linked_approval(
        self, approval: ApprovalRequest | None, *, actor: ActorRef, reason: str
    ) -> None:
        """Approve the pending scheduling request, or refuse a rejected one."""
        if approval is None or self._approvals is None:
            return
        if approval.status is ApprovalStatus.REJECTED:
            raise RecruitingError(
                "the linked scheduling approval was rejected; create a new proposal instead"
            )
        if not approval.active:
            return
        try:
            self._approvals.decide(
                approval.id,
                actor=actor,
                approve=True,
                reason=reason.strip() or "interview slots confirmed",
            )
        except ApprovalError as exc:
            raise RecruitingError(str(exc)) from exc

    def _withdraw_linked_approval(
        self, approval: ApprovalRequest | None, *, actor: ActorRef, reason: str
    ) -> None:
        if approval is None or self._approvals is None or not approval.active:
            return
        try:
            self._approvals.withdraw(approval.id, actor=actor, reason=reason.strip() or None)
        except ApprovalError as exc:
            raise RecruitingError(str(exc)) from exc

    def _sync_application_scheduled(self, proposal: SchedulingProposalRecord) -> None:
        """Move the candidate's live application to interview on confirmation."""
        if self._applications is None:
            return
        movable = {
            ApplicationStatus.EVALUATED,
            ApplicationStatus.GATED,
            ApplicationStatus.SCHEDULED,
        }
        for application in self._applications.find_by_candidate(proposal.payload.candidate_id):
            if application.status in movable:
                application.status = ApplicationStatus.SCHEDULED
                application.note("scheduling.proposal_confirmed")
                self._applications.save(application)

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
    """All recruitment-side services sharing one audit chain.

    Pass ``session_factory`` to build Postgres-backed services (ADR 0005);
    omit it for the in-memory contract used by tests and zero-config dev.
    """

    audit: AuditChain = field(default_factory=AuditChain)
    applications: ApplicationStore | None = None
    session_factory: sessionmaker[Session] | None = None
    approvals: ApprovalEngine | None = None

    documents: DocumentService = field(init=False)
    jobs: JobService = field(init=False)
    evaluations: EvaluationService = field(init=False)
    scheduling: SchedulingService = field(init=False)
    communications: CommunicationService = field(init=False)
    offers: OfferService = field(init=False)

    def __post_init__(self) -> None:
        if self.session_factory is None:
            self.documents = DocumentService(audit=self.audit)
            self.jobs = JobService(audit=self.audit)
            self.evaluations = EvaluationService(audit=self.audit, applications=self.applications)
            self.scheduling = SchedulingService(
                evaluations=self.evaluations,
                audit=self.audit,
                applications=self.applications,
                approvals=self.approvals,
            )
            self.communications = CommunicationService(
                evaluations=self.evaluations, audit=self.audit, applications=self.applications
            )
            self.offers = OfferService(
                evaluations=self.evaluations,
                communications=self.communications,
                audit=self.audit,
                approvals=self.approvals,
                applications=self.applications,
            )
            return

        from hr_agents.db.offers import DbOfferService
        from hr_agents.db.recruiting import (
            DbCommunicationService,
            DbDocumentService,
            DbEvaluationService,
            DbJobService,
            DbSchedulingService,
        )

        self.documents = DbDocumentService(session_factory=self.session_factory, audit=self.audit)
        self.jobs = DbJobService(session_factory=self.session_factory, audit=self.audit)
        self.evaluations = DbEvaluationService(
            session_factory=self.session_factory, audit=self.audit, applications=self.applications
        )
        self.scheduling = DbSchedulingService(
            evaluations=self.evaluations,
            session_factory=self.session_factory,
            audit=self.audit,
            applications=self.applications,
            approvals=self.approvals,
        )
        self.communications = DbCommunicationService(
            evaluations=self.evaluations,
            session_factory=self.session_factory,
            audit=self.audit,
            applications=self.applications,
        )
        self.offers = DbOfferService(
            evaluations=self.evaluations,
            communications=self.communications,
            session_factory=self.session_factory,
            audit=self.audit,
            approvals=self.approvals,
            applications=self.applications,
        )


__all__ = [
    "DOCUMENT_KINDS",
    "JOB_TRANSITIONS",
    "MAX_DOCUMENT_BYTES",
    "OVERRIDE_REVIEWER_ROLES",
    "REJECTION_DECISIONS",
    "CommunicationService",
    "DocumentService",
    "DocumentTooLargeError",
    "EvaluationRecord",
    "EvaluationService",
    "JobService",
    "OverrideOutcome",
    "ProposalStatus",
    "RecruitingError",
    "RecruitingServices",
    "SchedulingProposalRecord",
    "SchedulingService",
    "StoredDocument",
    "compose_rejection_body",
    "synthesize_feedback",
]
