"""Row-level tenancy isolation (PostgreSQL only).

Runs when ``HRAGENTS_TEST_DB_URL`` is set (the adapter fixture enables the RLS
policies and connects as a non-superuser role); skipped on SQLite.
"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import people_tables as pt
from hr_agents.db.people import DbEmployeeStore
from hr_agents.db.session import sync_session_scope
from hr_agents.models import Employee, EmployeeStatus
from hr_agents.tenancy import DEFAULT_TENANT_ID

pytestmark = pytest.mark.skipif(
    not os.environ.get("HRAGENTS_TEST_DB_URL"),
    reason="RLS requires PostgreSQL; set HRAGENTS_TEST_DB_URL",
)

OTHER_TENANT = uuid4()


def _employee(name: str) -> Employee:
    return Employee(full_name=name, status=EmployeeStatus.ACTIVE)


def test_unset_tenant_sees_only_default_rows(factory: sessionmaker[Session]) -> None:
    store = DbEmployeeStore(factory)
    store.add_employee(_employee("Sari Dewi"))

    other = _employee("Other Tenant")
    with sync_session_scope(factory, tenant_id=OTHER_TENANT) as session:
        session.add(
            pt.EmployeeRecord(
                id=other.id,
                tenant_id=OTHER_TENANT,
                full_name="Other Tenant",
                status="active",
            )
        )

    assert [item.full_name for item in store.list_employees()] == ["Sari Dewi"]

    with sync_session_scope(factory, tenant_id=OTHER_TENANT) as session:
        rows = session.execute(select(pt.EmployeeRecord)).scalars().all()
    assert [row.full_name for row in rows] == ["Other Tenant"]


def test_app_writes_default_to_the_default_tenant(factory: sessionmaker[Session]) -> None:
    store = DbEmployeeStore(factory)
    employee = _employee("Budi Santoso")
    store.add_employee(employee)
    with factory() as session:
        row = session.get(pt.EmployeeRecord, employee.id)
        assert row is not None
        assert row.tenant_id == DEFAULT_TENANT_ID


def test_write_check_blocks_cross_tenant_inserts(factory: sessionmaker[Session]) -> None:
    with (
        pytest.raises(DBAPIError),
        sync_session_scope(factory, tenant_id=OTHER_TENANT) as session,
    ):
        session.add(
            pt.EmployeeRecord(
                id=uuid4(),
                full_name="Wrong Tenant",
                status="active",
            )
        )


def test_write_check_allows_matching_tenant_inserts(factory: sessionmaker[Session]) -> None:
    with sync_session_scope(factory, tenant_id=OTHER_TENANT) as session:
        session.add(
            pt.EmployeeRecord(
                id=uuid4(),
                tenant_id=OTHER_TENANT,
                full_name="Matching Tenant",
                status="active",
            )
        )
    with sync_session_scope(factory, tenant_id=OTHER_TENANT) as session:
        rows = session.execute(select(pt.EmployeeRecord)).scalars().all()
    assert [row.full_name for row in rows] == ["Matching Tenant"]
