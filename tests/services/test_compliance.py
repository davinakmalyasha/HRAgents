from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from hr_agents.models import (
    ApprovalRequest,
    ApproverRole,
    BreachImpact,
    BreachStatus,
    DispositionAction,
    ErasureRequest,
    ErasureStatus,
    LawfulBasis,
    NotificationRecipient,
    PurgeAction,
    RecordEntity,
    RetentionRecord,
    SubjectKind,
)
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    ComplianceError,
    ComplianceService,
    add_months,
)
from hr_agents.services.audit import AuditChain

NOW = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def approvals(audit: AuditChain) -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=audit)


@pytest.fixture
def service(approvals: ApprovalEngine, audit: AuditChain) -> ComplianceService:
    return ComplianceService(approvals=approvals, audit=audit)


def track_candidate(
    service: ComplianceService,
    *,
    subject_id: str = "cand-1",
    anchor_at: datetime | None = None,
    entity: RecordEntity = RecordEntity.CANDIDATE,
) -> RetentionRecord:
    return service.track_record(
        entity=entity,
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=subject_id,
        created_by="screening-pipeline",
        label="Budi Santoso",
        anchor_at=anchor_at or (NOW - timedelta(days=800)),
    )


def approval_for(service: ComplianceService, request: ErasureRequest) -> ApprovalRequest:
    assert request.approval_id is not None
    approval = service._approvals._store.get(request.approval_id)
    assert approval is not None
    return approval


# --- consent registry --------------------------------------------------------


def test_record_and_check_consent(service: ComplianceService) -> None:
    record = service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="screening-agent",
        capture_method="web_form",
    )

    assert record.active
    assert service.has_active_consent(SubjectKind.CANDIDATE, "cand-1", "recruitment_evaluation")


def test_consent_is_purpose_scoped(service: ComplianceService) -> None:
    service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
    )

    assert not service.has_active_consent(SubjectKind.CANDIDATE, "cand-1", "talent_pool")


def test_refusal_is_recorded_but_inactive(service: ComplianceService) -> None:
    record = service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
        granted=False,
    )

    assert not record.active
    assert not service.has_active_consent(SubjectKind.CANDIDATE, "cand-1", "recruitment_evaluation")


def test_expired_consent_is_inactive(service: ComplianceService) -> None:
    service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    assert not service.has_active_consent(SubjectKind.CANDIDATE, "cand-1", "recruitment_evaluation")


def test_revoke_requires_human_and_reason(service: ComplianceService) -> None:
    record = service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
    )

    with pytest.raises(ComplianceError, match="named human"):
        service.revoke_consent(record.id, by="agent:screening", reason="subject asked")
    with pytest.raises(ComplianceError, match="requires a reason"):
        service.revoke_consent(record.id, by="hr-admin", reason="  ")

    revoked = service.revoke_consent(record.id, by="hr-admin", reason="subject asked")
    assert revoked.revoked_at is not None
    assert not service.has_active_consent(SubjectKind.CANDIDATE, "cand-1", "recruitment_evaluation")
    with pytest.raises(ComplianceError, match="already revoked"):
        service.revoke_consent(record.id, by="hr-admin", reason="again")


def test_list_consents_filters(service: ComplianceService) -> None:
    service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
    )
    service.record_consent(
        subject_kind=SubjectKind.EMPLOYEE,
        subject_id="emp-1",
        purpose="payroll_processing",
        captured_by="hr-admin",
        lawful_basis=LawfulBasis.CONTRACT,
    )

    candidates = service.list_consents(subject_kind=SubjectKind.CANDIDATE)
    assert len(candidates) == 1
    assert service.list_consents(subject_id="emp-1")[0].purpose == "payroll_processing"


# --- retention ---------------------------------------------------------------


def test_set_policy_upserts_and_keeps_id(service: ComplianceService) -> None:
    first = service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
        expiry_action=PurgeAction.ANONYMIZE,
    )
    second = service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=12,
        updated_by="hr-admin",
        expiry_action=PurgeAction.DELETE,
    )

    assert second.id == first.id
    assert service.get_policy(RecordEntity.CANDIDATE).retention_months == 12
    assert len(service.list_policies()) == 1


