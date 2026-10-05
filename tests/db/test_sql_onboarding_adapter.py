"""Onboarding adapter tests on in-memory SQLite.

The regression that matters is a lost *waiver*. A hire whose document check HR had
already waived, with a reason on the record, comes back as not-waived after a
restart, and the next person to open the plan sees a blocker that was already
resolved. These tests read through fresh adapter instances so a fallback to the
in-process dicts would fail here rather than in production.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.onboarding import DbOnboardingService
from hr_agents.identity import ActorRef
from hr_agents.models import (
    ContractType,
    DocumentKind,
    Employee,
    EmployeeDocument,
    OnboardingTemplate,
    StepKind,
    TemplateStep,
)
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.onboarding import OnboardingError
from hr_agents.services.people_store import ApprovalStore, EmployeeStore, TaskStore
from hr_agents.services.tasks import TaskEngine

TODAY = date.today()
ACTOR = ActorRef.legacy("hr-admin")


def _service(factory: sessionmaker[Session]) -> DbOnboardingService:
    audit = AuditChain()
    approvals = ApprovalEngine(ApprovalStore(), audit=audit)
    employees = EmployeeService(EmployeeStore(), audit=audit, approvals=approvals)
    tasks = TaskEngine(TaskStore(), audit=audit)
    return DbOnboardingService(factory, employees=employees, tasks=tasks, audit=audit)


def _steps() -> list[TemplateStep]:
    return [
        TemplateStep(
            key="collect_ktp",
            title="Collect KTP",
            kind=StepKind.DOCUMENT,
            document_kind=DocumentKind.KTP,
        ),
        TemplateStep(
            key="sign_contract",
            title="Sign contract",
            kind=StepKind.CONTRACT,
            requires_human_signoff=True,
        ),
    ]


def _employee(service: DbOnboardingService, name: str = "Sari Dewi") -> Employee:
    return service._employees.create(full_name=name, actor=ACTOR, hire_date=TODAY)


def _template(service: DbOnboardingService) -> OnboardingTemplate:
    return service.create_template(
        name="Engineering PKWT",
        description="Standard engineering hire",
        steps=_steps(),
        applies_to_contract_types=[ContractType.PKWT],
        applies_to_roles=["engineering"],
        actor=ACTOR,
    )


def test_template_round_trip(factory: sessionmaker[Session]) -> None:
    service = _service(factory)
    template = _template(service)

    fresh = _service(factory)
    loaded = fresh.get_template(template.id)
    assert loaded.name == "Engineering PKWT"
    assert loaded.description == "Standard engineering hire"
    assert [step.key for step in loaded.steps] == ["collect_ktp", "sign_contract"]
    # The DOCUMENT-step validator depends on document_kind surviving the round trip.
    assert loaded.steps[0].document_kind is DocumentKind.KTP
    assert loaded.steps[0].kind is StepKind.DOCUMENT
    assert loaded.applies_to_roles == ["engineering"]
    assert loaded.created_at.tzinfo is not None

    with pytest.raises(OnboardingError, match="unknown onboarding template"):
        _service(factory).get_template(uuid4())


def test_plan_round_trip(factory: sessionmaker[Session]) -> None:
    service = _service(factory)
    employee = _employee(service)
    template = _template(service)
    plan = service.start_plan(employee_id=employee.id, template_id=template.id, actor=ACTOR)

    fresh = _service(factory)
    loaded = fresh.get_plan(plan.id)
    assert loaded.employee_id == employee.id
    assert loaded.template_id == template.id
    assert loaded.template_name == "Engineering PKWT"
    # The version hash is what makes the instantiated plan reconstructible.
    assert len(loaded.template_version_hash) == 64
    assert [step.key for step in loaded.steps] == ["collect_ktp", "sign_contract"]
    assert loaded.completed_at is None
    assert loaded.is_complete is False

    with pytest.raises(OnboardingError, match="unknown onboarding plan"):
        _service(factory).get_plan(uuid4())


def test_waived_step_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """The regression: a waiver lost on restart reappears as an unresolved blocker."""
    service = _service(factory)
    employee = _employee(service)
    template = _template(service)
    plan = service.start_plan(employee_id=employee.id, template_id=template.id, actor=ACTOR)
    waived = service.waive_step(plan.id, "collect_ktp", reason="Verified at branch", actor=ACTOR)

    fresh = _service(factory)
    loaded = fresh.get_plan(plan.id)
    state = next(step for step in loaded.steps if step.key == "collect_ktp")
    assert state.complete is True
    assert state.note == "Verified at branch"
    assert [step.key for step in loaded.steps] == [s.key for s in waived.steps]


def test_completed_step_survives_a_restart(factory: sessionmaker[Session]) -> None:
    service = _service(factory)
    employee = _employee(service)
    template = _template(service)
    plan = service.start_plan(employee_id=employee.id, template_id=template.id, actor=ACTOR)
    service.complete_step(plan.id, "collect_ktp", actor=ACTOR)

    loaded = _service(factory).get_plan(plan.id)
    state = next(step for step in loaded.steps if step.key == "collect_ktp")
    assert state.complete is True
    assert state.completed_by is not None
    assert state.completed_at is not None
    assert state.completed_at.tzinfo is not None


def test_plan_completion_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """A finished plan must not reopen as outstanding in the active list."""
    service = _service(factory)
    employee = _employee(service)
    template = _template(service)
    plan = service.start_plan(employee_id=employee.id, template_id=template.id, actor=ACTOR)
    service.complete_step(plan.id, "collect_ktp", actor=ACTOR)
    service.complete_step(plan.id, "sign_contract", actor=ACTOR)
    assert service.get_plan(plan.id).is_complete is True

    fresh = _service(factory)
    assert fresh.get_plan(plan.id).is_complete is True
    assert fresh.get_plan(plan.id).completed_at is not None
    assert [item.id for item in fresh.active_plans()] == []
    assert [item.id for item in fresh.plans_for_employee(employee.id)] == [plan.id]


def test_in_flight_plan_stays_in_the_active_list(factory: sessionmaker[Session]) -> None:
    service = _service(factory)
    employee = _employee(service)
    template = _template(service)
    plan = service.start_plan(employee_id=employee.id, template_id=template.id, actor=ACTOR)

    fresh = _service(factory)
    assert [item.id for item in fresh.active_plans()] == [plan.id]


def test_linked_document_survives_a_restart(factory: sessionmaker[Session]) -> None:
    """Document auto-completion depends on the link; losing it reopens the step."""
    service = _service(factory)
    employee = _employee(service)
    template = _template(service)
    plan = service.start_plan(employee_id=employee.id, template_id=template.id, actor=ACTOR)
    service.link_document(
        plan.id,
        "collect_ktp",
        document=EmployeeDocument(
            employee_id=employee.id,
            kind=DocumentKind.KTP,
            storage_key="docs/ktp.pdf",
            filename="ktp.pdf",
            sha256="a" * 64,
        ),
        actor=ACTOR,
    )

    fresh = _service(factory)
    state = next(step for step in fresh.get_plan(plan.id).steps if step.key == "collect_ktp")
    assert state.linked_document_id is not None
    # Linking attaches the document but does not complete the step: it stays pending
    # until a human verifies it. Losing the link would lose the verification task too.
    assert state.complete is False
    assert state.linked_task_id is not None


def test_template_selection_matches_after_a_restart(factory: sessionmaker[Session]) -> None:
    service = _service(factory)
    _template(service)

    fresh = _service(factory)
    chosen = fresh.select_template(contract_type=ContractType.PKWT, role_text="engineering")
    assert chosen is not None
    assert chosen.name == "Engineering PKWT"
    assert fresh.select_template(contract_type=ContractType.PKWTT, role_text="engineering") is None
