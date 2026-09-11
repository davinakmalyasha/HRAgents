from hr_agents.models import EvaluationFlag, PolicyDecision
from hr_agents.services.policy import evaluate_policy


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
