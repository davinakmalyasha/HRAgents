"""Composable scoring primitives.

The four dimensions are composed from a handful of small, pure functions rather
than each re-deriving its own arithmetic. That is what makes a new family (or a
future fifth axis) a data question instead of a copy-paste question: the
primitives know how to saturate, count, density and rank, and the family passes
the vocabulary and the cap.

Everything here is deterministic and has no I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

from hr_agents.models import CertificationClaim, EvidenceRef, VerificationStatus

_TITLE_PUNCTUATION = str.maketrans({char: " " for char in ",.;:()[]/'\"&|!?"})

EVIDENCE_CAP = 10
"""References kept per dimension. Beyond this the list stops adding signal."""


def saturation(value: float, cap: float) -> float:
    """Clamp ``value / cap`` into ``[0, 1]``; a cap of zero yields zero."""
    if cap <= 0:
        return 0.0
    return min(value / cap, 1.0)


def tenure_saturation(months: int, cap: float) -> float:
    """How close a career length is to the point where more months stop adding."""
    return saturation(float(max(months, 0)), cap)


def evidence_density(required: Collection[str], available: Collection[str]) -> float:
    """The fraction of required terms present, or 0 when nothing was required."""
    if not required:
        return 0.0
    return len(set(required) & set(available)) / len(set(required))


def evidence_count(refs: Iterable[EvidenceRef], *, cap: int = EVIDENCE_CAP) -> int:
    """Distinct references, bounded. The same record cited twice counts once."""
    seen: set[tuple[str, str, str | None]] = set()
    for ref in refs:
        seen.add((ref.source_type.value, ref.locator, ref.excerpt))
        if len(seen) >= cap:
            break
    return len(seen)


def title_seniority_tiers(
    tiers: Sequence[tuple[frozenset[str], float]], titles: str
) -> tuple[float, str]:
    """``(component, matched_label)`` for a blob of lowercased job titles.

    Whole-word matched, first tier wins. Punctuation is stripped first because
    real titles carry it: "Team Lead, Payments" is a lead, and splitting on
    whitespace alone would leave ``lead,`` which matches no tier.
    """
    cleaned = titles.translate(_TITLE_PUNCTUATION)
    words = set(cleaned.replace("-", " ").replace("/", " ").split())
    for tokens, value in tiers:
        hit = words & tokens
        if hit:
            return value, sorted(hit)[0]
    return 0.0, "unranked"


@dataclass(frozen=True)
class CredentialCredit:
    """What the claimed certificates are worth, and the counts behind it."""

    score: float
    verified_fraction: float
    count_component: float
    verified: int
    expired: int
    failed: int


def credential_credit(
    claims: Sequence[CertificationClaim], *, count_saturation: float
) -> CredentialCredit:
    """Verified fraction (70%) plus a bounded count signal (30%).

    An empty claim set is zero credit, not a division error. The registry gate
    may have already rewritten the statuses; this primitive only scores what it
    is given.
    """
    total = len(claims)
    if total == 0:
        return CredentialCredit(
            score=0.0,
            verified_fraction=0.0,
            count_component=0.0,
            verified=0,
            expired=0,
            failed=0,
        )
    verified = sum(1 for cert in claims if cert.status is VerificationStatus.VERIFIED)
    expired = sum(1 for cert in claims if cert.status is VerificationStatus.EXPIRED)
    failed = sum(1 for cert in claims if cert.status is VerificationStatus.FAILED)
    verified_fraction = verified / total
    count_component = saturation(float(total), count_saturation)
    return CredentialCredit(
        score=0.7 * verified_fraction + 0.3 * count_component,
        verified_fraction=verified_fraction,
        count_component=count_component,
        verified=verified,
        expired=expired,
        failed=failed,
    )
