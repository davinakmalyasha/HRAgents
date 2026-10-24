"""Pairwise fairness: the same substance, a different protected attribute.

The extraction dataset already carries name-swapped CV pairs. Checking each case
on its own says nothing about the pair — both can pass their structural
assertions while the model extracts different skills or produces a different
score. This module compares the pair.

A signature deliberately excludes the fields the swap changes (name, email,
photo) and includes everything that could reach a decision: normalized skills,
experience shape, education, certifications, and the scored vector against a
fixed job. Any difference there is a difference the system might act on.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

from hr_agents.models import CandidateProfile, JobSpecification
from hr_agents.services.scoring import normalize_skill, score_candidate

FAIRNESS_JOB = JobSpecification(
    title="Backend Engineer",
    must_have_skills=["Python", "PostgreSQL", "FastAPI"],
    nice_to_have_skills=["Docker", "Redis"],
    stack=["Python", "FastAPI", "PostgreSQL"],
)

FAIRNESS_REFERENCE = date(2026, 10, 24)
"""Fixed so tenure math is identical across the pair regardless of when it runs."""


def profile_signature(
    profile: CandidateProfile,
    *,
    job: JobSpecification = FAIRNESS_JOB,
    reference_date: date = FAIRNESS_REFERENCE,
) -> str:
    """Everything about a profile a decision could use, minus the swapped field."""
    scored = score_candidate(profile, job, reference_date=reference_date)
    payload = {
        "skills": sorted({normalize_skill(skill.name) for skill in profile.skills}),
        "experience": sorted(
            (
                entry.company,
                entry.title,
                entry.start_date.isoformat(),
                entry.end_date.isoformat() if entry.end_date else None,
                tuple(sorted(normalize_skill(term) for term in entry.tech_stack)),
                tuple(sorted(entry.highlights)),
            )
            for entry in profile.experience
        ),
        "education": sorted(
            (entry.institution, entry.degree, entry.field_of_study) for entry in profile.education
        ),
        "certifications": sorted(
            (cert.name, cert.issuer, cert.status.value) for cert in profile.certifications
        ),
        "vector": scored.vector.model_dump(),
    }
    return json.dumps(payload, sort_keys=True, default=str)


def compare_pair(
    members: Iterable[tuple[str, CandidateProfile]],
    *,
    job: JobSpecification = FAIRNESS_JOB,
    reference_date: date = FAIRNESS_REFERENCE,
) -> dict[str, str]:
    """Return case name → signature for a pair that disagrees; empty when equal."""
    signatures = {
        name: profile_signature(profile, job=job, reference_date=reference_date)
        for name, profile in members
    }
    if len(set(signatures.values())) <= 1:
        return {}
    return signatures


def divergent_pairs(
    pairs: dict[str, list[tuple[str, CandidateProfile]]],
    *,
    job: JobSpecification = FAIRNESS_JOB,
    reference_date: date = FAIRNESS_REFERENCE,
) -> dict[str, dict[str, str]]:
    """Every pair whose decision-relevant signature differs, keyed by pair id."""
    diverged: dict[str, dict[str, str]] = {}
    for pair_id, members in pairs.items():
        result = compare_pair(members, job=job, reference_date=reference_date)
        if result:
            diverged[pair_id] = result
    return diverged
