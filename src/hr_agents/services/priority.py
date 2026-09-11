"""Dynamic queue priority.

P(c) = α·S̄(c) + β·e^(−λ·Δt) + γ·A(c) − δ·R(c)

- S̄  : weighted mean of the score tensor (0 when not yet evaluated)
- Δt : hours since submission
- A  : availability completeness ∈ [0, 1]
- R  : risk pressure, min(risk_flags / 3, 1)

Ranking is visibility, not elimination: every candidate remains in the queue.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from hr_agents.config import Settings, get_settings


@dataclass(frozen=True)
class PriorityInputs:
    s_tech: float
    hours_waiting: float
    availability_completeness: float = 0.0
    risk_flag_count: int = 0


def compute_priority(
    inputs: PriorityInputs,
    settings: Settings | None = None,
) -> float:
    """Compute the bounded priority score P ∈ [0, 1]."""
    if not 0.0 <= inputs.s_tech <= 1.0:
        raise ValueError("s_tech must be within [0, 1]")
    if inputs.hours_waiting < 0:
        raise ValueError("hours_waiting must be non-negative")
    if not 0.0 <= inputs.availability_completeness <= 1.0:
        raise ValueError("availability_completeness must be within [0, 1]")
    if inputs.risk_flag_count < 0:
        raise ValueError("risk_flag_count must be non-negative")

    settings = settings or get_settings()

    risk_pressure = min(inputs.risk_flag_count / 3.0, 1.0)
    recency = math.exp(-settings.priority_lambda_per_hour * inputs.hours_waiting)

    priority = (
        settings.priority_alpha * inputs.s_tech
        + settings.priority_beta * recency
        + settings.priority_gamma * inputs.availability_completeness
        - settings.priority_delta * risk_pressure
    )
    return max(0.0, min(1.0, round(priority, 6)))


def rank_queue(
    entries: list[tuple[str, PriorityInputs]],
    settings: Settings | None = None,
) -> list[tuple[str, float]]:
    """Rank ``(candidate_id, inputs)`` pairs by descending priority.

    Ties are broken by the caller's original order, which must already be
    ordered by earliest submission time.
    """
    scored = [
        (candidate_id, compute_priority(inputs, settings)) for candidate_id, inputs in entries
    ]
    indexed = list(enumerate(scored))
    indexed.sort(key=lambda pair: (-pair[1][1], pair[0]))
    return [value for _, value in indexed]
