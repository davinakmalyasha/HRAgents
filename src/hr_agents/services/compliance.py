"""Compliance service — consent registry, retention, erasure, and breach workflow.

Cross-cutting rules enforced here (not just documented):

- **Purge never touches legal holds.** Scan and execute both skip held records
  and report them; held records cannot be marked purged at all.
- **Erasure is a human workflow.** Identity verification, the approval decision
  (via the shared approval engine, Data Protection role), and execution each
  require a named human actor; agents may only open the request.
- **Retention windows come from operator policies.** No statutory number is
  hardcoded; a record whose entity has no active policy is reported as
  uncovered instead of guessed at.
- **Every mutation is audited** on the shared hash chain, and the chain can be
  verified end to end through this service.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from hr_agents.models import (
    ActorType,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    AuditActor,
    AuditVerificationReport,
    BreachChecklistTemplate,
    BreachImpact,
    BreachIncident,
    BreachNotification,
    BreachStatus,
    BreachStepState,
    BreachTemplateStep,
    ConsentGrant,
    DispositionAction,
    ErasureDisposition,
    ErasureRequest,
    ErasureStatus,
    LawfulBasis,
    NotificationRecipient,
    OverdueBreachStep,
    PurgeAction,
    PurgeOutcome,
    PurgeReport,
    RecordEntity,
    RetentionDue,
    RetentionPolicy,
    RetentionRecord,
    RetentionScanReport,
    SubjectKind,
    Urgency,
    utc_now,
)
from hr_agents.services.approvals import AGENT_ACTOR_PREFIX, ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import ComplianceStore

PurgeHandler = Callable[[RetentionRecord, PurgeAction], str]
"""Store-specific purge callback. Returns a human-readable detail string."""


class ComplianceError(RuntimeError):
    """Raised for invalid compliance operations."""


def default_breach_template() -> BreachChecklistTemplate:
    """Starter checklist — operator-editable, deliberately not legal advice.

    Offsets are hours after discovery. Titles use "if required" because whether
    a notification is mandatory depends on jurisdiction and facts; the engine
    never asserts a statutory deadline.
    """
    return BreachChecklistTemplate(
        name="default_incident_checklist",
        description=(
            "Starter breach-response checklist. Edit offsets and wording to match "
            "your jurisdiction and legal counsel. Not legal advice."
        ),
        steps=[
            BreachTemplateStep(
                key="contain",
                title="Contain the incident and preserve evidence",
                offset_hours=4,
            ),
            BreachTemplateStep(
                key="assess",
                title="Assess scope, affected data subjects, and risk",
                offset_hours=24,
            ),
            BreachTemplateStep(
                key="authority_notice",
                title="Prepare and send authority notification (if required)",
                offset_hours=48,
            ),
            BreachTemplateStep(
                key="subject_notice",
                title="Prepare and send data-subject communication (if required)",
                offset_hours=72,
            ),
            BreachTemplateStep(
                key="remediate",
                title="Remediate root cause and record lessons learned",
                offset_hours=168,
                required=False,
            ),
        ],
    )


def add_months(moment: datetime, months: int) -> datetime:
    """Add calendar months to a datetime, clamping the day to month length."""
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


class ComplianceService:
    """Consent registry, retention ledger, erasure workflow, breach checklists."""

    def __init__(
        self,
        store: ComplianceStore | None = None,
        *,
        approvals: ApprovalEngine,
        audit: AuditChain | None = None,
    ) -> None:
        self._store = store or ComplianceStore()
        self._approvals = approvals
        self._audit = audit or AuditChain()
        self._purge_handlers: dict[RecordEntity, PurgeHandler] = {}

    # --- consent registry ------------------------------------------------

    def record_consent(
        self,
        *,
        subject_kind: SubjectKind,
        subject_id: str,
        purpose: str,
        captured_by: str,
        granted: bool = True,
        lawful_basis: LawfulBasis = LawfulBasis.CONSENT,
        capture_method: str = "manual",
        policy_version: str = "1.0",
        expires_at: datetime | None = None,
        note: str | None = None,
    ) -> ConsentGrant:
        """Record consent (or an explicit refusal) as registry evidence.

        Agents may record evidence captured elsewhere (web form, email); the
        actor is preserved on the record and the audit chain.
        """
        record = ConsentGrant(
            subject_kind=subject_kind,
            subject_id=subject_id,
            purpose=purpose,
            granted=granted,
            lawful_basis=lawful_basis,
            capture_method=capture_method,
            policy_version=policy_version,
            expires_at=expires_at,
            captured_by=captured_by,
            note=note,
        )
        self._store.add_consent(record)
        self._record(
            action="compliance.consent_recorded",
            subject_type="consent",
            subject_id=str(record.id),
            actor_id=captured_by,
            payload={
                "subject_kind": subject_kind.value,
                "subject_id": subject_id,
                "purpose": purpose,
                "granted": granted,
                "lawful_basis": lawful_basis.value,
            },
        )
        return record

    def revoke_consent(self, consent_id: UUID, *, by: str, reason: str) -> ConsentGrant:
        """Revoke a consent grant. Humans only; a reason is mandatory."""
        self._require_human(by, "revoke consent")
        if not reason.strip():
            raise ComplianceError("revoking consent requires a reason")
        record = self.get_consent(consent_id)
        if not record.granted:
            raise ComplianceError("cannot revoke a record that was never granted")
        if record.revoked_at is not None:
            raise ComplianceError(f"consent {consent_id} is already revoked")
        updated = record.model_copy(update={"revoked_at": utc_now(), "revoked_reason": reason})
        self._store.save_consent(updated)
        self._record(
            action="compliance.consent_revoked",
            subject_type="consent",
            subject_id=str(updated.id),
            actor_id=by,
            payload={"reason": reason, "subject_id": record.subject_id},
        )
        return updated

    def get_consent(self, consent_id: UUID) -> ConsentGrant:
        record = self._store.get_consent(consent_id)
        if record is None:
            raise ComplianceError(f"unknown consent record {consent_id}")
        return record

    def list_consents(
        self, *, subject_kind: SubjectKind | None = None, subject_id: str | None = None
    ) -> list[ConsentGrant]:
        records = self._store.list_consents()
        if subject_kind is not None:
            records = [item for item in records if item.subject_kind is subject_kind]
        if subject_id is not None:
            records = [item for item in records if item.subject_id == subject_id]
        return records

    def has_active_consent(self, subject_kind: SubjectKind, subject_id: str, purpose: str) -> bool:
        """Purpose-scoped consent check — the pipeline's halt condition."""
        return any(
            item.active
            for item in self.list_consents(subject_kind=subject_kind, subject_id=subject_id)
            if item.purpose == purpose
        )

    # --- retention --------------------------------------------------------

    def set_policy(
        self,
        *,
        entity: RecordEntity,
        name: str,
        retention_months: int,
        updated_by: str,
        expiry_action: PurgeAction = PurgeAction.ANONYMIZE,
        jurisdiction: str = "ID",
        active: bool = True,
        note: str | None = None,
    ) -> RetentionPolicy:
        """Create or update the retention policy for one entity kind."""
        self._require_human(updated_by, "set retention policy")
        existing = self._store.get_policy(entity)
        policy = RetentionPolicy(
            entity=entity,
            name=name,
            retention_months=retention_months,
            expiry_action=expiry_action,
            jurisdiction=jurisdiction,
            active=active,
            updated_by=updated_by,
            note=note,
        )
        if existing is not None:
            policy = policy.model_copy(update={"id": existing.id})
        self._store.save_policy(policy)
        self._record(
            action="compliance.retention_policy_set",
            subject_type="retention_policy",
            subject_id=str(policy.id),
            actor_id=updated_by,
            payload={
                "entity": entity.value,
                "retention_months": retention_months,
                "expiry_action": expiry_action.value,
                "active": active,
            },
        )
        return policy

    def get_policy(self, entity: RecordEntity) -> RetentionPolicy:
        policy = self._store.get_policy(entity)
        if policy is None:
            raise ComplianceError(f"no retention policy configured for {entity.value}")
        return policy

    def list_policies(self) -> list[RetentionPolicy]:
        return self._store.list_policies()

    def track_record(
        self,
        *,
        entity: RecordEntity,
        subject_kind: SubjectKind,
        subject_id: str,
        created_by: str,
        label: str = "",
        anchor_at: datetime | None = None,
        retention_months_override: int | None = None,
    ) -> RetentionRecord:
        """Register a record with the retention ledger."""
        record = RetentionRecord(
            entity=entity,
            subject_kind=subject_kind,
            subject_id=subject_id,
            label=label,
            anchor_at=anchor_at or utc_now(),
            retention_months_override=retention_months_override,
        )
        self._store.add_record(record)
        self._record(
            action="compliance.record_tracked",
            subject_type="retention_record",
            subject_id=str(record.id),
            actor_id=created_by,
            payload={"entity": entity.value, "subject_id": subject_id},
        )
        return record

    def get_record(self, record_id: UUID) -> RetentionRecord:
        record = self._store.get_record(record_id)
        if record is None:
            raise ComplianceError(f"unknown retention record {record_id}")
        return record

    def list_records(
        self,
        *,
        subject_kind: SubjectKind | None = None,
        subject_id: str | None = None,
        entity: RecordEntity | None = None,
        include_purged: bool = False,
    ) -> list[RetentionRecord]:
        records = self._store.list_records()
        if subject_kind is not None:
            records = [item for item in records if item.subject_kind is subject_kind]
        if subject_id is not None:
            records = [item for item in records if item.subject_id == subject_id]
        if entity is not None:
            records = [item for item in records if item.entity is entity]
        if not include_purged:
            records = [item for item in records if not item.purged]
        return records

    def set_legal_hold(
        self, record_id: UUID, *, held: bool, by: str, reason: str
    ) -> RetentionRecord:
        """Place or lift a legal hold. Humans only; reason mandatory both ways."""
        self._require_human(by, "set legal hold")
        if not reason.strip():
            raise ComplianceError("legal hold changes require a reason")
        record = self.get_record(record_id)
        if record.purged:
            raise ComplianceError("cannot change hold on a purged record")
        if held and record.legal_hold:
            raise ComplianceError("record is already under legal hold")
        if not held and not record.legal_hold:
            raise ComplianceError("record is not under legal hold")
        updated = record.model_copy(
            update={
                "legal_hold": held,
                "legal_hold_reason": reason if held else None,
                "held_by": by if held else None,
                "held_at": utc_now() if held else None,
            }
        )
        self._store.save_record(updated)
        self._record(
            action="compliance.legal_hold_set" if held else "compliance.legal_hold_lifted",
            subject_type="retention_record",
            subject_id=str(updated.id),
            actor_id=by,
            payload={"reason": reason},
        )
        return updated

    def scan(self, *, as_of: datetime | None = None) -> RetentionScanReport:
        """Deterministic expiry scan — read-only, safe to run any time."""
        moment = as_of or utc_now()
        policies = {policy.entity: policy for policy in self._store.list_policies()}
        due: list[RetentionDue] = []
        held: list[RetentionRecord] = []
        uncovered: list[RetentionRecord] = []
        tracked = 0
        purged = 0

        for record in self._store.list_records():
            if record.purged:
                purged += 1
                continue
            tracked += 1
            policy = policies.get(record.entity)
            if policy is None or not policy.active:
                uncovered.append(record)
                continue
            months = record.retention_months_override or policy.retention_months
            expires_at = add_months(record.anchor_at, months)
            if expires_at > moment:
                continue
            if record.legal_hold:
                held.append(record)
            else:
                due.append(
                    RetentionDue(record=record, expires_at=expires_at, action=policy.expiry_action)
                )

        due.sort(key=lambda item: item.expires_at)
        return RetentionScanReport(
            as_of=moment,
            due=due,
            held=held,
            uncovered=uncovered,
            tracked_count=tracked,
            purged_count=purged,
        )

    def register_purge_handler(self, entity: RecordEntity, handler: PurgeHandler) -> None:
        """Attach the store-specific delete/anonymize implementation.

        Until a handler is registered the ledger still records the disposition,
        but the detail notes that no store was mutated.
        """
        self._purge_handlers[entity] = handler

    def execute_purge(
        self, *, by: str, as_of: datetime | None = None, dry_run: bool = False
    ) -> PurgeReport:
        """Purge every expired, unheld record per its policy.

        ``by`` may be a named human or ``system`` (scheduled job); agents are
        refused. A dry run reports what would happen without mutating anything.
        """
        self._require_automatic_actor(by, "execute retention purge")
        moment = as_of or utc_now()
        report = self.scan(as_of=moment)

        outcomes: list[PurgeOutcome] = []
        for item in report.due:
            if dry_run:
                detail = "dry run; no store mutation performed"
            else:
                detail = self._apply_purge(item.record, item.action, by)
                updated = item.record.model_copy(
                    update={
                        "purged_at": utc_now(),
                        "purge_action": item.action,
                        "purge_detail": detail,
                    }
                )
                self._store.save_record(updated)
                self._record(
                    action="compliance.record_purged",
                    subject_type="retention_record",
                    subject_id=str(updated.id),
                    actor_id=by,
                    payload={
                        "entity": updated.entity.value,
                        "subject_id": updated.subject_id,
                        "action": item.action.value,
                        "detail": detail,
                        "source": "retention_job",
                    },
                )
            outcomes.append(
                PurgeOutcome(
                    record_id=item.record.id,
                    entity=item.record.entity,
                    subject_kind=item.record.subject_kind,
                    subject_id=item.record.subject_id,
                    action=item.action,
                    detail=detail,
                )
            )

        if not dry_run and outcomes:
            self._record(
                action="compliance.purge_executed",
                subject_type="retention_ledger",
                subject_id="all",
                actor_id=by,
                payload={"purged": len(outcomes), "held": len(report.held)},
            )

        return PurgeReport(
            executed_at=moment,
            dry_run=dry_run,
            by=by,
            purged=outcomes,
            held=[record.id for record in report.held],
            uncovered=[record.id for record in report.uncovered],
        )

    # --- erasure workflow --------------------------------------------------

    def create_erasure_request(
        self,
        *,
        subject_kind: SubjectKind,
        subject_id: str,
        reason: str,
        requested_by: str,
        channel: str = "manual",
    ) -> ErasureRequest:
        """Open an erasure request. Agents may request; they cannot decide or execute."""
        request = ErasureRequest(
            subject_kind=subject_kind,
            subject_id=subject_id,
            reason=reason,
            requested_by=requested_by,
            channel=channel,
        )
        self._store.add_erasure(request)
        self._record(
            action="compliance.erasure_requested",
            subject_type="erasure_request",
            subject_id=str(request.id),
            actor_id=requested_by,
            payload={"subject_kind": subject_kind.value, "subject_id": subject_id},
        )
        return request

    def get_erasure(self, request_id: UUID) -> ErasureRequest:
        request = self._store.get_erasure(request_id)
        if request is None:
            raise ComplianceError(f"unknown erasure request {request_id}")
        return request

    def list_erasures(self) -> list[ErasureRequest]:
        return self._store.list_erasures()

    def verify_identity(self, request_id: UUID, *, by: str, method: str) -> ErasureRequest:
        """Record that a human verified the requester's identity."""
        self._require_human(by, "verify erasure identity")
        request = self.get_erasure(request_id)
        if request.status is not ErasureStatus.RECEIVED:
            raise ComplianceError(f"request is {request.status.value}; cannot verify identity")
        if not method.strip():
            raise ComplianceError("identity verification requires a method")
        updated = request.model_copy(
            update={
                "identity_verified_by": by,
                "identity_verified_at": utc_now(),
                "identity_method": method,
                "updated_at": utc_now(),
            }
        )
        self._store.save_erasure(updated)
        self._record(
            action="compliance.erasure_identity_verified",
            subject_type="erasure_request",
            subject_id=str(updated.id),
            actor_id=by,
            payload={"method": method},
        )
        return updated

    def submit_for_decision(self, request_id: UUID, *, by: str) -> ErasureRequest:
        """Route a verified request to the Data Protection approver."""
        request = self.get_erasure(request_id)
        if request.status is not ErasureStatus.RECEIVED:
            raise ComplianceError(f"request is {request.status.value}; cannot submit")
        if not request.identity_verified:
            raise ComplianceError("identity must be verified by a human before submission")
        approval = self._approvals.create(
            subject=ApprovalSubject.ERASURE_REQUEST,
            subject_id=str(request.id),
            title=f"Erasure request: {request.subject_kind.value} {request.subject_id}",
            assignee_role=ApproverRole.DATA_PROTECTION,
            requested_by=by,
            summary=(
                "Data-subject erasure request with identity verified. "
                "Approval is required before any data is deleted or anonymized."
            ),
            payload={"reason": request.reason, "channel": request.channel},
            urgency=Urgency.HIGH,
        )
        updated = request.model_copy(
            update={
                "status": ErasureStatus.PENDING_APPROVAL,
                "approval_id": approval.id,
                "updated_at": utc_now(),
            }
        )
        self._store.save_erasure(updated)
        self._record(
            action="compliance.erasure_submitted",
            subject_type="erasure_request",
            subject_id=str(updated.id),
            actor_id=by,
            payload={"approval_id": str(approval.id)},
        )
        return updated

    def apply_decision(self, approval_id: UUID) -> ErasureRequest:
        """Sync the request with the approver's decision. Never auto-executes."""
        request = next(
            (item for item in self._store.list_erasures() if item.approval_id == approval_id),
            None,
        )
        if request is None:
            raise ComplianceError(f"no erasure request linked to approval {approval_id}")
        approval = self._approvals._store.get(approval_id)
        if approval is None:
            raise ComplianceError(f"unknown approval {approval_id}")
        if approval.status not in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
        }:
            raise ComplianceError(
                f"approval {approval_id} is {approval.status.value}; no request transition"
            )
        if approval.status is ApprovalStatus.APPROVED and not approval.decided_by:
            raise ComplianceError("approval has no named human decider")

        approved = approval.status is ApprovalStatus.APPROVED
        updated = request.model_copy(
            update={
                "status": ErasureStatus.APPROVED if approved else ErasureStatus.DENIED,
                "decided_by": approval.decided_by,
                "decided_at": approval.decided_at,
                "decision_reason": approval.decision_reason
                or (None if approved else f"approval {approval.status.value}"),
                "updated_at": utc_now(),
            }
        )
        self._store.save_erasure(updated)
        self._record(
            action="compliance.erasure_approved" if approved else "compliance.erasure_denied",
            subject_type="erasure_request",
            subject_id=str(updated.id),
            actor_id=approval.decided_by or "system",
            payload={"approval_id": str(approval_id)},
        )
        return updated

    def execute_erasure(self, request_id: UUID, *, by: str) -> ErasureRequest:
        """Execute an approved erasure: purge unheld records, revoke consents.

        Legal holds are respected and reported per record. Execution is a
        separate human action from approval — defense in depth.
        """
        self._require_human(by, "execute erasure")
        request = self.get_erasure(request_id)
        if request.status is not ErasureStatus.APPROVED:
            raise ComplianceError(f"request is {request.status.value}; approval required first")

        dispositions: list[ErasureDisposition] = []
        records = self.list_records(
            subject_kind=request.subject_kind, subject_id=request.subject_id
        )
        for record in records:
            if record.legal_hold:
                dispositions.append(
                    ErasureDisposition(
                        record_id=record.id,
                        entity=record.entity,
                        action=DispositionAction.RETAINED_LEGAL_HOLD,
                        detail=record.legal_hold_reason or "under legal hold",
                    )
                )
                continue
            policy = self._store.get_policy(record.entity)
            action = policy.expiry_action if policy else PurgeAction.DELETE
            detail = self._apply_purge(record, action, by)
            purged_record = record.model_copy(
                update={
                    "purged_at": utc_now(),
                    "purge_action": action,
                    "purge_detail": detail,
                }
            )
            self._store.save_record(purged_record)
            dispositions.append(
                ErasureDisposition(
                    record_id=record.id,
                    entity=record.entity,
                    action=(
                        DispositionAction.DELETED
                        if action is PurgeAction.DELETE
                        else DispositionAction.ANONYMIZED
                    ),
                    detail=detail,
                )
            )
            self._record(
                action="compliance.record_erased",
                subject_type="retention_record",
                subject_id=str(record.id),
                actor_id=by,
                payload={
                    "entity": record.entity.value,
                    "subject_id": record.subject_id,
                    "action": action.value,
                    "source": "erasure_request",
                    "request_id": str(request.id),
                },
            )

        revoked = 0
        for consent in self.list_consents(
            subject_kind=request.subject_kind, subject_id=request.subject_id
        ):
            if not consent.granted or consent.revoked_at is not None:
                continue
            self._store.save_consent(
                consent.model_copy(
                    update={
                        "revoked_at": utc_now(),
                        "revoked_reason": f"erasure request {request.id} executed",
                    }
                )
            )
            revoked += 1

        updated = request.model_copy(
            update={
                "status": ErasureStatus.EXECUTED,
                "executed_at": utc_now(),
                "executed_by": by,
                "dispositions": dispositions,
                "consents_revoked": revoked,
                "updated_at": utc_now(),
            }
        )
        self._store.save_erasure(updated)
        self._record(
            action="compliance.erasure_executed",
            subject_type="erasure_request",
            subject_id=str(updated.id),
            actor_id=by,
            payload={
                "purged": len(dispositions),
                "retained_legal_hold": sum(
                    1
                    for item in dispositions
                    if item.action is DispositionAction.RETAINED_LEGAL_HOLD
                ),
                "consents_revoked": revoked,
            },
        )
        return updated

    # --- breach workflow ---------------------------------------------------

    def create_incident(
        self,
        *,
        title: str,
        description: str,
        impact: BreachImpact,
        discovered_by: str,
        created_by: str,
        discovered_at: datetime | None = None,
        template: BreachChecklistTemplate | None = None,
    ) -> BreachIncident:
        """Open a breach incident from a checklist template (default starter)."""
        checklist = template or default_breach_template()
        moment = discovered_at or utc_now()
        steps = [
            BreachStepState(
                key=step.key,
                title=step.title,
                offset_hours=step.offset_hours,
                required=step.required,
                due_at=moment + timedelta(hours=step.offset_hours),
            )
            for step in checklist.steps
        ]
        incident = BreachIncident(
            title=title,
            description=description,
            impact=impact,
            discovered_at=moment,
            discovered_by=discovered_by,
            template_name=checklist.name,
            steps=steps,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._store.add_incident(incident)
        self._record(
            action="compliance.breach_reported",
            subject_type="breach_incident",
            subject_id=str(incident.id),
            actor_id=created_by,
            payload={"impact": impact.value, "template": checklist.name},
        )
        return incident

    def get_incident(self, incident_id: UUID) -> BreachIncident:
        incident = self._store.get_incident(incident_id)
        if incident is None:
            raise ComplianceError(f"unknown breach incident {incident_id}")
        return incident

    def list_incidents(self) -> list[BreachIncident]:
        return self._store.list_incidents()

    def complete_step(
        self, incident_id: UUID, *, step_key: str, by: str, note: str | None = None
    ) -> BreachIncident:
        """Complete one checklist step. Humans only — steps are legal evidence."""
        self._require_human(by, "complete breach checklist step")
        incident = self.get_incident(incident_id)
        if incident.status is BreachStatus.CLOSED:
            raise ComplianceError("incident is closed")
        step = next((item for item in incident.steps if item.key == step_key), None)
        if step is None:
            raise ComplianceError(f"unknown checklist step {step_key}")
        if step.completed:
            raise ComplianceError(f"step {step_key} is already complete")
        steps = [
            item.model_copy(
                update={
                    "completed_by": by,
                    "completed_at": utc_now(),
                    "note": note,
                }
            )
            if item.key == step_key
            else item
            for item in incident.steps
        ]
        updated = incident.model_copy(update={"steps": steps, "updated_at": utc_now()})
        self._store.save_incident(updated)
        self._record(
            action="compliance.breach_step_completed",
            subject_type="breach_incident",
            subject_id=str(updated.id),
            actor_id=by,
            payload={"step": step_key},
        )
        return updated

    def record_notification(
        self,
        incident_id: UUID,
        *,
        recipient_kind: NotificationRecipient,
        recipient: str,
        sent_by: str,
        reference: str | None = None,
        note: str | None = None,
    ) -> BreachIncident:
        """Log a notification that was sent outside the system."""
        self._require_human(sent_by, "record breach notification")
        incident = self.get_incident(incident_id)
        if incident.status is BreachStatus.CLOSED:
            raise ComplianceError("incident is closed")
        notification = BreachNotification(
            recipient_kind=recipient_kind,
            recipient=recipient,
            sent_by=sent_by,
            reference=reference,
            note=note,
        )
        updated = incident.model_copy(
            update={
                "notifications": [*incident.notifications, notification],
                "updated_at": utc_now(),
            }
        )
        self._store.save_incident(updated)
        self._record(
            action="compliance.breach_notification_recorded",
            subject_type="breach_incident",
            subject_id=str(updated.id),
            actor_id=sent_by,
            payload={"recipient_kind": recipient_kind.value, "recipient": recipient},
        )
        return updated

    def transition(
        self,
        incident_id: UUID,
        *,
        status: BreachStatus,
        by: str,
        note: str | None = None,
    ) -> BreachIncident:
        """Advance the incident lifecycle. Closing requires all required steps."""
        self._require_human(by, "transition breach status")
        incident = self.get_incident(incident_id)
        allowed: dict[BreachStatus, set[BreachStatus]] = {
            BreachStatus.OPEN: {BreachStatus.CONTAINED, BreachStatus.NOTIFIED, BreachStatus.CLOSED},
            BreachStatus.CONTAINED: {BreachStatus.NOTIFIED, BreachStatus.CLOSED},
            BreachStatus.NOTIFIED: {BreachStatus.CLOSED},
            BreachStatus.CLOSED: set(),
        }
        if status not in allowed[incident.status]:
            raise ComplianceError(
                f"cannot move incident from {incident.status.value} to {status.value}"
            )
        if status is BreachStatus.NOTIFIED and not incident.notifications:
            raise ComplianceError("record at least one notification before marking notified")
        if status is BreachStatus.CLOSED:
            if not incident.required_steps_complete:
                pending = ", ".join(step.key for step in incident.open_steps if step.required)
                raise ComplianceError(f"required steps incomplete: {pending}")
            if not note or not note.strip():
                raise ComplianceError("closing an incident requires a closure note")

        now = utc_now()
        update: dict[str, object] = {"status": status, "updated_at": now}
        if status is BreachStatus.CONTAINED:
            update["contained_at"] = now
        elif status is BreachStatus.NOTIFIED:
            update["notified_at"] = now
        elif status is BreachStatus.CLOSED:
            update["closed_at"] = now
            update["closed_by"] = by
            update["closure_note"] = note
        updated = incident.model_copy(update=update)
        self._store.save_incident(updated)
        self._record(
            action=f"compliance.breach_{status.value}",
            subject_type="breach_incident",
            subject_id=str(updated.id),
            actor_id=by,
            payload={"note": note or ""},
        )
        return updated

    def overdue_steps(self, *, as_of: datetime | None = None) -> list[OverdueBreachStep]:
        """Incomplete, past-due steps across open incidents (oldest first)."""
        moment = as_of or utc_now()
        overdue: list[OverdueBreachStep] = []
        for incident in self._store.list_incidents():
            if incident.status is BreachStatus.CLOSED:
                continue
            for step in incident.steps:
                if not step.completed and step.due_at <= moment:
                    overdue.append(
                        OverdueBreachStep(
                            incident_id=incident.id,
                            incident_title=incident.title,
                            status=incident.status,
                            step=step,
                        )
                    )
        overdue.sort(key=lambda item: item.step.due_at)
        return overdue

    # --- audit verification ------------------------------------------------

    def verify_audit_chain(self, *, checked_by: str = "system") -> AuditVerificationReport:
        """Verify the full hash chain; report the first broken entry, if any."""
        first_invalid = self._audit.verify()
        intact = first_invalid == -1
        return AuditVerificationReport(
            intact=intact,
            entry_count=len(self._audit.entries),
            first_invalid_seq=None if intact else first_invalid,
            head_hash=self._audit.last_hash,
            checked_by=checked_by,
        )

    # --- internals ----------------------------------------------------------

    def _apply_purge(self, record: RetentionRecord, action: PurgeAction, by: str) -> str:
        handler = self._purge_handlers.get(record.entity)
        if handler is None:
            return (
                f"ledger disposition only ({action.value}); "
                f"no store handler registered for {record.entity.value} by {by}"
            )
        return handler(record, action)

    def _require_human(self, actor: str, action: str) -> None:
        if actor.startswith(AGENT_ACTOR_PREFIX):
            raise ComplianceError(f"agents cannot {action}; a named human is required")

    def _require_automatic_actor(self, actor: str, action: str) -> None:
        if actor.startswith(AGENT_ACTOR_PREFIX):
            raise ComplianceError(f"agents cannot {action}")

    def _record(
        self,
        *,
        action: str,
        subject_type: str,
        subject_id: str,
        actor_id: str,
        payload: dict[str, object],
    ) -> None:
        if actor_id.startswith(AGENT_ACTOR_PREFIX):
            actor_type = ActorType.AGENT
        elif actor_id == "system" or actor_id.startswith("system:"):
            actor_type = ActorType.SYSTEM
        else:
            actor_type = ActorType.HUMAN
        self._audit.append(
            actor=AuditActor(actor_type=actor_type, actor_id=actor_id),
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )
