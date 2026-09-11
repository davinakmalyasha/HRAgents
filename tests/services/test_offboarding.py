from datetime import UTC, date, datetime, timedelta

import pytest

from hr_agents.models import (
    AssetStatus,
    DocumentKind,
    Employee,
    EmployeeStatus,
    OffboardingReason,
    OffboardingStepKind,
    OffboardingTemplate,
    OffboardingTemplateStep,
    PayrollRunKind,
    StepStatus,
)
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    EmployeeService,
    EmployeeStore,
    OffboardingError,
    OffboardingService,
    OffboardingStore,
    PayrollService,
    RateTableService,
    RateTableStore,
    TaskEngine,
    TaskStore,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.offboarding import default_offboarding_template, template_hash

TODAY = date.today()
LAST_DAY = TODAY + timedelta(days=30)


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def approvals(audit: AuditChain) -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=audit)


@pytest.fixture
def employees(audit: AuditChain, approvals: ApprovalEngine) -> EmployeeService:
    return EmployeeService(EmployeeStore(), audit=audit, approvals=approvals)


@pytest.fixture
def tasks(audit: AuditChain) -> TaskEngine:
    return TaskEngine(TaskStore(), audit=audit)


@pytest.fixture
def payroll(
    employees: EmployeeService, approvals: ApprovalEngine, audit: AuditChain
) -> PayrollService:
    return PayrollService(
        employees=employees,
        rate_tables=RateTableService(RateTableStore(), audit=audit),
        approvals=approvals,
        audit=audit,
    )


@pytest.fixture
def service(
    employees: EmployeeService, tasks: TaskEngine, payroll: PayrollService, audit: AuditChain
) -> OffboardingService:
    return OffboardingService(
        OffboardingStore(), employees=employees, tasks=tasks, payroll=payroll, audit=audit
    )


def make_employee(employees: EmployeeService, *, name: str = "Rudi Hartono") -> Employee:
    return employees.create(
        full_name=name,
        created_by="hr-admin",
        hire_date=TODAY - timedelta(days=400),
        job_title="Engineering Lead",
    )


def make_template(service: OffboardingService, **overrides: object) -> OffboardingTemplate:
    defaults: dict[str, object] = {
        "name": "Standard Exit",
        "steps": [
            OffboardingTemplateStep(
                key="handover",
                title="Handover notes",
                kind=OffboardingStepKind.HANDOVER,
                due_days_before_last_day=7,
            ),
            OffboardingTemplateStep(
                key="interview",
                title="Exit interview",
                kind=OffboardingStepKind.EXIT_INTERVIEW,
                due_days_before_last_day=2,
            ),
            OffboardingTemplateStep(
                key="final_pay",
                title="Final pay",
                kind=OffboardingStepKind.FINAL_PAY,
                due_days_before_last_day=0,
                requires_human_signoff=True,
            ),
        ],
        "created_by": "hr-admin",
    }
    defaults.update(overrides)
    return service.create_template(**defaults)  # type: ignore[arg-type]


# --- templates -----------------------------------------------------------------


def test_default_template_ships_required_and_optional_steps() -> None:
    template = default_offboarding_template()
    assert template.name == "Resignation — starter"
    keys = [step.key for step in template.steps]
    assert keys == [
        "handover",
        "exit_interview",
        "return_assets",
        "close_accounts",
        "final_pay",
        "confirm_exit",
    ]
    assert template_hash(template) == template_hash(default_offboarding_template())
    assert len(template_hash(template)) == 64


def test_duplicate_step_keys_rejected(service: OffboardingService) -> None:
    with pytest.raises(ValueError, match="duplicate step keys"):
        make_template(
            service,
            steps=[
                OffboardingTemplateStep(key="x", title="A", kind=OffboardingStepKind.TASK),
                OffboardingTemplateStep(key="x", title="B", kind=OffboardingStepKind.TASK),
            ],
        )


def test_document_step_requires_document_kind() -> None:
    with pytest.raises(ValueError, match="DOCUMENT steps require document_kind"):
        OffboardingTemplateStep(key="doc", title="Doc", kind=OffboardingStepKind.DOCUMENT)


def test_select_template_by_reason(service: OffboardingService) -> None:
    make_template(
        service,
        applies_to_reasons=[OffboardingReason.RESIGNATION],
    )
    make_template(
        service,
        name="Termination",
        applies_to_reasons=[OffboardingReason.TERMINATION],
        steps=[OffboardingTemplateStep(key="x", title="X", kind=OffboardingStepKind.TASK)],
    )

    selected = service.select_template(reason=OffboardingReason.TERMINATION)
    assert selected is not None
    assert selected.name == "Termination"


