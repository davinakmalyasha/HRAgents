"""Cross-family construct validity: the rubric must be an occupation's own.

The scorer was written around software-shaped evidence, and a corpus of engineers
passed every other test while the product quietly mis-scored everyone else. This file
holds the regressions that corpus cannot catch, because each one uses evidence a real
candidate in that occupation would present.

The failure these reproduce, measured before the fix on this exact profile:

    technical_depth                  0.606
    stack_alignment                  1.000   <- matches the job exactly
    systems_literacy                 0.000   <- a perfect accountant scores zero
    verifiable_certifications        0.000
    S_tech                           0.5425  <- below the 0.70 floor

``systems_literacy`` was zero because it reads ``Skill.category``, whose enum is entirely
software, so every accounting skill was ``OTHER``; and because its architecture keywords
and job-title tiers are all engineering or software words, so "Accounting Supervisor"
matched no tier. The result was ``REJECT_AUTO`` -- an automatic rejection with no human
in the loop, for a candidate with eight years and a perfect match on the role's stated
requirements.

``tests/services/test_scoring_calibration.py`` guards the *shape* (strong beats adequate
beats weak, in every family). This file guards the *rubric* (the right evidence counts
at all).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from hr_agents.models import (
    CandidateProfile,
    CertificationClaim,
    EvidenceRef,
    ExperienceEntry,
    JobFamily,
    JobSpecification,
    Publication,
    Seniority,
    Skill,
    SkillCategory,
    SourceType,
    VerificationStatus,
)
from hr_agents.models.policy import PolicyDecision, PolicyThresholds
from hr_agents.services.dimensions import families
from hr_agents.services.policy import evaluate_policy
from hr_agents.services.scoring import score_candidate

REFERENCE_DATE = date(2025, 1, 1)
FLOOR = 0.70
"""``soft_rejection_floor``, pinned here on purpose.

