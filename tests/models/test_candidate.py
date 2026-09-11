from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from hr_agents.models import (
    CandidateProfile,
    CertificationClaim,
    ConsentRecord,
    EvidenceRef,
    ExperienceEntry,
    Skill,
    SkillCategory,
    SourceType,
    VerificationStatus,
)


def make_profile() -> CandidateProfile:
    return CandidateProfile(
        full_name="Budi Santoso",
        headline="Backend Engineer",
        emails=["budi@example.com"],
        experience=[
            ExperienceEntry(
                company="Nusantara Systems",
                title="Software Engineer",
                start_date=date(2022, 1, 1),
                end_date=date(2024, 6, 30),
                tech_stack=["Python", "FastAPI", "PostgreSQL"],
                evidence=[
                    EvidenceRef(
                        source_type=SourceType.RESUME,
                        locator="resume#/experience/0",
                        excerpt="Built payment services in Python/FastAPI",
                    )
                ],
            ),
            ExperienceEntry(
                company="Merdeka AI",
                title="Senior Engineer",
                start_date=date(2024, 7, 1),
                tech_stack=["Python", "PydanticAI"],
            ),
        ],
        skills=[
            Skill(name="Python", category=SkillCategory.LANGUAGE, claimed_proficiency=5),
            Skill(name="PostgreSQL", category=SkillCategory.DATABASE, claimed_proficiency=4),
        ],
        certifications=[
            CertificationClaim(
                name="AWS Solutions Architect",
                issuer="Amazon Web Services",
                status=VerificationStatus.CLAIMED,
            )
        ],
        consent=ConsentRecord(
            granted=True,
            granted_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )


def test_profile_round_trip() -> None:
    profile = make_profile()
    restored = CandidateProfile.model_validate_json(profile.model_dump_json())
    assert restored == profile


def test_current_experience_detection() -> None:
    profile = make_profile()
    assert profile.experience[1].is_current is True
    assert profile.experience[0].is_current is False


def test_invalid_email_rejected() -> None:
    with pytest.raises(ValidationError):
        CandidateProfile(full_name="X", emails=["not-an-email"])


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        CandidateProfile(full_name="X", salary_expectation=10_000_000)  # type: ignore[call-arg]


def test_field_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        CandidateProfile(full_name="X", field_confidence={"skills.python": 1.4})


def test_consent_lifecycle() -> None:
    active = ConsentRecord(granted=True, granted_at=datetime(2026, 9, 1, tzinfo=UTC))
    assert active.active is True

    revoked = ConsentRecord(
        granted=True,
        granted_at=datetime(2026, 9, 1, tzinfo=UTC),
        revoked_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert revoked.active is False

    never_granted = ConsentRecord(granted=False)
    assert never_granted.active is False


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        ConsentRecord(granted=True, granted_at=datetime(2026, 9, 1))
