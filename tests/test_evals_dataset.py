"""The generated profile dataset is complete and readable in all three formats.

The dataset is code, so these tests are the guard that it stays the size the
plan asks for (50 profiles: 18 engineering, 32 non-IT, EN/ID mixed), keeps
every case name unique, and that the Markdown, JSON and PDF variants each
survive the document extractor — the PDF variant is written by a hand-rolled
writer, so a bug in it would otherwise only surface on a live eval run.
"""

import json

from evals.profiles import (
    PROFILES,
    render_blank_pdf,
    render_json,
    render_markdown,
    render_pdf,
)
from evals.resume_extraction import build_dataset

from hr_agents.services.documents import extract_text


def test_the_catalogue_has_the_planned_mix() -> None:
    engineering = [profile for profile in PROFILES if profile.family == "engineering"]
    non_it = [profile for profile in PROFILES if profile.family != "engineering"]

    assert len(PROFILES) == 50
    assert len(engineering) == 18
    assert len(non_it) == 32
    assert len({profile.slug for profile in PROFILES}) == 50
    assert len({profile.name for profile in PROFILES}) == 50

    english = [profile for profile in PROFILES if profile.language == "en"]
    indonesian = [profile for profile in PROFILES if profile.language == "id"]
    assert len(english) >= 20
    assert len(indonesian) >= 20
    assert len(english) + len(indonesian) == 50


def test_build_dataset_includes_every_profile_and_the_edge_cases() -> None:
    dataset = build_dataset()
    names = [case.name or "" for case in dataset.cases]

    assert len(names) == len(set(names))
    for profile in PROFILES:
        assert f"profile_{profile.slug}" in names

    pair_ids = {case.inputs.pair_id for case in dataset.cases if case.inputs.pair_id is not None}
    assert pair_ids == {"swap-en", "swap-id"}
    assert any(name.startswith("edge_date_overlap") for name in names)
    assert any(name.startswith("edge_fake_certification") for name in names)
    assert "prompt_injection" in names, "the adversarial case must survive the expansion"


def test_each_profile_reads_back_from_markdown_json_and_pdf() -> None:
    for profile in PROFILES:
        markdown = render_markdown(profile)
        assert profile.name in markdown
        assert markdown.isascii(), "the PDF writer embeds Helvetica; keep text ASCII"

        payload = json.loads(render_json(profile))
        assert payload["name"] == profile.name
        assert payload["experience"]

        extracted = extract_text(render_pdf(profile), f"{profile.slug}.pdf")
        assert profile.name in extracted, f"PDF variant lost the name for {profile.slug}"


def test_a_scanned_pdf_yields_no_text() -> None:
    """A PDF with no text layer must extract to empty, not to garbage."""
    assert extract_text(render_blank_pdf(), "scan.pdf") == ""