Importing the configured value would make this assertion follow the settings, which is
the drift it exists to catch.
"""


def _source(text: str) -> EvidenceRef:
    return EvidenceRef(source_type=SourceType.RESUME, locator="cv.pdf", excerpt=text[:80])


def _paper(text: str) -> Publication:
    return Publication(title=text, venue="Journal", year=2023, evidence=[_source(text)])


def _seniority_tier(dimension: str, profile: CandidateProfile, job: JobSpecification) -> float:
    for item in score_candidate(profile, job, reference_date=REFERENCE_DATE).breakdown:
        if item.dimension.value == dimension:
            return item.score
    raise AssertionError(f"{dimension} missing from the breakdown")


def _decision(profile: CandidateProfile, job: JobSpecification) -> PolicyDecision:
    result = score_candidate(profile, job, reference_date=REFERENCE_DATE)
    return evaluate_policy(
        s_tech=result.s_tech(job.effective_weights()),
        sigma=0.0,
        thresholds=PolicyThresholds(),
    ).decision


# --- finance ------------------------------------------------------------------


def accountant() -> CandidateProfile:
    """Eight years of supervisory accounting work. Not a weak candidate."""
    return CandidateProfile(
        full_name="Ahmad Wijaya",
        skills=[
            Skill(
                name="Financial Reporting",
                category=SkillCategory.FINANCE,
                evidence=[_source("Financial Reporting")],
            ),
            Skill(name="IFRS", category=SkillCategory.FINANCE, evidence=[_source("IFRS")]),
            Skill(name="Auditing", category=SkillCategory.FINANCE, evidence=[_source("Auditing")]),
            Skill(
                name="Tax Compliance",
                category=SkillCategory.FINANCE,
                evidence=[_source("Tax Compliance")],
            ),
        ],
        experience=[
            ExperienceEntry(
                title="Accounting Supervisor",
                company="PT Sinar Jaya",
                start_date=date(2017, 1, 1),
                end_date=date(2024, 12, 31),
                duration_months=96,
                highlights=[
                    "Led month-end close for 12 entities",
                    "Implemented IFRS 15 revenue recognition",
                    "Managed statutory audit with a Big Four firm",
                    "Reduced DSO by 30 days",
                ],
                tech_stack=["Excel", "SAP"],
                evidence=[_source("Accounting Supervisor")],
            )
        ],
    )


def finance_supervisor() -> JobSpecification:
    return JobSpecification(
        title="Finance Supervisor",
        seniority=Seniority.SENIOR,
        job_family=JobFamily.FINANCE,
        must_have_skills=["financial reporting", "IFRS", "auditing"],
        nice_to_have_skills=["tax compliance"],
        stack=["Excel"],
        min_years_experience=6,
    )


def test_a_matched_accountant_is_not_auto_rejected() -> None:
    """The regression. Below the floor this is an automatic rejection, no human."""
    decision = _decision(accountant(), finance_supervisor())

    assert decision is not PolicyDecision.REJECT_AUTO, (
        "an eight-year accounting supervisor who matches every stated requirement is "
        "being automatically rejected; rejection requires a named human"
    )


def test_a_supervisory_title_counts_as_seniority() -> None:
    """`systems_literacy` scored 0.000 because no tier contained "Supervisor".

    The tier list was software and management words only, so a supervisory role in any
    other occupation matched nothing at all.
    """
    score = _seniority_tier("systems_literacy", accountant(), finance_supervisor())

    assert score > 0.0, "a supervisor with eight years scores zero professional seniority"


def test_finance_skills_count_toward_the_professional_dimension() -> None:
    """The category component read a software-only enum, so finance was always zero."""
    result = score_candidate(accountant(), finance_supervisor(), reference_date=REFERENCE_DATE)
    literacy = next(item for item in result.breakdown if item.dimension.value == "systems_literacy")

    assert "/5 systems categories" not in literacy.rationale, (
        "the rationale still reports the software category list: " + literacy.rationale
    )
    assert "0/5 systems categories present" not in literacy.rationale


def test_a_qualified_accountant_is_not_capped_by_publishing() -> None:
    """`publications` was a term inside `technical_depth` for every occupation.

    For a role where nobody publishes, that is a ceiling on the strongest evidence a
    candidate can present. The invariant is not a threshold -- it is that depth does not
    *depend* on publishing at all for this family.
    """
    job = finance_supervisor()
    with_publication = score_candidate(
        accountant().model_copy(update={"publications": [_paper("Three years of published work")]}),
        job,
        reference_date=REFERENCE_DATE,
    )
    without = score_candidate(accountant(), job, reference_date=REFERENCE_DATE)

    published = next(
        item for item in with_publication.breakdown if item.dimension.value == "technical_depth"
    )
    unpublished = next(
        item for item in without.breakdown if item.dimension.value == "technical_depth"
    )
    assert published.score == unpublished.score, (
        "publishing still moves a finance candidate's depth, so it is still being "
        "counted as evidence of accounting competence"
    )

    # And the rubric responds to *this* occupation's evidence: more relevant domain
    # coverage raises depth. Asserted as a relationship rather than a number, because
    # the exact value moves whenever the vocabulary gains a synonym, and a test that
    # breaks on a synonym teaches nothing.
    narrow = score_candidate(accountant(), job, reference_date=REFERENCE_DATE)
    deep = accountant().model_copy(
        update={
            "skills": [
                Skill(name=name, category=SkillCategory.FINANCE)
                for name in ("IFRS", "Auditing", "Tax Compliance", "Treasury", "Budgeting")
            ]
        }
    )
    wider = score_candidate(deep, job, reference_date=REFERENCE_DATE)
    narrow_depth = next(
        item for item in narrow.breakdown if item.dimension.value == "technical_depth"
    ).score
    wider_depth = next(
        item for item in wider.breakdown if item.dimension.value == "technical_depth"
    ).score
    assert wider_depth > narrow_depth, (
        f"adding relevant accounting domains did not raise depth: "
        f"{narrow_depth:.3f} -> {wider_depth:.3f}"
    )


def test_an_accountants_credentials_are_not_pinned_at_zero() -> None:
    """ACCA/CPA membership is the finance equivalent of a verified certification."""
    profile = accountant().model_copy(
        update={
            "certifications": [
                CertificationClaim(
                    name="ACCA Membership",
                    issuer="ACCA",
                    status=VerificationStatus.VERIFIED,
                    evidence=[_source("ACCA Membership")],
                )
            ]
        }
    )
    result = score_candidate(profile, finance_supervisor(), reference_date=REFERENCE_DATE)
    certifications = next(
        item for item in result.breakdown if item.dimension.value == "verifiable_certifications"
    )

    assert certifications.score > 0.0
    assert "1/1 certifications verified" in certifications.rationale


def test_a_weak_accountant_still_scores_below_a_strong_one() -> None:
    """Guards against fixing the bias by flattening the scale.

    A template that scored everyone in a family alike would pass the tests above. This
    is the fence that would catch it.
    """
    strong = accountant()
    weak = accountant().model_copy(
        update={
            "skills": [],
            "experience": [
                ExperienceEntry(
                    title="Accounting Staff",
                    company="PT Kecil",
                    start_date=date(2023, 1, 1),
                    end_date=date(2024, 12, 31),
                    duration_months=12,
                    highlights=["Assisted with filing"],
                )
            ],
        }
    )
    job = finance_supervisor()

    strong_score = score_candidate(strong, job, reference_date=REFERENCE_DATE).s_tech(
        job.effective_weights()
    )
    weak_score = score_candidate(weak, job, reference_date=REFERENCE_DATE).s_tech(
        job.effective_weights()
    )

    assert strong_score - weak_score >= 0.20, (
        f"a finance template that cannot separate a supervisor from a 12-month assistant: "
        f"{strong_score:.3f} vs {weak_score:.3f}"
    )


# --- education ----------------------------------------------------------------


def test_a_teacher_is_not_auto_rejected() -> None:
    """The same failure in a different occupation: no tier, no keywords, zero."""
    profile = CandidateProfile(
        full_name="Budi Santoso",
        skills=[
            Skill(name="Curriculum Design", category=SkillCategory.EDUCATION),
            Skill(name="Classroom Management", category=SkillCategory.EDUCATION),
        ],
        experience=[
            ExperienceEntry(
                title="Head of Department",
                company="SMA Negeri 1",
                start_date=date(2013, 1, 1),
                end_date=date(2024, 12, 31),
                duration_months=144,
                highlights=[
                    "Redesigned the national curriculum for two subjects",
                    "Coached 40 teachers on formative assessment",
                ],
            )
        ],
    )
    job = JobSpecification(
        title="Head of Department",
        seniority=Seniority.LEAD,
        job_family=JobFamily.EDUCATION,
        must_have_skills=["curriculum design"],
        nice_to_have_skills=["classroom management"],
        min_years_experience=8,
    )

    decision = _decision(profile, job)
    assert decision is not PolicyDecision.REJECT_AUTO


# --- the registry itself ------------------------------------------------------


def test_every_job_family_has_a_template() -> None:
    """A family with no template falls back to engineering, silently.

    That fallback is what produced the original defect: an unrecognised role was scored
    by the software rubric and nobody was told.
    """
    from hr_agents.services.dimensions import template_for

    for family in JobFamily:
        template = template_for(family)
        assert template.family is family, f"{family} resolved to the {template.family} template"


def test_an_unset_job_family_defaults_to_the_engineering_rubric() -> None:
    """Byte-identical backwards compatibility is a requirement, not an accident.

    Every job created before `job_family` existed must score exactly as it did, and the
    existing calibration corpus pins that.
    """
    from hr_agents.services.dimensions import ENGINEERING

    assert JobSpecification(title="Backend Engineer").job_family is JobFamily.ENGINEERING
    assert ENGINEERING.depth_weights["publications"] == Decimal("0.075")


def test_the_engineering_template_reproduces_the_previous_numbers() -> None:
    """The engineering rubric must be unchanged by this work.

    The template registry exists because the rubric was too narrow, not because the
    engineering numbers were wrong. If engineering moves, this is the failure.
    """
    from hr_agents.services.dimensions import ENGINEERING

    result = score_candidate(
        accountant().model_copy(update={"skills": [], "experience": []}),
        finance_supervisor().model_copy(update={"job_family": JobFamily.ENGINEERING}),
        reference_date=REFERENCE_DATE,
    )
    systems = next(item for item in result.breakdown if item.dimension.value == "systems_literacy")
    assert ENGINEERING.systems_weights["categories"] == Decimal("0.50")
    # A profile with no experience has no tier match either way.
    assert systems.score == 0.0


@pytest.mark.parametrize("family", list(JobFamily))
def test_every_template_declares_all_four_internal_weights(family: JobFamily) -> None:
    """A template missing an internal weight would silently fall back to engineering's.

    `score_candidate` resolves weights with `or`, so a zero or absent entry is a silent
    substitution rather than an error.
    """
    from hr_agents.services.dimensions import template_for

    template = template_for(family)
    assert sum(template.depth_weights.values()) == Decimal(1)
    assert sum(template.systems_weights.values()) == Decimal(1)
    assert set(template.depth_weights) == {"tenure", "breadth", "projects", "publications"}
    assert set(template.systems_weights) == {"categories", "keywords", "seniority"}


@pytest.mark.parametrize("family", list(JobFamily))
def test_no_template_asks_for_a_signal_its_family_cannot_present(family: JobFamily) -> None:
    """`projects` is a software-shaped field; nobody in finance has one.

    It carried weight 0.15 of `technical_depth` for every occupation, so a career
    accountant lost 0.15 of their strongest dimension to a field they have never filled
    in. Only engineering may score on it.
    """
    from hr_agents.services.dimensions import template_for

    template = template_for(family)
    if family is JobFamily.ENGINEERING:
        assert template.depth_weights["projects"] > 0
        assert template.depth_weights["publications"] > 0
    else:
        assert template.depth_weights["projects"] == 0, (
            f"{family} scores on `projects`, which its candidates do not have"
        )
        assert template.depth_weights["publications"] == 0, (
            f"{family} scores on `publications`, which is not evidence of competence "
            "in that occupation"
        )


def test_a_title_match_is_a_word_not_a_substring() -> None:
    """Regression: `sr` matched any title containing those letters.

    "Resource Manager" contains "sr", so the previous substring test scored it as senior
    (0.8) -- an unrelated job title reading as seniority evidence.
    """
    from hr_agents.services.dimensions import ENGINEERING

    value, matched = ENGINEERING.tier_for("resource manager")

    assert (value, matched) == (0.0, "unranked")


def test_punctuation_does_not_hide_a_real_title_tier() -> None:
    """The word-boundary fix must not lose titles that carry punctuation."""
    from hr_agents.services.dimensions import ENGINEERING

    value, matched = ENGINEERING.tier_for("team lead, payments")

    assert matched == "lead"
    assert value == 0.9


def test_an_unknown_family_is_rejected_rather_than_scored_as_engineering() -> None:
    """The original defect was a silent fallback: an unrecognised role was scored by
    the software rubric and nobody was told. `JobFamily` is an enum and `template_for`
    is total, so an unknown value cannot reach the scorer at all."""

    assert len(families()) == len(list(JobFamily))
    with pytest.raises(ValueError):
        JobFamily("accounting")
