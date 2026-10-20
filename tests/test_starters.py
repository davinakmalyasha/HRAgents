"""Starter content: process templates are seeded; statutory values never are."""

from __future__ import annotations

from hr_agents.services.people import PeopleServices
from hr_agents.setup import setup_actor
from hr_agents.starters import (
    STARTER_OFFBOARDING_NAME,
    STARTER_ONBOARDING_NAME,
    STARTER_RATE_TABLES,
    seed_starters,
)


def test_starters_seed_templates_and_empty_rate_shells() -> None:
    people = PeopleServices()
    report = seed_starters(people, actor=setup_actor("Rina"))

    assert f"onboarding_template:{STARTER_ONBOARDING_NAME}" in report.created
    assert f"offboarding_template:{STARTER_OFFBOARDING_NAME}" in report.created
    assert len([item for item in report.created if item.startswith("rate_table:")]) == len(
        STARTER_RATE_TABLES
    )

    onboarding = people.onboarding.list_templates(active_only=False)
    assert [template.name for template in onboarding] == [STARTER_ONBOARDING_NAME]
    assert len(onboarding[0].steps) == 5

    offboarding = people.offboarding.list_templates(active_only=False)
    assert [template.name for template in offboarding] == [STARTER_OFFBOARDING_NAME]
    final_pay = next(step for step in offboarding[0].steps if step.key == "final_pay")
    assert final_pay.requires_human_signoff is True

    tables = people.rate_tables.list_all()
    assert {table.kind for table in tables} == set(STARTER_RATE_TABLES)
    assert all(not table.verified for table in tables), "values must be entered by a human"
    assert all(table.entries == [] for table in tables), "no statutory numbers are seeded"

    assert people.leave.list_policies() == [], "leave entitlement is an operator policy"
    assert people.audit.verify() == -1


def test_seeding_twice_changes_nothing() -> None:
    people = PeopleServices()
    first = seed_starters(people, actor=setup_actor("Rina"))
    assert first.changed

    second = seed_starters(people, actor=setup_actor("Rina"))
    assert second.created == []
    assert len(second.skipped) == len(first.created)
