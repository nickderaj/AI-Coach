"""Programs: where the owner is in a block, and what each exercise aims for next.

A program is a block of training weeks followed by one deload week (D4). Its
days repeat every week in order. Targets are worked out from what was logged
whenever a day is opened, never stored ahead (D5), so a corrected set changes
the next target too.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from trainer.domain.exercises import Equipment

if TYPE_CHECKING:
    from collections.abc import Sequence

# D4: six training weeks, then the deload week.
TRAINING_WEEKS = 6

# Smallest load step for each kind of equipment, in kg: what the next plate,
# dumbbell or pin adds. Bands and "other" have no kg to step, so their load
# never changes by rule; the reps still do the work.
LOAD_INCREMENTS: dict[str, float] = {
    Equipment.BARBELL: 2.5,
    Equipment.DUMBBELL: 2.5,
    Equipment.EZ_BAR: 2.5,
    Equipment.CABLE: 2.5,
    Equipment.MACHINE: 5.0,
    Equipment.KETTLEBELL: 4.0,
    Equipment.BODYWEIGHT: 2.5,  # added load: a dip belt or a weight vest
}
# A deload load is rounded to this step when the exercise has no increment.
DELOAD_ROUNDING_KG = 0.5


class Decision(StrEnum):
    """Why a target is what it is."""

    START = "start"  # not done yet in this program: the program's starting load
    PROGRESS = "progress"  # every working set reached the top of the range: load up
    REPEAT = "repeat"  # somewhere in the range: same load, beat last time
    REDUCE = "reduce"  # every working set fell short of the range: load down
    DELOAD = "deload"  # the deload week (D6)


@dataclass(frozen=True)
class Prescription:
    """One exercise on a program day.

    ``rep_min``-``rep_max`` is the range each set aims for: reps, or seconds
    for a timed exercise. ``start_load_kg`` is ``None`` when the program leaves
    the first load to the owner.
    """

    sets: int
    rep_min: int
    rep_max: int
    start_load_kg: float | None
    increment_kg: float | None


@dataclass(frozen=True)
class SetDone:
    """One logged set: reps (or seconds) and the load, ``None`` for none added."""

    amount: float
    load_kg: float | None


@dataclass(frozen=True)
class Target:
    """What the next session of an exercise aims for.

    ``reps`` holds one prefilled amount per set.
    """

    decision: Decision
    load_kg: float | None
    reps: tuple[int, ...]


@dataclass(frozen=True)
class Position:
    """A place in a program: week (from 1) and day of that week (from 1)."""

    week: int
    day: int


def load_increment(equipment: str | None, override_kg: float | None) -> float | None:
    """The exercise's load step: its own if set, else its equipment's, else none."""
    if override_kg is not None:
        return override_kg
    return LOAD_INCREMENTS.get(str(equipment))  # str(None) is "None": not listed


def working_load(sets: Sequence[SetDone]) -> float | None:
    """The heaviest load in a session; ``None`` if no set carried added load."""
    return max((done.load_kg for done in sets if done.load_kg is not None), default=None)


# coverage-critical
def progress(prescription: Prescription, last: Sequence[SetDone]) -> Target:
    """The next training session's target, from the last session of this exercise (D5).

    Working sets are the sets at the session's heaviest load (lighter warm-ups
    do not count). If at least the prescribed number of them all reached the
    top of the range, the load rises one increment and the target resets to
    the bottom. If every one fell short of the bottom, the load drops one
    increment (never below none) and is worked back up. Otherwise the load
    repeats, and each set is prefilled with last time's amount, within the range.
    """
    bottom = (prescription.rep_min,) * prescription.sets
    if not last:
        return Target(Decision.START, prescription.start_load_kg, bottom)
    load = working_load(last)
    working = [done.amount for done in last if done.load_kg == load]
    step = prescription.increment_kg
    enough = len(working) >= prescription.sets
    if step is not None and enough and min(working) >= prescription.rep_max:
        return Target(Decision.PROGRESS, (load or 0.0) + step, bottom)
    if step is not None and load and max(working) < prescription.rep_min:
        return Target(Decision.REDUCE, max(load - step, 0.0), bottom)
    return Target(Decision.REPEAT, load, _repeat_reps(prescription, working))


def _repeat_reps(prescription: Prescription, working: Sequence[float]) -> tuple[int, ...]:
    """Last time's amount for each set, clamped to the range; the bottom for extra sets."""
    clamped = [
        int(min(max(amount, prescription.rep_min), prescription.rep_max)) for amount in working
    ]
    # A negative count repeats nothing: extra sets done last time are dropped.
    missing = prescription.sets - len(clamped)
    return (*clamped[: prescription.sets], *(prescription.rep_min,) * missing)


# coverage-critical
def deload(prescription: Prescription, last: Sequence[SetDone]) -> Target:
    """The deload week's target (D6): about 60% of the sets at about 90% of the load.

    The load is 90% of the last session's working load (or of the starting
    load, if there was none), to the nearest increment, a tie going lighter.
    Sets are 60% of the prescribed, to the nearest whole set and at least one.
    """
    load = working_load(last) if last else prescription.start_load_kg
    sets = (prescription.sets * 3 + 2) // 5
    reps = (prescription.rep_min,) * sets
    if load is None:
        return Target(Decision.DELOAD, None, reps)
    step = prescription.increment_kg or DELOAD_ROUNDING_KG
    return Target(Decision.DELOAD, math.ceil(load * 9 / 10 / step - 0.5) * step, reps)


def is_deload_week(week: int, training_weeks: int) -> bool:
    """Whether ``week`` is the program's deload week (the one after its training weeks)."""
    return week > training_weeks


# coverage-critical
def target_for(prescription: Prescription, last: Sequence[SetDone], *, deload_week: bool) -> Target:
    """The target for one exercise: the deload week's, or the next training session's."""
    if deload_week:
        return deload(prescription, last)
    return progress(prescription, last)


# coverage-critical
def next_position(last: Position | None, days: int, training_weeks: int) -> Position | None:
    """The program day after ``last``, the last one completed; ``None`` once the block is done.

    Position follows the sequence of completed days, not the calendar: a missed
    session is simply the next one, so a week never falls out of step. After
    the last day of a training week comes the first day of the next week, and
    after the last day of the deload week the block is over.
    """
    if last is None:
        return Position(1, 1)
    if last.day < days:
        return Position(last.week, last.day + 1)
    if last.week <= training_weeks:
        return Position(last.week + 1, 1)
    return None
