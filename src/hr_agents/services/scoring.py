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
    business_today,
)
from hr_agents.services.dimensions import (
    CERT_COUNT_SATURATION,
    PROJECT_SATURATION,
    PUBLICATION_SATURATION,
    TENURE_SATURATION_MONTHS,
    DimensionTemplate,
    template_for,
)
from hr_agents.services.primitives import (
    credential_credit,
    evidence_density,
    saturation,
    tenure_saturation,
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

# The engineering vocabulary -- architecture keywords, title tiers, the competency-area
# list and the four depth weights -- now lives in ``dimensions.ENGINEERING``, with a
# template per other occupation family. The saturation points are shared, in
# ``dimensions``, because "how much evidence is enough" is a property of the evidence
# rather than of the occupation.


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


def _breadth_terms(profile: CandidateProfile, template: DimensionTemplate) -> set[str]:
    """What counts as breadth for this occupation.

    Every term the candidate presents, when the template has no vocabulary -- which is
    engineering, and must stay `len(_candidate_terms(...))` exactly. When the template
    *does* have one, breadth is the intersection with it, so that a finance candidate is
    measured on accounting standards they have worked in rather than on how many tools
    they have touched.
    """
    terms = _candidate_terms(profile)
    if not template.breadth_vocabulary:
        return terms
    return terms & template.breadth_vocabulary


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


EVIDENCE_CONFIDENCE_FLOOR = 0.5
"""A reference weaker than this cannot, on its own, justify automation."""


def dimensions_evidenced(
    breakdown: Iterable[DimensionScore], *, floor: float = EVIDENCE_CONFIDENCE_FLOOR
) -> bool:
    """Whether every dimension carries at least one reference at or above ``floor``."""
    return all(any(ref.confidence >= floor for ref in item.evidence) for item in breakdown)


def _dedupe_evidence(refs: Iterable[EvidenceRef]) -> list[EvidenceRef]:
    """Stable, bounded evidence list; the same record cited twice counts once."""
    seen: set[tuple[str, str, str | None]] = set()
    unique: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source_type.value, ref.locator, ref.excerpt)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique[:10]


def _term_evidence(profile: CandidateProfile) -> dict[str, list[EvidenceRef]]:
    """Normalized term -> references on the record that names it.

    A skill carries its own refs; a technology named only in an experience or
    project stack is evidenced by that entry's refs. A term with no refs is
    absent, so the dimension stays unevidenced rather than borrowing confidence.
    """
    evidence: dict[str, list[EvidenceRef]] = {}
    for skill in profile.skills:
        term = normalize_skill(skill.name)
        if term and skill.evidence:
            evidence.setdefault(term, []).extend(skill.evidence)
    for entry in profile.experience:
        for tech in entry.tech_stack:
            term = normalize_skill(tech)
            if term and entry.evidence:
                evidence.setdefault(term, []).extend(entry.evidence)
    for project in profile.projects:
        for tech in project.tech_stack:
            term = normalize_skill(tech)
            if term and project.evidence:
                evidence.setdefault(term, []).extend(project.evidence)
    return evidence


def _technical_depth(
    profile: CandidateProfile, reference_date: date, template: DimensionTemplate
) -> DimensionScore:
    months = _experience_months(profile, reference_date)
    terms = _breadth_terms(profile, template)

    tenure = tenure_saturation(months, float(TENURE_SATURATION_MONTHS))
    breadth = template.taxonomy().breadth_component(terms)
    projects = saturation(len(profile.projects), float(PROJECT_SATURATION))
    publications = saturation(len(profile.publications), float(PUBLICATION_SATURATION))

    weights = template.depth_weights
    score = (
        float(weights["tenure"]) * tenure
        + float(weights["breadth"]) * breadth
        + float(weights["projects"]) * projects
        + float(weights["publications"]) * publications
    )
    unit = "distinct technologies" if not template.breadth_vocabulary else "domain areas"
    rationale = (
        f"{months} months experience (tenure {tenure:.2f}; saturates at "
        f"{int(TENURE_SATURATION_MONTHS)}), {len(terms)} {unit} "
        f"(breadth {breadth:.2f}), {len(profile.projects)} projects, "
        f"{len(profile.publications)} publications"
    )
    return DimensionScore(
        dimension=ScoreDimension.TECHNICAL_DEPTH,
        score=_clamp(score),
        weight=0.0,
        rationale=rationale,
        evidence=_dedupe_evidence(_evidence_pool(profile)),
        components={
            "tenure": float(weights["tenure"]) * tenure,
            "breadth": float(weights["breadth"]) * breadth,
            "projects": float(weights["projects"]) * projects,
            "publications": float(weights["publications"]) * publications,
        },
    )


