"""People services container — bundles the employee-domain engines.

One object holds the stores and engines so routers get a single dependency and
tests can build an isolated instance per test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hr_agents.models import PurgeAction, RecordEntity, RetentionRecord
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.compliance import ComplianceService, PurgeHandler
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
from hr_agents.services.retention import RetentionLedger, subject_uuid
from hr_agents.services.tasks import TaskEngine

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _consent_purge_handler(store: ComplianceStore) -> PurgeHandler:
    """Delete or redact the consent grant covering an erased subject.

    A ledger row only ever holds the subject id, so the grant is looked up by
    subject rather than by a foreign key the ledger does not carry. ``delete``
    removes the grant outright; ``anonymize`` keeps the fact that consent once
    existed (which the audit trail may need) while blanking the capture evidence.
    """

    def handler(record: RetentionRecord, action: PurgeAction) -> str:
        grants = [item for item in store.list_consents() if item.subject_id == record.subject_id]
        if not grants:
            return f"no consent grant on record for subject {record.subject_id}; nothing to remove"
        if action is PurgeAction.ANONYMIZE:
            redacted = sum(store.redact_consent(grant.id) is not None for grant in grants)
            return f"redacted capture evidence on {redacted} consent grant(s)"
        removed = sum(store.delete_consent(grant.id) for grant in grants)
        return f"deleted {removed} consent grant(s) for subject {record.subject_id}"

    return handler


def _employee_purge_handler(store: EmployeeStore) -> PurgeHandler:
    """Blank an erased employee's identity, keep the operational record.

    `delete` is carried out as anonymize and says so in the detail: deleting the
    employee row cascades into leave, onboarding, payroll lines, documents and
    contracts, so following the policy literally would destroy the history it was
    written to protect. The ledger and the audit chain both record the
    substitution rather than pretending the policy was followed literally.
    """

    def handler(record: RetentionRecord, action: PurgeAction) -> str:
        employee_id = subject_uuid(record)
        if employee_id is None:
            return f"subject {record.subject_id!r} is not an employee id; nothing to remove"
        employee = store.anonymize_employee(employee_id)
        if employee is None:
            return f"no employee record for subject {record.subject_id}; nothing to remove"
        if action is PurgeAction.DELETE:
            return (
                "anonymized rather than deleted: deleting this row cascades into "
                "leave, onboarding, payroll lines, documents and contracts"
            )
        return (
            "blanked name, contact details, job title, work location and emergency "
            "contact; kept the operational record"
        )

    return handler


def _document_purge_handler(store: EmployeeStore) -> PurgeHandler:
    """Delete every document filed under an erased subject.

    `anonymize` is carried out as delete, and the detail says why: a document's
    filename, hash and content *are* the personal data, so there is no
    non-personal remainder to keep.
    """

    def handler(record: RetentionRecord, action: PurgeAction) -> str:
        employee_id = subject_uuid(record)
        if employee_id is None:
            return f"subject {record.subject_id!r} is not an employee id; nothing to remove"
        documents = store.list_documents(employee_id)
        if not documents:
            return f"no documents on file for subject {record.subject_id}; nothing to remove"
        removed = sum(store.delete_document(document.id) for document in documents)
        if action is PurgeAction.ANONYMIZE:
            return (
                f"deleted {removed} document(s): a document has no non-personal "
                "remainder, so anonymizing and deleting are the same act"
            )
        return f"deleted {removed} document(s)"

    return handler


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

        # The services that create records are built before the compliance engine
        # they report to, so the ledger is late-bound rather than holding a direct
        # reference that would make this ordering a hard constraint.
        ledger = RetentionLedger()

        approvals = ApprovalEngine(approval_store, audit=self.audit)
        tasks = TaskEngine(task_store, audit=self.audit)
        self.approvals = approvals
        self.tasks = tasks
        self.employees = EmployeeService(
            employee_store, audit=self.audit, approvals=approvals, retention=ledger
        )
        self.contracts = ContractService(contract_store, audit=self.audit, tasks=tasks)
        self.rate_tables = RateTableService(rate_table_store, audit=self.audit)
        leave: LeaveService
        if self.session_factory is None:
            leave = LeaveService(employees=self.employees, approvals=approvals, audit=self.audit)
        else:
            from hr_agents.db.leave import DbLeaveService

            leave = DbLeaveService(
                self.session_factory,
                employees=self.employees,
                approvals=approvals,
                audit=self.audit,
            )
        self.leave = leave
        onboarding: OnboardingService
        if self.session_factory is None:
            onboarding = OnboardingService(employees=self.employees, tasks=tasks, audit=self.audit)
        else:
            from hr_agents.db.onboarding import DbOnboardingService

            onboarding = DbOnboardingService(
                self.session_factory,
                employees=self.employees,
                tasks=tasks,
                audit=self.audit,
            )
        self.onboarding = onboarding
        payroll: PayrollService
        if self.session_factory is None:
            payroll = PayrollService(
                employees=self.employees,
                rate_tables=self.rate_tables,
                approvals=approvals,
                audit=self.audit,
            )
        else:
            from hr_agents.db.payroll import DbPayrollService

            payroll = DbPayrollService(
                self.session_factory,
                employees=self.employees,
                rate_tables=self.rate_tables,
                approvals=approvals,
                audit=self.audit,
            )
        self.payroll = payroll
        self.compliance = ComplianceService(compliance_store, approvals=approvals, audit=self.audit)
        ledger.bind(self.compliance.track_record)
        self._register_purge_handlers(compliance_store, employee_store)
        self.growth = GrowthService(
            growth_store, employees=self.employees, tasks=tasks, audit=self.audit
        )
        self.offboarding = OffboardingService(
            offboarding_store,
            employees=self.employees,
            tasks=tasks,
            payroll=self.payroll,
            audit=self.audit,
        )

    def _register_purge_handlers(
        self, compliance_store: ComplianceStore, employee_store: EmployeeStore
    ) -> None:
        """Attach the store-backed purge implementations the compliance engine calls.

        Registered here, at the composition root, because that is the only place
        both the service and its store exist. An entity without a handler is
        reported as ``skipped`` / ``not_executed`` rather than purged, so the
        coverage gap is visible instead of silently reported as a deletion.
        """
        self.compliance.register_purge_handler(
            RecordEntity.CONSENT, _consent_purge_handler(compliance_store)
        )
        self.compliance.register_purge_handler(
            RecordEntity.EMPLOYEE, _employee_purge_handler(employee_store)
        )
        self.compliance.register_purge_handler(
            RecordEntity.DOCUMENT, _document_purge_handler(employee_store)
        )
