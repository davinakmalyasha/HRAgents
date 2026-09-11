"""In-memory stores for people-domain entities.

Define the behavioral contract; Postgres-backed repositories arrive with the
API wiring and must satisfy the same interface. All state changes are the
services' responsibility (stores are dumb persistence).
"""

from __future__ import annotations

from uuid import UUID

from hr_agents.models import (
    ApprovalRequest,
    BreachIncident,
    ConsentGrant,
    Contract,
    Employee,
    EmployeeDocument,
    ErasureRequest,
    Goal,
    OffboardingAsset,
    OffboardingPlan,
    OffboardingTemplate,
    OrgUnit,
    RateTable,
    RecordEntity,
    RetentionPolicy,
    RetentionRecord,
    ReviewAssignment,
    ReviewCycle,
    ReviewSummary,
    TaskItem,
)


class EmployeeStore:
    def __init__(self) -> None:
        self._employees: dict[UUID, Employee] = {}
        self._org_units: dict[UUID, OrgUnit] = {}
        self._documents: dict[UUID, EmployeeDocument] = {}

    # employees
    def add_employee(self, employee: Employee) -> None:
        if employee.id in self._employees:
            raise ValueError(f"employee {employee.id} already exists")
        self._employees[employee.id] = employee

    def save_employee(self, employee: Employee) -> None:
        if employee.id not in self._employees:
            raise KeyError(f"unknown employee {employee.id}")
        self._employees[employee.id] = employee

    def get_employee(self, employee_id: UUID) -> Employee | None:
        return self._employees.get(employee_id)

    def list_employees(self) -> list[Employee]:
        return sorted(self._employees.values(), key=lambda item: item.full_name.lower())

    # org units
    def add_org_unit(self, unit: OrgUnit) -> None:
        self._org_units[unit.id] = unit

    def get_org_unit(self, unit_id: UUID) -> OrgUnit | None:
        return self._org_units.get(unit_id)

    def list_org_units(self) -> list[OrgUnit]:
        return sorted(self._org_units.values(), key=lambda item: item.name.lower())

    # documents
    def add_document(self, document: EmployeeDocument) -> None:
        self._documents[document.id] = document

    def list_documents(self, employee_id: UUID) -> list[EmployeeDocument]:
        return [doc for doc in self._documents.values() if doc.employee_id == employee_id]


class ContractStore:
    def __init__(self) -> None:
        self._contracts: dict[UUID, Contract] = {}

    def add(self, contract: Contract) -> None:
        self._contracts[contract.id] = contract

    def save(self, contract: Contract) -> None:
        if contract.id not in self._contracts:
            raise KeyError(f"unknown contract {contract.id}")
        self._contracts[contract.id] = contract

    def get(self, contract_id: UUID) -> Contract | None:
        return self._contracts.get(contract_id)

    def list_all(self) -> list[Contract]:
        return sorted(self._contracts.values(), key=lambda item: item.start_date)

    def list_for_employee(self, employee_id: UUID) -> list[Contract]:
        return [item for item in self.list_all() if item.employee_id == employee_id]


class ApprovalStore:
    def __init__(self) -> None:
        self._requests: dict[UUID, ApprovalRequest] = {}

    def add(self, request: ApprovalRequest) -> None:
        self._requests[request.id] = request

    def save(self, request: ApprovalRequest) -> None:
        if request.id not in self._requests:
            raise KeyError(f"unknown approval {request.id}")
        self._requests[request.id] = request

    def get(self, request_id: UUID) -> ApprovalRequest | None:
        return self._requests.get(request_id)

    def list_all(self) -> list[ApprovalRequest]:
        return sorted(self._requests.values(), key=lambda item: item.created_at)


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[UUID, TaskItem] = {}

    def add(self, task: TaskItem) -> None:
        self._tasks[task.id] = task

    def save(self, task: TaskItem) -> None:
        if task.id not in self._tasks:
            raise KeyError(f"unknown task {task.id}")
        self._tasks[task.id] = task

    def get(self, task_id: UUID) -> TaskItem | None:
        return self._tasks.get(task_id)

    def list_all(self) -> list[TaskItem]:
        return sorted(self._tasks.values(), key=lambda item: item.created_at)


