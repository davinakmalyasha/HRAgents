"""The rubric registry: versions, the verified gate, and the code fallback."""

from __future__ import annotations

from typing import Any, cast

import pytest

from hr_agents.identity import ActorRef
from hr_agents.models import JobFamily, PolicyThresholds
from hr_agents.services.dimensions import ENGINEERING, DimensionTemplate, snapshot_for
from hr_agents.services.rubrics import RubricError, RubricRegistry, RubricStore

HUMAN = ActorRef.legacy("hr-admin")
AGENT = ActorRef.agent("resume_deconstructor")


def variant(**overrides: object) -> DimensionTemplate:
    return ENGINEERING.model_copy(update=overrides)


def test_an_empty_registry_resolves_the_code_template() -> None:
    template, snapshot = RubricRegistry().resolve(JobFamily.ENGINEERING)
    assert template == ENGINEERING
    assert snapshot == snapshot_for(JobFamily.ENGINEERING)


def test_version_lifecycle_and_single_active_version() -> None:
    registry = RubricRegistry()
    first = registry.create_version(
        family=JobFamily.ENGINEERING,
        template=variant(breadth_saturation=99),
        actor=HUMAN,
        note="wider breadth window",
    )
    assert (first.revision, first.active, first.verified_by) == (1, False, None)

    with pytest.raises(RubricError, match="identical"):
        registry.create_version(
            family=JobFamily.ENGINEERING,
            template=variant(breadth_saturation=99),
            actor=HUMAN,
        )

    with pytest.raises(RubricError, match="unverified"):
        registry.activate(first.id, actor=HUMAN)

    verified = registry.verify(first.id, actor=HUMAN, source_note="HR approved the taxonomy")
    assert verified.verified_by == "hr-admin"
    assert verified.verified_note == "HR approved the taxonomy"
    registry.activate(first.id, actor=HUMAN)

    template, snapshot = registry.resolve(JobFamily.ENGINEERING)
    assert template == variant(breadth_saturation=99)
    assert snapshot.digest == first.digest

    second = registry.create_version(
        family=JobFamily.ENGINEERING,
        template=variant(breadth_saturation=42),
        actor=HUMAN,
    )
    assert second.revision == 2
    registry.verify(second.id, actor=HUMAN, source_note="second revision")
    registry.activate(second.id, actor=HUMAN)

    assert registry.get(first.id).active is False
    assert registry.get(second.id).active is True
    assert registry.resolve(JobFamily.ENGINEERING)[0] == variant(breadth_saturation=42)


def test_mismatched_family_and_non_humans_are_refused() -> None:
    registry = RubricRegistry()
    with pytest.raises(RubricError, match="does not match"):
        registry.create_version(family=JobFamily.FINANCE, template=ENGINEERING, actor=HUMAN)
    with pytest.raises(RubricError, match="named human"):
        registry.create_version(family=JobFamily.ENGINEERING, template=ENGINEERING, actor=AGENT)

    draft = registry.create_version(
        family=JobFamily.ENGINEERING,
        template=variant(signal_saturation=2),
        actor=HUMAN,
    )
    with pytest.raises(RubricError, match="named human"):
        registry.verify(draft.id, actor=AGENT, source_note="agent cannot certify")
    with pytest.raises(RubricError, match="source note"):
        registry.verify(draft.id, actor=HUMAN, source_note="   ")

    registry.verify(draft.id, actor=HUMAN, source_note="approved")
    with pytest.raises(RubricError, match="already verified"):
        registry.verify(draft.id, actor=HUMAN, source_note="approved again")
    with pytest.raises(RubricError, match="named human"):
        registry.activate(draft.id, actor=AGENT)


def test_a_tampered_payload_is_refused_at_scoring_time() -> None:
    """A row edited in the database must not silently score candidates."""
    store = RubricStore()
    registry = RubricRegistry(store)
    draft = registry.create_version(
        family=JobFamily.ENGINEERING,
        template=variant(signal_saturation=2),
        actor=HUMAN,
    )
    registry.verify(draft.id, actor=HUMAN, source_note="approved")
    registry.activate(draft.id, actor=HUMAN)

    active = registry.get(draft.id)
    store.save(
        active.model_copy(
            update={"template": {**active.template, "description": "edited outside the service"}}
        )
    )

    with pytest.raises(RubricError, match="does not match its digest"):
        registry.resolve(JobFamily.ENGINEERING)


def test_thresholds_travel_with_the_verified_version() -> None:
    registry = RubricRegistry()
    revised = variant(
        breadth_saturation=42,
        thresholds=PolicyThresholds(auto_schedule_min_score=0.75, min_interviewer_slots=3),
    )
    draft = registry.create_version(family=JobFamily.ENGINEERING, template=revised, actor=HUMAN)
    registry.verify(draft.id, actor=HUMAN, source_note="threshold policy approved")
    registry.activate(draft.id, actor=HUMAN)

    template, snapshot = registry.resolve(JobFamily.ENGINEERING)
    assert template.thresholds is not None
    assert template.thresholds.auto_schedule_min_score == 0.75
    assert template.thresholds.min_interviewer_slots == 3
    snapshot_thresholds = cast("dict[str, Any]", snapshot.template["thresholds"])
    assert snapshot_thresholds["auto_schedule_min_score"] == 0.75

    threshold_only = variant(
        breadth_saturation=42,
        thresholds=PolicyThresholds(auto_schedule_min_score=0.80),
    )
    second = registry.create_version(
        family=JobFamily.ENGINEERING, template=threshold_only, actor=HUMAN
    )
    assert second.revision == 2, "thresholds are content, so the digest differs"
