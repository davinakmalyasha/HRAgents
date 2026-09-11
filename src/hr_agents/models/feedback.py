"""Candidate feedback domain models — the grounding contract for FeedbackWriter."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from hr_agents.models.common import EvidenceRef, StrictModel
from hr_agents.models.evaluation import ScoreDimension


class FeedbackStrength(StrictModel):
    """A positive point, tied to one score dimension."""

    dimension: ScoreDimension
    text: str = Field(min_length=1, max_length=500)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class FeedbackGrowthArea(StrictModel):
    """A development point, phrased as missing evidence — never ability judgment."""

    dimension: ScoreDimension
    text: str = Field(min_length=1, max_length=500)


class FeedbackReport(StrictModel):
    """Candidate-facing report. Internal notes and raw scores must not appear."""

    candidate_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    language: Literal["en", "id"] = "en"

    summary: str = Field(min_length=1, max_length=800)
    strengths: list[FeedbackStrength] = Field(default_factory=list, max_length=3)
    growth_areas: list[FeedbackGrowthArea] = Field(default_factory=list, max_length=3)

    process_note: str = Field(min_length=1, max_length=500)
    correction_notice: str = Field(min_length=1, max_length=500)
