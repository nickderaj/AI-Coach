"""Volume and best-set ranking."""

from collections.abc import Sequence

import pytest

from trainer.domain.exercises import Equipment, Measure
from trainer.domain.records import (
    BODYWEIGHT_SHARES,
    DEFAULT_BODYWEIGHT_SHARE,
    bodyweight_share,
    carried_load,
    set_rank,
    set_volume,
)


@pytest.mark.parametrize(
    ("reps", "load", "carried", "volume"),
    [
        (8, 60.0, 0.0, 480.0),
        (0, 60.0, 0.0, 0.0),
        (8, None, 0.0, 0.0),
        (None, 60.0, 0.0, 0.0),
        (3, 0.5, 0.0, 1.5),
        (10, None, 65.0, 650.0),  # pull-ups at body weight
        (8, 10.0, 65.0, 600.0),  # weighted dips: body weight plus the belt
        (None, None, 65.0, 0.0),  # a timed hold moves nothing
    ],
)
def test_set_volume(reps: int | None, load: float | None, carried: float, volume: float) -> None:
    assert set_volume(reps, load, carried) == volume


@pytest.mark.parametrize(
    ("name", "share"),
    [
        # Every listed exercise, by the name it is listed under.
        ("Pull-up", 0.93),
        ("Chin-up", 0.93),
        ("Dip", 0.93),
        ("Dead Hang", 0.93),
        ("Push-up", 0.64),
        ("Knee Push-up", 0.49),
        ("Incline Push-up", 0.55),
        ("Decline Push-up", 0.70),
        ("Squat", 0.77),
        ("Split Squat", 0.74),
        ("Lunge", 0.74),
        ("Step-up", 0.80),
        ("Pistol Squat", 0.80),
        ("Leg Raise", 0.33),
        ("Knee Raise", 0.33),
        ("Inverted Row", 0.60),
        ("Sit-up", 0.50),
        ("Crunch", 0.30),
        ("Glute Bridge", 0.50),
        ("Mountain Climber", 0.25),
        # Spellings, plurals, equipment words and extra words still match.
        ("Dips", 0.93),
        ("pull ups", 0.93),
        ("Bodyweight Squat", 0.77),
        ("BW Squats", 0.77),
        ("Weighted Pull-up", 0.93),
        ("Walking Lunge", 0.74),
        ("Hanging Leg Raise", 0.33),
        ("Hanging Knee Raises", 0.33),
        # The most specific entry wins over one it contains.
        ("Bulgarian Split Squat", 0.74),
        ("Decline Push-ups", 0.70),
        ("Single Leg Pistol Squat", 0.80),
        # ...and over a shorter, unrelated one listed earlier.
        ("Dip Bar Leg Raise", 0.33),
        # Not listed: about a push-up.
        ("Burpee", 0.65),
        ("Plank", 0.65),
        ("Pull", 0.65),  # only part of a listed name
    ],
)
def test_bodyweight_share(name: str, share: float) -> None:
    assert bodyweight_share(name) == share


def test_every_listed_exercise_is_found_by_its_own_name() -> None:
    assert {name: bodyweight_share(name) for name in BODYWEIGHT_SHARES} == BODYWEIGHT_SHARES
    assert DEFAULT_BODYWEIGHT_SHARE == 0.65


@pytest.mark.parametrize(
    ("name", "equipment", "bodyweight", "carried"),
    [
        ("Pull-up", Equipment.BODYWEIGHT, 80.0, 74.4),
        ("Push-up", "bodyweight", 70.3, 45.0),  # 44.992, to 0.1 kg
        ("Burpee", Equipment.BODYWEIGHT, 70.0, 45.5),
        ("Pull-up", Equipment.BODYWEIGHT, None, 0.0),  # body weight not set
        ("Squat", Equipment.BARBELL, 65.0, 0.0),
        ("Squat", None, 65.0, 0.0),
    ],
)
def test_carried_load(
    name: str, equipment: str | None, bodyweight: float | None, carried: float
) -> None:
    assert carried_load(name, equipment, bodyweight) == carried


def best(measure: Measure, sets: Sequence[tuple[int | None, float | None, float | None]]) -> int:
    """Index of the best set among (reps, load, duration) triples."""
    return max(range(len(sets)), key=lambda i: set_rank(measure, *sets[i]))


def test_reps_exercises_rank_by_load_then_reps() -> None:
    assert best(Measure.REPS, [(12, 50.0, None), (6, 70.0, None), (8, 70.0, None)]) == 2


def test_bodyweight_sets_rank_by_reps() -> None:
    assert best(Measure.REPS, [(8, None, None), (12, None, None), (10, None, None)]) == 1


def test_timed_exercises_rank_by_duration_then_load() -> None:
    sets = [(None, None, 50.0), (None, 10.0, 30.0), (None, 5.0, 50.0)]

    assert best(Measure.SECONDS, sets) == 2


def test_timed_sets_without_a_duration_rank_by_reps() -> None:
    sets = [(5, 10.0, None), (10, 10.0, None), (8, 10.0, None)]

    assert best(Measure.SECONDS, sets) == 1


@pytest.mark.parametrize(
    ("measure", "args", "key"),
    [
        (Measure.REPS, (8, 60.0, 30.0), (60.0, 8.0)),
        (Measure.REPS, (None, None, None), (0.0, 0.0)),
        (Measure.SECONDS, (8, 60.0, 30.0), (30.0, 60.0, 8.0)),
        (Measure.SECONDS, (None, None, None), (0.0, 0.0, 0.0)),
        (Measure.DISTANCE, (8, 60.0, 30.0), (60.0, 8.0)),
    ],
)
def test_set_rank_keys(
    measure: Measure, args: tuple[int | None, float | None, float | None], key: tuple[float, ...]
) -> None:
    assert set_rank(measure, *args) == key
