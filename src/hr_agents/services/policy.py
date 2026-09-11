"""Policy engine — automation boundaries and HITL routing.

Implements the decision table in ``docs/architecture/hitl-bounds.md`` §4.
First match wins. Pure function: no I/O, no LLM, fully auditable.
"""

from __future__ import annotations

from collections.abc import Iterable

from hr_agents.config import Settings, get_settings
from hr_agents.models import EvaluationFlag, PolicyDecision, PolicyEvaluation, PolicyThresholds


def evaluate_policy(
    *,
    s_tech: float,
    sigma: float,
    flags: Iterable[EvaluationFlag] = (),
    mutual_slots: int | None = None,
    consent_active: bool = True,
    thresholds: PolicyThresholds | None = None,
    settings: Settings | None = None,
) -> PolicyEvaluation:
    """Route an evaluation to automation or a human queue.

    Decision order (docs/architecture/hitl-bounds.md §4):
      1. consent inactive            → HITL_MANUAL (processing halted)
      2. non-calendar flags present  → HITL_ANOMALY
      3. mutual slots below minimum  → HITL_CALENDAR
      4. s ≥ auto threshold ∧ σ ok   → AUTO_SCHEDULE
      5. soft-rejection band         → HITL_SOFT_REJECTION
      6. otherwise                   → REJECT_AUTO
    """
    settings = settings or get_settings()
    thresholds = thresholds or PolicyThresholds(
        auto_schedule_min_score=settings.auto_schedule_min_score,
        auto_schedule_max_variance=settings.auto_schedule_max_variance,
        soft_rejection_floor=settings.soft_rejection_floor,
        min_interviewer_slots=settings.min_interviewer_slots,
    )

    flag_set = set(flags)
    reasons: list[str] = []

    if not consent_active:
        reasons.append("consent inactive: processing halted pending lawful basis")
        return PolicyEvaluation(
            decision=PolicyDecision.HITL_MANUAL, reasons=reasons, thresholds=thresholds
        )

    non_calendar_flags = flag_set - {EvaluationFlag.CALENDAR_CONSTRAINT}
    if non_calendar_flags:
        reasons.append(
            "anomaly flags present: " + ", ".join(sorted(f.value for f in non_calendar_flags))
        )
        return PolicyEvaluation(
            decision=PolicyDecision.HITL_ANOMALY, reasons=reasons, thresholds=thresholds
        )

    if EvaluationFlag.CALENDAR_CONSTRAINT in flag_set or (
        mutual_slots is not None and mutual_slots < thresholds.min_interviewer_slots
    ):
        if mutual_slots is not None:
            reasons.append(
                f"mutual interviewer slots {mutual_slots} < minimum "
                f"{thresholds.min_interviewer_slots}"
            )
        else:
            reasons.append("calendar constraint flagged by scheduling probe")
        return PolicyEvaluation(
            decision=PolicyDecision.HITL_CALENDAR, reasons=reasons, thresholds=thresholds
        )

    if (
        s_tech >= thresholds.auto_schedule_min_score
        and sigma <= thresholds.auto_schedule_max_variance
    ):
        reasons.append(
            f"s_tech {s_tech:.3f} ≥ {thresholds.auto_schedule_min_score:.2f} "
            f"and σ {sigma:.4f} ≤ {thresholds.auto_schedule_max_variance:.2f}; "
            "auto-scheduling is within bounds"
        )
        return PolicyEvaluation(
            decision=PolicyDecision.AUTO_SCHEDULE, reasons=reasons, thresholds=thresholds
        )

    if s_tech >= thresholds.soft_rejection_floor:
        reasons.append(
            f"s_tech {s_tech:.3f} within soft-rejection band "
            f"[{thresholds.soft_rejection_floor:.2f}, {thresholds.auto_schedule_min_score:.2f}); "
            "rejection requires named human sign-off"
        )
        return PolicyEvaluation(
            decision=PolicyDecision.HITL_SOFT_REJECTION, reasons=reasons, thresholds=thresholds
        )

    reasons.append(
        f"s_tech {s_tech:.3f} below merit floor {thresholds.soft_rejection_floor:.2f}; "
        "documented rejection with feedback report"
    )
    return PolicyEvaluation(
        decision=PolicyDecision.REJECT_AUTO, reasons=reasons, thresholds=thresholds
    )
