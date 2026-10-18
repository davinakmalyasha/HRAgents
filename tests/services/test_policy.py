import pytest

from hr_agents.models import EvaluationFlag, PolicyDecision, PolicyThresholds, Recommendation
from hr_agents.services.pipeline import _recommendation_for
from hr_agents.services.policy import evaluate_policy


def test_no_decision_the_engine_reaches_recommends_a_bare_rejection() -> None:
    """`Recommendation.REJECT` is now only ever written by a person.

    The sub-floor band used to map straight to `REJECT`, which wrote the
    application to the store as `REJECTED` before anyone had looked and made a
    rejection message communicable on that record alone. It was also the least
    evidenced decision available, so it was asserted most confidently exactly
    where the evidence was weakest.

    Both rejection bands now carry `REJECT_REQUIRES_SIGNOFF`, which is the same
    request a human has always been asked to make.
    """
    for decision in PolicyDecision:
        recommendation = _recommendation_for(decision)
        assert recommendation is not Recommendation.REJECT, (
            f"{decision.value} must not recommend a rejection on its own"
        )
    assert _recommendation_for(PolicyDecision.REJECT_AUTO) is (
        Recommendation.REJECT_REQUIRES_SIGNOFF
    )
    assert _recommendation_for(PolicyDecision.HITL_SOFT_REJECTION) is (
        Recommendation.REJECT_REQUIRES_SIGNOFF
    )


def test_consent_inactive_halts() -> None:
    result = evaluate_policy(s_tech=0.95, sigma=0.01, consent_active=False)
    assert result.decision is PolicyDecision.HITL_MANUAL
    assert "consent inactive" in result.reasons[0]


def test_anomaly_flag_routes_to_human() -> None:
    result = evaluate_policy(
        s_tech=0.95,
        sigma=0.01,
        flags=[EvaluationFlag.ANOMALY_EXPERIENCE_FORMAT],
    )
    assert result.decision is PolicyDecision.HITL_ANOMALY


def test_calendar_flag_alone_routes_to_calendar() -> None:
    result = evaluate_policy(
        s_tech=0.95,
        sigma=0.01,
        flags=[EvaluationFlag.CALENDAR_CONSTRAINT],
    )
    assert result.decision is PolicyDecision.HITL_CALENDAR


def test_low_mutual_slots_routes_to_calendar() -> None:
    result = evaluate_policy(s_tech=0.95, sigma=0.01, mutual_slots=1)
    assert result.decision is PolicyDecision.HITL_CALENDAR
    assert "minimum 2" in result.reasons[0]


def test_auto_schedule_when_high_score_and_low_variance() -> None:
    result = evaluate_policy(s_tech=0.86, sigma=0.04, mutual_slots=3)
    assert result.decision is PolicyDecision.AUTO_SCHEDULE


def test_boundary_exact_thresholds_auto_schedules() -> None:
    result = evaluate_policy(s_tech=0.85, sigma=0.05, mutual_slots=2)
    assert result.decision is PolicyDecision.AUTO_SCHEDULE


def test_high_score_with_high_variance_gated() -> None:
    result = evaluate_policy(s_tech=0.90, sigma=0.09, mutual_slots=4)
    assert result.decision is PolicyDecision.HITL_SOFT_REJECTION


def test_soft_rejection_band() -> None:
    result = evaluate_policy(s_tech=0.70, sigma=0.01, mutual_slots=3)
    assert result.decision is PolicyDecision.HITL_SOFT_REJECTION
    assert "sign-off" in result.reasons[0]

    upper = evaluate_policy(s_tech=0.84, sigma=0.01, mutual_slots=3)
    assert upper.decision is PolicyDecision.HITL_SOFT_REJECTION


def test_below_floor_rejects_with_feedback() -> None:
    result = evaluate_policy(s_tech=0.42, sigma=0.01, mutual_slots=3)
    assert result.decision is PolicyDecision.REJECT_AUTO
    assert "feedback report" in result.reasons[0]


def test_anomaly_beats_high_score() -> None:
    result = evaluate_policy(
        s_tech=0.99,
        sigma=0.0,
        flags=[EvaluationFlag.INJECTION_SUSPECTED],
        mutual_slots=5,
    )
    assert result.decision is PolicyDecision.HITL_ANOMALY


def test_thresholds_are_snapshotted() -> None:
    result = evaluate_policy(s_tech=0.5, sigma=0.0)
    assert result.thresholds.auto_schedule_min_score == 0.85
    assert result.thresholds.soft_rejection_floor == 0.70


# --- the threshold routing table -----------------------------------------------
#
# One row per decision boundary, including the exact edges: every comparison in
# `evaluate_policy` is inclusive on one side and exclusive on the other, and a
# boundary bug moves real candidates between "schedule an interview" and
# "requires a human decision". Defaults under test: auto at s >= 0.85 with
# sigma <= 0.05, soft-rejection band from 0.70, minimum two mutual slots.

DEFAULT = PolicyThresholds()


