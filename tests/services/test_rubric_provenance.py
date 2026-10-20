"""The rubric snapshot: deterministic, content-addressed, attached at scoring time."""

from __future__ import annotations

import json
from typing import Any, cast

from hr_agents.models import JobFamily, PolicyThresholds
from hr_agents.services.dimensions import (
    ENGINEERING,
    canonical_payload,
    families,
    rubric_digest,
    snapshot_for,
    template_for,
)


def test_every_family_has_a_snapshot() -> None:
    for family in families():
        snapshot = snapshot_for(family)
        assert snapshot.family == family
        assert len(snapshot.digest) == 64
        assert snapshot.template["family"] == family.value


def test_digest_is_stable_for_the_same_content() -> None:
    assert rubric_digest(template_for(JobFamily.ENGINEERING)) == rubric_digest(ENGINEERING)


def test_canonical_payload_sorts_every_set_derived_list() -> None:
    """Hash randomisation must not reach the digest.

    Three fields come from frozensets; set iteration order is an implementation
    detail, so the canonical payload sorts them. Tier order is semantic (most
    senior first) and is preserved.
    """
    payload = canonical_payload(ENGINEERING)
    breadth = cast("list[str]", payload["breadth_vocabulary"])
    categories = cast("list[str]", payload["professional_categories"])
    tiers = cast("list[list[Any]]", payload["title_tiers"])
    assert breadth == sorted(breadth)
    assert categories == sorted(categories)
    for keywords, _weight in tiers:
        assert keywords == sorted(keywords)


def test_engineering_digest_is_pinned() -> None:
    """A change to the engineering rubric must be deliberate.

    The digest is the identity every stored evaluation cites; if it moves
    without the rubric moving, canonicalisation is broken. If the rubric moves,
    this constant is the reviewer's prompt to say so.
    """
    assert rubric_digest(ENGINEERING) == (
        "64c9c8ce80752d5dc9768651ec2f8e0458ac155e1409e0a0c9595aeccb7a8f2d"
    )


def test_editing_a_template_changes_its_digest() -> None:
    edited = ENGINEERING.model_copy(
        update={"signal_keywords": (*ENGINEERING.signal_keywords, "kubernetes")}
    )
    assert rubric_digest(edited) != rubric_digest(ENGINEERING)


def test_snapshot_template_is_json_round_trippable() -> None:
    snapshot = snapshot_for(JobFamily.FINANCE)
    assert json.loads(json.dumps(snapshot.template)) == snapshot.template


def test_thresholds_are_part_of_the_rubric_identity() -> None:
    """A routing-threshold edit is a content change, so it gets its own digest."""
    governed = ENGINEERING.model_copy(
        update={
            "thresholds": PolicyThresholds(
                auto_schedule_min_score=0.9,
                auto_schedule_max_variance=0.02,
                soft_rejection_floor=0.75,
                min_interviewer_slots=3,
            )
        }
    )
    assert rubric_digest(governed) != rubric_digest(ENGINEERING)
    payload = canonical_payload(governed)
    thresholds = cast("dict[str, object]", payload["thresholds"])
    assert thresholds["auto_schedule_min_score"] == 0.9
    assert canonical_payload(ENGINEERING)["thresholds"] is None
