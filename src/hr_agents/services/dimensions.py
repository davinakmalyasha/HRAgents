"""Per-occupation scoring rubrics.

The scorer computed one rubric and applied it to every occupation. That rubric was
software-shaped: a skill-category list of ``{database, devops, cloud, systems, data}``,
sixteen architecture keywords, and job-title tiers made of software and management words.
A finance supervisor therefore scored **0.000** on the professional dimension -- not low,
zero -- because every accounting skill was ``SkillCategory.OTHER``, none of the keywords
appeared in their highlights, and "Accounting Supervisor" matched no title tier. Their
weighted total came to 0.5425 against a 0.70 floor, which is an automatic rejection with
no human in the loop.

A template varies *which evidence counts*, not how many axes there are. ``ScoreVector``
stays S in [0, 1]^4 and the axis names are unchanged, because those names are persisted
in ``evaluations``, exposed in the OpenAPI document, rendered in the dashboard and
translated in two locales. What was wrong was the rubric, not the tensor.

Two invariants hold here:

- ``ENGINEERING`` reproduces the previous numbers exactly. The templates exist because
  the rubric was too narrow, not because engineering was scored wrongly.
- No template invents a threshold. Every saturation point is shared and every internal
  weight is either the previous value or a named constant, so no family can quietly score
  on a different scale from the calibration fences in ``test_scoring_calibration.py``.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from hr_agents.models import JobFamily, SkillCategory, StrictModel

# Everything that is not a letter or digit in a job title becomes a space, so that
# "Team Lead, Payments" and "Sr. Accountant" split into the words a tier lists.
_TITLE_PUNCTUATION = str.maketrans({char: " " for char in ",.;:()[]/'\"&|!?"})

# Saturation points. These are properties of how much evidence is "enough", not of an
# occupation, so they are shared: a template that changed them would score its family on a
# different scale from every other family and the cross-family fences would stop meaning
# anything.
TENURE_SATURATION_MONTHS = Decimal(60)
BREADTH_SATURATION_SKILLS = Decimal(12)
PROJECT_SATURATION = Decimal(3)
PUBLICATION_SATURATION = Decimal(3)
KEYWORD_SATURATION = 6
CERT_COUNT_SATURATION = Decimal(3)

SYSTEMS_WEIGHTS = {
    "categories": Decimal("0.50"),
    "keywords": Decimal("0.30"),
    "seniority": Decimal("0.20"),
}
"""How the professional dimension is composed, as opposed to what counts as evidence.