def _custom() -> PolicyThresholds:
    return PolicyThresholds(
        auto_schedule_min_score=0.90,
        auto_schedule_max_variance=0.02,
        soft_rejection_floor=0.80,
        min_interviewer_slots=3,
    )


BOUNDARIES = (
    pytest.param(
        {"s_tech": 0.85, "sigma": 0.05},
        PolicyDecision.AUTO_SCHEDULE,
        "auto-scheduling is within bounds",
        id="auto-at-both-thresholds-inclusive",
    ),
    pytest.param(
        {"s_tech": 0.85, "sigma": 0.050_000_1},
        PolicyDecision.HITL_SOFT_REJECTION,
        "soft-rejection band",
        id="variance-a-hair-above-maximum",
    ),
    pytest.param(
        {"s_tech": 0.849_999_9, "sigma": 0.01},
        PolicyDecision.HITL_SOFT_REJECTION,
        "soft-rejection band",
        id="score-a-hair-below-auto",
    ),
    pytest.param(
        {"s_tech": 0.70, "sigma": 0.01},
        PolicyDecision.HITL_SOFT_REJECTION,
        "soft-rejection band",
        id="score-at-merit-floor-inclusive",
    ),
    pytest.param(
        {"s_tech": 0.699_999_9, "sigma": 0.01},
        PolicyDecision.REJECT_AUTO,
        "below merit floor",
        id="score-a-hair-below-floor",
    ),
    pytest.param(
        {"s_tech": 0.95, "sigma": 0.01, "mutual_slots": 2},
        PolicyDecision.AUTO_SCHEDULE,
        "auto-scheduling is within bounds",
        id="slots-at-minimum-still-auto",
    ),
    pytest.param(
        {"s_tech": 0.95, "sigma": 0.01, "mutual_slots": 1},
        PolicyDecision.HITL_CALENDAR,
        "mutual interviewer slots 1",
        id="slots-below-minimum-routes-calendar",
    ),
    pytest.param(
        {"s_tech": 0.95, "sigma": 0.01, "mutual_slots": None},
        PolicyDecision.AUTO_SCHEDULE,
        "auto-scheduling is within bounds",
        id="unknown-slots-do-not-block",
    ),
    pytest.param(
        {"s_tech": 0.95, "sigma": 0.01, "flags": [EvaluationFlag.CALENDAR_CONSTRAINT]},
        PolicyDecision.HITL_CALENDAR,
        "calendar constraint flagged",
        id="calendar-flag-beats-a-perfect-score",
    ),
    pytest.param(
        {
            "s_tech": 0.95,
            "sigma": 0.01,
            "flags": [EvaluationFlag.LOW_CONFIDENCE_EXTRACTION, EvaluationFlag.CALENDAR_CONSTRAINT],
            "mutual_slots": 0,
        },
        PolicyDecision.HITL_ANOMALY,
        "anomaly flags present",
        id="anomaly-beats-calendar-and-score",
    ),
    pytest.param(
        {
            "s_tech": 1.0,
            "sigma": 0.0,
            "consent_active": False,
            "flags": [EvaluationFlag.INJECTION_SUSPECTED],
        },
        PolicyDecision.HITL_MANUAL,
        "consent inactive",
        id="consent-halt-beats-everything",
    ),
)


@pytest.mark.parametrize(("inputs", "expected", "reason_fragment"), BOUNDARIES)
def test_the_threshold_routing_table(
    inputs: dict, expected: PolicyDecision, reason_fragment: str
) -> None:
    result = evaluate_policy(**inputs)

    assert result.decision is expected
    assert reason_fragment in result.reasons[0]
    assert result.thresholds == DEFAULT


def test_custom_thresholds_move_every_boundary_together() -> None:
    """The operator's table governs, and the snapshot records the values used.

    A regression here would keep the old bands while the settings page showed
    the new ones -- the audit record would name thresholds the run never used.
    """
    thresholds = _custom()

    assert (
        evaluate_policy(s_tech=0.95, sigma=0.01, mutual_slots=3, thresholds=thresholds).decision
        is PolicyDecision.AUTO_SCHEDULE
    )
    assert (
        evaluate_policy(s_tech=0.95, sigma=0.01, mutual_slots=2, thresholds=thresholds).decision
        is PolicyDecision.HITL_CALENDAR
    )
    assert (
        evaluate_policy(s_tech=0.88, sigma=0.01, thresholds=thresholds).decision
        is PolicyDecision.HITL_SOFT_REJECTION
    )
    assert (
        evaluate_policy(s_tech=0.95, sigma=0.03, thresholds=thresholds).decision
        is PolicyDecision.HITL_SOFT_REJECTION
    )
    assert (
        evaluate_policy(s_tech=0.75, sigma=0.01, thresholds=thresholds).decision
        is PolicyDecision.REJECT_AUTO
    )

    evaluation = evaluate_policy(s_tech=0.95, sigma=0.01, thresholds=thresholds)
    assert evaluation.thresholds == thresholds
