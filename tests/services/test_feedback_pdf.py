"""The feedback PDF: candidate-facing text, escaped, and readable."""

from __future__ import annotations

from io import BytesIO
from typing import Literal

from pypdf import PdfReader

from hr_agents.models import (
    FeedbackGrowthArea,
    FeedbackReport,
    FeedbackStrength,
    ScoreDimension,
)
from hr_agents.services.feedback_pdf import render_feedback_pdf


def report(language: Literal["en", "id"] = "en", *, name: str = "Sari Dewi") -> FeedbackReport:
    return FeedbackReport(
        candidate_name=name,
        job_title="Backend Engineer",
        language=language,
        summary="Your application was reviewed against the role's evidence.",
        strengths=[
            FeedbackStrength(
                dimension=ScoreDimension.TECHNICAL_DEPTH,
                text="Concrete API design examples.",
            )
        ],
        growth_areas=[
            FeedbackGrowthArea(
                dimension=ScoreDimension.STACK_ALIGNMENT,
                text="Add evidence for the must-have queueing skill.",
            )
        ],
        process_note="A person reviewed the recorded evidence.",
        correction_notice="Contact us if a fact in this report is wrong.",
    )


def text_of(pdf: bytes) -> str:
    return PdfReader(BytesIO(pdf)).pages[0].extract_text()


def test_the_pdf_carries_the_candidate_facing_sections() -> None:
    pdf = render_feedback_pdf(report())

    assert pdf.startswith(b"%PDF-")
    extracted = text_of(pdf)
    assert "Sari Dewi" in extracted
    assert "Backend Engineer" in extracted
    assert "Concrete API design examples." in extracted
    assert "Add evidence for the must-have queueing skill." in extracted
    assert "A person reviewed the recorded evidence." in extracted


def test_the_pdf_uses_the_report_language() -> None:
    extracted = text_of(render_feedback_pdf(report("id")))

    assert "Umpan balik kandidat" in extracted
    assert "Ringkasan" in extracted


def test_markup_in_a_name_is_escaped_not_interpreted() -> None:
    pdf = render_feedback_pdf(report(name="Sari <b>Dewi</b> & Co"))

    assert "Sari <b>Dewi</b> & Co" in text_of(pdf)
