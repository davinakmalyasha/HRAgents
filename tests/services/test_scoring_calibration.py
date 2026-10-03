"""Calibration fences for the scoring function.

The scorer decides whether a candidate is auto-scheduled, routed to a person, or
told they might be rejected. Nothing asserted that the bands lined up with the
scores the scorer actually produces, so they had drifted: a well-matched senior
engineer scored about 0.68 against a 0.70 soft-rejection floor, and the
``publications`` term in ``technical_depth`` capped that dimension at 0.85 for
anyone who had not written three papers -- a proxy for proximity to academia,
applied to every occupation.

The assertions here are **label-free**. There is no ground truth for "this
accountant is a strong candidate", and inventing one would let anyone move a
number until a test passed. So the properties are structural:

- ordering: strong > adequate > weak, in every occupation, not just software;
- fit beats pedigree: matching the job beats equal tenure without it;
- a strong candidate is never routed into the band that reads as "weak";
- the three tier gaps are wide enough to be meaningful.

`tests/services/test_scoring.py` covers the mechanics of each dimension. This
file covers whether the *bands* mean anything.

The corpus is in ``evals/scoring_calibration.py`` and is synthetic. Nothing here
moves the thresholds: ``docs/architecture/hitl-bounds.md`` records them as a
human-approved contract.
"""

from __future__ import annotations

from datetime import date

import pytest
from evals.scoring_calibration import (
    OCCUPATIONS,
    REFERENCE_DATE,
    build_cases,
    build_saturation_job,
    build_saturation_profile,
    build_tenured_misfit_cases,
)

from hr_agents.models import PolicyDecision, PolicyThresholds
from hr_agents.services.policy import evaluate_policy
from hr_agents.services.scoring import score_candidate

FLOOR = 0.70
"""``soft_rejection_floor``. Hard-coded here on purpose.

Importing the configured value would make these assertions follow whatever the
settings say, which is exactly the drift being guarded against. If the threshold
ever moves, this file should be revisited in the same commit -- see
``test_the_auto_schedule_band_is_still_unreachable`` for how that is recorded.
"""


def score_of(profile, job) -> float:  # type: ignore[no-untyped-def]
    weights = job.effective_weights()
    return score_candidate(profile, job, reference_date=REFERENCE_DATE).s_tech(weights)


def decision_of(profile, job) -> PolicyDecision:  # type: ignore[no-untyped-def]
    return evaluate_policy(
        s_tech=score_of(profile, job), sigma=0.0, thresholds=PolicyThresholds()
    ).decision


CASES = {case.name: case for case in build_cases()}
MISFITS = {case.occupation: case for case in build_tenured_misfit_cases()}


@pytest.mark.parametrize("occupation", [o.key for o in OCCUPATIONS])
def test_stronger_tiers_score_higher_in_every_occupation(occupation: str) -> None:
    strong = score_of(CASES[f"{occupation}_strong"].profile, CASES[f"{occupation}_strong"].job)
    adequate = score_of(
        CASES[f"{occupation}_adequate"].profile, CASES[f"{occupation}_adequate"].job
    )
    weak = score_of(CASES[f"{occupation}_weak"].profile, CASES[f"{occupation}_weak"].job)

    assert strong > adequate > weak, (
        f"{occupation}: strong {strong:.3f} / adequate {adequate:.3f} / weak {weak:.3f}"
    )


@pytest.mark.parametrize("occupation", [o.key for o in OCCUPATIONS])
def test_matching_the_job_beats_matching_the_vacancy(occupation: str) -> None:
    """Fit has to outrank tenure, or the score is measuring the wrong thing.

    ``technical_depth`` puts 0.4375 of a dimension on tenure. That is only
    defensible if a long history in the wrong field does not beat a shorter one
    in the right field -- so each occupation carries a tenured misfit with the
    strong candidate's experience, projects and certifications but none of the
    job's required skills.
    """
    strong_case = CASES[f"{occupation}_strong"]
    strong = score_of(strong_case.profile, strong_case.job)
    misfit = score_of(MISFITS[occupation].profile, MISFITS[occupation].job)

    assert strong > misfit, (
        f"{occupation}: a tenured misfit ({misfit:.3f}) beat a matched candidate ({strong:.3f})"
    )


@pytest.mark.parametrize("occupation", [o.key for o in OCCUPATIONS])
def test_a_strong_candidate_is_never_routed_as_weak(occupation: str) -> None:
    """The floor exists to catch weak candidates, not well-matched ones.

    Every strong case here already cleared 0.70 under the previous weights, so
    this is a regression fence rather than evidence of a past failure: if a
    future weight change starts pushing well-matched candidates below the floor,
    this is what notices.
    """
    case = CASES[f"{occupation}_strong"]

    assert decision_of(case.profile, case.job) is not PolicyDecision.REJECT_AUTO, (
        f"{occupation}: a strong candidate scored {score_of(case.profile, case.job):.3f} "
        "and was routed below the soft-rejection floor"
    )