def test_agent_cannot_set_policy(service: ComplianceService) -> None:
    with pytest.raises(ComplianceError, match="named human"):
        service.set_policy(
            entity=RecordEntity.CANDIDATE,
            name="X",
            retention_months=12,
            updated_by="agent:compliance",
        )


def test_scan_flags_overdue_unheld_records(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
    )
    track_candidate(service)

    report = service.scan(as_of=NOW)

    assert len(report.due) == 1
    assert report.due[0].action is PurgeAction.ANONYMIZE
    assert report.tracked_count == 1


def test_scan_keeps_recent_records_out_of_due(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
    )
    track_candidate(service, anchor_at=NOW - timedelta(days=30))

    assert service.scan(as_of=NOW).due == []


def test_scan_reports_records_without_policy(service: ComplianceService) -> None:
    track_candidate(service, entity=RecordEntity.DOCUMENT)

    report = service.scan(as_of=NOW)

    assert report.due == []
    assert len(report.uncovered) == 1


def test_legal_hold_requires_human_and_reason(service: ComplianceService) -> None:
    record = track_candidate(service)

    with pytest.raises(ComplianceError, match="named human"):
        service.set_legal_hold(record.id, held=True, by="agent:records", reason="case")
    with pytest.raises(ComplianceError, match="require a reason"):
        service.set_legal_hold(record.id, held=True, by="hr-admin", reason=" ")

    held = service.set_legal_hold(
        record.id, held=True, by="hr-admin", reason="litigation hold 2026-14"
    )
    assert held.legal_hold
    assert held.held_by == "hr-admin"


def test_scan_separates_held_from_due(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
    )
    record = track_candidate(service)
    service.set_legal_hold(record.id, held=True, by="hr-admin", reason="case")

    report = service.scan(as_of=NOW)

    assert report.due == []
    assert len(report.held) == 1
    assert report.held[0].id == record.id


def test_execute_purge_dry_run_does_not_mutate(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
    )
    record = track_candidate(service)

    report = service.execute_purge(by="system", as_of=NOW, dry_run=True)

    assert report.dry_run
    assert len(report.purged) == 1
    assert not service.get_record(record.id).purged
    assert len(service.scan(as_of=NOW).due) == 1


def test_execute_purge_marks_records_and_audits(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
        expiry_action=PurgeAction.DELETE,
    )
    record = track_candidate(service)

    report = service.execute_purge(by="system", as_of=NOW)

    assert len(report.purged) == 1
    purged = service.get_record(record.id)
    assert purged.purge_action is PurgeAction.DELETE
    assert service.scan(as_of=NOW).due == []
    assert service.scan(as_of=NOW).purged_count == 1
    actions = [entry.action for entry in service._audit.entries]
    assert "compliance.record_purged" in actions
    assert "compliance.purge_executed" in actions


def test_purge_skips_held_records(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
    )
    record = track_candidate(service)
    service.set_legal_hold(record.id, held=True, by="hr-admin", reason="case")

    report = service.execute_purge(by="system", as_of=NOW)

    assert report.purged == []
    assert report.held == [record.id]
    assert not service.get_record(record.id).purged


def test_purge_uses_registered_handler(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
    )
    record = track_candidate(service)
    seen: list[tuple[str, PurgeAction]] = []

    def handler(item: RetentionRecord, action: PurgeAction) -> str:
        seen.append((str(item.id), action))
        return "removed from candidate store"

    service.register_purge_handler(RecordEntity.CANDIDATE, handler)
    report = service.execute_purge(by="hr-admin", as_of=NOW)

    assert seen == [(str(record.id), PurgeAction.ANONYMIZE)]
    assert report.purged[0].detail == "removed from candidate store"


def test_dry_run_does_not_call_handler(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
    )
    track_candidate(service)
    calls: list[str] = []

    def handler(item: RetentionRecord, action: PurgeAction) -> str:
        calls.append(str(item.id))
        return "removed"

    service.register_purge_handler(RecordEntity.CANDIDATE, handler)
    report = service.execute_purge(by="system", as_of=NOW, dry_run=True)

    assert calls == []
    assert report.purged[0].detail == "dry run; no store mutation performed"


def test_agents_cannot_execute_purge(service: ComplianceService) -> None:
    with pytest.raises(ComplianceError, match="agents cannot"):
        service.execute_purge(by="agent:records", as_of=NOW)


