"""Approval-backed document requests: demand nothing without a human."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from tests.actors import hr_admin, manager

from hr_agents.models import (
    ApprovalStatus,
    ApproverRole,
    DocumentKind,
    Employee,
    business_today,
)
from hr_agents.services import DocumentRequestError, EmployeeError
from hr_agents.services.document_requests import (
    DOCUMENT_REQUEST_TASK_SUBJECT,
    DocumentRequestService,
)
from hr_agents.services.people import PeopleServices


def services() -> PeopleServices:
    return PeopleServices()


def make_employee(service: PeopleServices, *, name: str = "Rudi Hartono") -> Employee:
    return service.employees.create(
        full_name=name,
        actor=hr_admin(),
        hire_date=business_today() - timedelta(days=400),
        job_title="Engineering Lead",
    )


def make_service() -> tuple[PeopleServices, DocumentRequestService]:
    people = services()
    return people, people.document_requests


def test_a_request_creates_an_approval_and_no_task() -> None:
    people, service = make_service()
    employee = make_employee(people)

    request = service.request_document(
        employee_id=employee.id,
        kind=DocumentKind.KTP,
        reason="Payroll needs the ID for tax reporting.",
        actor=hr_admin(),
    )

    assert request.status is ApprovalStatus.PENDING
    assert request.assignee_role is ApproverRole.MANAGER
    assert request.payload["employee_id"] == str(employee.id)
    assert request.payload["kind"] == "ktp"
    assert people.tasks.open_tasks() == []


def test_a_repeat_request_returns_the_open_approval() -> None:
    people, service = make_service()
    employee = make_employee(people)
    first = service.request_document(
        employee_id=employee.id,
        kind=DocumentKind.KTP,
        reason="Payroll needs the ID.",
        actor=hr_admin(),
    )

    second = service.request_document(
        employee_id=employee.id,
        kind=DocumentKind.KTP,
        reason="Payroll needs the ID.",
        actor=hr_admin(),
    )

    assert second.id == first.id
    assert len(people.approvals.list_all()) == 1


def test_a_request_for_an_unknown_employee_is_a_404() -> None:
    _, service = make_service()

    with pytest.raises(EmployeeError) as exc:
        service.request_document(
            employee_id=uuid4(),
            kind=DocumentKind.KTP,
            reason="Payroll needs the ID.",
            actor=hr_admin(),
        )
    assert exc.value.status == 404


def test_a_request_without_a_reason_or_with_a_past_due_date_is_refused() -> None:
    people, service = make_service()
    employee = make_employee(people)

    with pytest.raises(DocumentRequestError, match="reason is required") as exc:
        service.request_document(
            employee_id=employee.id,
            kind=DocumentKind.KTP,
            reason="  ",
            actor=hr_admin(),
        )
    assert exc.value.status == 422

    with pytest.raises(DocumentRequestError, match="in the past") as exc:
        service.request_document(
            employee_id=employee.id,
            kind=DocumentKind.KTP,
            reason="Payroll needs the ID.",
            actor=hr_admin(),
            due_on=business_today() - timedelta(days=1),
        )
    assert exc.value.status == 422


def test_sync_before_a_decision_refuses() -> None:
    people, service = make_service()
    employee = make_employee(people)
    request = service.request_document(
        employee_id=employee.id,
        kind=DocumentKind.KTP,
        reason="Payroll needs the ID.",
        actor=hr_admin(),
    )

    with pytest.raises(DocumentRequestError, match="is pending"):
        service.sync_from_approval(request.id, actor=hr_admin())
    assert people.tasks.open_tasks() == []


def test_sync_after_approval_creates_the_employee_task_exactly_once() -> None:
    people, service = make_service()
    employee = make_employee(people)
    request = service.request_document(
        employee_id=employee.id,
        kind=DocumentKind.KTP,
        reason="Payroll needs the ID for tax reporting.",
        actor=hr_admin(),
        due_on=business_today() + timedelta(days=14),
    )
    people.approvals.decide(request.id, actor=manager(), approve=True, reason="legitimate need")

    task = service.sync_from_approval(request.id, actor=hr_admin())

    assert task.assignee_id == str(employee.id)
    assert task.related_subject == DOCUMENT_REQUEST_TASK_SUBJECT
    assert task.related_id == str(request.id)
    assert "KTP" in task.title
    assert task.is_open

    again = service.sync_from_approval(request.id, actor=hr_admin())
    assert again.id == task.id
    assert (
        len(
            people.tasks.open_for_related(
                related_subject=DOCUMENT_REQUEST_TASK_SUBJECT, related_id=str(request.id)
            )
        )
        == 1
    )


def test_sync_after_rejection_creates_nothing() -> None:
    people, service = make_service()
    employee = make_employee(people)
    request = service.request_document(
        employee_id=employee.id,
        kind=DocumentKind.BANK_ACCOUNT,
        reason="Finance wants bank details.",
        actor=hr_admin(),
    )
    people.approvals.decide(request.id, actor=manager(), approve=False, reason="ask later")

    with pytest.raises(DocumentRequestError, match="is rejected"):
        service.sync_from_approval(request.id, actor=hr_admin())
    assert people.tasks.open_tasks() == []


def test_sync_of_an_unknown_approval_is_a_404() -> None:
    _, service = make_service()

    with pytest.raises(DocumentRequestError) as exc:
        service.sync_from_approval(uuid4(), actor=hr_admin())
    assert exc.value.status == 404
