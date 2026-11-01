"""Render a candidate feedback report as a PDF.

The report is candidate-facing: internal notes and raw scores never enter it
(the model itself excludes them). Every piece of text is XML-escaped before it
reaches ReportLab, because a name or job title is user data and ReportLab
paragraphs are markup.
"""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from hr_agents.models import FeedbackReport

_LABELS = {
    "en": {
        "title": "Candidate feedback",
        "summary": "Summary",
        "strengths": "Strengths",
        "growth": "Where to strengthen",
        "process": "Process",
        "correction": "Correction",
    },
    "id": {
        "title": "Umpan balik kandidat",
        "summary": "Ringkasan",
        "strengths": "Kekuatan",
        "growth": "Area pengembangan",
        "process": "Proses",
        "correction": "Koreksi",
    },
}


def render_feedback_pdf(report: FeedbackReport) -> bytes:
    """A one-document PDF with the report's candidate-facing sections only."""
    labels = _LABELS[report.language]
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"{labels['title']} - {report.job_title}",
        author="HRAgents",
    )
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "FeedbackTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        spaceAfter=4,
    )
    heading = ParagraphStyle(
        "FeedbackHeading",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        spaceBefore=10,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "FeedbackBody",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        spaceAfter=4,
    )

    story: list[object] = [
        Paragraph(escape(labels["title"]), title),
        Paragraph(f"{escape(report.candidate_name)} — {escape(report.job_title)}", body),
        Spacer(1, 3 * mm),
        Paragraph(escape(labels["summary"]), heading),
        Paragraph(escape(report.summary), body),
    ]
    for label, items in (
        (labels["strengths"], report.strengths),
        (labels["growth"], report.growth_areas),
    ):
        if not items:
            continue
        story.append(Paragraph(escape(label), heading))
        story.extend(Paragraph(f"• {escape(item.text)}", body) for item in items)
    story.extend(
        [
            Paragraph(escape(labels["process"]), heading),
            Paragraph(escape(report.process_note), body),
            Paragraph(escape(labels["correction"]), heading),
            Paragraph(escape(report.correction_notice), body),
        ]
    )
    document.build(story)
    return buffer.getvalue()
