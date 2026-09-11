from datetime import date, timedelta
from uuid import uuid4

import pytest

from hr_agents.models import (
    ContractType,
    DocumentKind,
    Employee,
    OnboardingTemplate,
    StepKind,
    StepStatus,
    TemplateStep,
)
from hr_agents.services import (
    EmployeeService,
    EmployeeStore,
    TaskEngine,
    TaskStore,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.onboarding import (
    OnboardingError,
    OnboardingService,
    default_engineering_template,
    template_hash,
)

TODAY = date.today()


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def task_engine(audit: AuditChain) -> TaskEngine:
    return TaskEngine(TaskStore(), audit=audit)


@pytest.fixture
def employee_service(audit: AuditChain) -> EmployeeService:
    return EmployeeService(EmployeeStore(), audit=audit)


@pytest.fixture
def service(
    employee_service: EmployeeService, task_engine: TaskEngine, audit: AuditChain
) -> OnboardingService:
    return OnboardingService(employees=employee_service, tasks=task_engine, audit=audit)


def make_employee(
    employee_service: EmployeeService, *, job_title: str = "Backend Engineer"
) -> Employee:
    return employee_service.create(
        full_name="Budi Santoso",
        created_by="hr-admin",
        hire_date=TODAY,
        job_title=job_title,
    )


def make_template(
    service: OnboardingService, *, steps: list[TemplateStep] | None = None
) -> OnboardingTemplate:
    default_steps = [
        TemplateStep(
            key="collect_ktp",
            title="Collect KTP",
            kind=StepKind.DOCUMENT,
            document_kind=DocumentKind.KTP,
            due_days_after_hire=3,
        ),
        TemplateStep(
            key="sign_contract",
            title="Sign contract",
            kind=StepKind.CONTRACT,
            requires_human_signoff=True,
        ),
        TemplateStep(
            key="orientation",
            title="Orientation",
            kind=StepKind.ORIENTATION,
        ),
    ]
    return service.create_template(
        name="Test Template",
        steps=steps if steps is not None else default_steps,
        created_by="hr-admin",
    )


# --- templates ---------------------------------------------------------------


def test_template_creation_and_hash_stability(service: OnboardingService) -> None:
    template = make_template(service)
    assert template_hash(template) == template_hash(template)
    assert len(template_hash(template)) == 64


def test_template_hash_changes_with_content(service: OnboardingService) -> None:
    template = make_template(service)
    modified = template.model_copy(update={"name": "Renamed"})
    assert template_hash(template) != template_hash(modified)


def test_duplicate_step_keys_rejected(service: OnboardingService) -> None:
    step = TemplateStep(key="dup", title="A", kind=StepKind.TASK)
    with pytest.raises(ValueError, match="duplicate step keys"):
        service.create_template(name="X", steps=[step, step], created_by="hr")


def test_document_step_requires_document_kind() -> None:
    with pytest.raises(ValueError, match="document_kind"):
        TemplateStep(key="bad", title="Bad", kind=StepKind.DOCUMENT)


def test_non_document_step_rejects_document_kind() -> None:
    with pytest.raises(ValueError, match="only applies to DOCUMENT"):
        TemplateStep(
            key="bad",
            title="Bad",
            kind=StepKind.TASK,
            document_kind=DocumentKind.KTP,
        )


def test_template_selection_by_role(service: OnboardingService) -> None:
    engineering = default_engineering_template()
    service.create_template(
        name=engineering.name,
        steps=engineering.steps,
        created_by="system",
        applies_to_roles=engineering.applies_to_roles,
    )
    finance_template = service.create_template(
        name="Finance",
        steps=[TemplateStep(key="x", title="X", kind=StepKind.TASK)],
        created_by="hr",
        applies_to_roles=["finance"],
    )

    selection = service.select_template(contract_type=None, role_text="Backend Engineer")
    assert selection is not None
    assert selection.name == engineering.name

    selected = service.select_template(contract_type=None, role_text="Finance Staff")
    assert selected is not None
    assert selected.id == finance_template.id


def test_template_selection_by_contract_type(service: OnboardingService) -> None:
    service.create_template(
        name="PKWT only",
        steps=[TemplateStep(key="x", title="X", kind=StepKind.TASK)],
        created_by="hr",
        applies_to_contract_types=[ContractType.PKWT],
    )
    assert service.select_template(contract_type=ContractType.PKWT, role_text=None) is not None
    assert service.select_template(contract_type=ContractType.PKWTT, role_text=None) is None


# --- plan instantiation ------------------------------------------------------


def test_start_plan_creates_steps_and_tasks(
    service: OnboardingService, employee_service: EmployeeService, task_engine: TaskEngine
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)

    plan = service.start_plan(
        employee_id=employee.id, created_by="hr-admin", template_id=template.id
    )

    assert len(plan.steps) == 3
    assert plan.template_name == "Test Template"
    assert len(plan.template_version_hash) == 64
    assert plan.progress == 0.0
    assert not plan.is_complete
    # Tasks created for each step
    assert len(task_engine.open_tasks()) == 3


def test_start_plan_requires_matching_template(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service, job_title="Warehouse Operator")
    with pytest.raises(OnboardingError, match="no onboarding template"):
        service.start_plan(employee_id=employee.id, created_by="hr")


def test_start_plan_uses_auto_selected_template(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    template = service.create_template(
        name="Universal",
        steps=[TemplateStep(key="x", title="X", kind=StepKind.TASK)],
        created_by="hr",
    )
    employee = make_employee(employee_service, job_title="Anything")
    plan = service.start_plan(employee_id=employee.id, created_by="hr")
    assert plan.template_id == template.id


def test_due_dates_computed_from_hire(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    ktp_step = next(step for step in plan.steps if step.key == "collect_ktp")
    assert ktp_step.due_on == TODAY + timedelta(days=3)


# --- step completion ---------------------------------------------------------


def test_complete_step_by_human(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)

    updated = service.complete_step(plan.id, "orientation", by="hr-admin")
    assert updated.steps[2].status is StepStatus.DONE
    assert updated.progress == round(1 / 3, 4)


def test_agent_cannot_complete_step(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    with pytest.raises(OnboardingError, match="completed by humans"):
        service.complete_step(plan.id, "orientation", by="agent:onboarding_coordinator")


def test_double_completion_rejected(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    service.complete_step(plan.id, "orientation", by="hr-admin")
    with pytest.raises(OnboardingError, match="already"):
        service.complete_step(plan.id, "orientation", by="hr-admin")


def test_plan_completes_when_all_required_done(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    for step_key in ("collect_ktp", "sign_contract", "orientation"):
        plan = service.complete_step(plan.id, step_key, by="hr-admin")

    assert plan.is_complete
    assert plan.completed_at is not None
    assert plan.progress == 1.0


def test_waive_step_with_reason(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)

    waived = service.waive_step(
        plan.id, "collect_ktp", by="hr-admin", reason="document submitted offline"
    )
    assert waived.steps[0].status is StepStatus.WAIVED
    assert "offline" in (waived.steps[0].note or "")


def test_waive_requires_reason(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    with pytest.raises(OnboardingError, match="requires a reason"):
        service.waive_step(plan.id, "collect_ktp", by="hr-admin", reason="  ")


def test_agent_cannot_waive(service: OnboardingService, employee_service: EmployeeService) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    with pytest.raises(OnboardingError, match="named human"):
        service.waive_step(plan.id, "collect_ktp", by="agent:x", reason="skip")


# --- documents ---------------------------------------------------------------


def test_link_document_then_auto_complete(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)

    document = employee_service.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="ktp.pdf",
        sha256="a" * 64,
        uploaded_by="hr-admin",
    )
    linked = service.link_document(plan.id, "collect_ktp", document=document, linked_by="hr-admin")
    assert linked.steps[0].status is StepStatus.IN_PROGRESS
    assert linked.steps[0].linked_document_id == document.id

    # Unverified document cannot auto-complete
    with pytest.raises(OnboardingError, match="verified"):
        service.auto_complete_document_step(
            plan.id, "collect_ktp", document=document, agent_name="onboarding_coordinator"
        )

    verified = employee_service.mark_document_verified(
        document.id, verified_by="hr-admin", verified=True
    )
    completed = service.auto_complete_document_step(
        plan.id, "collect_ktp", document=verified, agent_name="onboarding_coordinator"
    )
    assert completed.steps[0].status is StepStatus.DONE
    assert completed.steps[0].completed_by == "agent:onboarding_coordinator"


def test_auto_complete_rejects_non_document_step(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    document = employee_service.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="ktp.pdf",
        sha256="a" * 64,
        uploaded_by="hr",
    )
    verified = employee_service.mark_document_verified(document.id, verified_by="hr", verified=True)
    with pytest.raises(OnboardingError, match="not a document step"):
        service.auto_complete_document_step(
            plan.id, "orientation", document=verified, agent_name="agent"
        )


def test_auto_complete_rejects_signoff_step(
    service: OnboardingService, employee_service: EmployeeService, task_engine: TaskEngine
) -> None:
    employee = make_employee(employee_service)
    template = service.create_template(
        name="Signoff doc",
        steps=[
            TemplateStep(
                key="doc",
                title="Doc with signoff",
                kind=StepKind.DOCUMENT,
                document_kind=DocumentKind.KTP,
                requires_human_signoff=True,
            )
        ],
        created_by="hr",
    )
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    document = employee_service.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="ktp.pdf",
        sha256="a" * 64,
        uploaded_by="hr",
    )
    verified = employee_service.mark_document_verified(document.id, verified_by="hr", verified=True)
    service.link_document(plan.id, "doc", document=verified, linked_by="hr")

    with pytest.raises(OnboardingError, match="human sign-off"):
        service.auto_complete_document_step(
            plan.id, "doc", document=verified, agent_name="onboarding_coordinator"
        )


def test_link_document_kind_mismatch(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    wrong = employee_service.add_document(
        employee.id,
        kind=DocumentKind.NPWP,
        storage_key="npwp.pdf",
        sha256="b" * 64,
        uploaded_by="hr",
    )
    with pytest.raises(OnboardingError, match="expects ktp"):
        service.link_document(plan.id, "collect_ktp", document=wrong, linked_by="hr")


def test_document_status_report(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    status = service.document_step_status(plan.id)
    assert status == {"collect_ktp": "missing"}

    document = employee_service.add_document(
        employee.id,
        kind=DocumentKind.KTP,
        storage_key="ktp.pdf",
        sha256="a" * 64,
        uploaded_by="hr",
    )
    service.link_document(plan.id, "collect_ktp", document=document, linked_by="hr")
    status = service.document_step_status(plan.id)
    assert status == {"collect_ktp": "pending_validation"}


# --- queries & audit ---------------------------------------------------------


def test_active_plans_and_blockers(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    assert [p.id for p in service.active_plans()] == [plan.id]
    assert {step.key for step in plan.blockers()} == {
        "collect_ktp",
        "sign_contract",
        "orientation",
    }


def test_unknown_plan_and_step_raise(
    service: OnboardingService, employee_service: EmployeeService
) -> None:
    with pytest.raises(OnboardingError, match="unknown onboarding plan"):
        service.get_plan(uuid4())

    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    with pytest.raises(OnboardingError, match="unknown step"):
        service.complete_step(plan.id, "nope", by="hr")


def test_audit_chain_covers_onboarding_events(
    service: OnboardingService, employee_service: EmployeeService, audit: AuditChain
) -> None:
    employee = make_employee(employee_service)
    template = make_template(service)
    plan = service.start_plan(employee_id=employee.id, created_by="hr", template_id=template.id)
    service.complete_step(plan.id, "orientation", by="hr-admin")

    actions = [entry.action for entry in audit.entries]
    assert "onboarding.template_created" in actions
    assert "onboarding.plan_started" in actions
    assert "onboarding.step_completed" in actions
    assert audit.verify() == -1