def test_add_months_clamps_month_end() -> None:
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert add_months(datetime(2026, 12, 15, tzinfo=UTC), 2) == datetime(2027, 2, 15, tzinfo=UTC)
    assert add_months(datetime(2026, 6, 10, tzinfo=UTC), 24) == datetime(2028, 6, 10, tzinfo=UTC)


# --- erasure workflow --------------------------------------------------------


def setup_erasure_fixture(service: ComplianceService) -> str:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
        expiry_action=PurgeAction.ANONYMIZE,
    )
    return "cand-1"


def test_erasure_requires_identity_verification(service: ComplianceService) -> None:
    service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        reason="subject request via email",
        requested_by="hr-admin",
    )
    request = service.list_erasures()[0]

    with pytest.raises(ComplianceError, match="identity must be verified"):
        service.submit_for_decision(request.id, by="hr-admin")


def test_erasure_identity_verification_is_human(service: ComplianceService) -> None:
    service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        reason="subject request",
        requested_by="agent:policy_assistant",
    )
    request = service.list_erasures()[0]

    with pytest.raises(ComplianceError, match="named human"):
        service.verify_identity(request.id, by="agent:policy_assistant", method="email reply")

    verified = service.verify_identity(request.id, by="hr-admin", method="email reply")
    assert verified.identity_verified_by == "hr-admin"


def test_erasure_routes_to_data_protection_approver(service: ComplianceService) -> None:
    service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        reason="subject request",
        requested_by="hr-admin",
    )
    request = service.list_erasures()[0]
    service.verify_identity(request.id, by="hr-admin", method="email reply")
    submitted = service.submit_for_decision(request.id, by="hr-admin")

    assert submitted.status is ErasureStatus.PENDING_APPROVAL
    approval = approval_for(service, submitted)
    assert approval is not None
    assert approval.assignee_role is ApproverRole.DATA_PROTECTION
    assert approval.subject.value == "erasure_request"


def test_erasure_approval_does_not_auto_execute(service: ComplianceService) -> None:
    service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        reason="subject request",
        requested_by="hr-admin",
    )
    request = service.list_erasures()[0]
    service.verify_identity(request.id, by="hr-admin", method="email")
    submitted = service.submit_for_decision(request.id, by="hr-admin")

    with pytest.raises(ComplianceError, match="no request transition"):
        service.apply_decision(submitted.approval_id)  # type: ignore[arg-type]


def test_erasure_full_flow_purges_and_revokes(service: ComplianceService) -> None:
    subject_id = setup_erasure_fixture(service)
    open_record = track_candidate(service, subject_id=subject_id)
    held_record = track_candidate(service, subject_id=subject_id)
    service.set_legal_hold(held_record.id, held=True, by="hr-admin", reason="litigation")
    consent = service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=subject_id,
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
    )

    request = service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=subject_id,
        reason="UU PDP erasure request",
        requested_by="hr-admin",
    )
    service.verify_identity(request.id, by="hr-admin", method="email")
    submitted = service.submit_for_decision(request.id, by="hr-admin")
    approval = approval_for(service, submitted)
    assert approval is not None

    with pytest.raises(ComplianceError, match="approval required first"):
        service.execute_erasure(request.id, by="hr-admin")

    service._approvals.decide(approval.id, decided_by="dpo-nadia", approve=True)
    synced = service.apply_decision(approval.id)
    assert synced.status is ErasureStatus.APPROVED
    assert synced.decided_by == "dpo-nadia"

    executed = service.execute_erasure(request.id, by="hr-admin")

    assert executed.status is ErasureStatus.EXECUTED
    assert executed.consents_revoked == 1
    assert service.get_record(open_record.id).purged
    assert not service.get_record(held_record.id).purged
    actions = {item.record_id: item.action for item in executed.dispositions}
    assert actions[open_record.id] is DispositionAction.ANONYMIZED
    assert actions[held_record.id] is DispositionAction.RETAINED_LEGAL_HOLD
    assert service.get_consent(consent.id).revoked_at is not None


