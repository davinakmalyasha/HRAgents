"""The scoring primitives: small, pure, and boundary-honest."""

from __future__ import annotations

from hr_agents.models import (
    CertificationClaim,
    EvidenceRef,
    SourceType,
    VerificationStatus,
)
from hr_agents.services.primitives import (
    credential_credit,
    evidence_count,
    evidence_density,
    saturation,
    tenure_saturation,
    title_seniority_tiers,
)


def ref(locator: str, *, confidence: float = 1.0) -> EvidenceRef:
    return EvidenceRef(
        source_type=SourceType.RESUME, locator=locator, excerpt=locator, confidence=confidence
    )


def test_saturation_clamps_and_treats_a_zero_cap_as_zero() -> None:
    assert saturation(0, 60) == 0.0
    assert saturation(30, 60) == 0.5
    assert saturation(60, 60) == 1.0
    assert saturation(120, 60) == 1.0
    assert saturation(10, 0) == 0.0


def test_tenure_saturation_never_goes_negative() -> None:
    assert tenure_saturation(-12, 60) == 0.0
    assert tenure_saturation(48, 60) == 0.8


def test_evidence_density_is_the_required_fraction() -> None:
    assert evidence_density(set(), {"python"}) == 0.0
    assert evidence_density({"python", "sql"}, {"python", "sql", "go"}) == 1.0
    assert evidence_density({"python", "sql"}, {"python"}) == 0.5


def test_evidence_count_dedupes_and_respects_the_cap() -> None:
    refs = [ref("a"), ref("a"), ref("b"), ref("c")]

    assert evidence_count(refs) == 3
    assert evidence_count(refs, cap=2) == 2
    assert evidence_count([]) == 0


def test_title_tiers_match_whole_words_only() -> None:
    tiers = ((frozenset({"sr", "senior"}), 0.9), (frozenset({"lead"}), 0.7))

    assert title_seniority_tiers(tiers, "senior software engineer") == (0.9, "senior")
    assert title_seniority_tiers(tiers, "team lead, payments") == (0.7, "lead")
    assert title_seniority_tiers(tiers, "supervision") == (0.0, "unranked")
    assert title_seniority_tiers(tiers, "ahead of schedule") == (0.0, "unranked")


def claim(status: VerificationStatus) -> CertificationClaim:
    return CertificationClaim(name="AWS Solutions Architect", issuer="AWS", status=status)


def test_credential_credit_weights_verified_and_count() -> None:
    credit = credential_credit(
        [claim(VerificationStatus.VERIFIED), claim(VerificationStatus.EXPIRED)],
        count_saturation=3.0,
    )

    assert credit.verified == 1
    assert credit.expired == 1
    assert credit.verified_fraction == 0.5
    assert credit.count_component == float(2 / 3)
    assert credit.score == 0.7 * 0.5 + 0.3 * (2 / 3)


def test_no_claims_is_zero_credit_not_a_division_error() -> None:
    credit = credential_credit([], count_saturation=3.0)

    assert credit.score == 0.0
    assert credit.verified == 0
