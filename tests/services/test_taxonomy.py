"""A family's evidence vocabulary as one composable object."""

from __future__ import annotations

from datetime import date

from hr_agents.models import EvidenceRef, ExperienceEntry, JobFamily, SourceType
from hr_agents.services.dimensions import ENGINEERING, FINANCE, template_for


def test_the_taxonomy_view_mirrors_the_template() -> None:
    taxonomy = FINANCE.taxonomy()

    assert taxonomy.family is JobFamily.FINANCE
    assert taxonomy.breadth_vocabulary == FINANCE.breadth_vocabulary
    assert taxonomy.signal_keywords == FINANCE.signal_keywords
    assert taxonomy.professional_categories == FINANCE.professional_categories
    assert taxonomy.title_tiers == FINANCE.title_tiers
    assert taxonomy.breadth_saturation == FINANCE.breadth_saturation


def test_breadth_only_counts_the_family_vocabulary() -> None:
    terms = frozenset({"ifrs", "excel", "python"})

    finance = FINANCE.taxonomy().breadth_component(terms & FINANCE.breadth_vocabulary)
    engineering = ENGINEERING.taxonomy().breadth_component(terms & ENGINEERING.breadth_vocabulary)

    assert finance != engineering


def test_signal_hits_count_keywords_and_cite_matching_entries() -> None:
    entry = ExperienceEntry(
        company="Nusantara Finance",
        title="Accounting Supervisor",
        start_date=date(2017, 1, 1),
        end_date=date(2024, 1, 1),
        highlights=["Implemented IFRS 15 revenue recognition", "Managed the audit"],
        evidence=[EvidenceRef(source_type=SourceType.RESUME, locator="cv.pdf", excerpt="IFRS 15")],
    )
    taxonomy = template_for(JobFamily.FINANCE).taxonomy()

    hits, evidence = taxonomy.signal_hits([entry])

    assert hits >= 1
    assert [item.locator for item in evidence] == ["cv.pdf"]


def test_seniority_delegates_to_the_shared_primitive() -> None:
    taxonomy = ENGINEERING.taxonomy()

    assert taxonomy.seniority("principal engineer") == ENGINEERING.tier_for("principal engineer")
