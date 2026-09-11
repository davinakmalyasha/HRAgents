"""Deterministic vector scorer.

This module contains **no LLM calls**. It maps structured, provenance-tagged
evidence (`CandidateProfile`) against a `JobSpecification` into the score tensor
S ∈ [0, 1]^4 with an explicit rationale for every dimension.

Same input + same reference date ⇒ same output, byte for byte.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from pydantic import Field

from hr_agents.models import (
    CandidateProfile,
    DimensionScore,
    EvidenceRef,
    JobSpecification,
    ScoreDimension,
    ScoreVector,
    StrictModel,
    VerificationStatus,
)

# --- Skill normalization -------------------------------------------------------

_ALIASES: dict[str, str] = {
    "postgres": "postgresql",
    "psql": "postgresql",
    "pg": "postgresql",
    "py": "python",
    "py3": "python",
    "golang": "go",
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "node-js": "node",
    "nodejs": "node",
    "react-js": "react",
    "reactjs": "react",
    "vue-js": "vue",
    "vuejs": "vue",
    "scikit": "scikit-learn",
    "sklearn": "scikit-learn",
    "tf": "tensorflow",
    "torch": "pytorch",
    "pydanticai": "pydantic-ai",
    "ml": "machine-learning",
    "llms": "llm",
}

_ARCHITECTURE_KEYWORDS = (
    "api",
    "distributed",
    "queue",
    "cache",
    "scaling",
    "microservice",
    "kubernetes",
    "docker",
    "ci/cd",
    "observability",
    "latency",
    "throughput",
    "postgres",
    "redis",
    "kafka",
    "event-driven",
)

_SENIORITY_TIERS: tuple[tuple[frozenset[str], float], ...] = (
    (frozenset({"principal", "architect", "head", "director", "vp"}), 1.0),
    (frozenset({"lead", "staff"}), 0.9),
    (frozenset({"senior", "sr"}), 0.8),
    (frozenset({"engineer", "developer", "programmer"}), 0.6),
    (frozenset({"junior", "jr", "intern", "trainee"}), 0.3),
)

# Internal dimension composition weights (fixed by design, auditable).
_TECH_W = {"tenure": 0.40, "breadth": 0.30, "projects": 0.15, "publications": 0.15}
_SYSTEMS_W = {"categories": 0.50, "keywords": 0.30, "seniority": 0.20}

_SYSTEMS_CATEGORIES = frozenset({"database", "devops", "cloud", "systems", "data"})

_TENURE_SATURATION_MONTHS = 60.0
_BREADTH_SATURATION_SKILLS = 12.0
_PROJECT_SATURATION = 3.0
_PUBLICATION_SATURATION = 3.0
_KEYWORD_SATURATION = 6
_CERT_COUNT_SATURATION = 3.0


class ScoringResult(StrictModel):
    """Full deterministic scoring output for one profile/job pair."""

    vector: ScoreVector
    breakdown: list[DimensionScore] = Field(min_length=4, max_length=4)

    def s_tech(self, weights: Mapping[ScoreDimension, float]) -> float:
        return self.vector.weighted_mean(weights)


def normalize_skill(name: str) -> str:
    """Normalize a skill name for deterministic comparison."""
    cleaned = name.strip().lower().replace(".", "-").replace("_", "-")
    cleaned = "-".join(part for part in cleaned.split() if part)
    return _ALIASES.get(cleaned, cleaned)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))


def _experience_months(profile: CandidateProfile, reference_date: date) -> int:
    total = 0
    for entry in profile.experience:
        if entry.duration_months is not None:
            total += entry.duration_months
            continue
        end = entry.end_date or reference_date
        months = (end.year - entry.start_date.year) * 12 + (end.month - entry.start_date.month)
        total += max(months, 0)
    return total


def _candidate_terms(profile: CandidateProfile) -> set[str]:
    terms = {normalize_skill(skill.name) for skill in profile.skills}
    for entry in profile.experience:
        terms.update(normalize_skill(tech) for tech in entry.tech_stack)
    for project in profile.projects:
        terms.update(normalize_skill(tech) for tech in project.tech_stack)
    terms.discard("")
    return terms


def _coverage(required: set[str], available: set[str]) -> float:
    if not required:
        return 0.0
    return len(required & available) / len(required)


def _evidence_pool(profile: CandidateProfile) -> list[EvidenceRef]:
    pool: list[EvidenceRef] = []
    for entry in profile.experience:
        pool.extend(entry.evidence)
    for skill in profile.skills:
        pool.extend(skill.evidence)
    for cert in profile.certifications:
        pool.extend(cert.evidence)
    for publication in profile.publications:
        pool.extend(publication.evidence)
    for project in profile.projects:
        pool.extend(project.evidence)
    return pool[:10]


def _technical_depth(profile: CandidateProfile, reference_date: date) -> DimensionScore:
    months = _experience_months(profile, reference_date)
    terms = _candidate_terms(profile)

    tenure = min(months / _TENURE_SATURATION_MONTHS, 1.0)
    breadth = min(len(terms) / _BREADTH_SATURATION_SKILLS, 1.0)
    projects = min(len(profile.projects) / _PROJECT_SATURATION, 1.0)
    publications = min(len(profile.publications) / _PUBLICATION_SATURATION, 1.0)

    score = (
        _TECH_W["tenure"] * tenure
        + _TECH_W["breadth"] * breadth
        + _TECH_W["projects"] * projects
        + _TECH_W["publications"] * publications
    )
    rationale = (
        f"{months} months experience (tenure {tenure:.2f}; saturates at "
        f"{int(_TENURE_SATURATION_MONTHS)}), {len(terms)} distinct technologies "
        f"(breadth {breadth:.2f}), {len(profile.projects)} projects, "
        f"{len(profile.publications)} publications"
    )
    return DimensionScore(
        dimension=ScoreDimension.TECHNICAL_DEPTH,
        score=_clamp(score),
        weight=0.0,
        rationale=rationale,
        evidence=_evidence_pool(profile),
    )


def _stack_alignment(profile: CandidateProfile, job: JobSpecification) -> DimensionScore:
    available = _candidate_terms(profile)

    components: list[tuple[str, set[str], float]] = [
        ("must-have", {normalize_skill(s) for s in job.must_have_skills}, 0.60),
        ("nice-to-have", {normalize_skill(s) for s in job.nice_to_have_skills}, 0.25),
        ("role stack", {normalize_skill(s) for s in job.stack}, 0.15),
    ]

    active = [(label, required, weight) for label, required, weight in components if required]
    if not active:
        return DimensionScore(
            dimension=ScoreDimension.STACK_ALIGNMENT,
            score=0.5,
            weight=0.0,
            rationale="no stack requirements specified; neutral score",
            evidence=[],
        )

    total_weight = sum(weight for _, _, weight in active)
    score = 0.0
    parts: list[str] = []
    for label, required, weight in active:
        covered = required & available
        part = _coverage(required, available)
        score += (weight / total_weight) * part
        missing = sorted(required - available)
        parts.append(
            f"{label}: {len(covered)}/{len(required)} matched"
            + (f" (missing: {', '.join(missing)})" if missing else "")
        )

    return DimensionScore(
        dimension=ScoreDimension.STACK_ALIGNMENT,
        score=_clamp(score),
        weight=0.0,
        rationale="; ".join(parts),
        evidence=[],
    )


def _systems_literacy(profile: CandidateProfile) -> DimensionScore:
    categories = {skill.category for skill in profile.skills}
    category_hits = len(categories & _SYSTEMS_CATEGORIES)
    category_component = category_hits / len(_SYSTEMS_CATEGORIES)

    highlights = " ".join(h.lower() for entry in profile.experience for h in entry.highlights)
    keyword_hits = sum(1 for keyword in _ARCHITECTURE_KEYWORDS if keyword in highlights)
    keyword_component = min(keyword_hits / _KEYWORD_SATURATION, 1.0)

    titles = " ".join(entry.title.lower() for entry in profile.experience)
    seniority_component = 0.0
    matched_tier = "unranked"
    for tokens, value in _SENIORITY_TIERS:
        if any(token in titles for token in tokens):
            seniority_component = value
            matched_tier = sorted(tokens)[0]
            break

    score = (
        _SYSTEMS_W["categories"] * category_component
        + _SYSTEMS_W["keywords"] * keyword_component
        + _SYSTEMS_W["seniority"] * seniority_component
    )
    rationale = (
        f"{category_hits}/{len(_SYSTEMS_CATEGORIES)} systems categories present, "
        f"{keyword_hits} architecture signals (saturates at {_KEYWORD_SATURATION}), "
        f"seniority signal: {matched_tier}"
    )
    return DimensionScore(
        dimension=ScoreDimension.SYSTEMS_LITERACY,
        score=_clamp(score),
        weight=0.0,
        rationale=rationale,
        evidence=[],
    )


def _verifiable_certifications(profile: CandidateProfile) -> DimensionScore:
    claims = profile.certifications
    if not claims:
        return DimensionScore(
            dimension=ScoreDimension.VERIFIABLE_CERTIFICATIONS,
            score=0.0,
            weight=0.0,
            rationale="no certifications claimed",
            evidence=[],
        )

    verified = sum(1 for cert in claims if cert.status is VerificationStatus.VERIFIED)
    expired = sum(1 for cert in claims if cert.status is VerificationStatus.EXPIRED)
    failed = sum(1 for cert in claims if cert.status is VerificationStatus.FAILED)
    verified_fraction = verified / len(claims)
    count_component = min(len(claims) / _CERT_COUNT_SATURATION, 1.0)

    score = 0.7 * verified_fraction + 0.3 * count_component
    rationale = (
        f"{verified}/{len(claims)} certifications verified"
        + (f", {expired} expired" if expired else "")
        + (f", {failed} failed verification" if failed else "")
        + f"; count signal {count_component:.2f}"
    )
    evidence: list[EvidenceRef] = []
    for cert in claims:
        evidence.extend(cert.evidence)
    return DimensionScore(
        dimension=ScoreDimension.VERIFIABLE_CERTIFICATIONS,
        score=_clamp(score),
        weight=0.0,
        rationale=rationale,
        evidence=evidence[:10],
    )


def score_candidate(
    profile: CandidateProfile,
    job: JobSpecification,
    *,
    reference_date: date | None = None,
) -> ScoringResult:
    """Deterministically score a profile against a job specification.

    ``reference_date`` is required for reproducibility of tenure math for
    candidates with ongoing roles; tests must pass a fixed date.
    """
    ref = reference_date or date.today()
    weights = job.effective_weights()

    breakdown = [
        _technical_depth(profile, ref),
        _stack_alignment(profile, job),
        _systems_literacy(profile),
        _verifiable_certifications(profile),
    ]

    weighted = [item.model_copy(update={"weight": weights[item.dimension]}) for item in breakdown]

    vector = ScoreVector(
        technical_depth=weighted[0].score,
        stack_alignment=weighted[1].score,
        systems_literacy=weighted[2].score,
        verifiable_certifications=weighted[3].score,
    )
    return ScoringResult(vector=vector, breakdown=weighted)


def score_runs(
    profiles: Iterable[CandidateProfile],
    job: JobSpecification,
    *,
    reference_date: date | None = None,
) -> list[ScoringResult]:
    """Score k independently extracted profiles for the same candidate."""
    return [score_candidate(profile, job, reference_date=reference_date) for profile in profiles]