class RateTableStore:
    def __init__(self) -> None:
        self._tables: dict[UUID, RateTable] = {}

    def add(self, table: RateTable) -> None:
        self._tables[table.id] = table

    def save(self, table: RateTable) -> None:
        if table.id not in self._tables:
            raise KeyError(f"unknown rate table {table.id}")
        self._tables[table.id] = table

    def get(self, table_id: UUID) -> RateTable | None:
        return self._tables.get(table_id)

    def list_all(self) -> list[RateTable]:
        return sorted(self._tables.values(), key=lambda item: item.name.lower())


class ComplianceStore:
    """In-memory persistence for the compliance pack.

    Policies are keyed by entity (one active policy per entity kind); every
    other collection is keyed by id and listed in insertion order.
    """

    def __init__(self) -> None:
        self._consents: dict[UUID, ConsentGrant] = {}
        self._policies: dict[RecordEntity, RetentionPolicy] = {}
        self._records: dict[UUID, RetentionRecord] = {}
        self._erasures: dict[UUID, ErasureRequest] = {}
        self._incidents: dict[UUID, BreachIncident] = {}

    # consent
    def add_consent(self, consent: ConsentGrant) -> None:
        self._consents[consent.id] = consent

    def save_consent(self, consent: ConsentGrant) -> None:
        if consent.id not in self._consents:
            raise KeyError(f"unknown consent {consent.id}")
        self._consents[consent.id] = consent

    def get_consent(self, consent_id: UUID) -> ConsentGrant | None:
        return self._consents.get(consent_id)

    def list_consents(self) -> list[ConsentGrant]:
        return sorted(self._consents.values(), key=lambda item: item.granted_at)

    # retention policies
    def save_policy(self, policy: RetentionPolicy) -> None:
        self._policies[policy.entity] = policy

    def get_policy(self, entity: RecordEntity) -> RetentionPolicy | None:
        return self._policies.get(entity)

    def list_policies(self) -> list[RetentionPolicy]:
        return sorted(self._policies.values(), key=lambda item: item.entity.value)

    # retention records
    def add_record(self, record: RetentionRecord) -> None:
        self._records[record.id] = record

    def save_record(self, record: RetentionRecord) -> None:
        if record.id not in self._records:
            raise KeyError(f"unknown retention record {record.id}")
        self._records[record.id] = record

    def get_record(self, record_id: UUID) -> RetentionRecord | None:
        return self._records.get(record_id)

    def list_records(self) -> list[RetentionRecord]:
        return sorted(self._records.values(), key=lambda item: item.anchor_at)

    # erasure requests
    def add_erasure(self, request: ErasureRequest) -> None:
        self._erasures[request.id] = request

    def save_erasure(self, request: ErasureRequest) -> None:
        if request.id not in self._erasures:
            raise KeyError(f"unknown erasure request {request.id}")
        self._erasures[request.id] = request

    def get_erasure(self, request_id: UUID) -> ErasureRequest | None:
        return self._erasures.get(request_id)

    def list_erasures(self) -> list[ErasureRequest]:
        return sorted(self._erasures.values(), key=lambda item: item.received_at)

    # breach incidents
    def add_incident(self, incident: BreachIncident) -> None:
        self._incidents[incident.id] = incident

    def save_incident(self, incident: BreachIncident) -> None:
        if incident.id not in self._incidents:
            raise KeyError(f"unknown breach incident {incident.id}")
        self._incidents[incident.id] = incident

    def get_incident(self, incident_id: UUID) -> BreachIncident | None:
        return self._incidents.get(incident_id)

    def list_incidents(self) -> list[BreachIncident]:
        return sorted(self._incidents.values(), key=lambda item: item.discovered_at)