def test_erasure_execution_is_human_only(service: ComplianceService) -> None:
    subject_id = setup_erasure_fixture(service)
    request = service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=subject_id,
        reason="subject request",
        requested_by="hr-admin",
    )
    service.verify_identity(request.id, by="hr-admin", method="email")
    submitted = service.submit_for_decision(request.id, by="hr-admin")
    approval = approval_for(service, submitted)
    assert approval is not None
    service._approvals.decide(approval.id, decided_by="dpo-nadia", approve=True)
    service.apply_decision(approval.id)

    with pytest.raises(ComplianceError, match="named human"):
        service.execute_erasure(request.id, by="agent:policy_assistant")


def test_erasure_denial_blocks_execution(service: ComplianceService) -> None:
    subject_id = setup_erasure_fixture(service)
    request = service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id=subject_id,
        reason="subject request",
        requested_by="hr-admin",
    )
    service.verify_identity(request.id, by="hr-admin", method="email")
    submitted = service.submit_for_decision(request.id, by="hr-admin")
    approval = approval_for(service, submitted)
    assert approval is not None
    service._approvals.decide(
        approval.id, decided_by="dpo-nadia", approve=False, reason="legal obligation to retain"
    )
    denied = service.apply_decision(approval.id)

    assert denied.status is ErasureStatus.DENIED
    assert denied.decision_reason == "legal obligation to retain"
    with pytest.raises(ComplianceError, match="approval required first"):
        service.execute_erasure(request.id, by="hr-admin")


def test_erasure_policy_action_delete(service: ComplianceService) -> None:
    service.set_policy(
        entity=RecordEntity.CANDIDATE,
        name="Candidate records",
        retention_months=24,
        updated_by="hr-admin",
        expiry_action=PurgeAction.DELETE,
    )
    record = track_candidate(service, subject_id="cand-9")
    request = service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-9",
        reason="subject request",
        requested_by="hr-admin",
    )
    service.verify_identity(request.id, by="hr-admin", method="email")
    submitted = service.submit_for_decision(request.id, by="hr-admin")
    approval = approval_for(service, submitted)
    assert approval is not None
    service._approvals.decide(approval.id, decided_by="dpo-nadia", approve=True)
    service.apply_decision(approval.id)

    executed = service.execute_erasure(request.id, by="hr-admin")

    assert executed.dispositions[0].action is DispositionAction.DELETED
    assert service.get_record(record.id).purge_action is PurgeAction.DELETE


def test_agents_can_open_erasure_requests(service: ComplianceService) -> None:
    request = service.create_erasure_request(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        reason="inbound message forwarded by agent",
        requested_by="agent:screening_coordinator",
        channel="whatsapp",
    )
    assert request.status is ErasureStatus.RECEIVED


# --- breach workflow ---------------------------------------------------------


def test_default_template_and_incident_materialization(service: ComplianceService) -> None:
    incident = service.create_incident(
        title="Laptop with HR export lost",
        description="Device encryption status unknown",
        impact=BreachImpact.HIGH,
        discovered_by="it-ops",
        created_by="hr-admin",
        discovered_at=NOW,
    )

    assert incident.template_name == "default_incident_checklist"
    assert [step.key for step in incident.steps][:2] == ["contain", "assess"]
    assert incident.steps[0].due_at == NOW + timedelta(hours=4)
    assert not incident.steps[-1].required


def test_breach_step_completion_is_human_only(service: ComplianceService) -> None:
    incident = service.create_incident(
        title="Misdirected email",
        description="",
        impact=BreachImpact.MEDIUM,
        discovered_by="hr-admin",
        created_by="hr-admin",
        discovered_at=NOW,
    )

    with pytest.raises(ComplianceError, match="named human"):
        service.complete_step(incident.id, step_key="contain", by="agent:compliance")

    updated = service.complete_step(
        incident.id, step_key="contain", by="hr-admin", note="attachment recalled"
    )
    assert updated.steps[0].completed_by == "hr-admin"
    with pytest.raises(ComplianceError, match="already complete"):
        service.complete_step(incident.id, step_key="contain", by="hr-admin")


def test_breach_unknown_step_rejected(service: ComplianceService) -> None:
    incident = service.create_incident(
        title="X",
        description="",
        impact=BreachImpact.LOW,
        discovered_by="hr-admin",
        created_by="hr-admin",
        discovered_at=NOW,
    )
    with pytest.raises(ComplianceError, match="unknown checklist step"):
        service.complete_step(incident.id, step_key="nope", by="hr-admin")


