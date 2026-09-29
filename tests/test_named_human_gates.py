"""Every consequential operation refuses a non-human actor.

Each test covers one operation that previously had no gate at all, or a gate that
a ``system`` actor walked through. This is why the shared identity module exists,
so it is an explicit list rather than a reflection over the codebase: a new
operation added later is not automatically covered, and that gap is the point.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from hr_agents.models import (
    ApprovalSubject,
    ApproverRole,
    Contract,
    ContractType,
    DocumentKind,
    Employee,
    EmployeeStatus,
    LeaveType,
    LeaveTypePolicy,
    RateTableKind,
    Recommendation,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
    Urgency,
)
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    AuditChain,
    ContractError,
    EmployeeError,
    LeaveError,
    LeaveService,
    OffboardingError,
    PayrollError,
    TaskError,
)
from hr_agents.services.contracts import ContractService
from hr_agents.services.employees import EmployeeService
from hr_agents.services.offboarding import OffboardingService, default_offboarding_template
from hr_agents.services.payroll import PayrollService
from hr_agents.services.people_store import (
    ContractStore,
    EmployeeStore,
    OffboardingStore,
    RateTableStore,
    TaskStore,
)
from hr_agents.services.rate_tables import RateTableService
from hr_agents.services.tasks import TaskEngine

NOW = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
HIRE_DATE = date(2024, 1, 15)

NON_HUMANS = ["agent:screening", "agent:", "system", "system:retention", "scheduler", ""]


def _employee(service: EmployeeService) -> Employee:
    return service.create(full_name="Rina", hire_date=HIRE_DATE, created_by="hr-admin")


def _contract(
    service: ContractService, employee_id: UUID, *, created_by: str = "hr-admin"
) -> Contract:
    return service.create(
        employee_id=employee_id,
        contract_type=ContractType.PKWTT,
        start_date=HIRE_DATE,
        end_date=date(2027, 1, 14),
        created_by=created_by,
    )


# --- employees ----------------------------------------------------------------


def test_document_verification_refuses_every_non_human() -> None:
    """The gate used to live in the router, so any other caller bypassed it, and it
    checked only ``agent:``, so ``system`` and ``scheduler`` passed it outright."""
    employees = EmployeeService(EmployeeStore(), audit=AuditChain())
    document = employees.add_document(
        employee_id=_employee(employees).id,
        kind=DocumentKind.KTP,
        storage_key="documents/ktp.pdf",
        sha256="0" * 64,
        uploaded_by="hr-admin",
        filename="ktp.pdf",
    )

    for actor in NON_HUMANS:
        with pytest.raises(EmployeeError, match="named human"):
            employees.mark_document_verified(document.id, verified_by=actor, verified=True)

    assert employees.mark_document_verified(document.id, verified_by="Rina", verified=True)


def test_employee_transition_refuses_every_non_human() -> None:
    """The most consequential state change in the people domain, previously ungated."""
    employees = EmployeeService(EmployeeStore(), audit=AuditChain())
    employee = _employee(employees)

    for actor in NON_HUMANS:
        with pytest.raises(EmployeeError, match="named human"):
            employees.transition(employee.id, target=EmployeeStatus.ACTIVE, by=actor)

    assert employees.transition(employee.id, target=EmployeeStatus.ACTIVE, by="Rina")


def test_the_transition_gate_sits_above_the_idempotent_shortcut() -> None:
    """A repeat call by a system actor is refused, not quietly a no-op success.

    ``transition`` returns early when the employee is already in the target
    state. Placing the gate above that early return is what stops a system actor
    from appearing to succeed at something it was never allowed to do.
    """
    employees = EmployeeService(EmployeeStore(), audit=AuditChain())
    employee = _employee(employees)
    employees.transition(employee.id, target=EmployeeStatus.ACTIVE, by="Rina")

    with pytest.raises(EmployeeError, match="named human"):
        employees.transition(employee.id, target=EmployeeStatus.ACTIVE, by="system")


# --- contracts ----------------------------------------------------------------


def test_contract_activation_and_termination_refuse_non_humans() -> None:
    employees = EmployeeService(EmployeeStore(), audit=AuditChain())
    contracts = ContractService(ContractStore(), audit=AuditChain(), tasks=TaskEngine(TaskStore()))
    contract = _contract(contracts, _employee(employees).id)

    for actor in NON_HUMANS:
        with pytest.raises(ContractError, match="named human"):
            contracts.activate(contract.id, by=actor)

    contracts.activate(contract.id, by="Rina")
    for actor in NON_HUMANS:
        with pytest.raises(ContractError, match="named human"):
            contracts.terminate(contract.id, by=actor, reason="resigned")

    assert contracts.terminate(contract.id, by="Rina", reason="resigned")


# --- tasks --------------------------------------------------------------------


def test_task_completion_and_cancellation_refuse_non_humans() -> None:
    """A task is a human work item by definition; agents may only create them."""
    tasks = TaskEngine(TaskStore(), audit=AuditChain())
    first = tasks.create(title="Collect KTP", created_by="hr-admin")
    second = tasks.create(title="Collect NPWP", created_by="hr-admin")

    for actor in NON_HUMANS:
        with pytest.raises(TaskError, match="named human"):
            tasks.complete(first.id, by=actor)
        with pytest.raises(TaskError, match="named human"):
            tasks.cancel(second.id, by=actor)

    assert tasks.complete(first.id, by="Rina").status.value == "done"
    assert tasks.cancel(second.id, by="Rina").status.value == "cancelled"


# --- leave --------------------------------------------------------------------


def test_leave_policy_and_balance_adjustment_refuse_non_humans() -> None:
    employees = EmployeeService(EmployeeStore(), audit=AuditChain())
    leave = LeaveService(employees=employees, approvals=ApprovalEngine(ApprovalStore()))
    employee = _employee(employees)
    policy = LeaveTypePolicy(leave_type=LeaveType.ANNUAL, name="Annual", days_per_year=12)

    for actor in NON_HUMANS:
        with pytest.raises(LeaveError, match="named human"):
            leave.set_policy(policy, by=actor)
    leave.set_policy(policy, by="Rina")

    for actor in NON_HUMANS:
        with pytest.raises(LeaveError, match="named human"):
            leave.adjust_balance(employee.id, LeaveType.ANNUAL, days=2, by=actor)

    assert leave.adjust_balance(employee.id, LeaveType.ANNUAL, days=2, by="Rina").adjustment == 2


# --- payroll ------------------------------------------------------------------


def test_payroll_export_and_cancellation_refuse_non_humans() -> None:
    payroll = PayrollService(
        employees=EmployeeService(EmployeeStore()),
        rate_tables=RateTableService(RateTableStore()),
        approvals=ApprovalEngine(ApprovalStore()),
        audit=AuditChain(),
    )

    for actor in NON_HUMANS:
        with pytest.raises(PayrollError, match="named human"):
            payroll.mark_exported(uuid4(), by=actor)
        with pytest.raises(PayrollError, match="named human"):
            payroll.cancel_run(uuid4(), by=actor, reason="mistake")


def test_the_payroll_gate_runs_before_the_lookup() -> None:
    """Otherwise the error changes from "unknown run" to "named human", which
    lets a system actor probe which run ids exist by watching status codes."""
    payroll = PayrollService(
        employees=EmployeeService(EmployeeStore()),
        rate_tables=RateTableService(RateTableStore()),
        approvals=ApprovalEngine(ApprovalStore()),
        audit=AuditChain(),
    )
    with pytest.raises(PayrollError, match="named human"):
        payroll.mark_exported(uuid4(), by="system")


# --- offboarding --------------------------------------------------------------


def test_finalizing_an_exit_refuses_non_humans() -> None:
    """This method had no gate whatsoever, and against a completed plan it was a
    one-call path to marking an employee OFFBOARDED that validated nothing.

    Asserted against a plan id that does not exist, so the refusal can only be
    the named-human gate: if the gate ran after the lookup the error would be
    "unknown plan" instead, and the test would pass for the wrong reason.
    """
    employees = EmployeeService(EmployeeStore(), audit=AuditChain())
    store = OffboardingStore()
    store.add_template(default_offboarding_template())
    service = OffboardingService(
        store,
        employees=employees,
        tasks=TaskEngine(TaskStore()),
        payroll=PayrollService(
            employees=employees,
            rate_tables=RateTableService(RateTableStore()),
            approvals=ApprovalEngine(ApprovalStore()),
        ),
        audit=AuditChain(),
    )
    missing = uuid4()

    for actor in NON_HUMANS:
        with pytest.raises(OffboardingError, match="named human"):
            service.finalize_employee_exit(missing, by=actor)

    # The gate is not merely present, it runs first: a human gets the real error.
    with pytest.raises(OffboardingError, match="unknown"):
        service.finalize_employee_exit(missing, by="Rina")


# --- the approval engine ------------------------------------------------------


def test_approval_decisions_refuse_system_actors() -> None:
    """The hole this whole module was written for.

    ``decide`` checked only the ``agent:`` prefix, so ``by="system"`` passed a
    check reading "decisions require a named human actor" and was then recorded
    on the chain as ``ActorType.SYSTEM`` 180 lines away.
    """
    approvals = ApprovalEngine(ApprovalStore(), audit=AuditChain())
    request = approvals.create(
        subject=ApprovalSubject.PAYROLL_RUN,
        subject_id=str(uuid4()),
        title="Sign off the March run",
        summary="All anomalies cleared; figures match last month.",
        requested_by="payroll",
        assignee_role=ApproverRole.FINANCE,
        urgency=Urgency.NORMAL,
    )

    for actor in NON_HUMANS:
        with pytest.raises(Exception, match="named human"):
            approvals.decide(request.id, decided_by=actor, approve=True, reason="ok")

    decision = approvals.decide(request.id, decided_by="dpo-nadia", approve=True, reason="ok")
    assert decision.action == "approved"
    assert decision.request.decided_by == "dpo-nadia"


# --- the chain records what the gate allows -----------------------------------


def test_an_agent_actor_reaches_the_chain_as_an_agent_everywhere() -> None:
    """Three services had a private classifier with no agent branch at all, and
    recorded ``agent:x`` as ``ActorType.HUMAN`` on the tamper-evident chain."""
    audit = AuditChain()
    employees = EmployeeService(EmployeeStore(), audit=audit)
    employee = employees.create(full_name="Rina", hire_date=HIRE_DATE, created_by="agent:x")
    assert audit.entries[-1].actor.actor_type.value == "agent"

    contracts = ContractService(ContractStore(), audit=audit, tasks=TaskEngine(TaskStore()))
    _contract(contracts, employee.id, created_by="agent:x")
    assert audit.entries[-1].actor.actor_type.value == "agent"

    rates = RateTableService(RateTableStore(), audit=audit)
    rates.create(kind=RateTableKind.BPJS_KESEHATAN, name="BPJS", created_by="agent:x")
    assert audit.entries[-1].actor.actor_type.value == "agent"


def test_a_system_prefixed_actor_is_system_everywhere() -> None:
    """Four services matched only the exact string ``"system"``, so a scheduler
    identifying itself as ``system:something`` was recorded as a human."""
    audit = AuditChain()
    employees = EmployeeService(EmployeeStore(), audit=audit)
    employee = employees.create(full_name="Rina", hire_date=HIRE_DATE, created_by="system:seed")
    assert audit.entries[-1].actor.actor_type.value == "system"

    contracts = ContractService(ContractStore(), audit=audit, tasks=TaskEngine(TaskStore()))
    _contract(contracts, employee.id, created_by="system:seed")
    assert audit.entries[-1].actor.actor_type.value == "system"

    tasks = TaskEngine(TaskStore(), audit=audit)
    tasks.create(title="Collect KTP", created_by="system:scheduler")
    assert audit.entries[-1].actor.actor_type.value == "system"


# --- the sigma floor ----------------------------------------------------------


def test_an_evaluation_cannot_be_built_from_a_single_run() -> None:
    """sigma is 0.0 by definition over one run, so a single extraction satisfied
    the ``sigma <= 0.05`` auto-schedule gate with the least evidence, not the most."""
    vector = ScoreVector(
        technical_depth=0.5,
        stack_alignment=0.5,
        systems_literacy=0.5,
        verifiable_certifications=0.5,
    )
    run = ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector)

    with pytest.raises(ValidationError):
        TechnicalEvaluation(
            candidate_id=uuid4(),
            job_id=uuid4(),
            runs=[run],
            mean_vector=vector,
            dimension_stddev={},
            s_tech=0.5,
            sigma=0.0,
            weights={},
            breakdown=[],
            recommendation=Recommendation.HUMAN_REVIEW,
        )

    ok = TechnicalEvaluation(
        candidate_id=uuid4(),
        job_id=uuid4(),
        runs=[run, run.model_copy(update={"run_index": 1})],
        mean_vector=vector,
        dimension_stddev={},
        s_tech=0.5,
        sigma=0.0,
        weights={},
        breakdown=[],
        recommendation=Recommendation.HUMAN_REVIEW,
    )
    assert len(ok.runs) == 2
