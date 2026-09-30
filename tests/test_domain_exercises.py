"""Exercise naming, measures, equipment and near-duplicate detection."""

import pytest

from trainer.domain.exercises import (
    EQUIPMENT_WORDS,
    Equipment,
    Measure,
    is_catalogued,
    is_near_duplicate,
    is_same_exercise,
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


@pytest.mark.parametrize(
    ("candidate", "existing"),
    [
        ("Dip", "Dips"),  # plural folded
        ("Pull-ups", "Pull-up"),  # "ups" keeps its "s" but the spellings are close
        ("Bodyweight Squat", "Squat"),  # equipment words say nothing here
        ("Dumbbell Fly", "Fly"),
        ("Barbell Row", "Row"),
        ("Kettlebell Swing", "Swing"),
        ("Cable Crunch", "Crunch"),
        ("Machine Chest Press", "Chest Press"),
        ("Band Pull-Apart", "Pull-Apart"),
        ("EZ Bar Curl", "Curl"),
        ("DB Row", "Dumbbell Row"),  # shorthand
    ],
)
def test_same_exercise(candidate: str, existing: str) -> None:
    assert is_same_exercise(candidate, existing)


@pytest.mark.parametrize(
    ("candidate", "existing"),
    [
        ("Incline Bench Press", "Barbell Bench Press"),  # a variant, not the same
        ("Seated Calf Raise", "Calf Raise"),
        ("Chin-up", "Pull-up"),
        ("Side Plank", "Plank"),
        ("Dumbbell Bench Press", "Dumbbell Clean Press"),  # near-duplicate spelling only
    ],
)
def test_variants_are_not_the_same_exercise(candidate: str, existing: str) -> None:
    assert not is_same_exercise(candidate, existing)


def test_same_spelling_threshold_is_inclusive() -> None:
    # 18 of 20 characters match: ratio = 2 * 18 / 40 = 0.9 exactly.
    assert is_same_exercise("abcdefghijklmnopqrst", "abcdefghijklmnopqrxy")
    # 17 of 20: 0.85, a near-duplicate but not the same exercise.
    assert not is_same_exercise("abcdefghijklmnopqrst", "abcdefghijklmnopqxyz")


def test_equipment_words() -> None:
    assert sorted(EQUIPMENT_WORDS) == [
        "band",
        "bar",
        "barbell",
        "bodyweight",
        "cable",
        "dumbbell",
        "ez",
        "kettlebell",
        "machine",
    ]


CATALOGUE = [("Squat", "bodyweight"), ("Dips", "bodyweight"), ("Plank", None)]


@pytest.mark.parametrize(
    ("name", "equipment", "known"),
    [
        ("squat", "barbell", True),  # the name is taken, whatever the equipment
        ("Bodyweight Squat", "bodyweight", True),
        ("Barbell Back Squat", "barbell", False),
        ("Bodyweight Squat", "barbell", False),  # the same words, other equipment
        ("Dip", "bodyweight", True),
        ("Dip", None, True),  # no equipment matches any
        ("Planks", "bodyweight", True),  # ...on either side
        ("Side Plank", None, False),
    ],
)
def test_is_catalogued(name: str, equipment: str | None, known: bool) -> None:  # noqa: FBT001  # why: parametrised expectation
    assert is_catalogued(name, equipment, CATALOGUE) is known


def test_nothing_is_catalogued_in_an_empty_catalogue() -> None:
    assert not is_catalogued("Squat", None, [])