def test_notified_requires_notification_record(service: ComplianceService) -> None:
    incident = service.create_incident(
        title="X",
        description="",
        impact=BreachImpact.HIGH,
        discovered_by="hr-admin",
        created_by="hr-admin",
        discovered_at=NOW,
    )

    with pytest.raises(ComplianceError, match="at least one notification"):
        service.transition(incident.id, status=BreachStatus.NOTIFIED, by="hr-admin")

    service.record_notification(
        incident.id,
        recipient_kind=NotificationRecipient.REGULATOR,
        recipient="authority portal",
        sent_by="hr-admin",
        reference="ticket-42",
    )
    updated = service.transition(
        incident.id, status=BreachStatus.NOTIFIED, by="hr-admin", note="notice sent"
    )
    assert updated.status is BreachStatus.NOTIFIED
    assert updated.notifications[0].reference == "ticket-42"


def test_close_requires_completed_checklist_and_note(service: ComplianceService) -> None:
    incident = service.create_incident(
        title="X",
        description="",
        impact=BreachImpact.MEDIUM,
        discovered_by="hr-admin",
        created_by="hr-admin",
        discovered_at=NOW,
    )

    with pytest.raises(ComplianceError, match="required steps incomplete"):
        service.transition(incident.id, status=BreachStatus.CLOSED, by="hr-admin", note="done")

    for step in incident.steps:
        if step.required:
            service.complete_step(incident.id, step_key=step.key, by="hr-admin")

    with pytest.raises(ComplianceError, match="closure note"):
        service.transition(incident.id, status=BreachStatus.CLOSED, by="hr-admin")

    closed = service.transition(
        incident.id, status=BreachStatus.CLOSED, by="hr-admin", note="post-mortem done"
    )
    assert closed.status is BreachStatus.CLOSED
    assert closed.closed_by == "hr-admin"
    with pytest.raises(ComplianceError, match="closed"):
        service.complete_step(incident.id, step_key="remediate", by="hr-admin")


def test_transitions_are_forward_only(service: ComplianceService) -> None:
    incident = service.create_incident(
        title="X",
        description="",
        impact=BreachImpact.LOW,
        discovered_by="hr-admin",
        created_by="hr-admin",
        discovered_at=NOW,
    )
    service.transition(incident.id, status=BreachStatus.CONTAINED, by="hr-admin", note="contained")
    with pytest.raises(ComplianceError, match="cannot move incident"):
        service.transition(incident.id, status=BreachStatus.OPEN, by="hr-admin")


def test_overdue_steps_report_open_incidents(service: ComplianceService) -> None:
    incident = service.create_incident(
        title="X",
        description="",
        impact=BreachImpact.LOW,
        discovered_by="hr-admin",
        created_by="hr-admin",
        discovered_at=NOW,
    )

    overdue = service.overdue_steps(as_of=NOW + timedelta(hours=25))

    assert {item.step.key for item in overdue} == {"contain", "assess"}
    assert overdue[0].incident_id == incident.id


# --- audit verification -------------------------------------------------------


def test_verify_audit_chain_intact(service: ComplianceService, audit: AuditChain) -> None:
    service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
    )

    report = service.verify_audit_chain(checked_by="auditor")

    assert report.intact
    assert report.first_invalid_seq is None
    assert report.entry_count == len(audit.entries)


def test_verify_audit_chain_detects_tampering(
    service: ComplianceService, audit: AuditChain
) -> None:
    service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
    )
    service.record_consent(
        subject_kind=SubjectKind.CANDIDATE,
        subject_id="cand-2",
        purpose="recruitment_evaluation",
        captured_by="hr-admin",
    )
    tampered = audit._entries[0].model_copy(update={"action": "compliance.denied"})
    audit._entries[0] = tampered

    report = service.verify_audit_chain()

    assert not report.intact
    assert report.first_invalid_seq == 0


# --- misc ---------------------------------------------------------------------


def test_get_record_unknown_raises(service: ComplianceService) -> None:
    with pytest.raises(ComplianceError, match="unknown retention record"):
        service.get_record(uuid4())
