"""People services container — bundles the employee-domain engines.

One object holds the stores and engines so routers get a single dependency and
tests can build an isolated instance per test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.compliance import ComplianceService
from hr_agents.services.contracts import ContractService
from hr_agents.services.employees import EmployeeService
from hr_agents.services.growth import GrowthService
from hr_agents.services.leave import LeaveService
from hr_agents.services.offboarding import OffboardingService
from hr_agents.services.onboarding import OnboardingService
from hr_agents.services.payroll import PayrollService
from hr_agents.services.people_store import (
    ApprovalStore,
    ComplianceStore,
    ContractStore,
    EmployeeStore,
    GrowthStore,
    OffboardingStore,
    RateTableStore,
    TaskStore,
)
from hr_agents.services.rate_tables import RateTableService
from hr_agents.services.tasks import TaskEngine

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


@dataclass
class PeopleServices:
    """All employee-domain engines sharing one audit chain.

    Pass ``session_factory`` to build Postgres-backed stores (ADR 0005);
    omit it for the in-memory contract used by tests and zero-config dev.
    """

    audit: AuditChain = field(default_factory=AuditChain)
    session_factory: sessionmaker[Session] | None = None
    employees: EmployeeService = field(init=False)
    contracts: ContractService = field(init=False)
    approvals: ApprovalEngine = field(init=False)
    tasks: TaskEngine = field(init=False)
    rate_tables: RateTableService = field(init=False)
    onboarding: OnboardingService = field(init=False)
    leave: LeaveService = field(init=False)
    payroll: PayrollService = field(init=False)
    compliance: ComplianceService = field(init=False)
    growth: GrowthService = field(init=False)
    offboarding: OffboardingService = field(init=False)

    def __post_init__(self) -> None:
        employee_store: EmployeeStore
        contract_store: ContractStore
        approval_store: ApprovalStore
        task_store: TaskStore
        rate_table_store: RateTableStore
        compliance_store: ComplianceStore
        growth_store: GrowthStore
        offboarding_store: OffboardingStore

        if self.session_factory is None:
            employee_store = EmployeeStore()
            contract_store = ContractStore()
            approval_store = ApprovalStore()
            task_store = TaskStore()
            rate_table_store = RateTableStore()
            compliance_store = ComplianceStore()
            growth_store = GrowthStore()
            offboarding_store = OffboardingStore()
        else:
            from hr_agents.db.domain import (
                DbComplianceStore,
                DbGrowthStore,
                DbOffboardingStore,
            )
            from hr_agents.db.people import (
                DbApprovalStore,
                DbContractStore,
                DbEmployeeStore,
                DbRateTableStore,
                DbTaskStore,
            )

            employee_store = DbEmployeeStore(self.session_factory)
            contract_store = DbContractStore(self.session_factory)
            approval_store = DbApprovalStore(self.session_factory)
            task_store = DbTaskStore(self.session_factory)
            rate_table_store = DbRateTableStore(self.session_factory)
            compliance_store = DbComplianceStore(self.session_factory)
            growth_store = DbGrowthStore(self.session_factory)
            offboarding_store = DbOffboardingStore(self.session_factory)

        approvals = ApprovalEngine(approval_store, audit=self.audit)
        tasks = TaskEngine(task_store, audit=self.audit)
        self.approvals = approvals
        self.tasks = tasks
        self.employees = EmployeeService(employee_store, audit=self.audit, approvals=approvals)
        self.contracts = ContractService(contract_store, audit=self.audit, tasks=tasks)
        self.rate_tables = RateTableService(rate_table_store, audit=self.audit)
        self.onboarding = OnboardingService(employees=self.employees, tasks=tasks, audit=self.audit)
        self.leave = LeaveService(employees=self.employees, approvals=approvals, audit=self.audit)
        self.payroll = PayrollService(
            employees=self.employees,
            rate_tables=self.rate_tables,
            approvals=approvals,
            audit=self.audit,
        )
        self.compliance = ComplianceService(compliance_store, approvals=approvals, audit=self.audit)
        self.growth = GrowthService(growth_store, tasks=tasks, audit=self.audit)
        self.offboarding = OffboardingService(
            offboarding_store,
            employees=self.employees,
            tasks=tasks,
            payroll=self.payroll,
            audit=self.audit,
        )
