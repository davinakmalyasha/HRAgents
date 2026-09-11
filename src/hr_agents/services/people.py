"""People services container — bundles the employee-domain engines.

One object holds the stores and engines so routers get a single dependency and
tests can build an isolated instance per test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class PeopleServices:
    """All employee-domain engines sharing one audit chain."""

    audit: AuditChain = field(default_factory=AuditChain)
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
        approvals = ApprovalEngine(ApprovalStore(), audit=self.audit)
        tasks = TaskEngine(TaskStore(), audit=self.audit)
        self.approvals = approvals
        self.tasks = tasks
        self.employees = EmployeeService(EmployeeStore(), audit=self.audit, approvals=approvals)
        self.contracts = ContractService(ContractStore(), audit=self.audit, tasks=tasks)
        self.rate_tables = RateTableService(RateTableStore(), audit=self.audit)
        self.onboarding = OnboardingService(employees=self.employees, tasks=tasks, audit=self.audit)
        self.leave = LeaveService(employees=self.employees, approvals=approvals, audit=self.audit)
        self.payroll = PayrollService(
            employees=self.employees,
            rate_tables=self.rate_tables,
            approvals=approvals,
            audit=self.audit,
        )
        self.compliance = ComplianceService(
            ComplianceStore(), approvals=approvals, audit=self.audit
        )
        self.growth = GrowthService(GrowthStore(), tasks=tasks, audit=self.audit)
        self.offboarding = OffboardingService(
            OffboardingStore(),
            employees=self.employees,
            tasks=tasks,
            payroll=self.payroll,
            audit=self.audit,
        )
