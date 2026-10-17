"""The CHECK constraints bite, one representative per family.

Every constraint in migration 0023 mirrors a Pydantic validator; these tests
prove the database enforces them even when the model never runs (a restore, a
replay, a hand-written INSERT). SQLite enforces CHECK constraints natively, so
these run locally and in CI alike; the Postgres job runs the same file with
real NUMERIC semantics behind the payroll rows.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import compliance_tables as ct
from hr_agents.db import people_tables as pt
from hr_agents.db.growth_tables import GoalRecord
from hr_agents.db.leave_tables import LeaveRequestRecord
from hr_agents.tenancy import DEFAULT_TENANT_ID

ANCHOR = datetime(2026, 1, 1, tzinfo=UTC)


def _expect_integrity_error(factory: sessionmaker[Session], row: object) -> None:
    with factory() as session:
        session.add(row)
        with pytest.raises(IntegrityError):
            session.commit()


def test_a_leave_request_cannot_end_before_it_starts(factory: sessionmaker[Session]) -> None:
    employee = pt.EmployeeRecord(
        id=uuid4(), tenant_id=DEFAULT_TENANT_ID, full_name="Sari Dewi", status="active"
    )
    with factory() as session:
        session.add(employee)
        session.commit()

    _expect_integrity_error(
        factory,
        LeaveRequestRecord(
            id=uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            employee_id=employee.id,
            leave_type="annual",
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 1),
            days=3.0,
            status="pending",
            created_at=ANCHOR,
            updated_at=ANCHOR,
        ),
    )


def test_a_pending_approval_cannot_name_a_decider(factory: sessionmaker[Session]) -> None:
    _expect_integrity_error(
        factory,
        pt.ApprovalRecord(
            id=uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            subject="leave_request",
            subject_id="leave-1",
            title="Approve leave",
            summary="",
            requested_by="hr-admin",
            assignee_role="manager",
            urgency="normal",
            status="pending",
            decided_by="manager-1",
            escalation_count=0,
            max_escalations=2,
        ),
    )


def test_a_decided_approval_needs_who_and_when(factory: sessionmaker[Session]) -> None:
    _expect_integrity_error(
        factory,
        pt.ApprovalRecord(
            id=uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            subject="leave_request",
            subject_id="leave-1",
            title="Approve leave",
            summary="",
            requested_by="hr-admin",
            assignee_role="manager",
            urgency="normal",
            status="approved",
            decided_by=None,
            escalation_count=0,
            max_escalations=2,
        ),
    )


def test_a_pkwt_without_an_end_date_is_refused(factory: sessionmaker[Session]) -> None:
    employee = pt.EmployeeRecord(
        id=uuid4(), tenant_id=DEFAULT_TENANT_ID, full_name="Sari Dewi", status="active"
    )
    with factory() as session:
        session.add(employee)
        session.commit()

    _expect_integrity_error(
        factory,
        pt.ContractRecord(
            id=uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            employee_id=employee.id,
            contract_type="pkwt",
            start_date=date(2026, 1, 1),
            status="draft",
            compensation_due=False,
        ),
    )


def test_a_retention_policy_needs_a_real_window(factory: sessionmaker[Session]) -> None:
    _expect_integrity_error(
        factory,
        ct.RetentionPolicyTable(
            id=uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            entity="employee",
            name="Employee records",
            retention_months=0,
            expiry_action="anonymize",
            updated_by="hr-admin",
        ),
    )


def test_a_legal_hold_needs_a_reason(factory: sessionmaker[Session]) -> None:
    _expect_integrity_error(
        factory,
        ct.RetentionRecordTable(
            id=uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            entity="employee",
            subject_kind="employee",
            subject_id="emp-1",
            label="",
            anchor_at=ANCHOR,
            legal_hold=True,
            legal_hold_reason=None,
            created_at=ANCHOR,
        ),
    )


def test_a_goal_cannot_progress_beyond_a_hundred(factory: sessionmaker[Session]) -> None:
    _expect_integrity_error(
        factory,
        GoalRecord(
            id=uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            employee_id=uuid4(),
            title="Ship the thing",
            description="",
            status="active",
            progress_percent=140.0,
        ),
    )


def test_the_control_row_is_accepted(factory: sessionmaker[Session]) -> None:
    """The same shape with valid values writes cleanly, so the tests above are
    detecting the constraints and not a broken fixture."""
    with factory() as session:
        session.add(
            ct.RetentionPolicyTable(
                id=uuid4(),
                tenant_id=DEFAULT_TENANT_ID,
                entity="employee",
                name="Employee records",
                retention_months=24,
                expiry_action="anonymize",
                updated_by="hr-admin",
            )
        )
        session.commit()
