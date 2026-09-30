"""How sets compare: training volume and which set counts as the best."""

from __future__ import annotations

from trainer.domain.exercises import Measure


def set_volume(reps: int | None, load_kg: float | None) -> float:
    """Volume moved in one set (reps x load); zero when either is unknown."""
    if reps is None or load_kg is None:
        return 0.0
    return reps * load_kg


def set_rank(
    measure: Measure, reps: int | None, load_kg: float | None, duration_s: float | None
) -> tuple[float, float]:
    """Sort key for "best set": heaviest then most reps, or longest then heaviest if timed."""
    if measure is Measure.SECONDS:
        return (duration_s or 0.0, load_kg or 0.0)
    return (load_kg or 0.0, float(reps or 0))