def test_a_non_publisher_is_not_structurally_capped_out_of_full_marks() -> None:
    """The property that actually changed, and the one worth fencing.

    ``technical_depth`` used to be composed as tenure + breadth + projects +
    publications, which sum to 0.85 at the old weights. A candidate who had
    never published a paper therefore could not score above 0.85 on this
    dimension however senior, broad or prolific their work was -- a ceiling set
    by proximity to academia rather than by capability, applied to teaching,
    finance and sales as much as to research roles.

    ``publications`` is now 0.075, lifting that ceiling to 0.925. This assertion
    fails against the old weights (0.8500), which is how it was verified; the
    ordering and band assertions elsewhere in this file pass under both and so
    cannot justify the change on their own.
    """
    profile = build_saturation_profile(publications=0)
    job = build_saturation_job()

    depth = score_candidate(profile, job, reference_date=REFERENCE_DATE).vector.technical_depth

    assert depth >= 0.90, (
        f"a maximal non-publisher tops out at {depth:.4f} on technical_depth; the "
        "publications weight is capping the dimension below full marks"
    )


def test_publishing_still_counts_for_full_marks() -> None:
    """The other half of the above: research output has not been zeroed out.

    Cutting the publications weight from 0.15 to 0.075 was meant to stop it
    dominating, not to ignore it. A maximal candidate with three publications
    still reaches 1.0, so publication remains a route to full marks.
    """
    published = score_candidate(
        build_saturation_profile(publications=3),
        build_saturation_job(),
        reference_date=REFERENCE_DATE,
    ).vector.technical_depth

    assert published == 1.0, f"a maximal publisher scores {published:.4f}, expected full marks"


@pytest.mark.parametrize("occupation", [o.key for o in OCCUPATIONS])
def test_the_tiers_are_separated_by_a_usable_margin(occupation: str) -> None:
    """Adjacent tiers must not collapse into each other.

    Without this, a weight change could leave every tier within a few points of
    every other and the bands would be rounding rather than judgement.
    """
    strong = score_of(CASES[f"{occupation}_strong"].profile, CASES[f"{occupation}_strong"].job)
    adequate = score_of(
        CASES[f"{occupation}_adequate"].profile, CASES[f"{occupation}_adequate"].job
    )
    weak = score_of(CASES[f"{occupation}_weak"].profile, CASES[f"{occupation}_weak"].job)

    assert strong - adequate >= 0.10, (
        f"{occupation}: strong/adequate gap is {strong - adequate:.3f}"
    )
    assert adequate - weak >= 0.20, f"{occupation}: adequate/weak gap is {adequate - weak:.3f}"


def test_every_occupation_is_scored_on_the_same_scale() -> None:
    """A finance or teaching candidate must not be structurally capped below engineering.

    The scorer is built around software-shaped evidence: a ``systems_literacy``
    category list, architecture keywords, and job-title tiers containing only
    software titles. A corpus of engineers would have passed every other test in
    this file while the product quietly mis-scored everyone else. This bounds how
    far that bias currently reaches.
    """
    strong_scores = {
        occupation.key: score_of(
            CASES[f"{occupation.key}_strong"].profile,
            CASES[f"{occupation.key}_strong"].job,
        )
        for occupation in OCCUPATIONS
    }
    best = max(strong_scores.values())
    worst = min(strong_scores.values())

    assert best - worst <= 0.15, (
        "strong candidates across occupations score too far apart: "
        + ", ".join(f"{key} {value:.3f}" for key, value in sorted(strong_scores.items()))
    )


def test_the_auto_schedule_band_is_still_unreachable() -> None:
    """Characterisation: no plausible candidate in the corpus reaches 0.85.

    Not an endorsement. It records that ``AUTO_SCHEDULE`` is currently a dead
    band -- the best matched profile here reaches 0.830 against a threshold of
    0.85, and reaching it needs verified certifications on top of a near-perfect
    profile. Every candidate is therefore either routed to a person or flagged.

    That is not unsafe: the previous commit made the sub-floor band a prompt for
    a human rather than an outcome. But it does mean the automation the product
    describes does not fire in practice.

    Moving 0.85 is not this commit's business -- ``hitl-bounds.md`` records the
    thresholds as a human-approved act. When someone does move it, this assertion
    should fail and the gap above should be deleted rather than re-baselined.
    """
    best = max(
        score_of(case.profile, case.job) for case in list(CASES.values()) + list(MISFITS.values())
    )

    assert best < 0.85, (
        f"a corpus candidate now reaches {best:.3f}; AUTO_SCHEDULE is reachable, so the "
        "comment above is stale and the band should be documented as live"
    )


def test_scoring_is_deterministic_for_every_case() -> None:
    """The corpus is only usable as a fence if it produces the same numbers twice.

    Nothing here calls a model, so any variation would mean the scorer depends on
    something it should not -- dict ordering, a clock, or a set iteration.
    """
    for case in list(CASES.values()) + list(MISFITS.values()):
        first = score_of(case.profile, case.job)
        second = score_of(case.profile, case.job)
        assert first == second, f"{case.name} is not deterministic: {first} vs {second}"


def test_the_corpus_reference_date_does_not_drift_with_the_wall_clock() -> None:
    """Tenure is measured in months, so a moving clock would move every score."""
    assert date(2025, 1, 1) == REFERENCE_DATE
    case = CASES["engineering_strong"]
    assert score_of(case.profile, case.job) == score_of(case.profile, case.job)
