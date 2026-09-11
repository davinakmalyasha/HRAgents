import pytest

from hr_agents.config import Settings
from hr_agents.services.priority import PriorityInputs, compute_priority, rank_queue


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "priority_alpha": 0.55,
        "priority_beta": 0.25,
        "priority_gamma": 0.10,
        "priority_delta": 0.10,
        "priority_lambda_per_hour": 0.05,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_priority_is_monotonic_in_score() -> None:
    settings = make_settings()
    low = compute_priority(PriorityInputs(s_tech=0.3, hours_waiting=10), settings=settings)
    high = compute_priority(PriorityInputs(s_tech=0.9, hours_waiting=10), settings=settings)
    assert high > low


def test_recency_decays_with_waiting_time() -> None:
    settings = make_settings()
    fresh = compute_priority(PriorityInputs(s_tech=0.8, hours_waiting=1), settings=settings)
    stale = compute_priority(PriorityInputs(s_tech=0.8, hours_waiting=100), settings=settings)
    assert fresh > stale


def test_risk_flags_lower_priority() -> None:
    settings = make_settings()
    clean = compute_priority(
        PriorityInputs(s_tech=0.8, hours_waiting=5, risk_flag_count=0), settings=settings
    )
    risky = compute_priority(
        PriorityInputs(s_tech=0.8, hours_waiting=5, risk_flag_count=3), settings=settings
    )
    assert clean > risky


def test_availability_raises_priority() -> None:
    settings = make_settings()
    without = compute_priority(
        PriorityInputs(s_tech=0.8, hours_waiting=5, availability_completeness=0.0),
        settings=settings,
    )
    with_availability = compute_priority(
        PriorityInputs(s_tech=0.8, hours_waiting=5, availability_completeness=1.0),
        settings=settings,
    )
    assert with_availability > without


def test_priority_is_bounded() -> None:
    settings = make_settings()
    worst = compute_priority(
        PriorityInputs(s_tech=0.0, hours_waiting=0, risk_flag_count=99), settings=settings
    )
    best = compute_priority(
        PriorityInputs(s_tech=1.0, hours_waiting=0, availability_completeness=1.0),
        settings=settings,
    )
    assert 0.0 <= worst <= 1.0
    assert 0.0 <= best <= 1.0


def test_exact_formula_value() -> None:
    settings = make_settings()
    result = compute_priority(
        PriorityInputs(s_tech=0.8, hours_waiting=0, availability_completeness=1.0),
        settings=settings,
    )
    expected = 0.55 * 0.8 + 0.25 * 1.0 + 0.10 * 1.0 - 0.10 * 0.0
    assert result == pytest.approx(expected)


def test_invalid_inputs_rejected() -> None:
    with pytest.raises(ValueError, match="s_tech"):
        compute_priority(PriorityInputs(s_tech=1.2, hours_waiting=0))
    with pytest.raises(ValueError, match="hours_waiting"):
        compute_priority(PriorityInputs(s_tech=0.5, hours_waiting=-1))
    with pytest.raises(ValueError, match="availability"):
        compute_priority(PriorityInputs(s_tech=0.5, hours_waiting=0, availability_completeness=2))


def test_rank_queue_orders_by_priority_then_arrival() -> None:
    settings = make_settings()
    entries = [
        ("first-arrival", PriorityInputs(s_tech=0.5, hours_waiting=10)),
        ("strong", PriorityInputs(s_tech=0.95, hours_waiting=1)),
        ("second-arrival", PriorityInputs(s_tech=0.5, hours_waiting=10)),
    ]
    ranked = rank_queue(entries, settings)
    assert ranked[0][0] == "strong"
    # equal priority ties keep arrival order
    assert [name for name, _ in ranked[1:]] == ["first-arrival", "second-arrival"]
