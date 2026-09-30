"""Volume and best-set ranking."""

from collections.abc import Sequence

import pytest

from trainer.domain.exercises import Equipment, Measure
from trainer.domain.records import carried_load, set_rank, set_volume


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
    ("equipment", "bodyweight", "carried"),
    [
        (Equipment.BODYWEIGHT, 65.0, 65.0),
        ("bodyweight", 72.5, 72.5),
        (Equipment.BODYWEIGHT, None, 0.0),  # body weight not set
        (Equipment.BARBELL, 65.0, 0.0),
        (None, 65.0, 0.0),
    ],
)
def test_carried_load(equipment: str | None, bodyweight: float | None, carried: float) -> None:
    assert carried_load(equipment, bodyweight) == carried


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
