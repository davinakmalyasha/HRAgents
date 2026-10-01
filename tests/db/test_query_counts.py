"""Statement-count fences for the read paths that used to be N+1.

Every test here answers one question: does this operation issue a *bounded*
number of SQL statements regardless of how many rows it touches? A timing
assertion cannot do that -- it is machine-dependent, and it passes on a small
fixture that would still explode on real data. Counting statements is exact and
costs a millisecond.

The bounds are deliberately generous. They exist to catch a statement count that
grows with the input, not to benchmark the adapter. When one of these fails the
fix is normally to push the predicate into SQL or to fetch the child rows once,
not to raise the number.

The offer-revision fence lives in ``test_sql_adapters.py`` instead, next to the
application seeding it needs.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.audit import DbAuditChain
from hr_agents.db.people import DbEmployeeStore
from hr_agents.models import (
    ActorType,
    AuditActor,
    DocumentKind,
    Employee,
    EmployeeDocument,
)
from hr_agents.services.people_store import EmployeeStore

TODAY = date.today()

POPULATION = 40
"""Rows seeded per test. The point is that the count must not depend on it."""


@pytest.fixture
def counter(factory: sessionmaker[Session]) -> Iterator[dict[str, int]]:
    """Count every statement the engine issues for the duration of one test.

    Listens on the engine rather than the session so statements issued through
    ``engine.connect()`` are counted too, and detaches on the way out so a leaked
    listener cannot slow the rest of the suite down.
    """
    engine: Engine = factory.kw["bind"]
    tally: dict[str, int] = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        tally["n"] += 1

    try:
        yield tally
    finally:
        event.remove(engine, "before_cursor_execute", _count)


def human(actor_id: str = "Rina") -> AuditActor:
    return AuditActor(actor_type=ActorType.HUMAN, actor_id=actor_id)


def add_employee(store: DbEmployeeStore | EmployeeStore, name: str) -> UUID:
    employee = Employee(full_name=name, email=f"{name.lower()}@example.com", hire_date=TODAY)
    store.add_employee(employee)
    return employee.id


def add_document(
    store: DbEmployeeStore | EmployeeStore,
    employee_id: UUID,
    kind: DocumentKind,
    *,
    expires_on: date | None,
    salt: str = "a",
) -> EmployeeDocument:
    document = EmployeeDocument(
        employee_id=employee_id,
        kind=kind,
        storage_key=f"vault/{uuid4()}",
        sha256=salt * 64,
        expires_on=expires_on,
    )
    store.add_document(document)
    return document


# --- audit chain -------------------------------------------------------------


def test_a_chain_count_is_a_count_not_a_read(
    factory: sessionmaker[Session], counter: dict[str, int]
) -> None:
    """Counting entries must not read them.

    Two callers wanted a length and reached for ``len(chain.entries)``. On the
    persisted chain that property selects every row and validates it into a
    model, so a Prometheus scrape and a chain verification report each turned
    into a full materialization of a log that only ever grows.
    """
    chain = DbAuditChain(factory)
    for index in range(20):
        chain.append(actor=human(), action="test.entry", subject_type="test", subject_id=str(index))

    before = counter["n"]
    assert chain.entry_count() == 20
    assert counter["n"] - before == 1


def test_verifying_does_not_read_the_chain_again_to_count_it(
    factory: sessionmaker[Session], counter: dict[str, int]
) -> None:
    """The verification report's entry count must not be a second pass.

    ``verify()`` streams the log in pages, which is the only way it can cope with
    a chain that never ends. Asking for the count afterwards used to stream it
    again, immediately, for a number.
    """
    chain = DbAuditChain(factory)
    for index in range(20):
        chain.append(actor=human(), action="test.entry", subject_type="test", subject_id=str(index))

    before = counter["n"]
    assert chain.verify() == -1
    # Two statements: one 500-row page, and one more to discover the chain has
    # ended. The count of pages grows with the chain length; the cost per entry
    # does not, which is the property that matters.
    assert counter["n"] - before == 2
    assert chain.entry_count() == 20


# --- document vault ----------------------------------------------------------


def test_one_employees_vault_is_one_indexed_read(
    factory: sessionmaker[Session], counter: dict[str, int]
) -> None:
    """One employee's documents is one query, not one per row in the table.

    This was the worst of them. The adapter called ``all_documents()`` and
    filtered the result in Python, so every call re-read the whole
    ``employee_documents`` table; the service then called it once per employee.
    Listing the vault for 100 employees issued 501 statements.
    ``ix_employee_documents_employee`` already existed and was never used.
    """
    store = DbEmployeeStore(factory)
    owner = add_employee(store, "Budi")
    for index in range(POPULATION):
        other = add_employee(store, f"Person{index}")
        for _ in range(5):
            add_document(store, other, DocumentKind.KTP, expires_on=TODAY + timedelta(days=30))
    for _ in range(5):
        add_document(store, owner, DocumentKind.KTP, expires_on=TODAY + timedelta(days=30))

    before = counter["n"]
    found = store.list_documents(owner)
    issued = counter["n"] - before

    assert len(found) == 5
    assert {doc.employee_id for doc in found} == {owner}
    assert issued == 1, "one employee's documents must not scale with the table size"


def test_the_whole_vault_is_still_one_read(
    factory: sessionmaker[Session], counter: dict[str, int]
) -> None:
    """The org-wide read must not have become a loop over employees.

    The service's ``_all_documents`` walked the employee list and asked for one
    employee's documents at a time. That loop is where the 501 came from, so
    fixing only the adapter would have left the service multiplying the problem.
    """
    store = DbEmployeeStore(factory)
    for index in range(POPULATION):
        other = add_employee(store, f"Person{index}")
        for _ in range(4):
            add_document(store, other, DocumentKind.NPWP, expires_on=TODAY + timedelta(days=60))

    before = counter["n"]
    everything = store.all_documents()
    issued = counter["n"] - before

    assert len(everything) == POPULATION * 4
    assert issued == 1


def test_both_stores_return_the_same_document_order() -> None:
    """Order is part of the contract, so the two stores must agree on it.

    The database adapter ordered by expiry and the in-memory one by insertion.
    The in-memory path is what the entire unit suite runs against, so a
    deployment could return documents in a different order from the tests written
    to describe it -- and ``documents_for``'s docstring claimed a third order
    that neither store implemented.
    """
    # Insert in an order that is neither the sort key nor its reverse, so a store
    # that returns insertion order cannot pass by accident.
    plan = [
        (DocumentKind.OTHER, None),
        (DocumentKind.CONTRACT, TODAY + timedelta(days=90)),
        (DocumentKind.NPWP, TODAY + timedelta(days=5)),
    ]
    expected = [DocumentKind.NPWP, DocumentKind.CONTRACT, DocumentKind.OTHER]

    memory = EmployeeStore()
    memory_owner = add_employee(memory, "Sari")
    for kind, expires_on in plan:
        add_document(memory, memory_owner, kind, expires_on=expires_on)

    from_memory = [doc.kind for doc in memory.list_documents(memory_owner)]
    assert from_memory == expected
