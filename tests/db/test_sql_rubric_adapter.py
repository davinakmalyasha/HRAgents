"""Rubric registry adapter tests on in-memory SQLite."""

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.rubrics import DbRubricStore
from hr_agents.identity import ActorRef
from hr_agents.models import JobFamily
from hr_agents.services.dimensions import ENGINEERING
from hr_agents.services.rubrics import RubricRegistry

HUMAN = ActorRef.legacy("hr-admin")


def test_rubric_versions_round_trip_and_resolve(factory: sessionmaker[Session]) -> None:
    registry = RubricRegistry(DbRubricStore(factory))
    draft = registry.create_version(
        family=JobFamily.ENGINEERING, template=ENGINEERING, actor=HUMAN, note="baseline"
    )
    registry.verify(draft.id, actor=HUMAN, source_note="baseline approved")
    registry.activate(draft.id, actor=HUMAN)

    fresh = RubricRegistry(DbRubricStore(factory))
    active = fresh.active_version(JobFamily.ENGINEERING)
    assert active is not None
    assert active.id == draft.id
    assert active.verified_by == "hr-admin"
    assert active.verified_note == "baseline approved"

    template, snapshot = fresh.resolve(JobFamily.ENGINEERING)
    assert template == ENGINEERING
    assert snapshot.digest == draft.digest
    assert [item.id for item in fresh.versions(JobFamily.ENGINEERING)] == [draft.id]
    assert fresh.active_version(JobFamily.FINANCE) is None


def test_activating_a_new_revision_deactivates_the_old_row(
    factory: sessionmaker[Session],
) -> None:
    registry = RubricRegistry(DbRubricStore(factory))
    first = registry.create_version(
        family=JobFamily.ENGINEERING,
        template=ENGINEERING.model_copy(update={"breadth_saturation": 42}),
        actor=HUMAN,
    )
    registry.verify(first.id, actor=HUMAN, source_note="first")
    registry.activate(first.id, actor=HUMAN)

    second = registry.create_version(
        family=JobFamily.ENGINEERING,
        template=ENGINEERING.model_copy(update={"breadth_saturation": 7}),
        actor=HUMAN,
    )
    assert second.revision == 2
    registry.verify(second.id, actor=HUMAN, source_note="second")
    registry.activate(second.id, actor=HUMAN)

    fresh = RubricRegistry(DbRubricStore(factory))
    assert fresh.active_version(JobFamily.ENGINEERING).id == second.id  # type: ignore[union-attr]
    assert [item.active for item in fresh.versions(JobFamily.ENGINEERING)] == [False, True]
    template, snapshot = fresh.resolve(JobFamily.ENGINEERING)
    assert template.breadth_saturation == 7
    assert snapshot.digest == second.digest