class GrowthStore:
    """In-memory persistence for review cycles, assignments, summaries, goals."""

    def __init__(self) -> None:
        self._cycles: dict[UUID, ReviewCycle] = {}
        self._assignments: dict[UUID, ReviewAssignment] = {}
        self._summaries: dict[UUID, ReviewSummary] = {}
        self._goals: dict[UUID, Goal] = {}

    # cycles
    def add_cycle(self, cycle: ReviewCycle) -> None:
        self._cycles[cycle.id] = cycle

    def save_cycle(self, cycle: ReviewCycle) -> None:
        if cycle.id not in self._cycles:
            raise KeyError(f"unknown review cycle {cycle.id}")
        self._cycles[cycle.id] = cycle

    def get_cycle(self, cycle_id: UUID) -> ReviewCycle | None:
        return self._cycles.get(cycle_id)

    def list_cycles(self) -> list[ReviewCycle]:
        return sorted(self._cycles.values(), key=lambda item: item.created_at)

    # assignments
    def add_assignment(self, assignment: ReviewAssignment) -> None:
        self._assignments[assignment.id] = assignment

    def save_assignment(self, assignment: ReviewAssignment) -> None:
        if assignment.id not in self._assignments:
            raise KeyError(f"unknown review assignment {assignment.id}")
        self._assignments[assignment.id] = assignment

    def get_assignment(self, assignment_id: UUID) -> ReviewAssignment | None:
        return self._assignments.get(assignment_id)

    def list_assignments(self) -> list[ReviewAssignment]:
        return sorted(self._assignments.values(), key=lambda item: item.created_at)

    # summaries
    def add_summary(self, summary: ReviewSummary) -> None:
        self._summaries[summary.id] = summary

    def save_summary(self, summary: ReviewSummary) -> None:
        if summary.id not in self._summaries:
            raise KeyError(f"unknown review summary {summary.id}")
        self._summaries[summary.id] = summary

    def get_summary(self, summary_id: UUID) -> ReviewSummary | None:
        return self._summaries.get(summary_id)

    def list_summaries(self) -> list[ReviewSummary]:
        return sorted(self._summaries.values(), key=lambda item: item.created_at)

    # goals
    def add_goal(self, goal: Goal) -> None:
        self._goals[goal.id] = goal

    def save_goal(self, goal: Goal) -> None:
        if goal.id not in self._goals:
            raise KeyError(f"unknown goal {goal.id}")
        self._goals[goal.id] = goal

    def get_goal(self, goal_id: UUID) -> Goal | None:
        return self._goals.get(goal_id)

    def list_goals(self) -> list[Goal]:
        return sorted(self._goals.values(), key=lambda item: item.created_at)


class OffboardingStore:
    """In-memory persistence for offboarding templates, plans, and assets."""

    def __init__(self) -> None:
        self._templates: dict[UUID, OffboardingTemplate] = {}
        self._plans: dict[UUID, OffboardingPlan] = {}
        self._assets: dict[UUID, OffboardingAsset] = {}

    # templates
    def add_template(self, template: OffboardingTemplate) -> None:
        self._templates[template.id] = template

    def get_template(self, template_id: UUID) -> OffboardingTemplate | None:
        return self._templates.get(template_id)

    def list_templates(self) -> list[OffboardingTemplate]:
        return sorted(self._templates.values(), key=lambda item: item.name.lower())

    # plans
    def add_plan(self, plan: OffboardingPlan) -> None:
        self._plans[plan.id] = plan

    def save_plan(self, plan: OffboardingPlan) -> None:
        if plan.id not in self._plans:
            raise KeyError(f"unknown offboarding plan {plan.id}")
        self._plans[plan.id] = plan

    def get_plan(self, plan_id: UUID) -> OffboardingPlan | None:
        return self._plans.get(plan_id)

    def list_plans(self) -> list[OffboardingPlan]:
        return sorted(self._plans.values(), key=lambda item: item.started_at)

    # assets
    def add_asset(self, asset: OffboardingAsset) -> None:
        self._assets[asset.id] = asset

    def save_asset(self, asset: OffboardingAsset) -> None:
        if asset.id not in self._assets:
            raise KeyError(f"unknown asset {asset.id}")
        self._assets[asset.id] = asset

    def get_asset(self, asset_id: UUID) -> OffboardingAsset | None:
        return self._assets.get(asset_id)

    def list_assets(self) -> list[OffboardingAsset]:
        return sorted(self._assets.values(), key=lambda item: item.created_at)
