"""The demo seeder populates a fresh app and refuses to seed twice.

Everything is created through the real services, so these assertions double as
a wiring check: if the seed leaves no pending approval, no tracked retention
row or no unverified rate table, the demo screens would tell a different story
than the product's own rules.
"""

from hr_agents.demo import seed_demo
from hr_agents.main import create_app
from hr_agents.models import ApprovalStatus, RecordEntity


def test_the_demo_seed_populates_and_is_idempotent() -> None:
    app = create_app()
    first = seed_demo(app)

    assert first.seeded is True
    assert first.employees == 5
    assert first.applications == 2

    people = app.state.people
    numbers = {employee.employee_number for employee in people.employees.list_employees()}
    assert numbers == {f"DEMO-00{index}" for index in range(1, 6)}

    pending = [
        request
        for request in people.approvals._store.list_all()
        if request.status is ApprovalStatus.PENDING
    ]
    assert pending, "the seeded leave request must raise an approval for the demo queue"

    tables = people.rate_tables.list_all()
    assert tables, "the payroll workspace needs tables to show the verification gate"
    assert all(not table.verified for table in tables), (
        "demo rate tables stay unverified: payroll must refuse invented figures"
    )

    assert len(app.state.store.list_all()) == 2
    assert len(people.compliance.list_records(entity=RecordEntity.APPLICATION)) == 2

    second = seed_demo(app)
    assert second.seeded is False
    assert "already present" in second.note
    assert len(people.employees.list_employees()) == 5
    assert len(app.state.store.list_all()) == 2
