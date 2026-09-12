"""Request/response schemas for the people, contracts, approvals, and tasks APIs."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import EmailStr, Field

from hr_agents.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    Contract,
    ContractStatus,
    ContractType,
    DocumentKind,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    RateTable,
    RateTableKind,
    StrictModel,
    TaskItem,
    TaskPriority,
    TaskSource,
    TaskStatus,
    Urgency,
)

# --- employees ---------------------------------------------------------------


class EmployeeCreate(StrictModel):
    full_name: str = Field(min_length=1, max_length=200)
    hire_date: date
    created_by: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=120)
    org_unit_id: UUID | None = None
    manager_id: UUID | None = None
    work_location: str | None = Field(default=None, max_length=120)
    probation_end_date: date | None = None
    employee_number: str | None = Field(default=None, max_length=40)


class EmployeeView(StrictModel):
    id: UUID
    full_name: str
    email: str | None
    job_title: str | None
    status: EmployeeStatus
    hire_date: date | None
    probation_end_date: date | None
    offboarded_on: date | None
    org_unit_id: UUID | None
    manager_id: UUID | None

    @classmethod
    def from_model(cls, employee: Employee) -> EmployeeView:
        return cls(
            id=employee.id,
            full_name=employee.full_name,
            email=str(employee.email) if employee.email else None,
            job_title=employee.job_title,
            status=employee.status,
            hire_date=employee.hire_date,
            probation_end_date=employee.probation_end_date,
            offboarded_on=employee.offboarded_on,
            org_unit_id=employee.org_unit_id,
            manager_id=employee.manager_id,
        )


class EmployeeTransitionRequest(StrictModel):
    target: EmployeeStatus
    by: str = Field(min_length=1, max_length=200)
    force: bool = False
    reason: str | None = Field(default=None, max_length=1000)


class DocumentCreate(StrictModel):
    kind: DocumentKind
    storage_key: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    uploaded_by: str = Field(min_length=1, max_length=200)
    filename: str | None = None
    issued_on: date | None = None
    expires_on: date | None = None


class DocumentView(StrictModel):
    id: UUID
    employee_id: UUID
    kind: DocumentKind
    storage_key: str
    filename: str | None
    sha256: str
    expires_on: date | None
    status: str

    @classmethod
    def from_model(cls, document: EmployeeDocument) -> DocumentView:
        return cls(
            id=document.id,
            employee_id=document.employee_id,
            kind=document.kind,
            storage_key=document.storage_key,
            filename=document.filename,
            sha256=document.sha256,
            expires_on=document.expires_on,
            status=document.status.value,
        )


# --- contracts ---------------------------------------------------------------


class ContractCreate(StrictModel):
    employee_id: UUID
    contract_type: ContractType
    start_date: date
    created_by: str = Field(min_length=1, max_length=200)
    end_date: date | None = None
    probation_end_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ContractView(StrictModel):
    id: UUID
    employee_id: UUID
    contract_type: ContractType
    start_date: date
    end_date: date | None
    status: ContractStatus
    probation_end_date: date | None
    signed_on: date | None
    compensation_due: bool
    days_until_expiry: int | None

    @classmethod
    def from_model(cls, contract: Contract) -> ContractView:
        return cls(
            id=contract.id,
            employee_id=contract.employee_id,
            contract_type=contract.contract_type,
            start_date=contract.start_date,
            end_date=contract.end_date,
            status=contract.status,
            probation_end_date=contract.probation_end_date,
            signed_on=contract.signed_on,
            compensation_due=contract.compensation_due,
            days_until_expiry=contract.days_until_expiry(),
        )


class ContractActionRequest(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


# --- approvals ---------------------------------------------------------------


class ApprovalCreate(StrictModel):
    subject: ApprovalSubject
    subject_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    assignee_role: ApproverRole
    requested_by: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    urgency: Urgency = Urgency.NORMAL
    requested_by_agent: bool = False


class ApprovalDecisionRequest(StrictModel):
    decided_by: str = Field(min_length=1, max_length=200)
    approve: bool
    reason: str | None = Field(default=None, max_length=500)


class ApprovalView(StrictModel):
    id: UUID
    subject: ApprovalSubject
    subject_id: str
    title: str
    summary: str
    requested_by: str
    requested_by_agent: bool
    assignee_role: ApproverRole
    urgency: Urgency
    status: ApprovalStatus
    escalation_count: int
    created_at: datetime
    sla_deadline: datetime | None
    is_overdue: bool

    @classmethod
    def from_model(cls, request: ApprovalRequest) -> ApprovalView:
        return cls(
            id=request.id,
            subject=request.subject,
            subject_id=request.subject_id,
            title=request.title,
            summary=request.summary,
            requested_by=request.requested_by,
            requested_by_agent=request.requested_by_agent,
            assignee_role=request.assignee_role,
            urgency=request.urgency,
            status=request.status,
            escalation_count=request.escalation_count,
            created_at=request.created_at,
            sla_deadline=request.sla_deadline,
            is_overdue=request.is_overdue(),
        )


class ApprovalDecisionResponse(StrictModel):
    request: ApprovalView
    action: str


# --- tasks -------------------------------------------------------------------


class TaskCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    assignee_role: ApproverRole | None = None
    assignee_id: str | None = Field(default=None, max_length=200)
    due_on: date | None = None
    priority: TaskPriority = TaskPriority.NORMAL
    related_subject: str | None = Field(default=None, max_length=60)
    related_id: str | None = Field(default=None, max_length=200)


class TaskCompleteRequest(StrictModel):
    by: str = Field(min_length=1, max_length=200)


class TaskView(StrictModel):
    id: UUID
    title: str
    description: str
    assignee_role: ApproverRole | None
    due_on: date | None
    priority: TaskPriority
    status: TaskStatus
    source: TaskSource
    related_subject: str | None
    related_id: str | None
    created_by: str
    is_overdue: bool

    @classmethod
    def from_model(cls, task: TaskItem) -> TaskView:
        return cls(
            id=task.id,
            title=task.title,
            description=task.description,
            assignee_role=task.assignee_role,
            due_on=task.due_on,
            priority=task.priority,
            status=task.status,
            source=task.source,
            related_subject=task.related_subject,
            related_id=task.related_id,
            created_by=task.created_by,
            is_overdue=task.is_overdue(),
        )


# --- rate tables -------------------------------------------------------------


class RateTableCreate(StrictModel):
    kind: RateTableKind
    name: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    jurisdiction: str = Field(default="ID", min_length=2, max_length=2)


class RateTableView(StrictModel):
    id: UUID
    kind: RateTableKind
    name: str
    jurisdiction: str
    entry_count: int
    verified: bool
    usable: bool
    verified_by: str | None
    source_note: str | None

    @classmethod
    def from_model(cls, table: RateTable) -> RateTableView:
        from hr_agents.models import RateTable

        assert isinstance(table, RateTable)
        return cls(
            id=table.id,
            kind=table.kind,
            name=table.name,
            jurisdiction=table.jurisdiction,
            entry_count=len(table.entries),
            verified=table.verified,
            usable=table.usable,
            verified_by=table.verified_by,
            source_note=table.source_note,
        )
