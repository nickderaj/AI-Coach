"""How sets compare: training volume and which set counts as the best."""

from __future__ import annotations

from trainer.domain.exercises import Equipment, Measure, exercise_key

# Share of body weight each rep of a bodyweight exercise lifts. Most figures are
# ExRx's "Calculating Actual Resistance" (body-segment masses, Plagenhoef 1983)
# and Ebben et al. 2011 for push-up variants; the core moves and the inverted row
# have no published figure and are estimates from the segments they lift.
# A name matches the entry with the most words all found in it, so "Weighted
# Pull-up" is a pull-up and "Bulgarian Split Squat" a split squat, not a squat.
BODYWEIGHT_SHARES: dict[str, float] = {
    "pull-up": 0.93,  # everything but the forearms and hands (92.8%)
    "chin-up": 0.93,
    "dip": 0.93,
    "dead hang": 0.93,
    "push-up": 0.64,
    "knee push-up": 0.49,
    "incline push-up": 0.55,
    "decline push-up": 0.70,
    "squat": 0.77,
    "split squat": 0.74,
    "lunge": 0.74,
    "step-up": 0.80,
    "pistol squat": 0.80,
    "leg raise": 0.33,  # both legs
    "knee raise": 0.33,
    "inverted row": 0.60,  # estimate: feet on the floor, body near horizontal
    "sit-up": 0.50,  # estimate: trunk, head and arms, pivoting at the hips
    "crunch": 0.30,  # estimate: only the shoulders leave the floor
    "glute bridge": 0.50,  # estimate: hips and trunk, pivoting at the shoulders
    "mountain climber": 0.25,  # estimate: one leg at a time
}
# For a bodyweight exercise not listed: about a push-up's share.
DEFAULT_BODYWEIGHT_SHARE = 0.65

_SHARES_BY_KEY = {exercise_key(name): share for name, share in BODYWEIGHT_SHARES.items()}


def bodyweight_share(name: str) -> float:
    """The share of body weight one rep of the bodyweight exercise ``name`` lifts."""
    key = exercise_key(name)
    matches = [entry for entry in _SHARES_BY_KEY if entry <= key]
    if not matches:
        return DEFAULT_BODYWEIGHT_SHARE
    return _SHARES_BY_KEY[max(matches, key=len)]


def carried_load(name: str, equipment: str | None, bodyweight_kg: float | None) -> float:
    """Body weight moved in each rep, to 0.1 kg: a share of the owner's, for bodyweight.

    Weight added to a bodyweight exercise (a weighted dip) is the set's load,
    counted on top of this. Other exercises carry none.
    """
    if equipment != Equipment.BODYWEIGHT or bodyweight_kg is None:
        return 0.0
    return round(bodyweight_share(name) * bodyweight_kg, 1)


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
