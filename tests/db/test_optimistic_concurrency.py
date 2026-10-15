"""Optimistic concurrency: a lost update is a conflict, not a silent overwrite.

The failure this exists for is two writers who both read a record and both save
it. Today the second write wins and the first change disappears; nobody is told,
and on a step completion or a mid-loop erasure there is no later reader who could
notice. The version column makes the second save refuse.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.api.problem import domain_problem
from hr_agents.db.onboarding import DbOnboardingService
from hr_agents.db.people import DbEmployeeStore
from hr_agents.errors import StaleRecordError
from hr_agents.identity import ActorRef
from hr_agents.models import (
    ContractType,
    DocumentKind,
    Employee,
    OnboardingPlan,
    StepKind,
    TemplateStep,
    business_today,
)
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService
from hr_agents.services.people_store import ApprovalStore, TaskStore
from hr_agents.services.tasks import TaskEngine

HUMAN = ActorRef.legacy("hr-admin")
TODAY = business_today()


def make_employee(store: DbEmployeeStore) -> Employee:
    service = EmployeeService(store)
    return service.create(
        full_name="Sari Dewi",
        actor=HUMAN,
        email="sari@example.com",
        hire_date=TODAY - timedelta(days=200),
        job_title="Finance Staff",
    )


def test_a_second_write_from_the_same_snapshot_is_refused(
    factory: sessionmaker[Session],
) -> None:
    store = DbEmployeeStore(factory)
    employee = make_employee(store)

    first = store.get_employee(employee.id)
    second = store.get_employee(employee.id)
    assert first is not None and second is not None

    first.email = "first@example.com"
    store.save_employee(first)

    second.email = "second@example.com"
    with pytest.raises(StaleRecordError, match="changed after this copy was read"):
        store.save_employee(second)

    survivor = store.get_employee(employee.id)
    assert survivor is not None
    assert survivor.email == "first@example.com", "the losing write must not land"


def test_the_refusal_names_both_versions(factory: sessionmaker[Session]) -> None:
    """A conflict message that says what diverged is one an operator can act on."""
    store = DbEmployeeStore(factory)
    employee = make_employee(store)
    first = store.get_employee(employee.id)
    second = store.get_employee(employee.id)
    assert first is not None and second is not None
    store.save_employee(first)

    with pytest.raises(StaleRecordError) as raised:
        store.save_employee(second)

    message = str(raised.value)
    assert f"employees {employee.id}" in message
    assert "(stored version 1, this copy holds 0)" in message


def test_a_saved_instance_carries_its_new_version(factory: sessionmaker[Session]) -> None:
    """Saving twice in one unit of work must not conflict with itself."""
    store = DbEmployeeStore(factory)
    employee = make_employee(store)
    loaded = store.get_employee(employee.id)
    assert loaded is not None

    loaded.email = "once@example.com"
    store.save_employee(loaded)
    assert loaded.version == 1

    loaded.email = "twice@example.com"
    store.save_employee(loaded)
    assert loaded.version == 2

    fresh = store.get_employee(employee.id)
    assert fresh is not None
    assert fresh.email == "twice@example.com"
    assert fresh.version == 2


def test_a_reloaded_copy_saves_normally(factory: sessionmaker[Session]) -> None:
    """The guard refuses staleness, not parallelism: reload and the write is fine."""
    store = DbEmployeeStore(factory)
    employee = make_employee(store)
    first = store.get_employee(employee.id)
    assert first is not None
    first.email = "first@example.com"
    store.save_employee(first)

    reloaded = store.get_employee(employee.id)
    assert reloaded is not None
    reloaded.email = "second@example.com"

    store.save_employee(reloaded)

    final = store.get_employee(employee.id)
    assert final is not None
    assert final.email == "second@example.com"


def test_a_service_that_loads_per_call_never_sees_the_conflict(
    factory: sessionmaker[Session],
) -> None:
    """The guard must not break ordinary sequential use: every service method
    reloads the record it is about to change, so its snapshot is always current."""
    store = DbEmployeeStore(factory)
    service = EmployeeService(store)
    employee = make_employee(store)

    service.update_contact(employee.id, actor=HUMAN, phone="+62-1")
    updated = service.update_contact(employee.id, actor=HUMAN, phone="+62-2")

    assert updated.phone == "+62-2"
    assert updated.version == 2


def test_the_version_never_leaks_into_a_serialized_model(factory: sessionmaker[Session]) -> None:
    """It is persistence bookkeeping, and `model_dump()` feeds API views and JSON
    columns; a version leaking there would change response shapes and stored JSON."""
    store = DbEmployeeStore(factory)
    employee = make_employee(store)
    loaded = store.get_employee(employee.id)
    assert loaded is not None

    assert loaded.version == 0
    assert "version" not in loaded.model_dump()
    assert "version" not in loaded.model_dump(mode="json")


def test_a_stale_write_becomes_a_409_problem() -> None:
    """The API edge has to be able to explain the refusal, not 500 on it."""
    problem = domain_problem(StaleRecordError("employees abc changed (stored 1, holds 0)"))

    assert problem.status_code == 409
    assert problem.code.value == "stale_write"


def test_the_app_registers_a_handler_for_unmapped_domain_errors() -> None:
    """Routers map the errors they know; a refusal from deep inside a store save
    has to leave as its own problem document too, and this is what guarantees it."""
    from hr_agents.errors import DomainError
    from hr_agents.main import create_app

    app = create_app()

    assert DomainError in app.exception_handlers


# --- the adapter rollout: onboarding, the plan's own example -------------------


def onboarding(factory: sessionmaker[Session]) -> DbOnboardingService:
    audit = AuditChain()
    approvals = ApprovalEngine(ApprovalStore(), audit=audit)
    employees = EmployeeService(DbEmployeeStore(factory), audit=audit, approvals=approvals)
    tasks = TaskEngine(TaskStore(), audit=audit)
    return DbOnboardingService(factory, employees=employees, tasks=tasks, audit=audit)


def plan_for(service: DbOnboardingService) -> OnboardingPlan:
    employee = service._employees.create(full_name="Sari Dewi", actor=HUMAN, hire_date=TODAY)
    template = service.create_template(
        name="Engineering PKWT",
        description="Standard hire",
        steps=[
            TemplateStep(
                key="collect_ktp",
                title="Collect KTP",
                kind=StepKind.DOCUMENT,
                document_kind=DocumentKind.KTP,
            ),
            TemplateStep(key="sign_contract", title="Sign contract", kind=StepKind.CONTRACT),
        ],
        applies_to_contract_types=[ContractType.PKWT],
        applies_to_roles=["engineering"],
        actor=HUMAN,
    )
    return service.start_plan(employee_id=employee.id, template_id=template.id, actor=HUMAN)


def test_a_step_completed_from_a_stale_snapshot_is_refused(
    factory: sessionmaker[Session],
) -> None:
    """The scenario the plan names: two people open one checklist, both act.

    Whoever holds the older copy is refused instead of silently un-completing the
    step the other person just closed.
    """
    service = onboarding(factory)
    plan = plan_for(service)
    held = service.get_plan(plan.id)  # read before the first writer lands

    service.complete_step(plan.id, "collect_ktp", actor=HUMAN)

    held.steps = [
        step.model_copy(update={"complete": True}) if step.key == "sign_contract" else step
        for step in held.steps
    ]
    with pytest.raises(StaleRecordError, match="changed after this copy was read"):
        service._save_plan(held)

    survived = service.get_plan(plan.id)
    first = next(step for step in survived.steps if step.key == "collect_ktp")
    second = next(step for step in survived.steps if step.key == "sign_contract")
    assert first.complete is True, "the first writer's step must survive"
    assert second.complete is False, "the losing write must not land"


def test_sequential_steps_still_work(factory: sessionmaker[Session]) -> None:
    """Every service call reloads the plan, so the guard must not turn ordinary
    use -- two steps completed one after another -- into a conflict."""
    service = onboarding(factory)
    plan = plan_for(service)

    service.complete_step(plan.id, "collect_ktp", actor=HUMAN)
    done = service.complete_step(plan.id, "sign_contract", actor=HUMAN)

    assert all(step.complete for step in done.steps)
    assert done.version == 2


def test_a_template_edit_from_a_stale_copy_is_refused(
    factory: sessionmaker[Session],
) -> None:
    service = onboarding(factory)
    plan_for(service)
    (template,) = [item for item in service._iter_templates()]
    held = service.get_template(template.id)

    service._save_template(template.model_copy(update={"name": "Renamed by the first writer"}))

    with pytest.raises(StaleRecordError):
        service._save_template(held.model_copy(update={"name": "Renamed by the loser"}))

    assert service.get_template(template.id).name == "Renamed by the first writer"
