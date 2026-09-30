"""How sets compare: training volume and which set counts as the best."""

from __future__ import annotations

from trainer.domain.exercises import Equipment, Measure


def carried_load(equipment: str | None, bodyweight_kg: float | None) -> float:
    """Body weight moved in each rep: the owner's for a bodyweight exercise, else none.

    Weight added to a bodyweight exercise (a weighted dip) is the set's load,
    counted on top of this.
    """
    if equipment != Equipment.BODYWEIGHT or bodyweight_kg is None:
        return 0.0
    return bodyweight_kg


def set_volume(reps: int | None, load_kg: float | None, carried_kg: float) -> float:
    """Volume moved in one set: reps x (load + body weight carried); zero without reps."""
    if reps is None:
        return 0.0
    return reps * ((load_kg or 0.0) + carried_kg)


def set_rank(
    measure: Measure, reps: int | None, load_kg: float | None, duration_s: float | None
) -> tuple[float, ...]:
    """Sort key for "best set": heaviest then most reps.

    Timed sets rank longest, then heaviest, then most reps: the write API lets
    a timed set carry reps without a duration, and it is shown as reps then.
    Keys are only compared between sets of the same exercise, so their lengths
    never mix.
    """
    if measure is Measure.SECONDS:
        return (duration_s or 0.0, load_kg or 0.0, float(reps or 0))
    return (load_kg or 0.0, float(reps or 0))