def _stack_alignment(profile: CandidateProfile, job: JobSpecification) -> DimensionScore:
    available = _candidate_terms(profile)
    term_evidence = _term_evidence(profile)

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
    matched: list[EvidenceRef] = []
    coverage: dict[str, float] = {}
    for label, required, weight in active:
        covered = required & available
        part = evidence_density(required, available)
        coverage[label.replace("-", "_")] = part
        score += (weight / total_weight) * part
        missing = sorted(required - available)
        for term in sorted(covered):
            matched.extend(term_evidence.get(term, []))
        parts.append(
            f"{label}: {len(covered)}/{len(required)} matched"
            + (f" (missing: {', '.join(missing)})" if missing else "")
        )

    return DimensionScore(
        dimension=ScoreDimension.STACK_ALIGNMENT,
        score=_clamp(score),
        weight=0.0,
        rationale="; ".join(parts),
        evidence=_dedupe_evidence(matched),
        components=coverage,
    )


def _systems_literacy(profile: CandidateProfile, template: DimensionTemplate) -> DimensionScore:
    """The professional dimension: evidence this candidate understands their field whole.

    Every input here is the occupation's, via the template. It previously read a
    software-only skill-category list, sixteen architecture keywords and a title-tier
    list made of software words, which combined to score a career accountant **exactly
    zero** -- not low, zero -- and put them below the automatic-rejection floor.
    """
    taxonomy = template.taxonomy()
    categories = {skill.category for skill in profile.skills}
    hits = categories & taxonomy.professional_categories
    category_component = len(hits) / len(taxonomy.professional_categories)
    category_evidence = [
        ref for skill in profile.skills if skill.category in hits for ref in skill.evidence
    ]

    keyword_hits, keyword_evidence = taxonomy.signal_hits(profile.experience)
    keyword_component = saturation(keyword_hits, float(taxonomy.signal_saturation))

    titles = " ".join(entry.title.lower() for entry in profile.experience)
    seniority_component, matched_tier = taxonomy.seniority(titles)

    weights = template.systems_weights
    score = (
        float(weights["categories"]) * category_component
        + float(weights["keywords"]) * keyword_component
        + float(weights["seniority"]) * seniority_component
    )
    rationale = (
        f"{len(hits)}/{len(template.professional_categories)} {template.family.value} "
        f"competency areas present, {keyword_hits} professional signals "
        f"(saturates at {template.signal_saturation}), seniority signal: {matched_tier}"
    )
    return DimensionScore(
        dimension=ScoreDimension.SYSTEMS_LITERACY,
        score=_clamp(score),
        weight=0.0,
        rationale=rationale,
        evidence=_dedupe_evidence([*category_evidence, *keyword_evidence]),
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

    credit = credential_credit(claims, count_saturation=float(CERT_COUNT_SATURATION))
    score = credit.score
    rationale = (
        f"{credit.verified}/{len(claims)} certifications verified"
        + (f", {credit.expired} expired" if credit.expired else "")
        + (f", {credit.failed} failed verification" if credit.failed else "")
        + f"; count signal {credit.count_component:.2f}"
    )
    evidence: list[EvidenceRef] = []
    for cert in claims:
        evidence.extend(cert.evidence)
    return DimensionScore(
        dimension=ScoreDimension.VERIFIABLE_CERTIFICATIONS,
        score=_clamp(score),
        weight=0.0,
        rationale=rationale,
        evidence=_dedupe_evidence(evidence),
    )


def score_candidate(
    profile: CandidateProfile,
    job: JobSpecification,
    *,
    reference_date: date | None = None,
    template: DimensionTemplate | None = None,
) -> ScoringResult:
    """Deterministically score a profile against a job specification.

    ``reference_date`` is required for reproducibility of tenure math for
    candidates with ongoing roles; tests must pass a fixed date.

    ``template`` is the active rubric when the caller has resolved one (the
    pipeline does, through the verified registry); without it the code template
    for ``job.job_family`` scores, which defaults to engineering so every job
    created before the family existed is scored exactly as it was.
    """
    ref = reference_date or business_today()
    weights = job.effective_weights()
    rubric = template or template_for(job.job_family)

    breakdown = [
        _technical_depth(profile, ref, rubric),
        _stack_alignment(profile, job),
        _systems_literacy(profile, rubric),
        _verifiable_certifications(profile),
    ]
    # A dimension the extraction could not point at must not contribute. The
    # alternative — keeping a title- or tenure-shaped number with no reference —
    # is how a confident-looking score outruns the record it is supposed to
    # describe. Policy pairs this with a gate: missing evidence also blocks an
    # automatic rejection, because an extraction gap is not a candidate's fault.
    # A "neutral" stack score exists when the *job* states no requirements; there
    # is no candidate fact to cite for it, and zeroing it would punish a person
    # for an empty job description. Every other unevidenced dimension scores 0.
    stack_neutral = not (job.must_have_skills or job.nice_to_have_skills or job.stack)
    breakdown = [
        _evidence_first(
            item,
            neutral=item.dimension is ScoreDimension.STACK_ALIGNMENT and stack_neutral,
        )
        for item in breakdown
    ]

    weighted = [item.model_copy(update={"weight": weights[item.dimension]}) for item in breakdown]

    vector = ScoreVector(
        technical_depth=weighted[0].score,
        stack_alignment=weighted[1].score,
        systems_literacy=weighted[2].score,
        verifiable_certifications=weighted[3].score,
    )
    return ScoringResult(vector=vector, breakdown=weighted)


def _evidence_first(item: DimensionScore, *, neutral: bool = False) -> DimensionScore:
    """Zero a dimension that carries no reference, and say why in its rationale.

    ``neutral`` is for the one score that is a statement about the job rather
    than about the candidate (no requirements were stated), so there is nothing
    to cite and nothing to punish.
    """
    if item.evidence or neutral:
        return item
    return item.model_copy(
        update={
            "score": 0.0,
            "rationale": f"{item.rationale} — no supporting evidence; contributes 0",
        }
    )


def role_fit_sufficient(
    breakdown: Iterable[DimensionScore], *, must_have_floor: float = 0.5
) -> bool:
    """Whether the record supports the role, not just a long career in *a* role.

    Tenure is a real signal, but a candidate whose depth is carried by tenure
    while fewer than half of the job's must-have skills are evidenced has not
    shown they can do *this* job. The check is deliberately narrow: it only
    fires when the must-have requirements exist and are thin, and it never
    lowers the score — policy routes the case to a person instead.
    """
    depth = next(
        (item for item in breakdown if item.dimension is ScoreDimension.TECHNICAL_DEPTH),
        None,
    )
    stack = next(
        (item for item in breakdown if item.dimension is ScoreDimension.STACK_ALIGNMENT), None
    )
    if depth is None or stack is None or depth.score <= 0:
        return True
    tenure = depth.components.get("tenure", 0.0)
    must_have = stack.components.get("must_have")
    if must_have is None:
        return True
    return not (tenure >= 0.5 * depth.score and must_have < must_have_floor)


def score_runs(
    profiles: Iterable[CandidateProfile],
    job: JobSpecification,
    *,
    reference_date: date | None = None,
) -> list[ScoringResult]:
    """Score k independently extracted profiles for the same candidate."""
    return [score_candidate(profile, job, reference_date=reference_date) for profile in profiles]