# --- plan lifecycle ---------------------------------------------------------------


def test_start_plan_creates_steps_tasks_and_notice_period(
    service: OffboardingService, employees: EmployeeService, tasks: TaskEngine
) -> None:
    employee = make_employee(employees)
    template = make_template(service)

    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )

    assert len(plan.steps) == 3
    assert len(plan.template_version_hash) == 64
    assert plan.progress == 0.0
    handover = next(step for step in plan.steps if step.key == "handover")
    assert handover.due_on == LAST_DAY - timedelta(days=7)
    assert len(tasks.open_tasks()) == 3
    assert employees.get(employee.id).status is EmployeeStatus.NOTICE_PERIOD


def test_start_plan_requires_human_and_template(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    with pytest.raises(OffboardingError, match="named human"):
        service.start_plan(
            employee_id=employee.id,
            reason=OffboardingReason.RESIGNATION,
            last_working_day=LAST_DAY,
            created_by="agent:offboarding_coordinator",
        )
    with pytest.raises(OffboardingError, match="no offboarding template"):
        service.start_plan(
            employee_id=employee.id,
            reason=OffboardingReason.RESIGNATION,
            last_working_day=LAST_DAY,
            created_by="hr-admin",
        )


def test_start_plan_rejects_already_offboarded(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    employees.transition(
        employee.id, target=EmployeeStatus.OFFBOARDED, by="hr-admin", force=True, reason="test"
    )
    make_template(service)

    with pytest.raises(OffboardingError, match="already offboarded"):
        service.start_plan(
            employee_id=employee.id,
            reason=OffboardingReason.RESIGNATION,
            last_working_day=LAST_DAY,
            created_by="hr-admin",
        )


# --- steps ------------------------------------------------------------------------


def test_complete_step_is_human_only(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )

    with pytest.raises(OffboardingError, match="named human"):
        service.complete_step(plan.id, "handover", by="agent:offboarding_coordinator")

    updated = service.complete_step(plan.id, "handover", by="hr-admin", note="notes added")
    step = next(item for item in updated.steps if item.key == "handover")
    assert step.status is StepStatus.DONE
    assert step.completed_by == "hr-admin"
    assert updated.progress == pytest.approx(1 / 3, abs=1e-4)

    with pytest.raises(OffboardingError, match="already done"):
        service.complete_step(plan.id, "handover", by="hr-admin")


def test_waive_requires_human_and_reason(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )

    with pytest.raises(OffboardingError, match="named human"):
        service.waive_step(plan.id, "interview", by="agent:x", reason="r")
    with pytest.raises(OffboardingError, match="requires a reason"):
        service.waive_step(plan.id, "interview", by="hr-admin", reason=" ")

    waived = service.waive_step(plan.id, "interview", by="hr-admin", reason="declined")
    step = next(item for item in waived.steps if item.key == "interview")
    assert step.status is StepStatus.WAIVED
    assert step.note == "declined"


def test_schedule_exit_interview(service: OffboardingService, employees: EmployeeService) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )
    moment = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

    with pytest.raises(OffboardingError, match="timezone-aware"):
        service.schedule_exit_interview(
            plan.id, scheduled_for=datetime(2026, 10, 1, 9, 0), by="hr-admin"
        )

    updated = service.schedule_exit_interview(plan.id, scheduled_for=moment, by="hr-admin")
    step = next(item for item in updated.steps if item.key == "interview")
    assert step.scheduled_for == moment
    assert step.status is StepStatus.IN_PROGRESS


def test_handover_note_appended(service: OffboardingService, employees: EmployeeService) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )

    updated = service.add_handover_note(
        plan.id, content="Prod credentials are in Vault path x.", authored_by="rudi"
    )
    assert len(updated.handover_notes) == 1
    assert updated.handover_notes[0].authored_by == "rudi"


# --- assets --------------------------------------------------------------------------


def test_asset_clearance_blocks_plan_completion(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )
    asset = service.register_asset(
        employee_id=employee.id, name="MacBook Pro", created_by="hr-admin", asset_code="MB-001"
    )

    for step in plan.steps:
        service.complete_step(plan.id, step.key, by="hr-admin")

    current = service.get_plan(plan.id)
    assert current.is_complete
    assert current.completed_at is None  # asset still out

    with pytest.raises(OffboardingError, match="assets not cleared"):
        service.complete_plan(plan.id, by="hr-admin")

    service.mark_asset_returned(asset.id, by="hr-admin", note="returned at office")
    completed = service.complete_plan(plan.id, by="hr-admin")
    assert completed.completed_at is not None