The three components describe the *shape* of the dimension: how much is the breadth of a
candidate's competency areas, how much is evidence of systemic judgement, how much is
their standing. Every family uses the same shape; the families differ in the vocabulary.
A default rather than a required field, so there is one source of truth and a family can
still override it deliberately.
"""


class DimensionTemplate(StrictModel):
    """One occupation's rubric: what counts as evidence of competence.

    Every field is required except ``systems_weights``. ``score_candidate`` resolves
    missing values with ``or``, which would substitute the engineering default silently --
    so a template that forgot a value would be indistinguishable from one that chose it.
    """

    family: JobFamily
    description: str = Field(min_length=1, max_length=300)

    depth_weights: dict[str, Decimal] = Field(
        description=(
            "Internal weights over the depth terms, summing to 1.0. `breadth` counts "
            "terms matched against `breadth_vocabulary`, not raw skills, which is how a "
            "family decides what breadth means for it."
        )
    )
    breadth_vocabulary: frozenset[str] = Field(
        default_factory=frozenset,
        description=(
            "Normalised terms that count towards breadth. Empty means the family's terms "
            "count as-is, which is what engineering does."
        ),
    )
    systems_weights: dict[str, Decimal] = Field(
        default_factory=lambda: dict(SYSTEMS_WEIGHTS),
        description=(
            "Relative weight of competency areas, professional signals and title seniority."
        ),
    )
    professional_categories: frozenset[SkillCategory] = Field(
        description="Skill categories that count towards the professional dimension."
    )
    signal_keywords: tuple[str, ...] = Field(
        description=(
            "Substrings matched against experience highlights that signal the systemic "
            "judgement this occupation demonstrates."
        )
    )
    signal_saturation: int = Field(description="Signal keywords that count as full marks.")
    breadth_saturation: int = Field(
        description=(
            "Distinct relevant terms that count as full breadth. Occupations differ: "
            "nobody lists twelve accounting standards, and a template that inherited "
            "engineering's twelve would cap every finance candidate's breadth at a "
            "quarter."
        ),
    )
    title_tiers: tuple[tuple[frozenset[str], float], ...] = Field(
        description=(
            "Job-title tiers, most senior first. Matched against the lowercased title as "
            "whole words, so `senior` cannot match inside `supervision`."
        )
    )

    def tier_for(self, titles: str) -> tuple[float, str]:
        """``(component, matched_label)`` for a blob of lowercased job titles.

        Word-boundary matched, first tier wins. The previous implementation used a plain
        substring test over concatenated titles, so ``sr`` matched any title containing
        those two letters and ``head`` matched "Ahead of schedule".

        Punctuation is stripped before splitting, because real titles carry it:
        "Team Lead, Payments" is a lead, and splitting on whitespace alone would leave
        ``lead,`` which matches no tier.
        """
        cleaned = titles.translate(_TITLE_PUNCTUATION)
        words = set(cleaned.replace("-", " ").replace("/", " ").split())
        for tokens, value in self.title_tiers:
            hit = words & tokens
            if hit:
                return value, sorted(hit)[0]
        return 0.0, "unranked"


ENGINEERING = DimensionTemplate(
    family=JobFamily.ENGINEERING,
    description="Software engineering, from the original scorer, preserved exactly.",
    depth_weights={
        "tenure": Decimal("0.4375"),
        "breadth": Decimal("0.3375"),
        "projects": Decimal("0.15"),
        "publications": Decimal("0.075"),
    },
    breadth_vocabulary=frozenset(),
    professional_categories=frozenset(
        {
            SkillCategory.DATABASE,
            SkillCategory.DEVOPS,
            SkillCategory.CLOUD,
            SkillCategory.SYSTEMS,
            SkillCategory.DATA,
        }
    ),
    signal_keywords=(
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
    ),
    signal_saturation=KEYWORD_SATURATION,
    breadth_saturation=12,
    title_tiers=(
        (frozenset({"principal", "architect", "head", "director", "vp"}), 1.0),
        (frozenset({"lead", "staff"}), 0.9),
        (frozenset({"senior", "sr"}), 0.8),
        (frozenset({"engineer", "developer", "programmer"}), 0.6),
        (frozenset({"junior", "jr", "intern", "trainee"}), 0.3),
    ),
)

FINANCE = DimensionTemplate(
    family=JobFamily.FINANCE,
    description=(
        "Accounting, audit, tax and corporate finance. Breadth counts the accounting "
        "standards and domains worked in, which is what range of experience means here "
        "rather than the number of tools."
    ),
    depth_weights={
        "tenure": Decimal("0.55"),
        "breadth": Decimal("0.45"),
        "projects": Decimal("0"),
        "publications": Decimal("0"),
    },
    breadth_vocabulary=frozenset(
        {
            "ifrs",
            "psak",
            "gaap",
            "fas",
            "isa",
            "ifac",
            "financial-reporting",
            "management-accounts",
            "cost-accounting",
            "tax",
            "taxation",
            "pajak",
            "transfer-pricing",
            "vat",
            "audit",
            "auditing",
            "internal-control",
            "internal-audit",
            "budgeting",
            "forecasting",
            "treasury",
            "cash-flow",
            "payroll",
            "general-ledger",
            "consolidation",
            "statutory",
            "compliance",
            "accounting",
            "bookkeeping",
            "accrual",
            "deferred-revenue",
            "lease-accounting",
            "financial-modelling",
            "financial-analysis",
            "fp-a",
        }
    ),
    professional_categories=frozenset(
        {SkillCategory.FINANCE, SkillCategory.DATA, SkillCategory.LEGAL, SkillCategory.GENERAL}
    ),
    signal_keywords=(
        "statutory",
        "close",
        "consolidat",
        "reconcil",
        "audit",
        "assurance",
        "controls",
        "compliance",
        "tax",
        "ledger",
        "accrual",
        "provision",
        "variance",
        "forecast",
        "budget",
        "treasury",
        "ifrs",
        "psak",
    ),
    signal_saturation=KEYWORD_SATURATION,
    breadth_saturation=6,
    title_tiers=(
        (frozenset({"chief", "cfo", "finance-director"}), 1.0),
        (frozenset({"head", "manager", "principal"}), 0.95),
        (frozenset({"supervisor", "lead", "senior", "sr"}), 0.8),
        (frozenset({"accountant", "auditor", "analyst", "controller", "staff"}), 0.6),
        (frozenset({"assistant", "associate", "junior", "jr", "trainee", "intern"}), 0.3),
    ),
)

EDUCATION = DimensionTemplate(
    family=JobFamily.EDUCATION,
    description=(
        "Teaching and academic leadership. Breadth counts subjects and curricula covered; "
        "there are no projects in the software sense, so depth leans on tenure."
    ),
    depth_weights={
        "tenure": Decimal("0.65"),
        "breadth": Decimal("0.35"),
        "projects": Decimal("0"),
        "publications": Decimal("0"),
    },
    breadth_vocabulary=frozenset(
        {
            "curriculum",
            "curriculum-design",
            "pedagogy",
            "pedagogical",
            "assessment",
            "formative-assessment",
            "classroom-management",
            "lesson-planning",
            "syllabus",
            "grading",
            "literacy",
            "numeracy",
            "subject-teaching",
            "class-management",
            "inclusive-education",
            "special-needs",
            "differentiation",
            "blended-learning",
            "teacher-training",
            "mentoring",
            "coaching",
            "supervision",
        }
    ),
    professional_categories=frozenset(
        {SkillCategory.EDUCATION, SkillCategory.GENERAL, SkillCategory.DATA}
    ),
    signal_keywords=(
        "curriculum",
        "pedagog",
        "classroom",
        "assessment",
        "student",
        "pupil",
        "lesson",
        "syllabus",
        "literacy",
        "numeracy",
        "grading",
        "behaviour",
        "inclusion",
        "mentoring",
        "coaching",
        "school",
        "learning",
        "teaching",
    ),
    signal_saturation=KEYWORD_SATURATION,
    breadth_saturation=6,
    title_tiers=(
        (frozenset({"principal", "director", "head", "dean"}), 1.0),
        (frozenset({"chair", "coordinator", "lead", "vice-principal"}), 0.95),
        (frozenset({"supervisor", "senior", "sr", "specialist"}), 0.8),
        (frozenset({"teacher", "instructor", "lecturer", "tutor"}), 0.6),
        (frozenset({"assistant", "junior", "jr", "trainee", "intern", "cadet"}), 0.3),
    ),
)

HEALTHCARE = DimensionTemplate(
    family=JobFamily.HEALTHCARE,
    description=(
        "Clinical and allied health. Breadth counts specialisms; certifications and "
        "registrations are the primary evidence of competence."
    ),
    depth_weights={
        "tenure": Decimal("0.60"),
        "breadth": Decimal("0.40"),
        "projects": Decimal("0"),
        "publications": Decimal("0"),
    },
    breadth_vocabulary=frozenset(
        {
            "emergency",
            "critical-care",
            "intensive-care",
            "icu",
            "theatre",
            "surgery",
            "surgical",
            "anaesthesia",
            "pediatrics",
            "paediatrics",
            "obstetrics",
            "geriatrics",
            "oncology",
            "cardiology",
            "neurology",
            "radiology",
            "pathology",
            "pharmacy",
            "nursing",
            "midwifery",
            "physiotherapy",
            "occupational-therapy",
            "dietetics",
            "primary-care",
            "public-health",
            "epidemiology",
            "triage",
            "clinical-audit",
            "medication-safety",
            "infection-control",
        }
    ),
    professional_categories=frozenset({SkillCategory.HEALTHCARE, SkillCategory.GENERAL}),
    signal_keywords=(
        "patient",
        "clinical",
        "care-plan",
        "ward",
        "triage",
        "diagnosis",
        "treatment",
        "clinical-audit",
        "safety",
        "infection",
        "discharge",
        "admission",
        "multidisciplinary",
        "mdt",
        "prescribing",
        "ward-round",
        "resuscitation",
        "guideline",
    ),
    signal_saturation=KEYWORD_SATURATION,
    breadth_saturation=6,
    title_tiers=(
        (frozenset({"chief", "medical-director", "director", "consultant"}), 1.0),
        (frozenset({"head", "principal", "attending", "lead"}), 0.95),
        (frozenset({"registrar", "supervisor", "senior", "sr", "specialist"}), 0.8),
        (frozenset({"officer", "practitioner", "nurse", "therapist", "pharmacist"}), 0.6),
        (frozenset({"junior", "jr", "trainee", "intern", "resident", "student"}), 0.3),
    ),
)

LEGAL = DimensionTemplate(
    family=JobFamily.LEGAL,
    description=(
        "Legal practice. Breadth counts practice areas; matter leadership is the "
        "systemic-judgement signal rather than architecture work."
    ),
    depth_weights={
        "tenure": Decimal("0.60"),
        "breadth": Decimal("0.40"),
        "projects": Decimal("0"),
        "publications": Decimal("0"),
    },
    breadth_vocabulary=frozenset(
        {
            "corporate-law",
            "commercial-law",
            "employment-law",
            "ip",
            "intellectual-property",
            "litigation",
            "dispute-resolution",
            "arbitration",
            "mediation",
            "contract",
            "contract-drafting",
            "compliance",
            "regulatory",
            "tax-law",
            "real-estate",
            "property",
            "immigration",
            "privacy",
            "data-protection",
            "mergers",
            "m-a",
            "due-diligence",
            "securities",
            "banking-law",
            "insurance",
            "construction-law",
            "environmental-law",
            "employment",
            "licensing",
            "permitting",
        }
    ),
    professional_categories=frozenset(
        {SkillCategory.LEGAL, SkillCategory.FINANCE, SkillCategory.GENERAL}
    ),
    signal_keywords=(
        "matter",
        "litigation",
        "hearing",
        "tribunal",
        "arbitration",
        "settlement",
        "client",
        "counsel",
        "brief",
        "opinion",
        "transaction",
        "due-diligence",
        "contract",
        "clause",
        "negotiat",
        "compliance",
        "regulator",
        "ruling",
    ),
    signal_saturation=KEYWORD_SATURATION,
    breadth_saturation=6,
    title_tiers=(
        (frozenset({"partner", "chief", "director", "general-counsel"}), 1.0),
        (frozenset({"counsel", "principal", "lead", "head"}), 0.95),
        (frozenset({"senior", "sr", "supervisor", "associate-director"}), 0.8),
        (frozenset({"associate", "solicitor", "lawyer"}), 0.6),
        (frozenset({"junior", "jr", "trainee", "paralegal", "intern"}), 0.3),
    ),
)

OPERATIONS = DimensionTemplate(
    family=JobFamily.OPERATIONS,
    description=(
        "Operations, logistics and supply chain. Breadth counts the operational domains "
        "owned; process improvement is the systemic-judgement signal."
    ),
    depth_weights={
        "tenure": Decimal("0.60"),
        "breadth": Decimal("0.40"),
        "projects": Decimal("0"),
        "publications": Decimal("0"),
    },
    breadth_vocabulary=frozenset(
        {
            "supply-chain",
            "logistics",
            "procurement",
            "purchasing",
            "inventory",
            "warehouse",
            "fulfilment",
            "fulfillment",
            "forecasting",
            "demand-planning",
            "production",
            "manufacturing",
            "quality-assurance",
            "qa",
            "qc",
            "maintenance",
            "reliability",
            "capacity-planning",
            "sourcing",
            "vendor-management",
            "fleet",
            "transport",
            "customs",
            "cold-chain",
            "lean",
            "six-sigma",
            "continuous-improvement",
            "process-improvement",
            "erp",
            "scm",
            "mrp",
            "planning",
            "scheduling",
        }
    ),
    professional_categories=frozenset(
        {SkillCategory.OPERATIONS, SkillCategory.GENERAL, SkillCategory.DATA}
    ),
    signal_keywords=(
        "process",
        "workflow",
        "bottleneck",
        "throughput",
        "utilisation",
        "utilization",
        "downtime",
        "root-cause",
        "improvement",
        "cost",
        "waste",
        "sla",
        "service-level",
        "capacity",
        "forecast",
        "demand",
        "lead-time",
        "inventory",
        "supplier",
        "vendor",
        "continuous-improvement",
    ),
    signal_saturation=KEYWORD_SATURATION,
    breadth_saturation=6,
    title_tiers=(
        (frozenset({"chief", "director", "vp", "head"}), 1.0),
        (frozenset({"general-manager", "manager", "principal", "lead"}), 0.95),
        (frozenset({"supervisor", "senior", "sr", "coordinator"}), 0.8),
        (frozenset({"officer", "specialist", "analyst", "operator", "planner"}), 0.6),
        (frozenset({"junior", "jr", "trainee", "intern", "assistant"}), 0.3),
    ),
)

SALES = DimensionTemplate(
    family=JobFamily.SALES,
    description=(
        "Commercial and account management. Breadth counts the customer segments and "
        "channels sold into; quota attainment is the systemic signal."
    ),
    depth_weights={
        "tenure": Decimal("0.60"),
        "breadth": Decimal("0.40"),
        "projects": Decimal("0"),
        "publications": Decimal("0"),
    },
    breadth_vocabulary=frozenset(
        {
            "account-management",
            "key-account",
            "new-business",
            "upsell",
            "cross-sell",
            "prospecting",
            "lead-generation",
            "salesforce",
            "crm",
            "hubspot",
            "negotiation",
            "closing",
            "renewal",
            "churn",
            "territory",
            "channel",
            "partner",
            "reseller",
            "distributor",
            "inside-sales",
            "outside-sales",
            "field-sales",
            "ecommerce",
            "marketplace",
            "rfq",
            "tender",
            "proposal",
            "commercial",
            "pricing",
            "discount",
        }
    ),
    professional_categories=frozenset(
        {SkillCategory.SALES, SkillCategory.GENERAL, SkillCategory.DATA}
    ),
    signal_keywords=(
        "quota",
        "pipeline",
        "forecast",
        "revenue",
        "arr",
        "contract",
        "renewal",
        "expansion",
        "account",
        "client",
        "territory",
        "channel",
        "partner",
        "negotiat",
        "close",
        "win-rate",
        "retention",
    ),
    signal_saturation=KEYWORD_SATURATION,
    breadth_saturation=6,
    title_tiers=(
        (frozenset({"chief", "ceo", "vp", "vice-president", "director"}), 1.0),
        (frozenset({"head", "principal", "regional-manager", "general-manager"}), 0.95),
        (frozenset({"senior", "sr", "account-director", "manager"}), 0.8),
        (
            frozenset(
                {
                    "account-executive",
                    "ae",
                    "account-manager",
                    "rep",
                    "representative",
                    "specialist",
                    "consultant",
                }
            ),
            0.6,
        ),
        (frozenset({"junior", "jr", "trainee", "intern", "assistant", "bdr"}), 0.3),
    ),
)

GENERAL = DimensionTemplate(
    family=JobFamily.GENERAL,
    description=(
        "Roles with no domain-specific rubric. Deliberately not engineering: a "
        "generalist with no engineering signals should not be measured against them, "
        "and a mid-career generalist should still not be auto-rejected for it."
    ),
    depth_weights={
        "tenure": Decimal("0.60"),
        "breadth": Decimal("0.40"),
        "projects": Decimal("0"),
        "publications": Decimal("0"),
    },
    breadth_vocabulary=frozenset(),
    professional_categories=frozenset(
        {
            SkillCategory.GENERAL,
            SkillCategory.OPERATIONS,
            SkillCategory.SALES,
            SkillCategory.DATA,
        }
    ),
    signal_keywords=(
        "led",
        "managed",
        "delivered",
        "owned",
        "coordinated",
        "planned",
        "budget",
        "stakeholder",
        "process",
        "improved",
        "reduced",
        "grew",
        "launched",
        "negotiat",
        "report",
        "risk",
        "compliance",
    ),
    signal_saturation=KEYWORD_SATURATION,
    breadth_saturation=6,
    title_tiers=(
        (frozenset({"chief", "ceo", "director", "vp", "head"}), 1.0),
        (frozenset({"principal", "manager", "lead"}), 0.9),
        (frozenset({"supervisor", "senior", "sr", "coordinator"}), 0.75),
        (
            frozenset(
                {
                    "specialist",
                    "officer",
                    "analyst",
                    "consultant",
                    "administrator",
                    "executive",
                }
            ),
            0.6,
        ),
        (frozenset({"junior", "jr", "trainee", "intern", "assistant"}), 0.3),
    ),
)


_TEMPLATES: dict[JobFamily, DimensionTemplate] = {
    template.family: template
    for template in (
        ENGINEERING,
        FINANCE,
        EDUCATION,
        HEALTHCARE,
        LEGAL,
        OPERATIONS,
        SALES,
        GENERAL,
    )
}

if set(_TEMPLATES) != set(JobFamily):
    _missing = sorted(family.value for family in JobFamily if family not in _TEMPLATES)
    raise RuntimeError(
        f"every JobFamily needs a template; missing {_missing}. A family without one "
        "falls back to the engineering rubric and is scored by evidence it cannot have."
    )


def template_for(family: JobFamily) -> DimensionTemplate:
    """The rubric for a job family.

    Total by construction: ``_TEMPLATES`` is checked against ``JobFamily`` at import, so
    there is no fallback branch here to get wrong. A missing family is an import-time
    error rather than a silent substitution at scoring time.
    """
    return _TEMPLATES[family]


def families() -> tuple[JobFamily, ...]:
    """Every family with a template, in declaration order."""
    return tuple(_TEMPLATES)
