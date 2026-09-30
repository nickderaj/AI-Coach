"""Exercise naming, measures, equipment and near-duplicate detection."""

import pytest

from trainer.domain.exercises import (
    Equipment,
    Measure,
    is_near_duplicate,
    near_duplicates,
    normalise_name,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Lat Pulldown", "lat pulldown"),
        ("  lat \t pulldown\n", "lat pulldown"),
        ("", ""),
    ],
)
def test_normalise_name(text: str, expected: str) -> None:
    assert normalise_name(text) == expected


def test_measure_values_match_the_schema() -> None:
    assert [measure.value for measure in Measure] == ["reps", "seconds", "distance"]


def test_equipment_values() -> None:
    assert [item.value for item in Equipment] == [
        "barbell",
        "dumbbell",
        "kettlebell",
        "cable",
        "machine",
        "bodyweight",
        "ez bar",
        "band",
        "other",
    ]


@pytest.mark.parametrize(
    ("candidate", "existing"),
    [
        ("Lateral Raises", "Lateral Raise"),  # plural folded
        ("lat-pulldown", "Lat Pulldown"),  # hyphen as space
        ("Bench Press", "Barbell Bench Press"),  # words contained
        ("Barbell Bench Press", "Bench Press"),  # ...either way round
        ("Lat Pull Down", "Lat Pulldown"),  # close spelling
        ("Tricep Pushdown", "Cable Tricep Pushdown"),
        ("abs", "Abs"),
        # Matched only by the word rules (their spellings are far apart):
        ("Curls Hammer", "Hammer Curl"),  # plural folded, same words in another order
        ("Pulldown-Lat", "Lat Pulldown"),  # hyphen splits words
        # Gym shorthand, each spelled out:
        ("Incline DB Press", "Incline Dumbbell Press"),
        ("BB Row", "Barbell Row"),
        ("KB Swing", "Kettlebell Swing"),
        ("BW Squat", "Bodyweight Squat"),
        ("Seated OHP", "Seated Overhead Press"),
        ("RDL", "Romanian Deadlift"),
        ("Single Leg RDL", "Single Leg Romanian Deadlift"),
        ("Incline DB Press", "Incline Dumbell Press"),  # shorthand and a typo together
        ("DB-Row", "Dumbbell Row"),
    ],
)
def test_near_duplicates_are_detected(candidate: str, existing: str) -> None:
    assert is_near_duplicate(candidate, existing)


@pytest.mark.parametrize(
    ("candidate", "existing"),
    [
        ("Goblet Squat", "Leg Press"),
        ("Hip Thrust", "Leg Curl"),
        ("Face Pull", "Lat Pulldown"),
        ("abs", "ab"),  # three-letter words keep their "s"
        ("Bench Curls", "Bench Crunches"),  # folding strips one trailing "s", nothing more
        ("KB Row", "Barbell Row"),  # equipment is part of the identity
        ("Dbl Crunch", "Dumbbell Crunch"),  # only whole words are shorthand
    ],
)
def test_different_exercises_are_not_flagged(candidate: str, existing: str) -> None:
    assert not is_near_duplicate(candidate, existing)


def test_similarity_threshold_is_inclusive() -> None:
    # 17 of 20 characters match: ratio = 2 * 17 / 40 = 0.85 exactly.
    assert is_near_duplicate("abcdefghijklmnopqrst", "abcdefghijklmnopqxyz")
    # 16 of 20: 0.8, below the threshold.
    assert not is_near_duplicate("abcdefghijklmnopqrst", "abcdefghijklmnopwxyz")


def test_near_duplicates_lists_each_id_once_in_order() -> None:
    names = [
        (3, "Barbell Bench Press"),
        (3, "bench"),
        (5, "Leg Press"),
        (7, "Decline Barbell Bench Press"),
    ]

    assert near_duplicates("Bench Press", names) == [3, 7]
    assert near_duplicates("Hip Thrust", names) == []