def test_asset_lifecycle_guards(service: OffboardingService, employees: EmployeeService) -> None:
    employee = make_employee(employees)
    asset = service.register_asset(employee_id=employee.id, name="Phone", created_by="hr-admin")

    with pytest.raises(OffboardingError, match="named human"):
        service.mark_asset_returned(asset.id, by="agent:records")

    missing = service.mark_asset_missing(asset.id, by="hr-admin", note="not in locker")
    assert missing.status is AssetStatus.MISSING
    assert service.asset_clearance(employee.id) == [missing]

    written_off = service.write_off_asset(asset.id, by="hr-admin", reason="police report filed")
    assert written_off.status is AssetStatus.WRITTEN_OFF
    assert service.asset_clearance(employee.id) == []

    with pytest.raises(OffboardingError, match="cannot be marked returned"):
        service.mark_asset_returned(asset.id, by="hr-admin")


def test_missing_requires_note(service: OffboardingService, employees: EmployeeService) -> None:
    employee = make_employee(employees)
    asset = service.register_asset(employee_id=employee.id, name="Phone", created_by="hr-admin")
    with pytest.raises(OffboardingError, match="requires a note"):
        service.mark_asset_missing(asset.id, by="hr-admin", note=" ")


# --- final pay -------------------------------------------------------------------------


def test_coordinate_final_pay_creates_final_run(
    service: OffboardingService, employees: EmployeeService, payroll: PayrollService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )

    with pytest.raises(OffboardingError, match="named human"):
        service.coordinate_final_pay(plan.id, by="agent:offboarding_coordinator")

    updated = service.coordinate_final_pay(plan.id, by="hr-admin")
    assert updated.final_pay_run_id is not None
    run = payroll.get_run(updated.final_pay_run_id)
    assert run.kind is PayrollRunKind.FINAL

    with pytest.raises(OffboardingError, match="already coordinated"):
        service.coordinate_final_pay(plan.id, by="hr-admin")


def test_final_pay_does_not_execute_payments(
    service: OffboardingService, employees: EmployeeService, payroll: PayrollService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )

    updated = service.coordinate_final_pay(plan.id, by="hr-admin")
    assert updated.final_pay_run_id is not None
    run = payroll.get_run(updated.final_pay_run_id)
    assert run.status.value == "draft"
    assert run.signed_off_by is None


# --- finalize ---------------------------------------------------------------------------


def test_finalize_employee_exit_transitions_status(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )
    for step in plan.steps:
        service.complete_step(plan.id, step.key, by="hr-admin")

    updated_employee = service.finalize_employee_exit(plan.id, by="hr-admin")

    assert updated_employee.status is EmployeeStatus.OFFBOARDED
    assert updated_employee.offboarded_on == TODAY
    assert service.get_plan(plan.id).completed_at is not None


def test_finalize_requires_completed_steps(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )

    with pytest.raises(OffboardingError, match="required steps incomplete"):
        service.complete_plan(plan.id, by="hr-admin")
    with pytest.raises(OffboardingError, match="required steps incomplete"):
        service.finalize_employee_exit(plan.id, by="hr-admin")


def test_plans_for_employee_and_active(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )

    assert [item.id for item in service.plans_for_employee(employee.id)] == [plan.id]
    assert [item.id for item in service.active_plans()] == [plan.id]


def test_audit_chain_records_offboarding_actions(
    service: OffboardingService, employees: EmployeeService
) -> None:
    employee = make_employee(employees)
    template = make_template(service)
    plan = service.start_plan(
        employee_id=employee.id,
        reason=OffboardingReason.RESIGNATION,
        last_working_day=LAST_DAY,
        created_by="hr-admin",
        template_id=template.id,
    )
    service.complete_step(plan.id, "handover", by="hr-admin")
    service.register_asset(employee_id=employee.id, name="Laptop", created_by="hr-admin")

    actions = [entry.action for entry in service._audit.entries]
    assert "offboarding.template_created" in actions
    assert "offboarding.plan_started" in actions
    assert "offboarding.step_completed" in actions
    assert "offboarding.asset_registered" in actions


def test_document_template_step_validation() -> None:
    step = OffboardingTemplateStep(
        key="return_doc",
        title="Return access card",
        kind=OffboardingStepKind.DOCUMENT,
        document_kind=DocumentKind.OTHER,
    )
    assert step.document_kind is DocumentKind.OTHER
