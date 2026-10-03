"""Calibration corpus for the scoring function.

The scorer gates three outcomes -- auto-schedule, route to a human, or flag for
review -- and until now nothing measured whether those bands lined up with the
scores the scorer actually produces. They did not: with the shipped weights a
well-matched senior engineer scored about 0.68 against a 0.70 floor, so ordinary
competent candidates were routed into the band that reads as "weak". The
thresholds themselves are a human-approved contract
(``docs/architecture/hitl-bounds.md``) and are *not* touched here; this corpus
exists to measure the scorer they gate.

**Label-free by design.** There is no ground truth saying "this accountant is a
strong candidate" -- inventing one would let anyone move a number until a test
passed. So the assertions are structural instead:

- the strong tier outscores the adequate tier, which outscores the weak tier,
  for every occupation;
- matching the job's must-haves beats equal tenure without them;
- every band is reachable, so no band is dead;
- the adequate tier is never routed below the soft-rejection floor.

Those fail on the old weights and pass on the current ones, which is what makes
this a fence rather than a snapshot.

Four occupations on purpose. The scorer is built around software-shaped evidence
-- a `systems_literacy` category list, architecture keywords, and job-title tiers
that only contain software titles -- so a corpus of engineers would pass while
the product quietly mis-scored everyone else. A teacher matches no title tier at
all and is scored as "unranked"; that is recorded here rather than smoothed over.

Scoring is pure and deterministic, so this needs no language model and is not
wired into ``scripts/run_evals.py``. The assertions in
``tests/services/test_scoring_calibration.py`` import the corpus from here, so
the gate enforces it and the dataset stays the single source of truth.

Anonymised and synthetic. No real candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from hr_agents.models import (
    CandidateProfile,
    CertificationClaim,
    ContractType,
    EvidenceRef,
    ExperienceEntry,
    JobSpecification,
    Location,
    ProjectEntry,
    Publication,
    Skill,
    SkillCategory,
    SourceType,
    VerificationStatus,
)

REFERENCE_DATE = date(2025, 1, 1)
"""Fixed, so scores do not drift with the wall clock."""


@dataclass(frozen=True)
class CalibrationCase:
    """One candidate scored against the job they are actually applying for."""

    occupation: str
    tier: str
    profile: CandidateProfile
    job: JobSpecification

    @property
    def name(self) -> str:
        return f"{self.occupation}_{self.tier}"


@dataclass(frozen=True)
class Occupation:
    """A job family and the shape of a candidate who fits it."""

    key: str
    job: JobSpecification
    strong: CandidateProfile
    adequate: CandidateProfile
    weak: CandidateProfile
    tenured_misfit: CandidateProfile
    """Same tenure as ``strong``, none of the required skills.

    This is the profile that separates pedigree from fit: if tenure alone could
    carry a score, this one would pass. It exists because ``technical_depth``
    puts 0.4375 of a dimension on tenure, and that is only defensible if a long
    history in the wrong field does not beat a shorter one in the right field.
    """


def _experience(
    company: str,
    title: str,
    *,
    years: float,
    highlights: tuple[str, ...] = (),
    stack: tuple[str, ...] = (),
) -> ExperienceEntry:
    return ExperienceEntry(
        company=company,
        title=title,
        start_date=date(REFERENCE_DATE.year - int(years), REFERENCE_DATE.month, 1),
        end_date=REFERENCE_DATE,
        highlights=list(highlights),
        tech_stack=list(stack),
    )


def _skills(*pairs: tuple[str, SkillCategory]) -> list[Skill]:
    return [Skill(name=name, category=category) for name, category in pairs]


def _projects(count: int, *, open_source: bool = True) -> list[ProjectEntry]:
    return [
        ProjectEntry(
            name=f"portfolio project {index}",
            description="Built and shipped an end-to-end system.",
            is_open_source=open_source,
        )
        for index in range(count)
    ]


def _certifications(count: int) -> list[CertificationClaim]:
    return [
        CertificationClaim(
            name=f"Professional certification {index}",
            issuer="Institute",
            status=VerificationStatus.VERIFIED,
            evidence=[
                EvidenceRef(source_type=SourceType.RESUME, locator=f"cert-{index}", confidence=1.0)
            ],
        )
        for index in range(count)
    ]


ENGINEERING_JOB = JobSpecification(
    title="Backend Engineer",
    must_have_skills=["Python", "PostgreSQL"],
    stack=["FastAPI"],
)

FINANCE_JOB = JobSpecification(
    title="Financial Accountant",
    must_have_skills=["IFRS", "GAAP"],
    stack=["Financial reporting"],
)

TEACHING_JOB = JobSpecification(
    title="Secondary School Teacher",
    must_have_skills=["Curriculum design", "Assessment"],
    stack=["Classroom management"],
)

SALES_JOB = JobSpecification(
    title="Account Executive",
    must_have_skills=["Pipeline management", "Negotiation"],
    stack=["CRM"],
)


def _engineering() -> Occupation:
    strong = CandidateProfile(
        full_name="Engineer Strong",
        emails=["strong@example.com"],
        location=Location(city="Jakarta", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "Nusantara Systems",
                "Senior Software Engineer",
                years=6.5,
                highlights=(
                    "Built queue-based ingestion handling 40k events per minute",
                    "Cut p99 latency by 60% across the payments path",
                    "Owned the event-driven architecture review",
                ),
                stack=("Python", "PostgreSQL", "Kafka", "Redis"),
            )
        ],
        skills=_skills(
            ("Python", SkillCategory.LANGUAGE),
            ("Go", SkillCategory.LANGUAGE),
            ("Rust", SkillCategory.LANGUAGE),
            ("PostgreSQL", SkillCategory.DATABASE),
            ("Redis", SkillCategory.DATABASE),
            ("Kafka", SkillCategory.SYSTEMS),
            ("Kubernetes", SkillCategory.DEVOPS),
            ("AWS", SkillCategory.CLOUD),
            ("GCP", SkillCategory.CLOUD),
            ("Docker", SkillCategory.DEVOPS),
        ),
        projects=_projects(4),
        certifications=_certifications(3),
    )
    adequate = CandidateProfile(
        full_name="Engineer Adequate",
        emails=["adequate@example.com"],
        location=Location(city="Jakarta", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "Nusantara Systems",
                "Backend Engineer",
                years=6,
                highlights=("Maintained the reporting API", "Owned two internal services"),
                stack=("Python", "PostgreSQL"),
            )
        ],
        skills=_skills(
            ("Python", SkillCategory.LANGUAGE),
            ("PostgreSQL", SkillCategory.DATABASE),
            ("Redis", SkillCategory.DATABASE),
            ("Docker", SkillCategory.DEVOPS),
            ("Kafka", SkillCategory.SYSTEMS),
            ("AWS", SkillCategory.CLOUD),
            ("GCP", SkillCategory.CLOUD),
            ("Git", SkillCategory.OTHER),
        ),
        projects=_projects(2),
    )
    weak = CandidateProfile(
        full_name="Engineer Weak",
        emails=["weak@example.com"],
        location=Location(city="Jakarta", timezone="Asia/Jakarta"),
        experience=[_experience("Studio", "Junior Developer", years=0.5, stack=("PHP",))],
        skills=_skills(("PHP", SkillCategory.LANGUAGE)),
    )
    tenured_misfit = CandidateProfile(
        full_name="Engineer Tenured Misfit",
        emails=["misfit@example.com"],
        location=Location(city="Jakarta", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "Nusantara Systems",
                "Senior Software Engineer",
                years=6.5,
                highlights=(
                    "Built queue-based ingestion handling 40k events per minute",
                    "Cut p99 latency by 60% across the payments path",
                    "Owned the event-driven architecture review",
                ),
                stack=("Java", "Oracle", "Kafka"),
            )
        ],
        skills=_skills(
            ("Java", SkillCategory.LANGUAGE),
            ("Oracle", SkillCategory.DATABASE),
            ("Kafka", SkillCategory.SYSTEMS),
            ("Kubernetes", SkillCategory.DEVOPS),
            ("AWS", SkillCategory.CLOUD),
        ),
        projects=_projects(4),
        certifications=_certifications(3),
    )
    return Occupation(
        key="engineering",
        job=ENGINEERING_JOB,
        strong=strong,
        adequate=adequate,
        weak=weak,
        tenured_misfit=tenured_misfit,
    )


def _finance() -> Occupation:
    strong = CandidateProfile(
        full_name="Accountant Strong",
        emails=["acct-strong@example.com"],
        location=Location(city="Jakarta", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "Karya Finance",
                "Senior Financial Accountant",
                years=7,
                highlights=(
                    "Owned statutory reporting under IFRS and GAAP",
                    "Led the year-end audit readiness programme",
                    "Reconciled the group ledger across four entities",
                ),
                stack=("IFRS", "GAAP", "Tax compliance"),
            )
        ],
        skills=_skills(
            ("IFRS", SkillCategory.OTHER),
            ("GAAP", SkillCategory.OTHER),
            ("Tax compliance", SkillCategory.OTHER),
            ("Financial reporting", SkillCategory.DATA),
            ("Audit", SkillCategory.OTHER),
            ("IFRS 15", SkillCategory.OTHER),
            ("Consolidation", SkillCategory.DATA),
            ("Odoo", SkillCategory.OTHER),
        ),
        projects=_projects(3, open_source=False),
        certifications=_certifications(3),
    )
    adequate = CandidateProfile(
        full_name="Accountant Adequate",
        emails=["acct-ok@example.com"],
        location=Location(city="Jakarta", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "Karya Finance",
                "Financial Accountant",
                years=6,
                highlights=("Prepared monthly statutory filings",),
                stack=("IFRS", "GAAP"),
            )
        ],
        skills=_skills(
            ("IFRS", SkillCategory.OTHER),
            ("GAAP", SkillCategory.OTHER),
            ("Tax compliance", SkillCategory.OTHER),
            ("Financial reporting", SkillCategory.DATA),
            ("Audit", SkillCategory.OTHER),
            ("Odoo", SkillCategory.OTHER),
            ("Consolidation", SkillCategory.DATA),
        ),
        projects=_projects(2, open_source=False),
    )
    weak = CandidateProfile(
        full_name="Accountant Weak",
        emails=["acct-weak@example.com"],
        location=Location(city="Jakarta", timezone="Asia/Jakarta"),
        experience=[
            _experience("Karya Finance", "Junior Accounting Clerk", years=0.4, stack=("Excel",))
        ],
        skills=_skills(("Excel", SkillCategory.OTHER)),
    )
    tenured_misfit = CandidateProfile(
        full_name="Accountant Tenured Misfit",
        emails=["acct-misfit@example.com"],
        location=Location(city="Jakarta", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "Karya Retail Group",
                "Senior Financial Accountant",
                years=7,
                highlights=(
                    "Owned statutory reporting for eleven retail outlets",
                    "Led the year-end audit readiness programme",
                ),
                stack=(
                    "Excel",
                    "Sage",
                ),
            )
        ],
        # Deliberately none of the job's must-haves. The first draft of this
        # fixture reused the strong profile's skill list, so it scored *exactly*
        # the same and the pedigree-versus-fit comparison silently tested nothing.
        skills=_skills(
            ("Excel", SkillCategory.OTHER),
            ("Sage", SkillCategory.OTHER),
            ("Payroll processing", SkillCategory.OTHER),
            ("Forecasting", SkillCategory.DATA),
            ("Vendor management", SkillCategory.OTHER),
        ),
        projects=_projects(3, open_source=False),
        certifications=_certifications(3),
    )
    return Occupation(
        key="finance",
        job=FINANCE_JOB,
        strong=strong,
        adequate=adequate,
        weak=weak,
        tenured_misfit=tenured_misfit,
    )


def _teaching() -> Occupation:
    strong = CandidateProfile(
        full_name="Teacher Strong",
        emails=["teach-strong@example.com"],
        location=Location(city="Bandung", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "SMA Nusantara",
                "Senior Subject Teacher",
                years=8,
                highlights=(
                    "Led the department curriculum review",
                    "Designed the assessment framework used across the year",
                    "Mentored four new teachers through their first year",
                ),
                stack=("Curriculum design", "Assessment", "Classroom management"),
            )
        ],
        skills=_skills(
            ("Curriculum design", SkillCategory.OTHER),
            ("Assessment", SkillCategory.OTHER),
            ("Classroom management", SkillCategory.OTHER),
            ("Pedagogy", SkillCategory.OTHER),
            ("Differentiated instruction", SkillCategory.OTHER),
            ("Learning analytics", SkillCategory.DATA),
            ("Curriculum mapping", SkillCategory.OTHER),
            ("Inclusive practice", SkillCategory.OTHER),
        ),
        projects=_projects(3, open_source=False),
        publications=_publications(2),
        certifications=_certifications(3),
    )
    adequate = CandidateProfile(
        full_name="Teacher Adequate",
        emails=["teach-ok@example.com"],
        location=Location(city="Bandung", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "SMA Nusantara",
                "Subject Teacher",
                years=6,
                highlights=("Taught the national syllabus",),
                stack=("Curriculum design", "Assessment"),
            )
        ],
        skills=_skills(
            ("Curriculum design", SkillCategory.OTHER),
            ("Assessment", SkillCategory.OTHER),
            ("Classroom management", SkillCategory.OTHER),
            ("Pedagogy", SkillCategory.OTHER),
            ("Differentiated instruction", SkillCategory.OTHER),
            ("Learning analytics", SkillCategory.DATA),
            ("Curriculum mapping", SkillCategory.OTHER),
        ),
        projects=_projects(2, open_source=False),
    )
    weak = CandidateProfile(
        full_name="Teacher Weak",
        emails=["teach-weak@example.com"],
        location=Location(city="Bandung", timezone="Asia/Jakarta"),
        experience=[_experience("SMA Nusantara", "Teaching Assistant", years=0.3)],
        skills=_skills(("Classroom management", SkillCategory.OTHER)),
    )
    tenured_misfit = CandidateProfile(
        full_name="Teacher Tenured Misfit",
        emails=["teach-misfit@example.com"],
        location=Location(city="Bandung", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "SMA Nusantara",
                "Senior Subject Teacher",
                years=8,
                highlights=(
                    "Led the department curriculum review",
                    "Designed the assessment framework used across the year",
                ),
                stack=("Curriculum design", "Assessment"),
            )
        ],
        skills=_skills(
            ("Curriculum design", SkillCategory.OTHER),
            ("Assessment", SkillCategory.OTHER),
            ("Classroom management", SkillCategory.OTHER),
            ("Pedagogy", SkillCategory.OTHER),
        ),
        projects=_projects(3, open_source=False),
        publications=_publications(2),
        certifications=_certifications(3),
    )
    return Occupation(
        key="teaching",
        job=TEACHING_JOB,
        strong=strong,
        adequate=adequate,
        weak=weak,
        tenured_misfit=tenured_misfit,
    )


def _publications(count: int) -> list[Publication]:
    return [
        Publication(
            title=f"Teaching practice note {index}",
            venue="Journal of Practitioner Research",
            year=2023,
            peer_reviewed=True,
            citation_count=3,
        )
        for index in range(count)
    ]


def _sales() -> Occupation:
    strong = CandidateProfile(
        full_name="Sales Strong",
        emails=["sales-strong@example.com"],
        location=Location(city="Surabaya", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "PT Nusantara Niaga",
                "Senior Account Executive",
                years=7,
                highlights=(
                    "Closed 1.2B IDR of new business across three territories",
                    "Rebuilt the pipeline review cadence for a 14-person team",
                    "Negotiated the renewal that saved the largest account",
                ),
                stack=("Pipeline management", "Negotiation", "CRM"),
            )
        ],
        skills=_skills(
            ("Pipeline management", SkillCategory.OTHER),
            ("Negotiation", SkillCategory.OTHER),
            ("CRM", SkillCategory.OTHER),
            ("Account management", SkillCategory.OTHER),
            ("Forecasting", SkillCategory.DATA),
            ("Territory planning", SkillCategory.OTHER),
            ("Channel partnerships", SkillCategory.OTHER),
            ("Bid management", SkillCategory.OTHER),
        ),
        projects=_projects(3, open_source=False),
        certifications=_certifications(3),
    )
    adequate = CandidateProfile(
        full_name="Sales Adequate",
        emails=["sales-ok@example.com"],
        location=Location(city="Surabaya", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "PT Nusantara Niaga",
                "Account Executive",
                years=6,
                highlights=("Managed a territory of 40 accounts",),
                stack=("Pipeline management", "Negotiation"),
            )
        ],
        skills=_skills(
            ("Pipeline management", SkillCategory.OTHER),
            ("Negotiation", SkillCategory.OTHER),
            ("CRM", SkillCategory.OTHER),
            ("Account management", SkillCategory.OTHER),
            ("Forecasting", SkillCategory.DATA),
            ("Territory planning", SkillCategory.OTHER),
            ("Bid management", SkillCategory.OTHER),
        ),
        projects=_projects(2, open_source=False),
    )
    weak = CandidateProfile(
        full_name="Sales Weak",
        emails=["sales-weak@example.com"],
        location=Location(city="Surabaya", timezone="Asia/Jakarta"),
        experience=[_experience("PT Nusantara Niaga", "Sales Intern", years=0.3)],
        skills=_skills(("CRM", SkillCategory.OTHER)),
    )
    tenured_misfit = CandidateProfile(
        full_name="Sales Tenured Misfit",
        emails=["sales-misfit@example.com"],
        location=Location(city="Surabaya", timezone="Asia/Jakarta"),
        experience=[
            _experience(
                "PT Nusantara Niaga",
                "Senior Account Executive",
                years=7,
                highlights=(
                    "Closed 1.2B IDR of new business across three territories",
                    "Rebuilt the pipeline review cadence for a 14-person team",
                ),
                stack=("CRM",),
            )
        ],
        skills=_skills(
            ("CRM", SkillCategory.OTHER),
            ("Forecasting", SkillCategory.DATA),
            ("Account management", SkillCategory.OTHER),
            ("Territory planning", SkillCategory.OTHER),
        ),
        projects=_projects(3, open_source=False),
        certifications=_certifications(3),
    )
    return Occupation(
        key="sales",
        job=SALES_JOB,
        strong=strong,
        adequate=adequate,
        weak=weak,
        tenured_misfit=tenured_misfit,
    )


OCCUPATIONS: tuple[Occupation, ...] = (_engineering(), _finance(), _teaching(), _sales())
"""Four families. Deliberately not four versions of an engineer."""


def build_cases() -> list[CalibrationCase]:
    """Every tier of every occupation, as flat calibration cases."""
    cases: list[CalibrationCase] = []
    for occupation in OCCUPATIONS:
        for tier in ("strong", "adequate", "weak"):
            cases.append(
                CalibrationCase(
                    occupation=occupation.key,
                    tier=tier,
                    profile=getattr(occupation, tier),
                    job=occupation.job,
                )
            )
    return cases


def build_tenured_misfit_cases() -> list[CalibrationCase]:
    """Equal tenure, wrong skills -- the pedigree-versus-fit comparison."""
    return [
        CalibrationCase(
            occupation=occupation.key,
            tier="tenured_misfit",
            profile=occupation.tenured_misfit,
            job=occupation.job,
        )
        for occupation in OCCUPATIONS
    ]


def build_saturation_profile(*, publications: int) -> CandidateProfile:
    """A candidate who maxes out every term ``technical_depth`` measures.

    Long enough past the 60-month tenure saturation, more distinct skills than
    the 12-skill breadth saturation, more projects than the 3-project saturation.
    Varying only ``publications`` isolates what publication history is worth.
    """
    return CandidateProfile(
        full_name="Maximal Candidate",
        emails=["maximal@example.com"],
        experience=[
            _experience(
                "Nusantara Systems",
                "Principal",
                years=15,
                stack=tuple(f"skill-{index}" for index in range(20)),
            )
        ],
        skills=_skills(
            *((f"skill-{index}", SkillCategory.OTHER) for index in range(20)),
        ),
        projects=_projects(6),
        publications=_publications(publications),
    )


def build_saturation_job() -> JobSpecification:
    """A vacancy matching every skill on :func:`build_saturation_profile`.

    Only ``technical_depth`` is under test here, but a job the candidate does not
    match would drag the other three dimensions down and obscure the ceiling.
    """
    return JobSpecification(
        title="Principal Engineer",
        must_have_skills=[f"skill-{index}" for index in range(20)],
        min_years_experience=10,
    )


def build_dataset() -> object:
    """A ``pydantic_evals`` dataset wrapping the corpus.

    Scoring is a pure function, so this exists for discoverability and reuse
    rather than to be driven by an LLM harness -- ``scripts/run_evals.py`` needs
    no model to run these. The gate is the assertions in
    ``tests/services/test_scoring_calibration.py``.
    """
    from pydantic_evals import Case, Dataset

    return Dataset(
        name="scoring_calibration",
        cases=[Case(name=case.name, inputs=case) for case in build_cases()],
        evaluators=[],
    )


__all__ = [
    "OCCUPATIONS",
    "REFERENCE_DATE",
    "CalibrationCase",
    "ContractType",
    "Occupation",
    "build_cases",
    "build_dataset",
    "build_saturation_job",
    "build_saturation_profile",
    "build_tenured_misfit_cases",
]
